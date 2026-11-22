"""Shared parts of the tests: the check list runner and a few small songs. Run a test file with `python3 -I`."""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from lsp_mod import ModError, parse
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
    return [(t, ch, key) for t, ev in enumerate(tl.ticks) for ch, key in ev if key]


def run(name: str, groups: list[Callable[[], list[Check]]]) -> int:
    ok = [c for g in groups for c in g()]
    for text, good in ok:
        print(("ok   " if good else "FAIL ") + text)
    bad = sum(not g for _, g in ok)
    print(f"{name}: {len(ok) - bad} passed, {bad} failed")
    return 1 if bad else 0
