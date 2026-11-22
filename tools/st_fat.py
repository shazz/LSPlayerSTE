"""FAT12 geometry and cluster chains of an Atari .st image (shared by st_blank.py and st_put.py)."""
from __future__ import annotations


def geometry(img: bytes) -> dict[str, int]:
    """Byte offsets and sizes from the boot sector: FAT, root directory, data area, cluster size."""
    def le(o: int, n: int) -> int:
        return int.from_bytes(img[o:o + n], "little")
    bps, spc, res, nfat, nroot, spf = le(11, 2), img[13], le(14, 2), img[16], le(17, 2), le(22, 2)
    root = (res + nfat * spf) * bps
    return {"fat": res * bps, "root": root, "nroot": nroot, "data": root + nroot * 32, "csize": spc * bps}


def chain(img: bytes, g: dict[str, int], cl: int) -> list[int]:
    """The clusters of a file, from its first one; a loop in the FAT is an error."""
    out: list[int] = []
    while 2 <= cl < 0xFF0:
        if cl in out:
            raise ValueError(f"FAT loop at cluster {cl}")
        out.append(cl)
        v = int.from_bytes(img[g["fat"] + cl * 3 // 2:g["fat"] + cl * 3 // 2 + 2], "little")
        cl = v >> 4 if cl & 1 else v & 0xFFF
    return out
