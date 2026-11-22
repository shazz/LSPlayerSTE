#!/usr/bin/env python3
"""STE sound effects: WAV files -> FX.DAT (DMA samples for the LSPSTE player's effects channel).

    python3 -I tools/fx_pack.py OUT_FX.DAT A.wav B.wav ... [--max-count 16] [--max-total 61440]

Sample 0 is the first WAV, and so on (keys 1..9 of the example play 0..8). FX.DAT: 'FX01', w count,
count x (l offset from the file start, l length), then the samples: signed 8-bit mono at 12,517 Hz (STE DMA mode
$81), each at an even offset with an even length and followed by PAD zero bytes (not in its length): the mixer
reads whole 252-byte ticks, so it may read that far past a sample's end. --max-count and --max-total are
LSP_FXN and LSP_FXMAX of src/lsp_config.s.
Stdlib only: any PCM WAV (8/16-bit, mono/stereo, any rate) is mixed to mono, low-passed and resampled.
"""
from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

RATE = 12517                       # STE DMA "12.5 kHz" mode (8,012,800 Hz / 640)
PEAK = 0.9                         # normalise to 90 % of full scale
MAX_TOTAL = 0xF000                 # LSP_FXMAX in src/lsp_config.s
MAX_COUNT = 16                     # LSP_FXN in src/lsp_config.s
PAD = 256                          # silence after each sample (at least one tick)


class FxError(ValueError):
    """A map or WAV the packer refuses (the message says why)."""


def read_wav(path: Path) -> tuple[list[float], int]:
    """Mono samples in -1..1 and the source rate."""
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width not in (1, 2):
        raise FxError(f"{path.name}: {8 * width}-bit samples (8 or 16-bit PCM only)")
    if width == 1:
        vals = [(b - 128) / 128 for b in raw]
    else:
        vals = [v / 32768 for v in struct.unpack(f"<{len(raw) // 2}h", raw)]
    mono = [sum(vals[i:i + ch]) / ch for i in range(0, len(vals) - ch + 1, ch)]
    if not mono:
        raise FxError(f"{path.name}: no samples")
    return mono, rate


def resample(x: list[float], src: int, dst: int = RATE) -> list[float]:
    """Box low-pass over one output period, then linear interpolation."""
    k = max(1, round(src / dst))
    if k > 1:
        acc, sm = 0.0, []
        for i, v in enumerate(x):
            acc += v - (x[i - k] if i >= k else 0.0)
            sm.append(acc / k)
        x = sm
    n = int(len(x) * dst / src)
    out = []
    for j in range(n):
        p = j * src / dst
        i = int(p)
        f = p - i
        out.append(x[i] * (1 - f) + x[min(i + 1, len(x) - 1)] * f)
    return out


def to_s8(x: list[float]) -> bytes:
    peak = max(abs(v) for v in x) or 1.0
    s = bytes((max(-127, min(127, round(v / peak * PEAK * 127))) & 0xFF) for v in x)
    return s + (b"\0" if len(s) & 1 else b"")


def pack(wavs: list[Path], max_count: int = MAX_COUNT, max_total: int = MAX_TOTAL) -> bytes:
    """FX.DAT from WAV files; the sample index is the position in the list."""
    if not wavs:
        raise FxError("no WAV files given")
    if len(wavs) > max_count:
        raise FxError(f"{len(wavs)} samples > {max_count} (LSP_FXN in src/lsp_config.s)")
    blobs = []
    for p in wavs:
        if not p.is_file():
            raise FxError(f"{p}: not found")
        mono, rate = read_wav(p)
        blobs.append(to_s8(resample(mono, rate)))
    out, table, off = bytearray(b"FX01" + struct.pack(">H", len(blobs))), [], 6 + 8 * len(blobs)
    for b in blobs:
        table.append(struct.pack(">II", off, len(b)))
        off += len(b) + PAD
    out += b"".join(table) + b"".join(b + bytes(PAD) for b in blobs)
    if len(out) > max_total:
        raise FxError(f"FX.DAT would be {len(out)} B > {max_total} B (LSP_FXMAX in src/lsp_config.s)")
    return bytes(out)


def main(argv: list[str]) -> int:
    args = argv[1:]
    opt = {"--max-count": MAX_COUNT, "--max-total": MAX_TOTAL}
    for name in opt:
        if name in args:
            i = args.index(name)
            opt[name] = int(args[i + 1])
            del args[i:i + 2]
    if len(args) < 2:
        raise SystemExit(__doc__)
    try:
        dat = pack([Path(a) for a in args[1:]], opt["--max-count"], opt["--max-total"])
    except (FxError, OSError, wave.Error) as e:
        print(f"fx_pack: {e}", file=sys.stderr)
        return 1
    Path(args[0]).write_bytes(dat)
    print(f"fx_pack: {args[0]}: {len(dat)} B, {len(args) - 1} samples")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
