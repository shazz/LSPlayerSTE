#!/usr/bin/env python3
"""LSPSTE.DAT: the file layout and what the 68000 loader builds from the file.

File (big-endian, every offset from the start of the file):
     0 'LSP1'   4 w version   6 w variants   8 l file size   12 l bank size (what the loader generates)
    16 l volume tables (256 B each)   20 l effects table (256 B)   24 l stream   28 l the stream's loop record
    32 w volume tables   34 w bytes per tick   36 l rendition table   40 l checksum (sum of the bytes from 48)
    44 l target table
    48 variants, 16 B each: w rendition, w volume table, l 16.16 step, l first sample, w first fraction,
       w size in long words (the loader makes them one after the other from LSP_BANK: the bank)
    then the rendition table, up to the target table, 12 B each: l data, l end, l loop length, in samples: the
       loader reads samples 0..end-1 and the one after for the interpolation, and at `end` goes back a loop length
    then the target table, up to the volume tables: one long per place a stream event can point a channel at,
       = its offset in the bank (even, a whole tick of the bank follows it). Entry 0 is silence. The loader turns
       the offsets into addresses (entry 0: the silent tick).
Where the file and the bank sit in memory is src/lsp_config.s; the player checks both against it at start,
and pack() takes the same two limits (defaults = the config's) so a too big song is refused at conversion.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from lsp_bank import TICK, Key, Plan, Rendition, fxtab, interp, voltab
from lsp_mod import ModError

MAGIC, VERSION = b"LSP1", 2
HEAD = struct.Struct(">4sHHIIIIIIHHIII")
VAR = struct.Struct(">HHIIHH")
REND = struct.Struct(">III")
MAX_FILE = 0x10000                  # LSP_DATMAX in src/lsp_config.s
MAX_BANK = 0x53000                  # LSP_LIMIT - LSP_BANK in src/lsp_config.s
MAX_TARGETS = 0x3FFF                # a stream event holds the target's index in 14 bits
MAX_LONGS = 0xFFFF                  # a variant's size is a word


@dataclass(frozen=True)
class Head:
    nvar: int
    size: int
    bank: int
    off_vol: int
    off_fx: int
    off_stream: int
    off_loop: int
    nvol: int
    off_rend: int                   # the rendition table
    off_tgt: int


@dataclass(frozen=True)
class Bank:
    data: bytes                     # unsigned bytes, silence = $80
    starts: tuple[int, ...]         # offset of each variant in data
    targets: tuple[int | None, ...]     # per target table entry: its offset in data (None: silence)


def places(plan: Plan, targets: list[tuple[Key, int]]) -> list[int]:
    """The bank offset of each target: its variant's place plus the target's byte in it."""
    at: dict[Key, list[tuple[int, int, int]]] = {}
    pos = 0
    for v in plan.variants:
        at.setdefault(v.key, []).append((v.start, v.size, pos))
        pos += v.size
    out = []
    for key, off in targets:
        start, size, base = max(w for w in at[key] if w[0] <= off)
        if off + TICK > start + size:
            raise ModError(f"internal: target {key} + {off} is not inside a variant")
        out.append(base + off - start)
    return out


def _variants(plan: Plan) -> bytes:
    out = bytearray()
    for v in plan.variants:
        if v.size // 4 > MAX_LONGS:
            raise ModError(f"sample {v.key[0]} at period {v.key[1]} plays {v.size} B in one go: more than {MAX_LONGS * 4}")
        first = v.start * v.step
        out += VAR.pack(v.rend, v.vol, v.step, plan.rends[v.rend].wrap(first >> 16), first & 0xFFFF, v.size // 4)
    return bytes(out)


def _layout(plan: Plan, ntargets: int, stream: bytes) -> tuple[int, int, int, int, int, int]:
    """Offsets of the rendition table, the target table, the volume tables, the effects table, the stream, the data."""
    off_rend = HEAD.size + VAR.size * len(plan.variants)
    off_tgt = off_rend + REND.size * len(plan.rends)
    off_vol = off_tgt + 4 * (ntargets + 1)
    off_fx = off_vol + 256 * len(plan.vols)
    return off_rend, off_tgt, off_vol, off_fx, off_fx + 256, off_fx + 256 + len(stream) + (len(stream) & 1)


def pack(plan: Plan, targets: list[tuple[Key, int]], gain: int, fx_peak: int, stream: bytes, loop_off: int,
         max_file: int = MAX_FILE, max_bank: int = MAX_BANK) -> bytes:
    if len(targets) > MAX_TARGETS:
        raise ModError(f"the song points at {len(targets)} places in its samples: more than {MAX_TARGETS}")
    off_rend, off_tgt, off_vol, off_fx, off_stream, pos = _layout(plan, len(targets), stream)
    body = _variants(plan)
    for r in plan.rends:
        body += REND.pack(pos, r.end, r.lap)
        pos += len(r.data)
    bank = sum(v.size for v in plan.variants)
    body += struct.pack(f">{len(targets) + 1}I", 0, *places(plan, targets))
    body += b"".join(voltab(vol, gain) for vol in plan.vols) + fxtab(fx_peak)
    body += stream + bytes(len(stream) & 1) + b"".join(r.data for r in plan.rends)
    if pos > max_file:
        raise ModError(f"LSPSTE.DAT would be {pos} B: more than the {max_file} B the player's file area holds")
    if bank > max_bank:
        raise ModError(f"the bank would be {bank} B: more than the {max_bank} B the player's bank area holds")
    head = HEAD.pack(MAGIC, VERSION, len(plan.variants), pos, bank, off_vol, off_fx, off_stream,
                     off_stream + loop_off, len(plan.vols), TICK, off_rend, sum(body) & 0xFFFFFFFF, off_tgt)
    return head + body


def head(dat: bytes) -> Head:
    if len(dat) < HEAD.size or dat[:4] != MAGIC:
        raise ModError("not an LSPSTE.DAT (magic)")
    _m, ver, nvar, size, bank, ov, of, os_, ol, nvol, tick, orend, csum, otgt = HEAD.unpack_from(dat)
    if ver != VERSION or tick != TICK or size != len(dat) or csum != sum(dat[HEAD.size:]) & 0xFFFFFFFF:
        raise ModError("LSPSTE.DAT: wrong version, tick length, size or checksum")
    return Head(nvar, size, bank, ov, of, os_, ol, nvol, orend, otgt)


def expand(dat: bytes) -> Bank:
    """The bank as the 68000 loader generates it from the file, and where the targets point in it."""
    h = head(dat)
    out, starts = bytearray(), []
    for i in range(h.nvar):
        rend, vol, step, idx, frac, longs = VAR.unpack_from(dat, HEAD.size + VAR.size * i)
        src, end, lap = REND.unpack_from(dat, h.off_rend + REND.size * rend)
        tab = dat[h.off_vol + 256 * vol:][:256]
        raw = interp(Rendition(dat[src:src + end + 1], end, lap), step, longs * 4, idx << 16 | frac)
        starts.append(len(out))
        out += raw.translate(bytes(tab[b ^ 0x80] for b in range(256)))
    offs = struct.unpack_from(f">{(h.off_vol - h.off_tgt) // 4}I", dat, h.off_tgt)
    if any(o & 1 or o + TICK > len(out) for o in offs[1:]):
        raise ModError("LSPSTE.DAT: a target points outside the bank or at an odd byte")
    return Bank(bytes(out), tuple(starts), (None, *offs[1:]))
