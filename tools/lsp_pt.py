#!/usr/bin/env python3
"""LSPSTE: what ProTracker does to one channel, tick by tick (the rules of the PT 2.3 replay routine, finetune 0).

A row's first tick is row(): the sample number sets the sample and its volume, a note starts it (not with 3xx/5xx,
which only set the slide's target, and not yet with EDx), then the effects that act once: 9xx Cxx E1x E2x EAx EBx.
The other ticks are tick(): 0xy 1xx 2xx 3xx 4xy 5xy 6xy Axy, and E9x ECx EDx on their tick. Kept from the original:
- `out` is the period register. Arpeggio and vibrato only write it; it goes back to the note's period on the next
  tick that writes it (a row without effect, or one of 0 1 2 3 4 5 6 7 A; on its first tick a row with 9 B C D E F
  writes it only if the row before was empty).
- 1xx stops at 113 and 2xx at 856; vibrato is not limited. Slides and vibrato do nothing on a row's first tick.
- 3xx and 4xy remember their arguments (4xy each half on its own); 300 without a target does nothing.
- 9xx moves the start for the notes that follow without a sample number, twice on a row that has a note.
- A note without a sample number restarts the channel's sample at the volume it has now.
Not played here (lsp_mod.check refuses them): 7xy, E3x..E8x, EEx, EFx.
"""
from __future__ import annotations

from dataclasses import dataclass

from lsp_mod import PERIODS, Cell, ModError, Sample

VIBRATO = (0, 24, 49, 74, 97, 120, 141, 161, 180, 197, 212, 224, 235, 244, 250, 253,
           255, 253, 250, 244, 235, 224, 212, 197, 180, 161, 141, 120, 97, 74, 49, 24)
LOW, HIGH = 113, 856                # where 1xx and 2xx stop
EMPTY = Cell(0, 0, 0, 0)


@dataclass
class Chan:
    sample: int = 0                 # the sample the next note plays
    volume: int = 0
    period: int = 0                 # the note's period, moved by the slides
    out: int = 0                    # the period that sounds
    wanted: int = 0                 # 3xx target, 0 = none
    up: bool = False                # 3xx direction: towards a shorter period
    porta: int = 0                  # 3xx speed
    vib: int = 0                    # 4xy speed << 4 | depth
    vibpos: int = 0
    memo: int = 0                   # 9xx argument
    base: int = 0                   # bytes 9xx has moved the start by
    left: int = 0                   # bytes from there to the end of the sample (0: none, a note cannot start)
    blank: bool = True              # the row before was empty
    trig: int | None = None         # this tick (re)starts the sample at that byte


def _start(ch: Chan) -> None:
    if not ch.left:
        raise ModError("a note without a sample (no sample number on this channel yet, or 9xx ran past its end)")
    ch.trig, ch.out = ch.base, ch.period


def _offset(ch: Chan, arg: int) -> None:
    ch.memo = arg or ch.memo
    step = min(ch.memo * 256, ch.left)
    ch.left, ch.base = ch.left - step, ch.base + step


def _slide(ch: Chan, by: int) -> None:
    p = (ch.period + by) & 0xFFFF
    if by < 0 and p & 0xFFF < LOW:
        p = (p & 0xF000) | LOW
    if by > 0 and p & 0xFFF > HIGH:
        p = (p & 0xF000) | HIGH
    ch.period, ch.out = p, p & 0xFFF


def _target(ch: Chan, note: int) -> None:
    ch.wanted, ch.up = (0 if note == ch.period else note), note < ch.period


def _porta(ch: Chan) -> None:
    if not ch.wanted:
        return
    p = ch.period + (-ch.porta if ch.up else ch.porta)
    if (p <= ch.wanted) if ch.up else (p >= ch.wanted):
        p, ch.wanted = ch.wanted, 0
    ch.period = ch.out = p


def _vibrato(ch: Chan) -> None:
    delta = (VIBRATO[(ch.vibpos >> 2) & 31] * (ch.vib & 15)) >> 7
    ch.out = ch.period + (delta if ch.vibpos < 128 else -delta)
    ch.vibpos = (ch.vibpos + (ch.vib >> 4) * 4) & 0xFF


def _arpeggio(ch: Chan, arg: int, t: int) -> None:
    add = (0, arg >> 4, arg & 15)[t % 3]
    if not add:
        ch.out = ch.period
        return
    note = next((i for i, p in enumerate(PERIODS) if ch.period >= p), None)
    if note is None:
        return
    if note + add >= len(PERIODS):
        raise ModError(f"arpeggio 0{arg:02X} goes above B-3 (ProTracker reads past its period table there)")
    ch.out = PERIODS[note + add]


def _volume(ch: Chan, arg: int) -> None:
    ch.volume = min(64, ch.volume + (arg >> 4)) if arg >> 4 else max(0, ch.volume - (arg & 15))


def _extended(ch: Chan, c: Cell, t: int) -> None:
    x, y = c.arg >> 4, c.arg & 15
    if t == 0 and x in (1, 2):
        _slide(ch, -y if x == 1 else y)
    elif t == 0 and x in (0xA, 0xB):
        ch.volume = min(64, ch.volume + y) if x == 0xA else max(0, ch.volume - y)
    elif x == 9 and y and t % y == 0 and not (t == 0 and c.period):
        _start(ch)
    elif x == 0xC and t == y:
        ch.volume = 0
    elif x == 0xD and t == y and c.period:
        _start(ch)


def _once(ch: Chan, c: Cell) -> None:
    """The end of a row's first tick: the effects that act once."""
    if c.effect == 9:
        _offset(ch, c.arg)
    elif c.effect == 0xC:
        ch.volume = min(c.arg, 64)
    elif c.effect == 0xE:
        _extended(ch, c, 0)
    elif c.effect not in (0xB, 0xD, 0xF):
        ch.out = ch.period


def row(ch: Chan, c: Cell, samples: dict[int, Sample]) -> None:
    """The first tick of a row."""
    ch.trig = None
    if ch.blank:
        ch.out = ch.period
    ch.blank = c == EMPTY
    if c.sample:
        s = samples[c.sample]
        ch.sample, ch.volume, ch.base = c.sample, s.volume, 0
        ch.left = s.loop_start + s.loop_len if s.loop_len else len(s.data)
    if c.period and c.effect in (3, 5):
        _target(ch, c.period)
    elif c.period:
        if c.effect == 9:
            _offset(ch, c.arg)
        ch.period = c.period
        if (c.effect, c.arg >> 4) != (0xE, 0xD):
            ch.vibpos = 0
            _start(ch)
    _once(ch, c)


def tick(ch: Chan, c: Cell, t: int) -> None:
    """Tick t >= 1 of a row."""
    ch.trig = None
    e, a = c.effect, c.arg
    if e == 0 and a == 0:
        return
    if e == 0:
        _arpeggio(ch, a, t)
    elif e in (1, 2):
        _slide(ch, -a if e == 1 else a)
    elif e in (3, 5):
        ch.porta = a if e == 3 and a else ch.porta
        _porta(ch)
    elif e in (4, 6):
        if e == 4:
            ch.vib = ((a & 0xF0) or (ch.vib & 0xF0)) | ((a & 15) or (ch.vib & 15))
        _vibrato(ch)
    elif e == 0xE:
        _extended(ch, c, t)
    else:
        ch.out = ch.period
    if e in (5, 6, 0xA):
        _volume(ch, a)
