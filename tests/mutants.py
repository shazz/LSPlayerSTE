#!/usr/bin/env python3
"""Mutation check: break the tools in small ways, one at a time, in a temporary copy, and require that the tests fail.
Run: python3 -I tests/mutants.py        (takes a few minutes; prints one line per mutant, exit 1 if one survives)
The mutants are in mutant_list.py."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mutant_list import MUTANTS

ROOT = Path(__file__).resolve().parent.parent


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
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", "scratch", "build", "__pycache__", ".*_cache",
                                                                      ".venv"))
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
