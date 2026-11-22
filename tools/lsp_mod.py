#!/usr/bin/env python3
"""LSPSTE: read a ProTracker module and refuse what the light player cannot play.

The subset (anything else raises ModError, with the place): 'M.K.' 4 channels, finetune 0, periods of the
ProTracker table, a note always with its sample number, and the effects
    Bxx position jump     Dxx pattern break (decimal row)     Fxx speed 1..31 (ticks per row)
    Cxx on a note row: that note's volume; C00 alone: cut the channel. A volume change inside a note is refused.
Only the rows the song really plays are checked (rows after a pattern break may hold anything).
"""
from __future__ import annotations

from dataclasses import dataclass

PERIODS = (856, 808, 762, 720, 678, 640, 604, 570, 538, 508, 480, 453, 428, 404, 381, 360, 339, 320, 302, 285,
           269, 254, 240, 226, 214, 202, 190, 180, 170, 160, 151, 143, 135, 127, 120, 113)
ROWS = 64
CHANNELS = 4
SUPPORTED = ("Bxx position jump, Cxx volume of a note (C00 alone: cut the channel), Dxx pattern break, "
             "Fxx speed 1..31 (F20 and above set a BPM tempo: not supported)")


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


@dataclass(frozen=True)
class Action:
    """What one cell asks for. key = (sample, period, volume) to start, cut = stop the channel."""
    key: tuple[int, int, int] | None = None
    cut: bool = False
    jump: int | None = None         # B: next position
    brk: int | None = None          # D: row in the next position
    speed: int | None = None        # F


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


def _key(mod: Module, c: Cell, where: str) -> tuple[int, int, int] | None:
    if not c.sample and not c.period:
        return None
    if not c.sample or not c.period:
        raise ModError(f"{where}: a note without a sample number or a sample number without a note")
    if c.period not in PERIODS:
        raise ModError(f"{where}: period {c.period} is not in the ProTracker table")
    s = mod.samples.get(c.sample)
    if s is None:
        raise ModError(f"{where}: sample {c.sample} is empty")
    if s.finetune:
        raise ModError(f"{where}: sample {c.sample} has finetune {s.finetune} (only 0)")
    vol = min(c.arg, 64) if c.effect == 0xC else s.volume
    return (c.sample, c.period, vol)


def action(mod: Module, pattern: int, row: int, channel: int) -> Action:
    """The checked meaning of one cell; raises ModError outside the subset."""
    c = mod.cell(pattern, row, channel)
    where = f"pattern {pattern} row {row} channel {channel + 1}"
    key = _key(mod, c, where)
    if c.effect == 0 and c.arg == 0:
        return Action(key=key)
    if c.effect == 0xC:
        if key is None and c.arg != 0:
            raise ModError(f"{where}: C{c.arg:02X} without a note (a volume change inside a note)")
        return Action(key=key if key and key[2] else None, cut=key is None or key[2] == 0)
    if c.effect == 0xB:
        return Action(key=key, jump=c.arg)
    if c.effect == 0xD:
        brk = (c.arg >> 4) * 10 + (c.arg & 0x0F)
        if brk >= ROWS:
            raise ModError(f"{where}: D{c.arg:02X} breaks to row {brk}")
        return Action(key=key, brk=brk)
    if c.effect == 0xF and 1 <= c.arg <= 31:
        return Action(key=key, speed=c.arg)
    raise ModError(f"{where}: effect {c.effect:X}{c.arg:02X} is not supported; the player has {SUPPORTED}")
