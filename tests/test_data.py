#!/usr/bin/env python3
"""Tests for the converter, sample side (lsp_bank, lsp_dat, lsp_ref, lsp_ste). Run: python3 -I tests/test_data.py
Expected values come from the formulas and layouts in the tool docstrings, not from running the code."""
from __future__ import annotations

import random
import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SAMPLES, SHOT, Check, refused, run
from lsp_bank import Plan, Rendition, Variant, fxtab, interp, natural_bytes, step_for, virtual, voltab
from lsp_dat import expand, head, pack
from lsp_mod import ModError, Sample
from lsp_ref import MixOverflow, Player, mix
from lsp_ste import build
from make_demo import module
from mod_write import Cells, make_mod

FLAT = (bytes([64]) * 400, 64, 0, 0, 400)                       # a looped constant: every output byte is known
SONG: list[Cells] = [{(0, 0): (1, 428, 0, 0), (0, 1): (4, 428, 0, 0), (9, 0): (0, 0, 0xB, 0)}]
MOD = make_mod(SONG, [0], SAMPLES + [FLAT])                     # variants: (1,428,64) 2 ticks, (4,428,64) 60 ticks
ROUND = make_mod([{**{(0, ch): (1, 428, 0, 0) for ch in range(4)}, (9, 0): (0, 0, 0xB, 0)}], [0],
                 [(bytes([43]) * 400, 64, 0, 0, 400)])


def bank_checks() -> list[Check]:
    ramp = Sample(bytes(range(10)), 64, 0, 4, 3)
    shot = Sample(bytes(range(10)), 64, 0, 0, 0)
    src = bytes([0, 100, 156, 0, 0, 0])                         # 0, 100, -100, 0
    exact = [(p, Fraction(3546895, p * 12517)) for p in (428, 254, 190, 143)]
    steps = [(step_for(p), r) for p, r in exact]
    return [
        ("bank: step = Paula rate / 12,517 in 16.16; halved rendition (half the step) above sqrt(2)",
         [s[0] for s, _ in steps] == [0, 0, 1, 1]
         and all(abs(Fraction(s[1] << s[0], 65536) - r) <= Fraction(1, 65536) for s, r in steps)),
        ("bank: a 300 B one-shot lasts 300 / 0.66207 = 453.1 -> 454 bytes at period 428; at 143 it is read halved, "
         "150 samples at 0.99079 = 151.4 -> 152",
         natural_bytes(Sample(SHOT[0], 64, 0, 0, 0), 428) == 454 and natural_bytes(Sample(SHOT[0], 64, 0, 0, 0), 143) == 152),
        ("bank: a loop is unrolled as ProTracker plays it (to the loop end, then the loop again)",
         virtual(ramp, 12, 0) == bytes([0, 1, 2, 3, 4, 5, 6, 4, 5, 6, 4, 5])),
        ("bank: a one-shot is followed by zeros; the halved rendition averages pairs (floor)",
         virtual(shot, 12, 0) == bytes(range(10)) + bytes(2) and virtual(ramp, 6, 1) == bytes([0, 2, 4, 5, 5, 4])),
        ("bank: interpolation at step 0.5 gives the midpoints, at 1.0 the source, at 1.5 every 1.5 samples",
         interp(Rendition(src, 5, 1), 0x8000, 5) == bytes([0, 50, 100, 0, 156])
         and interp(Rendition(src, 5, 1), 0x10000, 3) == src[:3]
         and interp(Rendition(bytes([0, 10, 20, 30, 40, 50, 60, 70]), 7, 1), 0x18000, 4) == bytes([0, 15, 30, 45])),
        ("bank: volume table = $80 + round(sample * vol/64 * gain), index sample + 128",
         voltab(64, 65536) == bytes(range(256)) and voltab(32, 32768)[127 + 128] == 160
         and voltab(32, 32768)[-127 + 128] == 96 and voltab(48, 20000)[128] == 128),
        ("bank: effects table = $80 + round(sample * 47/127): 127 -> +47, -127 -> -47, -128 -> -47, 0 -> $80, "
         "+2 -> +1 (0.74 rounds up), -2 -> -1",
         [fxtab(47)[i] for i in (255, 1, 0, 128, 130, 126)] == [175, 81, 81, 128, 129, 127]),
    ]


