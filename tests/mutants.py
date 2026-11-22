#!/usr/bin/env python3
"""Mutation check: break the tools in small ways, one at a time, in a temporary copy, and require that the tests fail.
Run: python3 -I tests/mutants.py        (takes a minute; prints one line per mutant, exit 1 if one survives)"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# (file, text in the file, what it becomes, what the mutant breaks)
MUTANTS = [
    ("tools/lsp_bank.py", "PAL_CLOCK = 3546895", "PAL_CLOCK = 3579545", "NTSC clock: every pitch is off"),
    ("tools/lsp_bank.py", "TICK = 252 ", "TICK = 256 ", "a tick of 256 bytes"),
    ("tools/lsp_bank.py", "(frac >> 1)", "(frac)", "interpolation fraction not halved"),
    ("tools/lsp_bank.py", "(abs(v) * vol * gain + (1 << 21)) >> 22", "(abs(v) * vol * gain) >> 22", "volume table not rounded"),
    ("tools/lsp_bank.py", "(abs(v) * peak * 2 + 127) // 254", "(abs(v) * peak * 2) // 254", "effects table not rounded"),
    ("tools/lsp_bank.py", "return -(-out // TICK)", "return out // TICK", "one-shot length rounded down"),
    ("tools/lsp_seq.py", "cur[1] == natural_ticks", "cur[1] + 1 == natural_ticks", "stop event one tick late"),
    ("tools/lsp_seq.py", "(pos + 1 if jump is None else jump)", "(pos + 1 if jump is None else jump + 1)", "B jumps one too far"),
    ("tools/lsp_seq.py", "hold[old[0]] = max(", "hold[old[0]] = min(", "hold time is the shortest, not the longest"),
    ("tools/lsp_seq.py", "(len(tl.ticks[a]) << 8)", "(len(tl.ticks[a]) << 7)", "event count in the wrong bits"),
    ("tools/lsp_mod.py", "cut=key is None or key[2] == 0", "cut=False", "C00 does not cut"),
    ("tools/lsp_mod.py", "if c.period not in PERIODS:", "if False:", "any period accepted"),
    ("tools/lsp_mod.py", "1 <= c.arg <= 31", "1 <= c.arg <= 255", "BPM tempo accepted"),
    ("tools/lsp_ref.py", "- 0x02020200", "- 0x02020202", "wrong carry constant in the mixer"),
    ("tools/lsp_ref.py", "if self.playing and not paused:", "if self.playing:", "hold does not freeze the song"),
    ("tools/lsp_ref.py", "if pos + TICK < end else None", "if pos + TICK <= end else None", "effect plays a tick too long"),
    ("tools/lsp_dat.py", "sum(body) & 0xFFFFFFFF", "(sum(body) + 1) & 0xFFFFFFFF", "wrong checksum"),
    ("tools/lsp_dat.py", "or size != len(dat)", "", "file size not checked"),
    ("tools/lsp_ste.py", "if peak <= music_peak and", "if peak <= music_peak + 20 and", "music may pass its headroom"),
    ("tools/fx_pack.py", "PEAK = 0.9 ", "PEAK = 1.0 ", "effects at full scale"),
    ("tools/fx_pack.py", "PAD = 256 ", "PAD = 128 ", "padding shorter than a tick"),
    ("tools/st_put.py", "self.set_fat(c, 0)", "pass", "replaced file keeps its clusters"),
    ("tools/st_blank.py", "1440, 0xF9, 5", "1440, 0xF8, 5", "wrong media byte"),
    ("tools/make_demo.py", "end = 12 if last else 16", "end = 16", "the last bar does not end in silence"),
]


def run_tests(tree: Path) -> bool:
    for t in sorted((tree / "tests").glob("test_*.py")):
        if subprocess.run([sys.executable, "-I", str(t)], capture_output=True, cwd=tree).returncode:
            return False
    return True


def main() -> int:
    survived = 0
    for rel, old, new, what in MUTANTS:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "t"
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", "scratch", "build", "__pycache__", ".*_cache"))
            path = tree / rel
            text = path.read_text()
            if text.count(old) != 1:
                print(f"BAD MUTANT {rel}: {old!r} found {text.count(old)} times")
                return 2
            path.write_text(text.replace(old, new))
            killed = not run_tests(tree)
        survived += not killed
        print(("killed   " if killed else "SURVIVED ") + f"{rel}: {what}")
    print(f"{len(MUTANTS) - survived} of {len(MUTANTS)} mutants killed")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
