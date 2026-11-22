#!/usr/bin/env python3
"""LSPSTE converter: a ProTracker module -> LSPSTE.DAT, for the light STE player (the idea of Leonard's LSP: the
song is played off line into a per-tick event stream, the samples are prepared per note, the run-time only mixes).

    python3 -I tools/lsp_ste.py SONG.mod LSPSTE.DAT [--music-peak 80] [--fx-peak 47]
                                [--max-file 65536] [--max-bank 339968]

The module must stay in the subset of lsp_mod.py (refused with the place otherwise). --max-file and --max-bank
are the sizes of the player's file and bank areas (src/lsp_config.s: LSP_DATMAX, LSP_LIMIT - LSP_BANK).
Headroom: the music gain is
set so that the exact mix of the whole song (intro + two passes of its loop, lsp_ref.py) peaks at --music-peak or
less; the effects channel is scaled to +-fx-peak by a table; the two must add up to 127 at most, so the five
channels can never leave a signed byte (which the long-add mixer relies on).
Parts: lsp_mod (module, subset), lsp_seq (timeline, stream), lsp_bank (variants, resampling), lsp_dat (file).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lsp_bank import plan
from lsp_dat import MAX_BANK, MAX_FILE, head, pack, voff
from lsp_mod import ModError, parse
from lsp_ref import levels
from lsp_seq import encode, simulate

FIRST_GAIN = 16000                  # under 1/4: four full-scale channels cannot overflow the first measure
TRIES = 8


@dataclass(frozen=True)
class Built:
    dat: bytes
    gain: int                       # 16.16
    low: int
    high: int
    rms: float
    ticks: int                      # song length
    loop: int                       # tick it loops to
    variants: int


def build(mod_bytes: bytes, music_peak: int = 80, fx_peak: int = 47,
          max_file: int = MAX_FILE, max_bank: int = MAX_BANK) -> Built:
    if not (0 < music_peak and 0 < fx_peak and music_peak + fx_peak <= 127):
        raise ModError(f"music peak {music_peak} + effects peak {fx_peak} must be 127 or less")
    mod = parse(mod_bytes)
    tl = simulate(mod)
    pl = plan(mod, tl.hold)
    stream, loop_off = encode(tl, {v.key: voff(i) for i, v in enumerate(pl.variants)})
    span = len(tl.ticks) + 2 * (len(tl.ticks) - tl.loop)
    gain = FIRST_GAIN
    for _ in range(TRIES):
        dat = pack(pl, gain, fx_peak, stream, loop_off, max_file, max_bank)
        low, high, rms = levels(dat, span)
        peak = max(-low, high, 1)
        if peak <= music_peak and gain != FIRST_GAIN:
            return Built(dat, gain, low, high, rms, len(tl.ticks), tl.loop, len(pl.variants))
        gain = gain * music_peak // peak - (0 if gain == FIRST_GAIN else 64)
    raise ModError(f"no gain keeps the music under {music_peak} after {TRIES} tries")


def main(argv: list[str]) -> int:
    args = argv[1:]
    opt = {"--music-peak": 80, "--fx-peak": 47, "--max-file": MAX_FILE, "--max-bank": MAX_BANK}
    for name in opt:
        if name in args:
            i = args.index(name)
            opt[name] = int(args[i + 1])
            del args[i:i + 2]
    if len(args) != 2:
        raise SystemExit(__doc__)
    try:
        b = build(Path(args[0]).read_bytes(), opt["--music-peak"], opt["--fx-peak"], opt["--max-file"],
                  opt["--max-bank"])
    except (ModError, OSError) as e:
        print(f"lsp_ste: {e}", file=sys.stderr)
        return 1
    Path(args[1]).write_bytes(b.dat)
    bank = head(b.dat).bank
    print(f"lsp_ste: {args[1]}: {len(b.dat)} B + {bank} B bank built at start, {b.variants} variants, "
          f"{b.ticks} ticks (loop to {b.loop}), gain {b.gain / 65536:.4f}, music {b.low}..{b.high} "
          f"rms {b.rms:.1f}, effects +-{opt['--fx-peak']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
