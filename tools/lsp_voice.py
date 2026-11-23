#!/usr/bin/env python3
"""LSPSTE: from what ProTracker asks of a channel (sample, period, volume, restart) to what the player can do:
point the channel at a byte of a variant, or silence it. The player only adds bytes, so a channel changes pitch
or volume in the middle of a note by going on in another variant, at the byte that matches where it is in the
sample: that is an event, like a new note.

Position. Byte `off` of the variant at a period is the sample's position off * step (16.16, lsp_bank.step_for);
a halved rendition holds the average of samples 2j and 2j+1, so there it is 2 * off * step + 0.5: src_pos().
enter() is the way back: the even byte (the mixer reads long words) nearest to a position, so a pitch change
can be up to one output byte off (80 us); a volume change alone gets its own byte back.
Loops. Once a looped sample is in its loop, every position one loop length further sounds the same. enter()
takes the first such position at or after the loop start, or one of the following within SLACK bytes if it is
nearer to an even byte: a looped variant then only has to hold its start, one turn of the loop and the longest
time it plays untouched, and a short loop (a chip waveform) is entered nearly exactly. (A volume change far
into a long loop is taken back like that too, and can then be up to a byte off.)
"""
from __future__ import annotations

from dataclasses import dataclass

from lsp_bank import TICK, Key, natural_bytes, step_for
from lsp_mod import ModError, Module, Sample

Target = tuple[Key, int]            # a variant and the byte in it (even, from the start of the note)
SLACK = TICK                        # bytes above the first equivalent offset a loop may be entered at
PERIOD_MIN, PERIOD_MAX = 57, 4095   # one octave above B-3 .. 12 bits (a 1xx that wrapped, on its own row)


def src_pos(period: int, off: int) -> int:
    """The sample position (16.16) of byte `off` of the variant at this period."""
    shift, step = step_for(period)
    return ((off * step) << shift) + (shift << 15)


def ended(s: Sample, period: int, off: int) -> bool:
    """True when byte `off` and all that follow are past the end of a one-shot sample."""
    return not s.loop_len and off >= natural_bytes(s, period)


def enter(s: Sample, period: int, pos: int) -> int:
    """The even byte of the variant at this period that goes on from sample position pos (16.16)."""
    shift, step = step_for(period)
    unit, lap, start = step << shift, s.loop_len << 16, s.loop_start << 16
    pos -= shift << 15
    if lap and pos >= start:
        pos = start + (pos - start) % lap
    last = pos + SLACK * unit if lap and pos >= start else pos
    best: tuple[int, int] | None = None
    while pos <= last:
        off = max(0, 2 * ((pos + unit) // (2 * unit)))
        err = abs(off * unit - pos)
        if best is None or err < best[0]:
            best = (err, off)
        pos += lap or 1 << 62
    assert best is not None
    return best[1]


@dataclass
class Voice:
    """What a channel is playing: sample 0 = nothing. `off` is the byte of the next tick."""
    sample: int = 0
    period: int = 0
    volume: int = 0
    off: int = 0

    def target(self) -> Target | None:
        return ((self.sample, self.period, self.volume), self.off) if self.sample and self.volume else None

    def view(self, mod: Module) -> tuple[int, int, int, int]:
        """The voice for loop detection: the byte inside a loop is left out (it never comes back exactly). A silent
        voice that still runs counts (its volume may come back)."""
        s = mod.samples.get(self.sample)
        if s is None:
            return (0, 0, 0, -1)
        looping = s.loop_len and src_pos(self.period, self.off) >= s.loop_start << 16
        return (self.sample, self.period, self.volume, -1 if looping else self.off)


def _move(v: Voice, s: Sample, period: int, volume: int) -> None:
    if ended(s, v.period, v.off):
        v.sample = 0
    elif (period, volume) != (v.period, v.volume):
        v.off = enter(s, period, src_pos(v.period, v.off))
        v.period, v.volume = period, volume


def step(v: Voice, mod: Module, sample: int, period: int, volume: int, trig: int | None) -> tuple[bool, Target | None]:
    """Play one tick. (True if the channel needs an event, its target or None for silence)."""
    before = v.target()
    if (trig is not None or v.sample) and not PERIOD_MIN <= period <= PERIOD_MAX:
        raise ModError(f"period {period} is outside {PERIOD_MIN}..{PERIOD_MAX}")
    if trig is not None:
        v.sample, v.period, v.volume = sample, period, volume
        v.off = enter(mod.samples[sample], period, trig << 16)
    elif v.sample:
        _move(v, mod.samples[v.sample], period, volume)
    now = v.target()
    v.off += TICK
    return now != before, now