def dat_checks() -> list[Check]:
    b = build(MOD)
    d = b.dat
    w = struct.unpack_from(">HH", d, 4)
    size, bank, o_vol, o_fx, o_str, o_loop = struct.unpack_from(">6I", d, 8)
    o_rend, csum, o_tgt = struct.unpack_from(">III", d, 36)
    v0, v1 = struct.unpack_from(">HHIIHH", d, 48), struct.unpack_from(">HHIIHH", d, 64)
    rends = [struct.unpack_from(">III", d, o_rend + 12 * i) for i in range(2)]
    flat = expand(d).data[2 * 252:]
    level = 128 + (64 * b.gain + 32768) // 65536
    return [
        ("dat: header 'LSP1', version 2, 2 variants; after the 48 B header: 2 variants of 16 B, 2 renditions of "
         "12 B (at 80), 3 targets of 4 B (at 104), one volume table (at 116), the effects table, the stream; tick 252",
         d[:4] == b"LSP1" and w == (2, 2) and size == len(d) and (o_rend, o_tgt) == (80, 104)
         and (o_vol, o_fx, o_str) == (116, 116 + 256, 116 + 512)
         and o_str <= o_loop < rends[0][0] < size and struct.unpack_from(">HH", d, 32) == (1, 252)),
        ("dat: checksum = sum of the bytes from offset 48", csum == sum(d[48:]) & 0xFFFFFFFF),
        ("dat: variant entries (rendition, table, step, first sample and fraction, long words): the one-shot 2 "
         "ticks = 126 longs, the held loop 60 ticks = 3,780, both from the start of their sample",
         v0 == (0, 0, step_for(428)[1], 0, 0, 126) and v1 == (1, 0, step_for(428)[1], 0, 0, 3780)),
        ("dat: rendition entries (data, end, loop): the 300 B one-shot ends after 4 more zeros and loops over "
         "them, the 400 B loop is stored once; the targets are silence, the one-shot at 0 and the loop at 504",
         [r[1:] for r in rends] == [(304, 4), (400, 400)] and rends[0][0] + 306 == rends[1][0]
         and rends[1][0] + 402 == size and struct.unpack_from(">III", d, o_tgt) == (0, 0, 504)),
        ("dat: bank = (2 + 60) ticks of 252 B; a constant 64 at volume 64 becomes $80 + round(64 * gain) everywhere",
         bank == 62 * 252 and len(flat) == 60 * 252 and set(flat) == {level}),
    ]


def target_checks() -> list[Check]:
    d = build(MOD).dat
    at = struct.unpack_from(">I", d, 44)[0] + 8                 # the second target: the looped note, at 504
    cut = bytearray(d)
    cut[len(d) - 5] ^= 1
    big = Plan(tuple(Variant((1, p, 64), 0, 65536, 0, 850 * 252, 0) for p in (428, 404)), (Rendition(bytes(8), 4, 4),), (64,))

    def moved(value: int) -> bytes:
        out = bytearray(d)
        struct.pack_into(">I", out, at, value)
        struct.pack_into(">I", out, 40, sum(out[48:]) & 0xFFFFFFFF)
        return bytes(out)
    return [
        ("dat: a changed byte, a short file, a file with zeros appended and a wrong magic are refused",
         refused(lambda: head(bytes(cut)), "checksum") and refused(lambda: head(d[:-2]), "size")
         and refused(lambda: head(d + bytes(2)), "size")
         and refused(lambda: head(b"FX01" + d[4:]), "magic")),
        ("dat: a bank over the limit (default 332 KB = 1,700 ticks x 252 B is 428,400 B) is refused",
         refused(lambda: pack(big, [], 16000, 47, b"\xff\xff", 0), "bank would be 428400 B")),
        ("dat: a file over the limit is refused, with the limit as given",
         refused(lambda: build(MOD, max_file=100), "more than the 100 B")),
        ("dat: a target may be the last whole tick of the bank (62 ticks: 61 x 252), not a byte further, nor odd",
         expand(moved(61 * 252)).targets[2] == 61 * 252 and refused(lambda: expand(moved(61 * 252 + 2)), "outside the bank")
         and refused(lambda: expand(moved(503)), "odd byte")),
        ("gain: a song of silent samples converts (the gain stops at 0.992: a volume table stays in the byte)",
         build(make_mod(SONG, [0], [(bytes(300), 64, 0, 0, 0)] * 4)).gain == 0xFE00),
    ]


