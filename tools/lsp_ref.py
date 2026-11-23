#!/usr/bin/env python3
"""LSPSTE reference mixer: what the 68000 player (src/lsp_rt.s, src/lsp_mix.s) writes into the DMA ring, byte
for byte, from LSPSTE.DAT (and FX.DAT for the effects channel). Also renders a WAV to listen to.

    python3 -I tools/lsp_ref.py LSPSTE.DAT OUT.wav [--ticks N] [--fx FX.DAT TICK:INDEX ...]

One tick = 252 bytes. Five channels of unsigned bytes (silence $80) are added as 63 longs; while the true sum of
the five signed samples stays in -128..127 each byte column adds up to 512..767, so the carry into the next byte
is always 2: `sum - $02020200` then `eor $80808080` is the signed mix. mix() does those long adds and checks them
against the plain per-byte sum; a sum outside the range raises (the converter sets the gain so it cannot happen).
"""
from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lsp_bank import RATE, TICK
from lsp_dat import expand, head
from lsp_mod import ModError

LONGS = struct.Struct(f">{TICK // 4}L")
SILENCE = bytes([0x80]) * TICK
MUSIC = 4                           # channels 0..3; channel 4 = effects


class MixOverflow(ModError):
    """The five channels add up outside a signed byte."""


def mix(chunks: list[bytes]) -> bytes:
    """One tick of signed output from five unsigned chunks, as the 68000 computes it."""
    sums = [sum(col) - 0x80 * len(chunks) for col in zip(*chunks)]
    if min(sums) < -128 or max(sums) > 127:
        raise MixOverflow(f"mix overflow: {min(sums)}..{max(sums)}")
    cols = zip(*(LONGS.unpack(c) for c in chunks))
    out = LONGS.pack(*((((sum(col) - 0x02020200) & 0xFFFFFFFF) ^ 0x80808080) for col in cols))
    if out != bytes(s & 0xFF for s in sums):
        raise AssertionError("long adds differ from the per-byte sum")
    return out


def fx_image(fx: bytes, table: bytes) -> tuple[bytes, list[tuple[int, int]]]:
    """FX.DAT as the loader converts it in place (samples through the effects table), and (start, end) per sample."""
    n = struct.unpack_from(">H", fx, 4)[0]
    first = 6 + 8 * n
    ends = [(o, o + ln) for o, ln in struct.iter_unpack(">II", fx[6:first])]
    return fx[:first] + fx[first:].translate(bytes(table[b ^ 0x80] for b in range(256))), ends


class Player:
    def __init__(self, dat: bytes, fx: bytes | None = None) -> None:
        self.h, self.dat, self.bank = head(dat), dat, expand(dat)
        self.fx, self.fx_ends = fx_image(fx, dat[self.h.off_fx:][:256]) if fx else (b"", [])
        self.ptr: list[int | None] = [None] * MUSIC
        self.fx_ptr: tuple[int, int] | None = None
        self.playing, self.wait, self.sptr, self.ticks = False, 0, 0, 0

    def start(self) -> None:
        self.ptr, self.playing, self.wait, self.sptr = [None] * MUSIC, True, 1, self.h.off_stream

    def stop(self) -> None:
        self.ptr, self.playing = [None] * MUSIC, False

    def fx_start(self, index: int) -> None:
        self.fx_ptr = self.fx_ends[index]

    def _record(self) -> None:
        word = struct.unpack_from(">H", self.dat, self.sptr)[0]
        if word == 0xFFFF:
            self.sptr = self.h.off_loop
            word = struct.unpack_from(">H", self.dat, self.sptr)[0]
        self.wait = word & 0xFF
        for i in range(word >> 8):
            ev = struct.unpack_from(">H", self.dat, self.sptr + 2 + 2 * i)[0]
            self.ptr[ev & 3] = self.bank.targets[ev >> 2]
        self.sptr += 2 + 2 * (word >> 8)

    def tick(self, paused: bool = False) -> bytes:
        """Advance one tick and return its 252 output bytes (signed)."""
        if self.playing and not paused:
            self.wait -= 1
            if self.wait == 0:
                self._record()
        chunks = [SILENCE if p is None or paused else self.bank.data[p:p + TICK] for p in self.ptr]
        if not paused:
            self.ptr = [None if p is None else p + TICK for p in self.ptr]
        if self.fx_ptr:
            pos, end = self.fx_ptr
            chunks.append(self.fx[pos:pos + TICK])
            self.fx_ptr = (pos + TICK, end) if pos + TICK < end else None
        else:
            chunks.append(SILENCE)
        self.ticks += 1
        return mix(chunks)


def levels(dat: bytes, ticks: int) -> tuple[int, int, float]:
    """(lowest, highest, RMS) of the music alone over the first ticks."""
    p = Player(dat)
    p.start()
    lo, hi, sq = 0, 0, 0
    for _ in range(ticks):
        vals = [b - 256 if b & 0x80 else b for b in p.tick()]
        lo, hi, sq = min(lo, *vals), max(hi, *vals), sq + sum(v * v for v in vals)
    return lo, hi, (sq / (ticks * TICK)) ** 0.5


def render(dat: bytes, ticks: int, fx: bytes | None, starts: dict[int, int]) -> bytes:
    """Signed output of `ticks` ticks from a music start, effects started at starts[tick] = index."""
    p = Player(dat, fx)
    p.start()
    out = bytearray()
    for t in range(ticks):
        if t in starts:
            p.fx_start(starts[t])
        out += p.tick()
    return bytes(out)


def main(argv: list[str]) -> int:
    args = argv[1:]
    ticks, fx, starts = 3000, None, {}
    if "--ticks" in args:
        i = args.index("--ticks")
        ticks = int(args[i + 1])
        del args[i:i + 2]
    if "--fx" in args:
        i = args.index("--fx")
        fx = Path(args[i + 1]).read_bytes()
        starts = {int(a.split(":")[0]): int(a.split(":")[1]) for a in args[i + 2:]}
        del args[i:]
    if len(args) != 2:
        raise SystemExit(__doc__)
    try:
        pcm = render(Path(args[0]).read_bytes(), ticks, fx, starts)
    except (ModError, OSError) as e:
        print(f"lsp_ref: {e}", file=sys.stderr)
        return 1
    with wave.open(args[1], "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(RATE)
        w.writeframes(bytes(b ^ 0x80 for b in pcm))
    print(f"lsp_ref: {args[1]}: {ticks} ticks, {len(pcm) / RATE:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
