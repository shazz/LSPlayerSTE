#!/usr/bin/env python3
"""LSPSTE: read a ProTracker module and refuse what the light player cannot play.

The subset (anything else raises ModError, with the place): 'M.K.' 4 channels, finetune 0, periods of the
ProTracker table, and the effects of SUPPORTED below (their rules are in lsp_pt.py). Refused: 7xy tremolo, 8xx,
E3x glissando, E4x/E7x waveforms, E5x finetune, E6x pattern loop, E8x, EEx pattern delay, EFx invert loop, F00
and the BPM tempos F20..FF.
Only the rows the song really plays are checked (rows after a pattern break may hold anything).
"""
from __future__ import annotations

from dataclasses import dataclass

PERIODS = (856, 808, 762, 720, 678, 640, 604, 570, 538, 508, 480, 453, 428, 404, 381, 360, 339, 320, 302, 285,
           269, 254, 240, 226, 214, 202, 190, 180, 170, 160, 151, 143, 135, 127, 120, 113)
ROWS = 64
CHANNELS = 4
SUPPORTED = ("0xy arpeggio, 1xx 2xx 3xx portamento, 4xy vibrato, 5xy 6xy the same with a volume slide, 9xx sample "
             "offset, Axy volume slide, Bxx position jump, Cxx volume, Dxx pattern break, E0x (ignored), E1x E2x "
             "fine portamento, E9x retrigger, EAx EBx fine volume, ECx cut, EDx delay, "
             "Fxx speed 1..31 (F20 and above set a BPM tempo: not supported)")
E_PLAYED = (0x0, 0x1, 0x2, 0x9, 0xA, 0xB, 0xC, 0xD)


class ModError(ValueError):
    """A module outside the subset (the message says what and where)."""


@dataclass(frozen=True)
class Sample:
    data: bytes                     # signed 8-bit
    volume: int                     # 0..64
    finetune: int
    loop_start: int                 # bytes
    loop_len: int                   # bytes, 0 = no loop


@dataclass(frozen=True)
class Cell:
    sample: int
    period: int
    effect: int
    arg: int


@dataclass(frozen=True)
class Module:
    samples: dict[int, Sample]      # 1..31, only those with data
    order: tuple[int, ...]
    patterns: tuple[bytes, ...]     # 1024 bytes each

    def cell(self, pattern: int, row: int, channel: int) -> Cell:
        b = self.patterns[pattern][(row * CHANNELS + channel) * 4:][:4]
        return Cell((b[0] & 0xF0) | (b[2] >> 4), ((b[0] & 0x0F) << 8) | b[1], b[2] & 0x0F, b[3])


def _sample(data: bytes, i: int) -> tuple[int, int, int, int, int]:
    o = 20 + 30 * i
    words = [int.from_bytes(data[o + k:o + k + 2], "big") * 2 for k in (22, 26, 28)]
    return words[0], data[o + 24] & 0x0F, data[o + 25], words[1], words[2]


def parse(data: bytes) -> Module:
    if len(data) < 1084 or data[1080:1084] != b"M.K.":
        raise ModError(f"not a 4-channel ProTracker module (tag {data[1080:1084]!r}, want b'M.K.')")
    n = data[950]
    if not 1 <= n <= 128:
        raise ModError(f"song length {n} (want 1..128)")
    order = tuple(data[952:952 + n])
    npat = max(data[952:952 + 128]) + 1
    pos = 1084 + npat * 1024
    if len(data) < pos:
        raise ModError(f"file ends inside the patterns ({len(data)} B, {npat} patterns need {pos})")
    patterns = tuple(data[1084 + p * 1024:1084 + (p + 1) * 1024] for p in range(npat))
    samples: dict[int, Sample] = {}
    for i in range(31):
        length, fine, vol, ls, ll = _sample(data, i)
        body = data[pos:pos + length]
        if len(body) != length:
            raise ModError(f"sample {i + 1}: file ends inside it")
        pos += length
        if ll > 2 and ls + ll > length:
            raise ModError(f"sample {i + 1}: its loop ({ls}+{ll}) passes its end ({length})")
        if length > 2:
            samples[i + 1] = Sample(body, min(vol, 64), fine, ls if ll > 2 else 0, ll if ll > 2 else 0)
    return Module(samples, order, patterns)


def check(mod: Module, c: Cell, where: str) -> None:
    """Raise ModError (with the place) if the player cannot play this cell."""
    if c.period and c.period not in PERIODS:
        raise ModError(f"{where}: period {c.period} is not in the ProTracker table")
    if c.sample:
        s = mod.samples.get(c.sample)
        if s is None:
            raise ModError(f"{where}: sample {c.sample} is empty")
        if s.finetune:
            raise ModError(f"{where}: sample {c.sample} has finetune {s.finetune} (only 0)")
    bad = c.effect in (7, 8) or (c.effect == 0xE and c.arg >> 4 not in E_PLAYED)
    if bad or (c.effect == 0xF and not 1 <= c.arg <= 31):
        raise ModError(f"{where}: effect {c.effect:X}{c.arg:02X} is not supported; the player has {SUPPORTED}")
    if c.effect == 0xD and (c.arg >> 4) * 10 + (c.arg & 0x0F) >= ROWS:
        raise ModError(f"{where}: D{c.arg:02X} breaks to row {(c.arg >> 4) * 10 + (c.arg & 0x0F)}")
