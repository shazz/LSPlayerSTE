#!/usr/bin/env python3
"""LSPSTE.DAT: the file layout and what the 68000 loader builds from the file.

File (big-endian, every offset from the start of the file):
     0 'LSP1'   4 w version   6 w variants   8 l file size   12 l bank size (what the loader generates)
    16 l volume tables (256 B each)   20 l effects table (256 B)   24 l stream   28 l the stream's loop record
    32 w volume tables   34 w bytes per tick   36 l renditions   40 l checksum (sum of the bytes from 48)   44 l 0
    48 variants, 12 B each: l rendition data, l 16.16 step, w ticks, w volume table
       (the loader overwrites the first long with the variant's address in the bank)
Where the file and the bank sit in memory is src/lsp_config.s; the player checks both against it at start,
and pack() takes the same two limits (defaults = the config's) so a too big song is refused at conversion.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from lsp_bank import TICK, Plan, fxtab, interp, voltab
from lsp_mod import ModError

MAGIC, VERSION = b"LSP1", 1
HEAD = struct.Struct(">4sHHIIIIIIHHIII")
VAR = struct.Struct(">IIHH")
MAX_FILE = 0x10000                  # LSP_DATMAX in src/lsp_config.s
MAX_BANK = 0x53000                  # LSP_LIMIT - LSP_BANK in src/lsp_config.s
MAX_VOFF = 0x3FFF                   # a stream event holds the variant entry's offset in 14 bits


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
    off_rend: int


@dataclass(frozen=True)
class Bank:
    data: bytes                     # unsigned bytes, silence = $80
    starts: tuple[int, ...]         # offset of each variant in data


def voff(index: int) -> int:
    """A variant's table entry, as a stream event names it."""
    off = HEAD.size + VAR.size * index
    if off > MAX_VOFF:
        raise ModError(f"too many variants ({index + 1}): entry offset {off} > {MAX_VOFF}")
    return off


def pack(plan: Plan, gain: int, fx_peak: int, stream: bytes, loop_off: int,
         max_file: int = MAX_FILE, max_bank: int = MAX_BANK) -> bytes:
    nvar = len(plan.variants)
    off_vol = HEAD.size + VAR.size * nvar
    off_fx = off_vol + 256 * len(plan.vols)
    off_stream = off_fx + 256
    off_rend = off_stream + len(stream) + (len(stream) & 1)
    rend_off, pos = [], off_rend
    for r in plan.rends:
        rend_off.append(pos)
        pos += len(r)
    bank = sum(v.ticks for v in plan.variants) * TICK
    body = b"".join(VAR.pack(rend_off[v.rend], v.step, v.ticks, v.vol) for v in plan.variants)
    body += b"".join(voltab(vol, gain) for vol in plan.vols) + fxtab(fx_peak)
    body += stream + bytes(len(stream) & 1) + b"".join(plan.rends)
    if pos > max_file:
        raise ModError(f"LSPSTE.DAT would be {pos} B: more than the {max_file} B the player's file area holds")
    if bank > max_bank:
        raise ModError(f"the bank would be {bank} B: more than the {max_bank} B the player's bank area holds")
    head = HEAD.pack(MAGIC, VERSION, nvar, pos, bank, off_vol, off_fx, off_stream, off_stream + loop_off,
                     len(plan.vols), TICK, off_rend, sum(body) & 0xFFFFFFFF, 0)
    return head + body


def head(dat: bytes) -> Head:
    if len(dat) < HEAD.size or dat[:4] != MAGIC:
        raise ModError("not an LSPSTE.DAT (magic)")
    _m, ver, nvar, size, bank, ov, of, os_, ol, nvol, tick, orend, csum, _z = HEAD.unpack_from(dat)
    if ver != VERSION or tick != TICK or size != len(dat) or csum != sum(dat[HEAD.size:]) & 0xFFFFFFFF:
        raise ModError("LSPSTE.DAT: wrong version, tick length, size or checksum")
    return Head(nvar, size, bank, ov, of, os_, ol, nvol, orend)


def expand(dat: bytes) -> Bank:
    """The bank as the 68000 loader generates it from the file."""
    h = head(dat)
    out, starts = bytearray(), []
    for i in range(h.nvar):
        src, step, ticks, vol = VAR.unpack_from(dat, HEAD.size + VAR.size * i)
        tab = dat[h.off_vol + 256 * vol:][:256]
        raw = interp(dat[src:], step, ticks * TICK)
        starts.append(len(out))
        out += raw.translate(bytes(tab[b ^ 0x80] for b in range(256)))
    return Bank(bytes(out), tuple(starts))
