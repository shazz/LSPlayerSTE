#!/usr/bin/env python3
"""Tests for the converter, song side (lsp_mod, lsp_seq) and the demo module's design. Run: python3 -I tests/test_song.py
Expected values come from the ProTracker rules, the formats in the tool docstrings and the design written in
tools/make_demo.py, not from running the code."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import K1, K2, ROOT, SAMPLES, SHOT, Check, held, refused, run, sim, starts
from lsp_mod import parse
from lsp_seq import encode, simulate
from make_demo import module
from mod_write import make_mod


def subset_checks() -> list[Check]:
    def bad(cell: tuple[int, int, int, int], words: str, samples: list[tuple[bytes, int, int, int, int]] = SAMPLES) -> bool:
        return refused(lambda: simulate(parse(make_mod([{(0, 0): cell, (1, 0): (0, 0, 0xB, 0)}], [0], samples))), words)
    tuned = [(SHOT[0], 64, 3, 0, 0)]
    junk = sim([{(0, 0): (1, 428, 0xD, 0), (1, 0): (1, 428, 7, 5)}])       # row 1 is never played
    return [
        ("subset: effect 7xy (tremolo) is refused, with its place",
         bad((1, 428, 7, 5), "pattern 0 row 0 channel 1: effect 705 is not supported")),
        ("subset: the refusal lists what is supported (0xy .. Fxx)",
         bad((1, 428, 7, 5), "the player has 0xy arpeggio, 1xx 2xx 3xx portamento, 4xy vibrato")
         and bad((1, 428, 7, 5), "Bxx position jump, Cxx volume, Dxx pattern break")),
        ("subset: E6x (pattern loop) is refused", bad((1, 428, 0xE, 0x62), "effect E62")),
        ("subset: Fxx above 31 (tempo) is refused", bad((0, 0, 0xF, 0x7D), "effect F7D")),
        ("subset: finetune 3 is refused", bad((1, 428, 0, 0), "finetune 3", tuned)),
        ("subset: a period outside the ProTracker table is refused", bad((1, 430, 0, 0), "period 430")),
        ("subset: an empty sample is refused", bad((9, 428, 0, 0), "sample 9 is empty")),
        ("subset: a D break to row 64 or more is refused", bad((0, 0, 0xD, 0x70), "breaks to row 70")),
        ("subset: a bad tag is refused", refused(lambda: parse(bytes(2000)), "not a 4-channel ProTracker module")),
        ("subset: rows after a pattern break are not checked (D00 on row 0: only that row plays, 6 ticks)",
         len(junk.ticks) == 6),
    ]


def timing_checks() -> list[Check]:
    f3 = sim([{(0, 0): (1, 428, 0, 0), (0, 1): (0, 0, 0xF, 3), (1, 0): (1, 428, 0, 0), (2, 0): (1, 428, 0xD, 0)}])
    d5 = sim([{(0, 0): (1, 428, 0, 0), (1, 0): (0, 0, 0xD, 5)}, {(5, 0): (2, 428, 0, 0), (6, 0): (0, 0, 0xB, 0)}], [0, 1])
    wrap = sim([{(0, 0): (1, 428, 0, 0)}])
    jump = sim([{(0, 0): (2, 428, 0, 0), (1, 0): (0, 0, 0xD, 0)}, {(0, 0): (1, 428, 0, 0), (1, 1): (0, 0, 0xB, 1)}], [0, 1])
    vol = sim([{(0, 0): (1, 428, 0xC, 0x20), (1, 0): (3, 428, 0, 0), (2, 0): (0, 0, 0xB, 0)}])
    return [
        ("timing: default speed 6, 64 rows: the pattern lasts 384 ticks and the song wraps to position 0",
         len(wrap.ticks) == 384 and wrap.loop == 0 and starts(wrap) == [(0, 0, K1)]),
        ("timing: F03 on row 0 applies to that row: notes at ticks 0, 3, 6, pattern break after row 2: a pass is 9 ticks",
         starts(f3)[:3] == [(0, 0, K1), (3, 0, K1), (6, 0, K1)] and len(f3.ticks) - f3.loop == 9 and f3.loop in (0, 3)),
        ("timing: D05 on row 1 continues at row 5 of the next position (tick 12), B00 on its row 6 ends at tick 24",
         starts(d5)[:2] == [(0, 0, K1), (12, 0, K2)] and len(d5.ticks) - d5.loop == 24),
        ("timing: B01 loops to position 1: intro 12 ticks, then a loop of 12",
         (len(jump.ticks), jump.loop) == (24, 12) and starts(jump) == [(0, 0, K2), (12, 0, K1)]),
        ("timing: Cxx on a note bakes the volume; without it the sample's default volume",
         [k for _, _, k in starts(vol)] == [(1, 428, 32), (3, 428, 48)]),
    ]


def loop_checks() -> list[Check]:
    cut = sim([{(0, 0): (2, 428, 0, 0), (0, 1): (1, 428, 0, 0), (4, 0): (0, 0, 0xC, 0), (9, 0): (0, 0, 0xB, 0)}])
    full = sim([{(0, 0): (2, 428, 0, 0), (9, 0): (0, 0, 0xB, 0)}])
    over = sim([{(9, 0): (2, 428, 0, 0), (9, 1): (0, 0, 0xD, 0)},
                {(1, 0): (0, 0, 0xC, 0), (2, 0): (2, 428, 0, 0), (9, 1): (0, 0, 0xB, 1)}], [0, 1])
    events = [(t, ev) for t, ev in enumerate(cut.ticks) if ev]
    return [
        ("loops: a 300 B one-shot at period 428 lasts 453.1 output samples = 2 ticks: stop event at tick 2",
         (2, ((1, None),)) in events and cut.spans[K1] == ((0, 2 * 252),)),
        ("loops: C00 alone cuts the channel at its row (row 4 = tick 24); the looped note was held 24 ticks",
         (24, ((0, None),)) in events and cut.spans[K2] == ((0, 24 * 252),)),
        ("loops: a looped note restarted every pass is held for the whole pass (10 rows = 60 ticks)",
         full.spans[K2] == ((0, 60 * 252),) and len(full.ticks) - full.loop == 60),
        (("loops: a note that sounds across the song's loop is held to its cut in the next pass (row 2 to row 1: "
          "54 ticks), not only as long as the intro's (12 ticks)"),
         over.spans[K2] == ((0, 12 * 252), (0, 54 * 252)) and over.loop == 60),
        ("loops: a looped note that nothing replaces or cuts is refused",
         refused(lambda: sim([{(0, 0): (2, 428, 0, 0)}, {(0, 0): (0, 0, 0xB, 1)}], [0, 1]), "never replaced or cut")),
    ]


def stream_checks() -> list[Check]:
    tl = sim([{(0, 0): (2, 428, 0, 0), (1, 1): (1, 428, 0, 0), (2, 0): (0, 0, 0xC, 0), (63, 3): (0, 0, 0xB, 0)}])
    raw, loop_off = encode(tl, {(K1, 0): 12, (K2, 0): 15})
    words = list(struct.unpack(f">{len(raw) // 2}H", raw))
    # ticks: 0 start K2 on ch 1; 6 start K1 on ch 2; 8 K1 has played out; 12 cut ch 1; then nothing until tick 384
    want = [0x0106, 15 << 2, 0x0102, 12 << 2 | 1, 0x0104, 1, 0x01FF, 0, 0x0075, 0xFFFF]
    return [
        (("stream: records (events << 8 | wait), events (target << 2 | channel, target 0 = silence), a wait over "
          "255 split by an empty record, $FFFF at the end"), words == want),
        ("stream: the loop record of a song looping to tick 0 is the first", loop_off == 0),
    ]


def demo_checks() -> list[Check]:
    raw = module()
    tl = simulate(parse(raw))
    disk = simulate(parse((ROOT / "assets/demo.mod").read_bytes()))
    cells = [raw[1084 + p * 1024 + (r * 4 + c) * 4:][:4] for p in range(3) for r in range(64) for c in range(4)]
    effects = {b[2] & 0x0F for b in cells if b[2] & 0x0F or b[3]}
    events = [(t, ev) for t, ev in enumerate(tl.ticks) if ev]
    bass, lead, hold = 2, 4, {k: held(tl, k) for k in tl.spans}
    return [
        (("demo: intro 32 rows x 5 = 160 ticks (D00 on row 31); loop = 64 rows x 5 + 32 x 5 + 8 x 6 + 8 x 5 = 568; "
          "the stream is 728 ticks and loops to tick 160"), len(tl.ticks) == 728 and tl.loop == 160),
        ("demo: the committed assets/demo.mod has the same timeline", len(disk.ticks) == 728 and disk.loop == 160),
        ("demo: notes of the design = start events: intro 16 + 12, loop 3 x 20 + 15 + 2 x 20 + 15 = 158",
         len(starts(tl)) == 158),
        ("demo: 16 variants = kick 1 + hat 1 + bass 8 (A F G E, two octaves) + lead 6 (214 190 170 160 143 127)",
         len(hold) == 16 and sum(1 for k in hold if k[0] == bass) == 8 and sum(1 for k in hold if k[0] == lead) == 6),
        ("demo: a 1,400 B kick at period 428 plays 9 ticks and a 600 B hat at period 254 plays 3, then stop events",
         hold[(1, 428, 64)] == 9 and hold[(3, 254, 32)] == 3),
        ("demo: bass notes last 2 rows (10 ticks), but 12 in the slow rows 32..39 of the third bar of pattern 2 (G)",
         hold[(2, 508, 48)] == 10 and hold[(2, 570, 48)] == 12 and hold[(2, 285, 48)] == 12),
        ("demo: lead notes last 4 rows (20 ticks), 24 for 190 and 160 which sit in the slow rows",
         hold[(4, 143, 48)] == 20 and hold[(4, 190, 48)] == 24 and hold[(4, 160, 48)] == 24),
        ("demo: the bass is cut by C00 on row 28 of the intro (tick 140), nothing else stops then",
         (140, ((1, None),)) in events),
        ("demo: the song uses B, C, D and F and nothing else", effects == {0xB, 0xC, 0xD, 0xF}),
    ]


def main() -> int:
    return run("song tests", [subset_checks, timing_checks, loop_checks, stream_checks, demo_checks])


if __name__ == "__main__":
    sys.exit(main())
