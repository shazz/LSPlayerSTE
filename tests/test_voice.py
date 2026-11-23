#!/usr/bin/env python3
"""Tests for the middle of a note (lsp_voice.py, the spans of lsp_seq.py, the variants made from them): where a
channel goes on when an effect changes its pitch or volume. Run: python3 -I tests/test_voice.py
Expected values come from the rates: a variant at period p holds R(p) = 3,546,895 / (p x 12,517) sample positions
per byte (428: 0.66207, 214: twice that), a tick is 252 bytes; they are worked out in each claim."""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import Check, run, strays
from lsp_bank import Rendition, Variant, interp, plan, rendition, step_for, virtual, windows
from lsp_dat import expand, head, pack, places
from lsp_mod import Sample, parse
from lsp_ref import Player
from lsp_seq import Timeline, simulate
from lsp_ste import build
from lsp_voice import SLACK, enter, src_pos
from mod_write import Cells, SampleDef, make_mod

LONG: SampleDef = (bytes([100, 156] * 2000), 64, 0, 0, 0)       # one-shot, 4,000 B: 6,041.6 bytes at period 428
RING: SampleDef = (bytes(range(60, 100)) * 10, 64, 0, 0, 400)   # looped over its 400 B
CHIP: SampleDef = (bytes(range(100, 116)), 64, 0, 0, 16)        # looped over 16 B
SIX: SampleDef = (bytes([100, 156] * 300), 64, 0, 0, 0)         # one-shot, 600 B
SET = [LONG, RING, CHIP, SIX]
K64, K32 = (1, 428, 64), (1, 428, 32)


def ratio(period: int) -> Fraction:
    return Fraction(3546895, period * 12517)


def song(cells: Cells) -> Timeline:
    return simulate(parse(make_mod([cells], [0], SET)))


def smp(i: int) -> Sample:
    d, v, f, ls, ll = SET[i - 1]
    return Sample(d, v, f, ls, ll)


