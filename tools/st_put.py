#!/usr/bin/env python3
"""Put files on a FAT12 .st image: replace (any size) or add, both FATs updated.

    python3 -I tools/st_put.py IN.st OUT.st DEST=SRC...        e.g. AUTO/DEMO.PRG=build/DEMO.PRG

DEST is a path from the root (folders must exist, 8.3 names); a new file goes into that folder's directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from st_fat import chain, geometry


class DiskError(ValueError):
    """The image cannot take the change (the message says why)."""


class Disk:
    def __init__(self, img: bytes) -> None:
        self.img = bytearray(img)
        self.g = geometry(img)
        def le(o: int) -> int:
            return int.from_bytes(img[o:o + 2], "little")
        self.bps, self.nfat, self.spf = le(11), img[16], le(22)
        total = le(19) or int.from_bytes(img[32:36], "little")
        self.ncl = (total * self.bps - self.g["data"]) // self.g["csize"] + 2

    def get(self, c: int) -> int:
        o = self.g["fat"] + c * 3 // 2
        v = int.from_bytes(self.img[o:o + 2], "little")
        return v >> 4 if c & 1 else v & 0xFFF

    def set_fat(self, c: int, val: int) -> None:
        for f in range(self.nfat):
            o = self.g["fat"] + f * self.spf * self.bps + c * 3 // 2
            v = int.from_bytes(self.img[o:o + 2], "little")
            v = (v & 0x000F) | (val << 4) if c & 1 else (v & 0xF000) | val
            self.img[o:o + 2] = v.to_bytes(2, "little")

    def entry(self, path: str) -> tuple[int, int | None]:
        """(directory-entry byte offset or -1, first cluster of the folder or None for the root) for path."""
        parts = path.upper().split("/")
        folder: int | None = None
        for k, part in enumerate(parts):
            stem, _, ext = part.partition(".")
            name = stem.ljust(8).encode() + ext.ljust(3).encode()
            slots = self.slots(folder)
            hit = [o for o in slots if self.img[o:o + 11] == name and self.img[o] not in (0, 0xE5)]
            if k == len(parts) - 1:
                return (hit[0] if hit else -1), folder
            if not hit or not self.img[hit[0] + 11] & 0x10:
                raise DiskError(f"{path}: folder {part} not found")
            folder = int.from_bytes(self.img[hit[0] + 26:hit[0] + 28], "little")
        raise DiskError(f"{path}: empty path")

    def slots(self, folder: int | None) -> list[int]:
        if folder is None:
            return list(range(self.g["root"], self.g["root"] + self.g["nroot"] * 32, 32))
        return [self.g["data"] + (c - 2) * self.g["csize"] + i
                for c in chain(bytes(self.img), self.g, folder) for i in range(0, self.g["csize"], 32)]

    def put(self, path: str, data: bytes) -> int:
        e, folder = self.entry(path)
        if e >= 0:
            for c in chain(bytes(self.img), self.g, int.from_bytes(self.img[e + 26:e + 28], "little")):
                self.set_fat(c, 0)
        else:
            free = [o for o in self.slots(folder) if self.img[o] in (0, 0xE5)]
            if not free:
                raise DiskError(f"{path}: directory full")
            e = free[0]
            stem, _, ext = path.upper().split("/")[-1].partition(".")
            self.img[e:e + 32] = stem.ljust(8).encode() + ext.ljust(3).encode() + bytes(21)
        need = -(-len(data) // self.g["csize"])
        cls = [c for c in range(2, self.ncl) if self.get(c) == 0][:need]
        if len(cls) < need:
            raise DiskError(f"{path}: needs {need} clusters, {len(cls)} free")
        for a, b in zip(cls, cls[1:] + [0xFFF]):
            self.set_fat(a, b)
        for i, c in enumerate(cls):
            piece = data[i * self.g["csize"]:(i + 1) * self.g["csize"]]
            o = self.g["data"] + (c - 2) * self.g["csize"]
            self.img[o:o + self.g["csize"]] = piece.ljust(self.g["csize"], b"\0")
        self.img[e + 26:e + 28] = (cls[0] if cls else 0).to_bytes(2, "little")
        self.img[e + 28:e + 32] = len(data).to_bytes(4, "little")
        return len(cls)


def main(argv: list[str]) -> int:
    args = argv[1:]
    if len(args) < 3 or not all("=" in a for a in args[2:]):
        raise SystemExit(__doc__)
    try:
        d = Disk(Path(args[0]).read_bytes())
        for spec in args[2:]:
            dest, src = spec.split("=", 1)
            n = d.put(dest, Path(src).read_bytes())
            print(f"st_put: {dest}: {Path(src).stat().st_size} B in {n} clusters")
    except (ValueError, OSError) as e:                  # DiskError is a ValueError
        print(f"st_put: {e}", file=sys.stderr)
        return 1
    Path(args[1]).write_bytes(bytes(d.img))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
