#!/usr/bin/env python3
"""Size limits: no file over 200 lines, no Python function over 30 lines. Run: python3 -I tests/check_limits.py"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_FILE, MAX_FUNC = 200, 30
CODE = ("*.py", "*.s", "*.sh")


def functions(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text())
    return [(f"{n.name}:{n.lineno}", (n.end_lineno or n.lineno) - n.lineno + 1)
            for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def main() -> int:
    files = sorted(p for pat in CODE for d in ("src", "tools", "tests", "example", ".") for p in (ROOT / d).glob(pat))
    bad = []
    for p in dict.fromkeys(files):
        n = len(p.read_text().splitlines())
        if n > MAX_FILE:
            bad.append(f"{p.relative_to(ROOT)}: {n} lines (max {MAX_FILE})")
        if p.suffix == ".py":
            bad += [f"{p.relative_to(ROOT)}:{name}: {size} lines (max {MAX_FUNC})"
                    for name, size in functions(p) if size > MAX_FUNC]
    print("\n".join(bad) or f"limits ok: {len(set(files))} files, none over {MAX_FILE} lines, no function over {MAX_FUNC}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