def position_checks() -> list[Check]:
    unit143 = 2 * step_for(143)[1]
    return [
        ("position: byte 504 of a variant at period 428 is sample 504 x 0.66207 = 333.68 (16.16)",
         abs(Fraction(src_pos(428, 504), 65536) - 504 * ratio(428)) < Fraction(504, 65536)),
        ("position: a halved rendition (period 143) holds the mean of samples 2j and 2j+1: byte 100 is 100 x R + 0.5",
         abs(Fraction(src_pos(143, 100), 65536) - 100 * ratio(143) - Fraction(1, 2)) < Fraction(200, 65536)),
        ("enter: the same period gives the same byte back (a volume change keeps its place)",
         enter(smp(1), 428, src_pos(428, 504)) == 504 and enter(smp(1), 143, src_pos(143, 100)) == 100),
        ("enter: an octave up (214) halves the byte: 504 -> 252", enter(smp(1), 214, src_pos(428, 504)) == 252),
        ("enter: the nearest even byte, up or down: byte 756 at 428 is sample 500.5 = byte 713.6 at 404 -> 714",
         enter(smp(1), 404, src_pos(428, 756)) == 714),
        ("enter: into a halved rendition the half sample is taken off: 0.9 byte after byte 100 is still nearer to 100",
         enter(smp(1), 143, src_pos(143, 100) + unit143 * 9 // 10) == 100),
        ("enter: 100 samples into the 101st turn of a 400-sample loop = 100 samples in: byte 151.04 -> 152",
         enter(smp(2), 428, (400 * 100 + 100) << 16) == 152),
        ("enter: a 16-sample loop turns every 24.17 bytes at 428; 5 samples in is byte 7.55, 31.72, 55.88, 80.05...: "
         "of those within a tick, 80 is the nearest to an even byte", enter(smp(3), 428, (16 * 1000 + 5) << 16) == 80),
        ("enter: before the loop's end a position is taken as it is (no turn is taken off): sample 100 -> byte 152",
         enter(smp(2), 428, 100 << 16) == 152 and SLACK == 252),
    ]


def event_checks() -> list[Check]:
    tl = song({(0, 0): (1, 428, 0, 0), (1, 0): (0, 0, 0xC, 0x20), (2, 0): (0, 0, 0xC, 0), (3, 0): (0, 0, 0xC, 0x40)})
    ev = [(t, e[0][1]) for t, e in enumerate(tl.ticks[:40]) if e]
    arp = song({(0, 0): (4, 428, 0, 0xC0)})
    stops = [t for t, e in enumerate(arp.ticks[:12]) if e and e[0][1] is None]
    plain = song({(0, 0): (4, 428, 0, 0)})
    return [
        ("events: C20 on row 1 goes on in the volume-32 variant at the same byte (6 ticks x 252 = 1,512); C00 "
         "silences the channel, the note runs on unheard and C40 finds it at byte 4,536; the 4,000 B sample is "
         "over after 6,041.6 bytes: stop at tick 24",
         ev == [(0, (K64, 0)), (6, (K32, 1512)), (12, None), (18, (K64, 4536)), (24, None)]),
        ("spans: each variant is read where it is played: volume 64 from 0 to 1,512 and 4,536 to 6,048, volume 32 "
         "from 1,512 to 3,024", tl.spans == {K64: ((0, 1512), (4536, 6048)), K32: ((1512, 3024),)}),
        ("9xx: 901 starts the note 256 samples in: byte 386.7 of its variant -> 386",
         song({(0, 0): (1, 428, 9, 1)}).ticks[0] == ((0, (K64, 386)),)),
        ("a 600 B one-shot lasts 906.2 bytes at 428 (stop at tick 4); with 0C0 its second tick is an octave up and "
         "uses 333.7 samples instead of 166.8: 667.4 after three ticks, so the stop is at tick 3",
         stops == [3] and [t for t, e in enumerate(plain.ticks[:12]) if e and e[0][1] is None] == [4]),
    ]


def _jumps(tl: Timeline, lap: int) -> list[Fraction]:
    """Per event of channel 1 that goes on in a note: how far (bytes of the new variant) the new place is from the
    old one, turns of the loop taken off. Worked out with exact rates, not with the converter's fixed point."""
    out: list[Fraction] = []
    cur: tuple[int, int, int] | None = None
    for t, events in enumerate(tl.ticks):
        for ch, target in events:
            if ch == 0 and target and cur and target[1]:
                was = (cur[1] + (t - cur[2]) * 252) * ratio(cur[0])
                d = (target[1] * ratio(target[0][1]) - was) % lap
                out.append(min(d, lap - d) / ratio(target[0][1]))
            if ch == 0:
                cur = (target[0][1], target[1], t) if target else None
    return out


def loop_checks() -> list[Check]:
    cells: Cells = {(r, 0): (0, 0, 0, 0x47) for r in range(1, 8)}
    cells.update({(0, 0): (2, 428, 0, 0x47), (8, 0): (0, 0, 0xC, 0), (9, 0): (0, 0, 0xB, 0)})
    mod = make_mod([cells], [0], SET)
    tl = simulate(parse(mod))
    b = build(mod)
    jumps = _jumps(tl, 400)
    p = Player(b.dat)
    p.start()
    out = [p.tick() for _ in range(180)]
    chip = dict(cells)
    chip[(0, 0)] = (3, 428, 0, 0x47)
    over = make_mod([{(0, 0): (0, 0, 0xC, 0x20), (4, 0): (2, 428, 0, 0), (9, 0): (0, 0, 0xB, 0)}], [0], SET)
    return [
        ("arpeggio on a looped sample: an event on each of the 48 ticks, then the cut; the song loops after 60 ticks",
         [len(e) for e in tl.ticks[:49]] == [1] * 49 and tl.ticks[48] == ((0, None),) and (len(tl.ticks), tl.loop) == (60, 0)),
        ("arpeggio: every change of pitch goes on within one byte of where the note was (47 changes)",
         len(jumps) == 47 and max(jumps) <= 1 + Fraction(1, 100)),
        ("arpeggio on a 16-sample loop: with ten or more turns of the loop to choose from, every change is within "
         "a quarter of a byte", max(_jumps(simulate(parse(make_mod([chip], [0], SET))), 16)) <= Fraction(1, 4)),
        ("bank: a looped variant holds the loop once (400 samples = 604.2, 478.6 and 402.3 bytes at 428, 339 and "
         "285), a tick of choice and the tick it plays: under 3 x 252 + 1,490 = 2,246 bytes for the three, not 16 "
         "ticks each", head(b.dat).bank <= 2246 and head(b.dat).nvar == 3),
        ("mixer: with effects too, every pass of the loop gives the same bytes", out[60:120] == out[120:180]),
        ("bank: over five passes no channel reads past the variant its event pointed into, also when a looped "
         "note sounds across the song's loop and is bent there (C20 on row 0, the note on row 4)",
         strays(b.dat, 300) == 0 and strays(build(over).dat, 300) == 0),
    ]


def _rend(s: Sample, shift: int) -> tuple[bytes, int, int, int]:
    r = rendition(s, shift)
    return r.data[:r.end + 1], r.end, r.lap, len(r.data) % 2


def variant_checks() -> list[Check]:
    mid = song({(0, 0): (1, 428, 0, 0), (1, 0): (0, 0, 0xC, 0x20), (2, 0): (0, 0, 0xC, 0), (3, 0): (0, 0, 0xC, 0x40)})
    pl = plan(parse(make_mod([{}], [0], SET)), mid.spans)
    targets = [(K32, 1512), (K64, 0), (K64, 4536)]
    part = expand(pack(pl, targets, 16000, 47, b"\xff\xff", 0))
    whole = plan(parse(make_mod([{}], [0], SET)), {K64: ((0, 6048),)})
    full = expand(pack(whole, [(K64, 0)], 16000, 47, b"\xff\xff", 0)).data
    return [
        ("windows: runs that touch or lie within 64 bytes share a variant, others do not; sizes are whole long words",
         windows(((0, 504), (504, 756), (5000, 5254))) == [(0, 756), (5000, 256)]
         and windows(((0, 504), (560, 812))) == [(0, 812)] and windows(((0, 504), (600, 852))) == [(0, 504), (600, 252)]),
        ("variants: sorted by sample, period, volume, start; the note bent by Cxx needs 3 x 1,512 B, not 24 ticks",
         [(v.key, v.start, v.size) for v in pl.variants] == [(K32, 1512, 1512), (K64, 0, 1512), (K64, 4536, 1512)]),
        ("targets: the bank offset of a target is its variant's place plus its byte in it",
         places(pl, targets) == [0, 1512, 3024] and part.targets == (None, 0, 1512, 3024)
         and places(pl, [(K64, 4788)]) == [3276]),
        ("variants: one that starts in the middle of a note holds the bytes the whole note has there",
         part.data[3024:4536] == full[4536:6048] and part.data[1512:3024] == full[:1512]),
    ]


def loader_checks() -> list[Check]:
    step = step_for(428)[1]
    ring = smp(2)
    flat = Rendition(virtual(ring, 3000, 0), 3000, 1)
    return [
        ("rendition: a loop is stored once (to its end, plus its first sample again, an even number of bytes); a "
         "one-shot is followed by zeros and loops over four of them; halved: the means of pairs, loop 4..8 -> 2..4",
         _rend(ring, 0) == (ring.data + ring.data[:1], 400, 400, 0)
         and rendition(smp(4), 0) == Rendition(smp(4).data + bytes(6), 604, 4)
         and _rend(Sample(bytes(range(10)), 64, 0, 4, 4), 1) == (bytes([0, 2, 4, 6, 4]), 4, 2, 0)),
        ("loader: going back at the loop's end gives the bytes of the unrolled loop, from any start (byte 1,000 of "
         "the note = sample 662.07, in the second turn)",
         interp(rendition(ring, 0), step, 900, 1000 * step) == interp(flat, step, 900, 1000 * step)
         and interp(Rendition(bytes([0, 10, 20, 30, 40, 20]), 5, 3), 0x10000, 9) == bytes([0, 10, 20, 30, 40, 20, 30, 40, 20])
         and interp(Rendition(bytes([0, 10, 20, 30, 40, 20]), 5, 3), 0x8000, 12)[7:] == bytes([35, 40, 30, 20, 25])),
        ("variants: the sample of a variant's first byte is given to the loader inside the loop (byte 1,512 at 428 "
         "is sample 1,001.05: 201 of the 400-sample loop)",
         Variant((2, 428, 64), 0, step, 1512, 252, 0).start * step >> 16 == 1001 and rendition(ring, 0).wrap(1001) == 201),
    ]


def main() -> int:
    return run("voice tests", [position_checks, event_checks, loop_checks, variant_checks, loader_checks])


if __name__ == "__main__":
    sys.exit(main())
