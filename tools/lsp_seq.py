#!/usr/bin/env python3
"""LSPSTE: the song side. Play the module tick by tick (off line) into a timeline of channel events, find where
it loops, and encode it as the stream the 68000 player reads: one record per tick that has events.

Timeline: per tick, (channel, key) to start a variant or (channel, None) to silence the channel. A one-shot sample
gets its stop when it has played out, so the mixer never tests for a sample's end. The song loops when the whole
player state (position, row, speed, what each channel plays and for how long) comes back: `loop` is that tick.
Stream (big-endian words): record = (events << 8 | ticks until the next record, 1..255), then per event
(channel << 14 | offset of the variant's table entry in the file, 0 = silence); $FFFF = jump to the loop record.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from lsp_bank import Key, natural_ticks
from lsp_mod import CHANNELS, ROWS, Action, ModError, Module, action

Event = tuple[int, "Key | None"]
MAX_ROWS = 1 << 16                  # a song that has not looped by then is refused
MAX_WAIT = 255
END = 0xFFFF


@dataclass(frozen=True)
class Timeline:
    ticks: tuple[tuple[Event, ...], ...]
    loop: int                       # after the last tick the song continues at this one
    hold: dict[Key, int]            # the longest time (ticks) each variant sounds


def _tick(mod: Module, chans: list[tuple[Key, int] | None], acts: list[Action] | None) -> tuple[Event, ...]:
    out: list[Event] = []
    for ch in range(CHANNELS):
        cur, act = chans[ch], (acts[ch] if acts else Action())
        if act.key:
            out.append((ch, act.key))
            cur = (act.key, 0)
        elif cur and (act.cut or cur[1] == natural_ticks(mod.samples[cur[0][0]], cur[0][1])):
            out.append((ch, None))
            cur = None
        chans[ch] = (cur[0], cur[1] + 1) if cur else None
    return tuple(out)


def _next(mod: Module, pos: int, row: int, acts: list[Action]) -> tuple[int, int]:
    jump = next((a.jump for a in reversed(acts) if a.jump is not None), None)
    brk = next((a.brk for a in reversed(acts) if a.brk is not None), None)
    if jump is None and brk is None:
        pos, row = (pos, row + 1) if row + 1 < ROWS else (pos + 1, 0)
    else:
        pos, row = (pos + 1 if jump is None else jump), (brk or 0)
    return (pos if pos < len(mod.order) else 0), row


def _hold(ticks: list[tuple[Event, ...]], loop: int) -> dict[Key, int]:
    """Longest sounding time per variant, over the intro and two more passes of the loop."""
    span = ticks + ticks[loop:] * 2
    last_pass = len(span) - (len(ticks) - loop)
    hold: dict[Key, int] = {}
    cur: list[tuple[Key, int] | None] = [None] * CHANNELS
    for t, events in enumerate(span):
        for ch, key in events:
            old = cur[ch]
            if old:
                hold[old[0]] = max(hold.get(old[0], 0), t - old[1])
            cur[ch] = (key, t) if key else None
    for ch, old in enumerate(cur):
        if old and old[1] < last_pass:
            raise ModError(f"channel {ch + 1}: looped sample {old[0][0]} is never replaced or cut (it would play for ever)")
    return hold


def simulate(mod: Module) -> Timeline:
    pos, row, speed = 0, 0, 6
    chans: list[tuple[Key, int] | None] = [None] * CHANNELS
    ticks: list[tuple[Event, ...]] = []
    seen: dict[object, int] = {}
    for _ in range(MAX_ROWS):
        view = tuple(c and (c[0], c[1] if natural_ticks(mod.samples[c[0][0]], c[0][1]) else -1) for c in chans)
        state = (pos, row, speed, view)
        if state in seen:
            return Timeline(tuple(ticks), seen[state], _hold(ticks, seen[state]))
        seen[state] = len(ticks)
        acts = [action(mod, mod.order[pos], row, ch) for ch in range(CHANNELS)]
        speed = next((a.speed for a in reversed(acts) if a.speed), speed)
        for t in range(speed):
            ticks.append(_tick(mod, chans, acts if t == 0 else None))
        pos, row = _next(mod, pos, row, acts)
    raise ModError(f"the song does not loop within {MAX_ROWS} rows")


def encode(tl: Timeline, voff: dict[Key, int]) -> tuple[bytes, int]:
    """(stream, offset of the loop record in it)."""
    marks = sorted({0, tl.loop} | {t for t, ev in enumerate(tl.ticks) if ev})
    recs: list[int] = []
    for a, b in zip(marks, marks[1:] + [len(tl.ticks)]):
        recs += range(a, b, MAX_WAIT)
    out, loop_off = bytearray(), 0
    for a, b in zip(recs, recs[1:] + [len(tl.ticks)]):
        if a == tl.loop:
            loop_off = len(out)
        out += struct.pack(">H", (len(tl.ticks[a]) << 8) | (b - a))
        for ch, key in tl.ticks[a]:
            out += struct.pack(">H", (ch << 14) | (voff[key] if key else 0))
    return bytes(out) + struct.pack(">H", END), loop_off
