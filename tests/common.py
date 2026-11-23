"""Shared parts of the tests: the check list runner and a few small songs. Run a test file with `python3 -I`."""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from lsp_dat import HEAD, VAR, expand, head
from lsp_mod import ModError, parse
from lsp_ref import Player
from lsp_seq import Timeline, simulate
from mod_write import Cells, SampleDef, make_mod

ROOT = Path(__file__).resolve().parent.parent
Check = tuple[str, bool]
SHOT: SampleDef = (bytes([100, 156] * 150), 64, 0, 0, 0)        # one-shot, 300 B: 36.2 ms at period 428
LOOP: SampleDef = (bytes([90, 166] * 200), 64, 0, 0, 400)       # looped over its 400 B
SOFT: SampleDef = (bytes([100, 156] * 150), 48, 0, 0, 0)        # default volume 48
SAMPLES = [SHOT, LOOP, SOFT]
K1, K2 = (1, 428, 64), (2, 428, 64)


def refused(fn: Callable[[], object], words: str) -> bool:
    """True if fn raises a ModError whose message contains words."""
    try:
        fn()
    except ModError as e:
        return words in str(e)
    return False


def sim(patterns: list[Cells], order: list[int] | None = None) -> Timeline:
    return simulate(parse(make_mod(patterns, order or [0], SAMPLES)))


def starts(tl: Timeline) -> list[tuple[int, int, object]]:
    """(tick, channel, variant) of every note start (an event that points at byte 0 of a variant)."""
    return [(t, ch, target[0]) for t, ev in enumerate(tl.ticks) for ch, target in ev if target and target[1] == 0]


def held(tl: Timeline, key: tuple[int, int, int]) -> int:
    """The longest time (ticks) the variant is played from its start."""
    return max(end for start, end in tl.spans[key] if start == 0) // 252


def regs(cells: Cells, n: int, samples: list[SampleDef] | None = None) -> list[tuple[int, int, int | None]]:
    """(period, volume, restart byte or None) of channel 1 on the first n ticks of a one-pattern song."""
    tl = simulate(parse(make_mod([cells], [0], samples or SAMPLES)))
    return [tick[0][1:] for tick in tl.trace[:n]]


def strays(dat: bytes, ticks: int) -> int:
    """Ticks on which a channel of the reference player reads past the end of the variant its last event pointed
    into (it would play the next variant of the bank, and the 68000 and the reference would still agree)."""
    bank, p, bad = expand(dat), Player(dat), 0
    ends = [s + VAR.unpack_from(dat, HEAD.size + VAR.size * i)[5] * 4 for i, s in enumerate(bank.starts)]
    room = [0] * 4
    p.start()
    for _ in range(ticks):
        due = _events(dat, head(dat).off_loop, p.sptr) if p.wait == 1 else set()
        p.tick()                                                # p.ptr is now where each channel's next tick is
        for ch, q in enumerate(p.ptr):
            if q is not None and ch in due:
                room[ch] = next(e for s, e in zip(bank.starts, ends) if s <= q - 252 < e)
            bad += q is not None and q > room[ch]
    return bad


def _events(dat: bytes, loop: int, at: int) -> set[int]:
    """The channels that have an event in the stream record at `at` (the loop record if that is the end mark)."""
    word = int.from_bytes(dat[at:at + 2], "big")
    if word == 0xFFFF:
        at, word = loop, int.from_bytes(dat[loop:loop + 2], "big")
    return {dat[at + 3 + 2 * i] & 3 for i in range(word >> 8)}


def run(name: str, groups: list[Callable[[], list[Check]]]) -> int:
    ok = [c for g in groups for c in g()]
    for text, good in ok:
        print(("ok   " if good else "FAIL ") + text)
    bad = sum(not g for _, g in ok)
    print(f"{name}: {len(ok) - bad} passed, {bad} failed")
    return 1 if bad else 0