def mix_checks() -> list[Check]:
    rnd = random.Random(1)
    vals = [[rnd.randint(-25, 25) for _ in range(252)] for _ in range(5)]
    want = bytes(sum(col) & 0xFF for col in zip(*vals))
    loud = [bytes([255] * 252), bytes([129] * 252)] + [bytes([128] * 252)] * 3
    return [
        ("mixer: the long adds give the signed sum of the five channels in every byte",
         mix([bytes(v + 128 for v in ch) for ch in vals]) == want),
        ("mixer: a sum of +128 is refused (it would break the carries)", refused(lambda: mix(loud), "overflow")
         and issubclass(MixOverflow, ModError)),
    ]


def fx_checks() -> list[Check]:
    def effect(length: int) -> Player:
        p = Player(build(MOD).dat, b"FX01" + struct.pack(">HII", 1, 14, length) + bytes([100]) * length + bytes(256))
        p.fx_start(0)
        return p
    p, exact = effect(300), effect(252)
    t0, t1, t2 = p.tick(), p.tick(), p.tick()
    e0 = exact.tick()
    return [
        ("mixer: an effect of 300 B plays 252 B, then 48 B and the padding, then the channel is silent (no pointer left)",
         t0 == bytes([37]) * 252 and t1 == bytes([37]) * 48 + bytes(204) and t2 == bytes(252) and p.fx_ptr is None),
        ("mixer: an effect of exactly 252 B plays one tick and its channel is free right after",
         e0 == bytes([37]) * 252 and exact.fx_ptr is None),
    ]


def ref_checks() -> list[Check]:
    b = build(MOD)
    q = Player(b.dat)
    q.start()
    first, held, after = q.tick(), q.tick(paused=True), q.tick()
    level = (64 * b.gain + 32768) // 65536
    r = Player(b.dat)
    r.start()
    out = [r.tick() for _ in range(b.ticks + 2 * (b.ticks - b.loop))]
    lap = b.ticks - b.loop
    return [
        ("mixer: a paused tick is silent and does not advance the song (after it, 1 tick left before the stop at 2)",
         held == bytes(252) and first[:4] != bytes(4) and after[-1] == level and q.wait == 1),
        ("mixer: every pass of the loop gives the same bytes", out[-lap:] == out[-2 * lap:-lap]),
        ("gain: the song's exact peak uses the headroom (72..80 of 80) and never passes it",
         72 <= max(-b.low, b.high) <= 80),
        ("gain: music + effects peaks above 127 are refused", refused(lambda: build(MOD, 90, 40), "127 or less")),
        ("gain: four channels of a constant 43 (rounding pushes a first guess to 4 x 21 = 84) still end at 80 or less",
         72 <= build(ROUND).high <= 80),
    ]


def demo_checks() -> list[Check]:
    b = build(module())
    h = head(b.dat)
    bank = expand(b.dat)
    return [
        ("demo: the bank is 224 ticks x 252 B = 56,448 B (kick 9 + hat 3 + bass 84 + lead 128 ticks, see test_song)",
         h.bank == 224 * 252 == len(bank.data) and h.nvar == 16),
        ("demo: the music peaks at 80 or less and uses the headroom (72..80), the file is under 64 KB",
         72 <= max(-b.low, b.high) <= 80 and len(b.dat) < 65536),
        ("demo: 728 ticks, loop to 160, 16 variants", (b.ticks, b.loop, b.variants) == (728, 160, 16)),
    ]


def main() -> int:
    return run("data tests", [bank_checks, dat_checks, target_checks, mix_checks, fx_checks, ref_checks, demo_checks])


if __name__ == "__main__":
    sys.exit(main())
