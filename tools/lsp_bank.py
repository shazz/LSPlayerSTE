#!/usr/bin/env python3
"""LSPSTE: the sample side. Every (sample, period, volume) the song plays becomes a "variant": that note already
resampled to the STE's 12,517 Hz and scaled, stored as a straight run of bytes (loops unrolled, the tail of a
one-shot padded with silence), so the run-time mixer only adds bytes. A variant holds the bytes the song reads
(lsp_seq.py: spans) and no more: a plain note the ticks it is held, a note bent by effects the pieces it is entered
at; pieces more than GAP bytes apart become variants of their own.

The variants are several times bigger than the source samples (the demo's bank is 56 KB, a real song's is a few
hundred KB), so LSPSTE.DAT carries the source samples ("renditions") and the 68000 loader builds the bank once at
start with interp() below, which this module mirrors instruction for instruction: 16.16 step, linear
interpolation with a 15-bit fraction, then a 256-byte table that applies volume and gain and makes the byte
unsigned (silence = $80). A rendition is the sample up to the end of its loop and one more byte (the loop's
first); the loader goes back one loop length whenever it reaches the end, so the file does not hold loops
unrolled. A one-shot sample "loops" over four zero bytes added after it, as Paula does over its first word.
A note played above 12,517 * sqrt(2) Hz reads a rendition halved offline (two-sample average) at half the step,
so the loader never skips more than 1.41 source samples (aliasing stays out of the hi-hats at period 143).
"""
from __future__ import annotations

from dataclasses import dataclass

from lsp_mod import ModError, Module, Sample

PAL_CLOCK = 3546895                 # Paula: sample rate = PAL_CLOCK / period
RATE = 12517                        # STE DMA mode $81
TICK = 252                          # output bytes per player tick (63 longs): 49.67 ticks/s
HALF_ABOVE = 92682                  # 16.16 sqrt(2): above this step, use the halved rendition
ZEROS = 4                           # silent samples a one-shot is followed by, and loops over
GAP = 64                            # bytes: runs of a variant further apart than this are stored apart
Key = tuple[int, int, int]          # sample, period, volume


@dataclass(frozen=True)
class Variant:
    key: Key
    rend: int                       # index into Plan.rends
    step: int                       # 16.16 source samples per output byte
    start: int                      # its first byte, counted from the start of the note (even)
    size: int                       # bytes, a multiple of 4 (the loader writes long words)
    vol: int                        # index into Plan.vols


@dataclass(frozen=True)
class Rendition:
    data: bytes                     # signed 8-bit: `end` samples, the one read after the last, padded to even
    end: int                        # the loader reads samples 0..end-1, then goes back by `lap`
    lap: int                        # loop length (4 zero samples after a one-shot)

    def wrap(self, idx: int) -> int:
        """Where the loader is when it has read idx samples of the unrolled sample."""
        return idx if idx < self.end else self.end - self.lap + (idx - self.end) % self.lap


@dataclass(frozen=True)
class Plan:
    variants: tuple[Variant, ...]
    rends: tuple[Rendition, ...]
    vols: tuple[int, ...]           # distinct volumes, one table each


def step_for(period: int) -> tuple[int, int]:
    """(1 if the halved rendition is used else 0, 16.16 step) for a period."""
    den = period * RATE
    full = (2 * PAL_CLOCK * 65536 + den) // (2 * den)
    if full > HALF_ABOVE:
        return 1, (2 * PAL_CLOCK * 32768 + den) // (2 * den)
    return 0, full


def natural_bytes(s: Sample, period: int) -> int:
    """Output bytes a sample's data lasts at this period (the loop of a looped sample not counted)."""
    shift, step = step_for(period)
    n = (len(s.data) + shift) >> shift
    return -(-(n << 16) // step)


def _s8(b: int) -> int:
    return b - 256 if b & 0x80 else b


def virtual(s: Sample, n: int, shift: int) -> bytes:
    """The first n source samples as ProTracker plays them (loop unrolled, zeros after a one-shot), halved if shift."""
    end = s.loop_start + s.loop_len if s.loop_len else len(s.data)

    def at(i: int) -> int:
        if i < end:
            return _s8(s.data[i])
        return _s8(s.data[s.loop_start + (i - end) % s.loop_len]) if s.loop_len else 0
    if not shift:
        return bytes(at(i) & 0xFF for i in range(n))
    return bytes(((at(2 * i) + at(2 * i + 1)) >> 1) & 0xFF for i in range(n))


def rendition(s: Sample, shift: int) -> Rendition:
    lap = s.loop_len >> shift or ZEROS
    end = (s.loop_start + s.loop_len) >> shift if s.loop_len else (len(s.data) >> shift) + ZEROS
    return Rendition(virtual(s, end + 1 + (end + 1) % 2, shift), end, lap)


def interp(r: Rendition, step: int, n: int, first: int = 0) -> bytes:
    """n output samples (signed bytes) from position `first` (16.16, in unrolled samples) of a rendition: the 68000
    loader's inner loop (src/lsp_bank.s), bit for bit."""
    out = bytearray(n)
    idx, frac, si, sf = r.wrap(first >> 16), first & 0xFFFF, step >> 16, step & 0xFFFF
    for j in range(n):
        a = _s8(r.data[idx])
        v = a + (((_s8(r.data[idx + 1]) - a) * (frac >> 1)) >> 15)
        out[j] = v & 0xFF
        frac += sf
        idx += si + (frac >> 16)
        frac &= 0xFFFF
        while idx >= r.end:
            idx -= r.lap
    return bytes(out)


def voltab(vol: int, gain: int) -> bytes:
    """256 bytes indexed by sample + 128: $80 + round(sample * vol/64 * gain/65536)."""
    out = bytearray(256)
    for v in range(-128, 128):
        mag = (abs(v) * vol * gain + (1 << 21)) >> 22
        out[v + 128] = 128 + (mag if v >= 0 else -mag)
    return bytes(out)


def fxtab(peak: int) -> bytes:
    """256 bytes indexed by sample + 128 for the effects channel: $80 + round(sample * peak/127)."""
    out = bytearray(256)
    for v in range(-128, 128):
        mag = (abs(v) * peak * 2 + 127) // 254
        out[v + 128] = 128 + (mag if v >= 0 else -mag)
    return bytes(out)


def windows(runs: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
    """(start, size) of the variants that hold these runs: runs closer than GAP share one, sizes are whole longs."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(runs):
        if out and a <= out[-1][1] + GAP:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return [(a, (b - a + 3) // 4 * 4) for a, b in out]


def plan(mod: Module, spans: dict[Key, tuple[tuple[int, int], ...]]) -> Plan:
    """Variants (sorted by key, then start) for the bytes the song reads, and the renditions they are made from."""
    vols = tuple(sorted({k[2] for k in spans}))
    rid: dict[tuple[int, int], int] = {}
    variants = []
    for key in sorted(spans):
        shift, step = step_for(key[1])
        r = rid.setdefault((key[0], shift), len(rid))
        variants += [Variant(key, r, step, start, n, vols.index(key[2])) for start, n in windows(spans[key])]
    if not variants:
        raise ModError("the song plays no note")
    return Plan(tuple(variants), tuple(rendition(mod.samples[s], shift) for s, shift in rid), vols)
