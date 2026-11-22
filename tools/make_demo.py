#!/usr/bin/env python3
"""Make the demo's data: an original short ProTracker module (demo.mod) and five sound effects (WAV files).

    python3 -I tools/make_demo.py OUT_DIR        writes OUT_DIR/demo.mod and OUT_DIR/fx/*.wav

Everything is synthesised here from a fixed seed (stdlib only), so the committed files in assets/ can be remade.
The module stays inside what the converter accepts (lsp_mod.py): four channels, finetune 0, effects B C D F only.
Samples: 1 kick (sine sweep, one-shot), 2 bass (square, looped), 3 hat (noise, one-shot), 4 lead (sine, looped).
Channels: 1 kick + tempo, 2 bass, 3 hat, 4 lead + jumps. Rows are 16th notes, speed 5 (about 150 BPM at 49.67 ticks/s).
Order (3 positions): pattern 0, the intro, two bars, ends with D00 on row 31 (32 rows x 5 = 160 ticks);
pattern 1, four bars (64 rows, 320 ticks), with the lead; pattern 2, three bars, B01 on row 47 jumps back to
position 1, a slow-down F06 on rows 32..39 and F05 on row 40 (rows 0..47: 248 ticks). The song loops over
positions 1 and 2: 568 ticks, so the stream is 160 + 568 = 728 ticks. The last bar of a pattern ends in silence
(everything cut by C00 or played out) so that the loop is found at once. Notes carry a C volume or the sample's own.
"""
from __future__ import annotations

import math
import random
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mod_write import Cells, SampleDef, make_mod

KICK, BASS, HAT, LEAD = 1, 2, 3, 4
ROOTS = ((508, 254), (640, 320), (570, 285), (678, 339))        # A F G E: bass note, an octave up
MELODY = ((214, 170, 143, 170), (160, 143, 127, 143), (190, 160, 143, 160), (170, 143, 127, 114))
Chan = tuple[int, int, int, int]


def s8(values: list[float]) -> bytes:
    return bytes(max(-127, min(127, round(v))) & 0xFF for v in values)


def samples() -> list[SampleDef]:
    rnd = random.Random(1987)
    kick, ph = [], 0.0
    for i in range(1400):
        ph += 2 * math.pi * (50 + 130 * math.exp(-i / 160)) / 8287
        kick.append(120 * math.exp(-i / 500) * math.sin(ph))
    hat = [rnd.uniform(-1, 1) * 110 * math.exp(-i / 110) for i in range(600)]
    bass = [100.0 if i < 32 else -100.0 for i in range(64)]
    lead = [80 * math.sin(2 * math.pi * i / 32) + 25 * math.sin(6 * math.pi * i / 32) for i in range(32)]
    return [(s8(kick), 64, 0, 0, 0), (s8(bass), 48, 0, 0, 64), (s8(hat), 40, 0, 0, 0), (s8(lead), 40, 0, 0, 32)]


def bar(base: int, roots: tuple[int, int], melody: tuple[int, ...] | None, last: bool) -> Cells:
    """One bar of 16 rows from row `base`. The last bar of a pattern stops at row 12 and cuts what still sounds."""
    end = 12 if last else 16
    cells: Cells = {}
    for r in range(0, end, 4):
        cells[(base + r, 0)] = (KICK, 428, 0, 0)
    for r in range(2, end, 4):
        cells[(base + r, 2)] = (HAT, 254, 0xC, 0x20)               # C20: volume 32
    for k, r in enumerate(range(0, end, 2)):
        cells[(base + r, 1)] = (BASS, roots[k % 4 == 3], 0, 0)     # every 4th note an octave up
    if last:
        cells[(base + end, 1)] = (0, 0, 0xC, 0)                    # C00 alone: cut the channel
    if melody:
        for k in range(end // 4):
            cells[(base + 4 * k, 3)] = (LEAD, melody[k], 0xC, 0x30)
        if last:
            cells[(base + end, 3)] = (0, 0, 0xC, 0)
    return cells


def patterns() -> tuple[list[Cells], list[int]]:
    intro: Cells = {}
    for b in range(2):
        intro.update(bar(16 * b, ROOTS[0], None, b == 1))
    intro[(0, 0)] = (KICK, 428, 0xF, 5)                            # F05: speed 5 (ticks per row)
    intro[(31, 3)] = (0, 0, 0xD, 0)                                # D00: next position, row 0
    main: Cells = {}
    for b in range(4):
        main.update(bar(16 * b, ROOTS[b], MELODY[b], b == 3))
    outro: Cells = {}
    for b in range(3):
        outro.update(bar(16 * b, ROOTS[b], MELODY[b], b == 2))
    outro[(32, 0)] = (KICK, 428, 0xF, 6)                           # F06: slow down for 8 rows
    outro[(40, 0)] = (KICK, 428, 0xF, 5)
    outro[(47, 3)] = (0, 0, 0xB, 1)                                # B01: back to position 1
    return [intro, main, outro], [0, 1, 2]


def module() -> bytes:
    pats, order = patterns()
    return make_mod(pats, order, samples(), "LSPSTE demo")


RATE = 11025


def chirp(f0: float, f1: float, dur: float, square: bool = False, decay: float = 3.0) -> list[float]:
    n, ph, out = int(RATE * dur), 0.0, []
    for i in range(n):
        t = i / n
        ph += 2 * math.pi * (f0 + (f1 - f0) * t) / RATE
        v = (0.6 if math.sin(ph) >= 0 else -0.6) if square else math.sin(ph)
        out.append(v * math.exp(-decay * t))
    return out


def noise(dur: float, decay: float, seed: int, smooth: float = 0.5) -> list[float]:
    rnd, n, lo, out = random.Random(seed), int(RATE * dur), 0.0, []
    for i in range(n):
        lo += smooth * (rnd.uniform(-1, 1) - lo)                   # one-pole low-pass
        out.append(lo * math.exp(-decay * i / n))
    return out


def effects() -> dict[str, list[float]]:
    boom = [a + 1.5 * b for a, b in zip(chirp(70, 35, 0.5, decay=3), noise(0.5, 4, 7, 0.15))]
    return {"jump": chirp(300, 900, 0.18), "coin": chirp(988, 988, 0.08, True, 1) + chirp(1319, 1319, 0.22, True, 4),
            "hit": noise(0.3, 5, 3), "laser": chirp(1800, 200, 0.3, True, 2), "boom": boom}


def write_wav(path: Path, vals: list[float]) -> None:
    peak = max(abs(v) for v in vals)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(RATE)
        w.writeframes(bytes(round(128 + 120 * v / peak) for v in vals))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    out = Path(argv[1])
    (out / "fx").mkdir(parents=True, exist_ok=True)
    mod, fx = module(), effects()
    (out / "demo.mod").write_bytes(mod)
    for name, vals in fx.items():
        write_wav(out / "fx" / f"{name}.wav", vals)
    print(f"make_demo: {out}: demo.mod {len(mod)} B, {len(fx)} effects")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
