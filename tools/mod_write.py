"""Write a ProTracker 'M.K.' module from Python data (used by make_demo.py and the tests)."""
from __future__ import annotations

import struct

# (row, channel) -> (sample number 1..31 or 0, period or 0, effect 0..15, argument 0..255)
Cells = dict[tuple[int, int], tuple[int, int, int, int]]
# (signed 8-bit data, volume 0..64, finetune 0..15, loop start in bytes, loop length in bytes, 0 = no loop)
SampleDef = tuple[bytes, int, int, int, int]


def make_mod(patterns: list[Cells], order: list[int], samples: list[SampleDef], title: str = "test") -> bytes:
    """Sample i + 1 is samples[i]. Every pattern has 64 rows; cells not given are empty."""
    out = bytearray(title.encode("ascii").ljust(20, b"\0"))
    for i in range(31):
        d, vol, fine, ls, ll = samples[i] if i < len(samples) else (b"", 0, 0, 0, 0)
        out += bytes(22) + struct.pack(">HBBHH", len(d) // 2, fine, vol, ls // 2, (ll // 2) or 1)
    out += bytes([len(order), 0]) + bytes(order).ljust(128, b"\0") + b"M.K."
    for cells in patterns:
        pat = bytearray(1024)
        for (row, ch), (s, per, eff, arg) in cells.items():
            o = (row * 4 + ch) * 4
            pat[o:o + 4] = bytes([(s & 0xF0) | (per >> 8), per & 0xFF, ((s & 0x0F) << 4) | eff, arg])
        out += pat
    return bytes(out) + b"".join(s[0] for s in samples)
