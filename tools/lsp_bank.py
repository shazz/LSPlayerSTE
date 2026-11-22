#!/usr/bin/env python3
"""LSPSTE: the sample side. Every (sample, period, volume) the song plays becomes a "variant": that note already
resampled to the STE's 12,517 Hz and scaled, stored as a straight run of whole ticks (252 bytes each, loops
unrolled, the tail of a one-shot padded with silence), so the run-time mixer only adds bytes.

The variants are several times bigger than the source samples (the demo's bank is 56 KB, a real song's is a few
hundred KB), so LSPSTE.DAT carries the source samples ("renditions") and the 68000 loader builds the bank once at
start with interp() below, which this module mirrors instruction for instruction: 16.16 step, linear
interpolation with a 15-bit fraction, then a 256-byte table that applies volume and gain and makes the byte
unsigned (silence = $80).
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
Key = tuple[int, int, int]          # sample, period, volume


@dataclass(frozen=True)
class Variant:
    key: Key
    rend: int                       # index into Plan.rends
    step: int                       # 16.16 source samples per output byte
    ticks: int                      # length in ticks
    vol: int                        # index into Plan.vols


@dataclass(frozen=True)
class Plan:
    variants: tuple[Variant, ...]
    rends: tuple[bytes, ...]        # signed 8-bit, long enough for every variant that reads them
    vols: tuple[int, ...]           # distinct volumes, one table each


def step_for(period: int) -> tuple[int, int]:
    """(1 if the halved rendition is used else 0, 16.16 step) for a period."""
    den = period * RATE
    full = (2 * PAL_CLOCK * 65536 + den) // (2 * den)
    if full > HALF_ABOVE:
        return 1, (2 * PAL_CLOCK * 32768 + den) // (2 * den)
    return 0, full


def natural_ticks(s: Sample, period: int) -> int | None:
    """Ticks until a one-shot sample has played out at this period; None for a looped sample."""
    if s.loop_len:
        return None
    shift, step = step_for(period)
    n = (len(s.data) + shift) >> shift
    out = -(-(n << 16) // step)
    return -(-out // TICK)


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


def interp(src: bytes, step: int, n: int) -> bytes:
    """n output samples (signed bytes) from src: the 68000 loader's inner loop (src/lsp_bank.s), bit for bit."""
    out = bytearray(n)
    idx, frac, si, sf = 0, 0, step >> 16, step & 0xFFFF
    for j in range(n):
        a = _s8(src[idx])
        v = a + (((_s8(src[idx + 1]) - a) * (frac >> 1)) >> 15)
        out[j] = v & 0xFF
        frac += sf
        idx += si + (frac >> 16)
        frac &= 0xFFFF
    return bytes(out)


def need(step: int, ticks: int) -> int:
    """Source samples interp() reads for a variant of this many ticks."""
    return (((ticks * TICK - 1) * step) >> 16) + 2


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


def plan(mod: Module, hold: dict[Key, int]) -> Plan:
    """Variants (sorted by key) with the ticks each is held at most, and the renditions they read."""
    vols = tuple(sorted({k[2] for k in hold}))
    rid: dict[tuple[int, int], int] = {}
    size: list[int] = []
    variants = []
    for key in sorted(hold):
        shift, step = step_for(key[1])
        r = rid.setdefault((key[0], shift), len(rid))
        if r == len(size):
            size.append(0)
        size[r] = max(size[r], need(step, hold[key]))
        variants.append(Variant(key, r, step, hold[key], vols.index(key[2])))
    if not variants:
        raise ModError("the song plays no note")
    rends = tuple(virtual(mod.samples[s], size[r] + (size[r] & 1), shift) for (s, shift), r in rid.items())
    return Plan(tuple(variants), rends, vols)
