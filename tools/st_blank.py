#!/usr/bin/env python3
"""Make a blank FAT12 Atari disk image (720 KB: 80 tracks, 2 sides, 9 sectors), with empty folders in its root.

    python3 -I tools/st_blank.py OUT.st [FOLDER]...        e.g. OUT.st AUTO

Layout (what TOS formats): 512-byte sectors, 2 per cluster, 1 boot sector, 2 FATs of 5 sectors, 112 root
entries (7 sectors), data from sector 18, 711 clusters. The boot sector is not executable (its word checksum is
not $1234); files are added with tools/st_put.py.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

BPS, SPC, RES, NFAT, NROOT, TOTAL, MEDIA, SPF, SPT, SIDES = 512, 2, 1, 2, 112, 1440, 0xF9, 5, 9, 2
DATA = (RES + NFAT * SPF) * BPS + NROOT * 32


class BlankError(ValueError):
    """A folder name the tool refuses (the message says why)."""


def entry(name: str, attr: int, cluster: int) -> bytes:
    return name.ljust(11).encode() + bytes([attr]) + bytes(14) + struct.pack("<HI", cluster, 0)


def blank(folders: list[str]) -> bytes:
    img = bytearray(TOTAL * BPS)
    img[0:2] = b"\xEB\x34"
    img[8:11] = b"LSP"                                          # serial number
    struct.pack_into("<HBHBHHBHHH", img, 11, BPS, SPC, RES, NFAT, NROOT, TOTAL, MEDIA, SPF, SPT, SIDES)
    if sum(struct.unpack(">256H", img[:512])) & 0xFFFF == 0x1234:
        raise BlankError("boot sector checksum is $1234 (it would be executed)")
    fat = bytearray(SPF * BPS)
    fat[0:3] = bytes([MEDIA, 0xFF, 0xFF])
    root = RES * BPS + NFAT * SPF * BPS
    for k, name in enumerate(folders):
        if not (name.isalnum() and name.isupper() and len(name) <= 8) or name in folders[:k]:
            raise BlankError(f"folder {name!r}: want 1..8 upper-case letters or digits, each name once")
        c = 2 + k
        o = c * 3 // 2
        v = int.from_bytes(fat[o:o + 2], "little")
        fat[o:o + 2] = ((v & 0x000F) | (0xFFF << 4) if c & 1 else (v & 0xF000) | 0xFFF).to_bytes(2, "little")
        img[root + 32 * k:root + 32 * k + 32] = entry(name, 0x10, c)
        at = DATA + (c - 2) * SPC * BPS
        img[at:at + 64] = entry(".", 0x10, c) + entry("..", 0x10, 0)
    for f in range(NFAT):
        img[(RES + f * SPF) * BPS:(RES + (f + 1) * SPF) * BPS] = fat
    return bytes(img)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    try:
        Path(argv[1]).write_bytes(blank(argv[2:]))
    except (BlankError, OSError) as e:
        print(f"st_blank: {e}", file=sys.stderr)
        return 1
    print(f"st_blank: {argv[1]}: {TOTAL * BPS} B, folders: {' '.join(argv[2:]) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
