#!/usr/bin/env python3
"""Tests for the ProTracker effects (lsp_pt.py), on what the tracker's registers hold tick by tick: period, volume,
and where a sample restarts. Run: python3 -I tests/test_fx.py
Expected values are worked out by hand from the ProTracker 2.3 rules (period table, vibrato table, the tick each
effect acts on), written in each claim; speed is 6 ticks per row, sample 1 has volume 64 and sample 3 volume 48."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import Check, refused, regs, run, sim
from mod_write import Cells, SampleDef

BIG: SampleDef = (bytes([100, 156] * 512), 64, 0, 0, 0)         # 1,024 B, for 9xx


def per(cells: Cells, n: int = 6) -> list[int]:
    return [r[0] for r in regs(cells, n)]


def vol(cells: Cells, n: int = 6) -> list[int]:
    return [r[1] for r in regs(cells, n)]


def trig(cells: Cells, n: int = 6, samples: list[SampleDef] | None = None) -> list[int | None]:
    return [r[2] for r in regs(cells, n, samples)]


def pitch_checks() -> list[Check]:
    return [
        ("0xy: 047 on C-2 (428) plays C-2, E-2 (339), G-2 (285) on ticks 0 1 2 and again; the next row is C-2",
         per({(0, 0): (1, 428, 0, 0x47)}, 12) == [428, 339, 285] * 2 + [428] * 6),
        ("0xy: 002 on A-3 (127): x = 0 keeps the note on tick 1, tick 2 is B-3 (113)",
         per({(0, 0): (1, 127, 0, 0x02)}, 3) == [127, 127, 113]),
        ("0xy: 007 on A-3 would go above B-3: refused, with the place",
         refused(lambda: sim([{(0, 0): (1, 127, 0, 0x07)}]), "pattern 0 row 0 channel 1: arpeggio 007 goes above B-3")),
        ("1xx: 105 from 428 takes 5 off on ticks 1..5 (not on tick 0): 423 418 413 408 403, and the note stays there",
         per({(0, 0): (1, 428, 1, 5)}, 12) == [428, 423, 418, 413, 408, 403] + [403] * 6),
        ("1xx: 10F from A#3 (120) stops at 113", per({(0, 0): (1, 120, 1, 0x0F)}) == [120, 113, 113, 113, 113, 113]),
        ("1xx: a step larger than the period wraps in 12 bits (ProTracker's own bug: a very low note, no stop at "
         "113): 1FF from 120 gives 120 - 255 = -135 -> 3961, then 3706; the row after would play the whole 16-bit "
         "word (120 - 5 x 255 = -1155 -> 64381) if the sample still sounds: refused",
         per({(0, 0): (1, 120, 1, 0xFF)}, 3) == [120, 3961, 3706]
         and refused(lambda: regs({(0, 0): (1, 120, 1, 0xFF)}, 12, [BIG]),
                     "pattern 0 row 1 channel 1: period 64381 is outside 57..4095")),
        ("2xx: 220 from C#1 (808) goes to 840 and stops at 856",
         per({(0, 0): (1, 808, 2, 0x20)}) == [808, 840, 856, 856, 856, 856]),
        ("E1x E2x: once, on tick 0: E12 from 428 is 426 for the whole row and after it, E21 is 429",
         per({(0, 0): (1, 428, 0xE, 0x12)}, 12) == [426] * 12 and per({(0, 0): (1, 428, 0xE, 0x21)}) == [429] * 6),
    ]


def porta_checks() -> list[Check]:
    up: Cells = {(0, 0): (1, 428, 0, 0), (1, 0): (1, 381, 3, 0x10), (2, 0): (0, 0, 3, 0)}
    down: Cells = {(0, 0): (1, 381, 0, 0), (1, 0): (0, 428, 3, 0x20)}
    memo: Cells = {(0, 0): (1, 428, 0, 0), (1, 0): (0, 320, 3, 8), (2, 0): (0, 0, 3, 0)}
    both: Cells = {(0, 0): (1, 428, 0, 0), (1, 0): (0, 320, 3, 8), (2, 0): (0, 0, 5, 0x02)}
    return [
        ("3xx: a note with 310 is the target, not a new note: from 428 towards 381 by 16 a tick, 412 396, then 381 "
         "(not 380); 300 after the target is reached changes nothing",
         per(up, 18)[6:] == [428, 412, 396, 381, 381, 381] + [381] * 6 and trig(up, 18)[6:] == [None] * 12),
        ("3xx: towards a longer period it adds: 381 -> 413 -> 428", per(down, 12)[6:] == [381, 413, 428, 428, 428, 428]),
        ("3xx: 300 goes on with the speed and target of the row before: 308 then 300 from 428: 8 a tick for 10 ticks",
         per(memo, 18)[6:] == [428, 420, 412, 404, 396, 388, 388, 380, 372, 364, 356, 348]),
        ("5xy: goes on with the slide of 3xx and slides the volume: 502 = 8 a tick and 2 off the volume",
         per(both, 18)[12:] == [388, 380, 372, 364, 356, 348] and vol(both, 18)[12:] == [64, 62, 60, 58, 56, 54]),
        ("5xy: a note on its row is a target too (no restart); its sample number still sets the volume",
         trig({(0, 0): (1, 428, 0, 0), (1, 0): (3, 320, 5, 0x02)}, 12)[6:] == [None] * 6
         and vol({(0, 0): (1, 428, 0, 0), (1, 0): (3, 320, 5, 0x02)}, 12)[6:] == [48, 46, 44, 42, 40, 38]),
    ]


def vibrato_checks() -> list[Check]:
    vib: Cells = {(0, 0): (1, 428, 4, 0x82), (1, 0): (0, 0, 4, 0), (2, 0): (0, 0, 0xC, 0x20)}
    return [
        ("4xy: 482 (speed 8, depth 2): the table is read every 8th entry, 0 180 255 180 0, times 2 / 128: "
         "+0 +2 +3 +2 on ticks 1..4, then the negative half starts with 0; tick 0 is the note",
         per(vib) == [428, 428, 430, 431, 430, 428]),
        ("4xy: 400 goes on where it was: -2 -3 -2 0 +2", per(vib, 12)[6:] == [428, 426, 425, 426, 428, 430]),
        ("4xy: the row after (C20 here) leaves the last period on its tick 0 and is back on the note from tick 1",
         per(vib, 18)[12:] == [430, 428, 428, 428, 428, 428]),
        ("4xy: 403 after 482 keeps speed 8 and takes depth 3: 180 * 3 / 128 = 4, 255 * 3 / 128 = 5",
         per({(0, 0): (1, 428, 4, 0x82), (1, 0): (0, 0, 4, 0x03)}, 12)[6:] == [428, 424, 423, 424, 428, 432]),
        ("4xy: a new note starts the vibrato again from 0",
         per({(0, 0): (1, 428, 4, 0x82), (1, 0): (1, 428, 4, 0x82)}, 12)[6:] == [428, 428, 430, 431, 430, 428]),
        ("6xy: goes on with the vibrato of 4xy and slides the volume: 602 = 2 off a tick",
         per({(0, 0): (1, 428, 4, 0x82), (1, 0): (0, 0, 6, 0x02)}, 12)[6:] == [428, 426, 425, 426, 428, 430]
         and vol({(0, 0): (1, 428, 4, 0x82), (1, 0): (0, 0, 6, 0x02)}, 12)[6:] == [64, 62, 60, 58, 56, 54]),
    ]


def volume_checks() -> list[Check]:
    inside: Cells = {(0, 0): (1, 428, 0, 0), (1, 0): (0, 0, 0xC, 0x20), (2, 0): (0, 428, 0, 0), (3, 0): (1, 0, 0, 0)}
    return [
        ("Axy: A02 takes 2 off on ticks 1..5: 64 62 60 58 56 54", vol({(0, 0): (1, 428, 0xA, 0x02)}) == [64, 62, 60, 58, 56, 54]),
        ("Axy: A30 adds 3 a tick from 48 and stops at 64; with both digits the first counts (A31 adds 3)",
         vol({(0, 0): (3, 428, 0xA, 0x30), (1, 0): (0, 0, 0xA, 0x31)}, 12) == [48, 51, 54, 57, 60, 63, 63, 64, 64, 64, 64, 64]),
        ("Axy: stops at 0: C03 then A02 gives 3 1 0 0",
         vol({(0, 0): (1, 428, 0xC, 0x03), (1, 0): (0, 0, 0xA, 0x02)}, 10)[6:] == [3, 1, 0, 0]),
        ("Cxx inside a note changes the volume and restarts nothing; a note without a sample number restarts the "
         "sample at that volume; a sample number alone gives the sample's own volume back",
         vol(inside, 24)[::6] == [64, 32, 32, 64] and trig(inside, 24)[::6] == [0, None, 0, None]),
        ("Cxx above 40 is 64", vol({(0, 0): (1, 428, 0xC, 0x50)}, 1) == [64]),
        ("EAx EBx: once, on tick 0: EA4 from 48 is 52, EB4 is 44, EAF from 64 stays 64",
         vol({(0, 0): (3, 428, 0xE, 0xA4)}) == [52] * 6 and vol({(0, 0): (3, 428, 0xE, 0xB4)}) == [44] * 6
         and vol({(0, 0): (1, 428, 0xE, 0xAF)}) == [64] * 6),
        ("ECx: EC2 sets the volume to 0 on tick 2, and it stays 0",
         vol({(0, 0): (1, 428, 0xE, 0xC2)}, 12) == [64, 64] + [0] * 10),
    ]


def trigger_checks() -> list[Check]:
    late: Cells = {(0, 0): (1, 428, 0, 0), (1, 0): (3, 214, 0xE, 0xD3)}
    off: Cells = {(0, 0): (1, 428, 9, 0x01), (1, 0): (0, 428, 0, 0), (2, 0): (1, 428, 9, 0), (3, 0): (1, 428, 0, 0)}
    return [
        ("E0x (the Amiga's filter) changes nothing: the note starts on tick 0 at its period and volume",
         regs({(0, 0): (1, 428, 0xE, 0x01)}, 2) == [(428, 64, 0), (428, 64, None)]),
        ("E9x: E92 restarts the sample every 2 ticks (the note itself is the first); on a row without a note E93 "
         "restarts on ticks 0 and 3",
         trig({(0, 0): (1, 428, 0xE, 0x92)}) == [0, None, 0, None, 0, None]
         and trig({(0, 0): (1, 428, 0, 0), (1, 0): (0, 0, 0xE, 0x93)}, 12)[6:] == [0, None, None, 0, None, None]),
        ("EDx: ED3 starts the note on tick 3: the old note sounds until then (at the new sample's volume)",
         trig(late, 12)[6:] == [None, None, None, 0, None, None] and per(late, 12)[6:] == [428, 428, 428, 214, 214, 214]
         and vol(late, 12)[6:] == [48] * 6),
        ("EDx: a delay of the row's length or more never starts the note",
         trig({(0, 0): (1, 428, 0xE, 0xD6)}) == [None] * 6),
        ("9xx: 901 starts the sample 256 bytes in; ProTracker moves the start twice on a row with a note, so the "
         "next note without a sample number starts at 512; 900 with a sample number starts at 256 again (9xx "
         "remembers its argument, the number resets the start); a plain note with its number starts at 0",
         trig(off, 24, [BIG])[::6] == [256, 512, 256, 0]),
        ("9xx: without a note it moves the start of the notes that follow: 902 then a note starts at 512",
         trig({(0, 0): (1, 428, 0, 0), (1, 0): (0, 0, 9, 2), (2, 0): (0, 428, 0, 0)}, 18, [BIG])[12] == 512),
        ("9xx: an offset past the end of the sample (905 = 1,280 bytes into 300) leaves nothing to play: refused",
         refused(lambda: sim([{(0, 0): (1, 428, 9, 5)}]), "9xx ran past its end")),
        ("a note before any sample number on its channel is refused, with the place",
         refused(lambda: sim([{(0, 0): (0, 428, 0, 0)}]), "pattern 0 row 0 channel 1: a note without a sample")),
        ("a sample number without a note while another sample plays (ProTracker swaps them) is refused",
         refused(lambda: sim([{(0, 0): (2, 428, 0, 0), (1, 0): (1, 0, 0, 0)}]), "sample number 1 without a note")),
    ]


def refusal_checks() -> list[Check]:
    def bad(effect: int, arg: int) -> bool:
        return refused(lambda: sim([{(0, 0): (1, 428, effect, arg)}]),
                       f"pattern 0 row 0 channel 1: effect {effect:X}{arg:02X} is not supported")
    return [
        ("refused, with the place: 7xy tremolo, 8xx, E3x E4x E5x E6x E7x E8x EEx EFx, F00",
         all(bad(e, a) for e, a in [(7, 0x42), (8, 1), (0xE, 0x31), (0xE, 0x41), (0xE, 0x52), (0xE, 0x62), (0xE, 0x71),
                                    (0xE, 0x81), (0xE, 0xE2), (0xE, 0xF1), (0xF, 0)])),
        ("accepted: every effect of the list (0 1 2 3 4 5 6 9 A B C D, E0 E1 E2 E9 EA EB EC ED, F06)",
         all(len(sim([{(0, 0): (1, 428, e, a), (1, 0): (0, 0, 0xC, 0)}]).ticks) > 0
             for e, a in [(0, 0x37), (1, 1), (2, 1), (3, 1), (4, 0x11), (5, 1), (6, 1), (9, 0), (0xA, 1), (0xB, 0),
                          (0xC, 9), (0xD, 0), (0xE, 0x01), (0xE, 0x11), (0xE, 0x21), (0xE, 0x91), (0xE, 0xA1),
                          (0xE, 0xB1), (0xE, 0xC1), (0xE, 0xD1), (0xF, 6)])),
    ]


def main() -> int:
    return run("effect tests", [pitch_checks, porta_checks, vibrato_checks, volume_checks, trigger_checks, refusal_checks])


if __name__ == "__main__":
    sys.exit(main())
