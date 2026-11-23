#!/usr/bin/env python3
"""LSPSTE: the song side. Play the module tick by tick (off line) into a timeline of channel events, find where
it loops, and encode it as the stream the 68000 player reads: one record per tick that has events.

Timeline: per tick, (channel, target) to point the channel at a byte of a variant (a new note starts at byte 0,
an effect goes on elsewhere: lsp_voice.py) or (channel, None) to silence it. A one-shot sample gets its stop when
it has played out, so the mixer never tests for a sample's end. The song loops when the whole player state
(position, row, speed, every channel of lsp_pt.py and what it plays) comes back: `loop` is that tick.
`spans` is what the player reads of each variant, (first byte, end) per run, found by following the events as the
player does over the intro and two more passes of the loop.
Stream (big-endian words): record = (events << 8 | ticks until the next record, 1..255), then per event
(target << 2 | channel), target = index in the file's target table, 0 = silence; $FFFF = jump to the loop record.
"""
from __future__ import annotations

import struct
from dataclasses import astuple, dataclass

from lsp_bank import TICK, Key
from lsp_mod import CHANNELS, ROWS, Cell, ModError, Module, check
from lsp_pt import Chan, row, tick
from lsp_voice import Target, Voice, step

Event = tuple[int, "Target | None"]
Paula = tuple[int, int, int, "int | None"]      # sample, period, volume, byte the sample restarts at (or None)
Spans = dict[Key, tuple[tuple[int, int], ...]]
MAX_ROWS = 1 << 16                  # a song that has not looped by then is refused
MAX_WAIT = 255
END = 0xFFFF


@dataclass(frozen=True)
class Timeline:
    ticks: tuple[tuple[Event, ...], ...]
    loop: int                       # after the last tick the song continues at this one
    spans: Spans                    # the bytes of each variant that are played
    trace: tuple[tuple[Paula, ...], ...]    # per tick and channel, what ProTracker's registers hold


def _swap(c: Cell, v: Voice) -> None:
    if c.sample and not c.period and v.sample and c.sample != v.sample:
        raise ModError(f"sample number {c.sample} without a note while sample {v.sample} plays "
                       "(ProTracker would change samples at the end of the loop: not supported)")


def _tick(mod: Module, chans: list[Chan], voices: list[Voice], cells: list[Cell], t: int,
          where: str) -> tuple[tuple[Event, ...], tuple[Paula, ...]]:
    out: list[Event] = []
    regs: list[Paula] = []
    for ch in range(CHANNELS):
        c, v = chans[ch], voices[ch]
        try:
            if t == 0:
                _swap(cells[ch], v)
                row(c, cells[ch], mod.samples)
            else:
                tick(c, cells[ch], t)
            changed, target = step(v, mod, c.sample, c.out, c.volume, c.trig)
        except ModError as e:
            raise ModError(f"{where} channel {ch + 1}: {e}") from None
        regs.append((c.sample, c.out, c.volume, c.trig))
        if changed:
            out.append((ch, target))
    return tuple(out), tuple(regs)


def _next(mod: Module, pos: int, row_: int, cells: list[Cell]) -> tuple[int, int]:
    jump = next((c.arg for c in reversed(cells) if c.effect == 0xB), None)
    brk = next(((c.arg >> 4) * 10 + (c.arg & 15) for c in reversed(cells) if c.effect == 0xD), None)
    if jump is None and brk is None:
        pos, row_ = (pos, row_ + 1) if row_ + 1 < ROWS else (pos + 1, 0)
    else:
        pos, row_ = (pos + 1 if jump is None else jump), (brk or 0)
    return (pos if pos < len(mod.order) else 0), row_


def _spans(ticks: list[tuple[Event, ...]], loop: int) -> Spans:
    """The runs of each variant the player reads, over the intro and two more passes of the loop."""
    span = ticks + ticks[loop:] * 2
    last_pass = len(span) - (len(ticks) - loop)
    runs: dict[Key, set[tuple[int, int]]] = {}
    cur: list[tuple[Target, int] | None] = [None] * CHANNELS
    for t, events in enumerate(span):
        for ch, target in events:
            old = cur[ch]
            if old:
                runs.setdefault(old[0][0], set()).add((old[0][1], old[0][1] + (t - old[1]) * TICK))
            cur[ch] = (target, t) if target else None
    for ch, old in enumerate(cur):
        if old and old[1] < last_pass:
            raise ModError(f"channel {ch + 1}: looped sample {old[0][0][0]} is never replaced or cut "
                           "(it would play for ever)")
    return {k: tuple(sorted(v)) for k, v in runs.items()}


def _shrink(ticks: list[tuple[Event, ...]], loop: int, tags: list[object]) -> int:
    """Ticks to drop from the end, moving the loop as far back. The state of lsp_pt.py holds things that may never
    matter again (a channel's last sample number), so the loop can be found late. While the tick before the loop
    and the last tick are the same tick of the song (tags) with the same events, the song can as well jump one
    tick earlier: after the jump the player gets the events it would have got."""
    cut = 0
    while cut < loop and (tags[a := loop - cut - 1], ticks[a]) == (tags[b := -cut - 1], ticks[b]):
        cut += 1
    return cut


def simulate(mod: Module) -> Timeline:
    pos, row_, speed = 0, 0, 6
    chans, voices = [Chan() for _ in range(CHANNELS)], [Voice() for _ in range(CHANNELS)]
    ticks: list[tuple[Event, ...]] = []
    trace: list[tuple[Paula, ...]] = []
    seen: dict[object, int] = {}
    tags: list[object] = []
    for _ in range(MAX_ROWS):
        state = (pos, row_, speed, tuple(astuple(c) for c in chans), tuple(v.view(mod) for v in voices))
        if state in seen:
            loop = seen[state]
            cut = _shrink(ticks, loop, tags)
            ticks, trace, loop = ticks[:len(ticks) - cut], trace[:len(trace) - cut], loop - cut
            return Timeline(tuple(ticks), loop, _spans(ticks, loop), tuple(trace))
        seen[state] = len(ticks)
        where = f"pattern {mod.order[pos]} row {row_}"
        cells = [mod.cell(mod.order[pos], row_, ch) for ch in range(CHANNELS)]
        for ch, c in enumerate(cells):
            check(mod, c, f"{where} channel {ch + 1}")
        speed = next((c.arg for c in reversed(cells) if c.effect == 0xF), speed)
        for t in range(speed):
            events, regs = _tick(mod, chans, voices, cells, t, where)
            ticks.append(events)
            tags.append((pos, row_, t, speed))
            trace.append(regs)
        pos, row_ = _next(mod, pos, row_, cells)
    raise ModError(f"the song does not loop within {MAX_ROWS} rows")


def encode(tl: Timeline, index: dict[Target, int]) -> tuple[bytes, int]:
    """(stream, offset of the loop record in it). index: the target table entry of each target (1 and up)."""
    marks = sorted({0, tl.loop} | {t for t, ev in enumerate(tl.ticks) if ev})
    recs: list[int] = []
    for a, b in zip(marks, marks[1:] + [len(tl.ticks)]):
        recs += range(a, b, MAX_WAIT)
    out, loop_off = bytearray(), 0
    for a, b in zip(recs, recs[1:] + [len(tl.ticks)]):
        if a == tl.loop:
            loop_off = len(out)
        out += struct.pack(">H", (len(tl.ticks[a]) << 8) | (b - a))
        for ch, target in tl.ticks[a]:
            out += struct.pack(">H", ((index[target] if target else 0) << 2) | ch)
    return bytes(out) + struct.pack(">H", END), loop_off
