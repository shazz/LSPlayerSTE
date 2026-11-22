#!/usr/bin/env bash
# Build the demo disk: tests, data files, DEMO.PRG, build/lsplayer_demo.st (AUTO/DEMO.PRG, data in the root).
#   ./build.sh                      needs Python 3.10+ and rg-asm (RG_ASM=/path/to/rg-asm if it is not on PATH)
#   SKIP_TESTS=1 ./build.sh         leave out the tests
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
ASM="${RG_ASM:-rg-asm}"
B="${BUILD:-build}"
command -v "$ASM" >/dev/null || { echo "build.sh: rg-asm not found: put it on PATH or set RG_ASM (see README)" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "build.sh: Python 3.10+ needed" >&2; exit 1; }
mkdir -p "$B"
if [ -z "${SKIP_TESTS:-}" ]; then
  for t in tests/test_*.py tests/check_limits.py; do "$PY" -I "$t" | tail -1; done
fi
"$PY" -I tools/lsp_ste.py assets/demo.mod "$B/LSPSTE.DAT"
"$PY" -I tools/fx_pack.py "$B/FX.DAT" assets/fx/jump.wav assets/fx/coin.wav assets/fx/hit.wav assets/fx/laser.wav assets/fx/boom.wav
"$ASM" -m 68000 -q --no-opt-size -Werror -I src -I example -o "$B/DEMO.PRG" example/demo.s
"$PY" -I tools/st_blank.py "$B/blank.st" AUTO
"$PY" -I tools/st_put.py "$B/blank.st" "$B/lsplayer_demo.st" "AUTO/DEMO.PRG=$B/DEMO.PRG" \
  "LSPSTE.DAT=$B/LSPSTE.DAT" "FX.DAT=$B/FX.DAT"
rm -f "$B/blank.st"
echo "built $B/lsplayer_demo.st"
