#!/usr/bin/env python3
"""Tests for the other tools: fx_pack, the disk tools, make_demo, the converter's and the renderer's command lines.
Run: python3 -I tests/test_tools.py. Expected values come from the file formats in the tool docstrings and the
FAT12 layout (an independent reader below), not from running the code."""
from __future__ import annotations

import contextlib
import io
import struct
import sys
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, Check, run
from fx_pack import FxError, pack
from lsp_ref import main as ref_main
from lsp_ste import main as ste_main
from make_demo import effects, module, write_wav
from mod_write import make_mod
from st_blank import blank
from st_put import Disk, DiskError


def make_wav(path: Path, frames: bytes, width: int = 1, rate: int = 12517, channels: int = 1) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


def refused_fx(fn: Callable[[], object], words: str) -> bool:
    try:
        fn()
    except FxError as e:
        return words in str(e)
    return False


def fx_checks() -> list[Check]:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        loud = make_wav(t / "a.wav", bytes([228] * 1000))                       # +100 on 8-bit unsigned
        quiet = make_wav(t / "b.wav", struct.pack("<500h", *([-8000] * 500)), 2, 12517)
        stereo = make_wav(t / "c.wav", bytes([128, 228] * 100), 1, 12517, 2)    # mean of the channels: +50
        dat = pack([loud, quiet])
        one = pack([stereo])
        slow = pack([make_wav(t / "d.wav", bytes([228] * 1000), 1, 6258)])      # half rate: twice the samples
        refusals = (refused_fx(lambda: pack([loud] * 17), "17 samples > 16")
                    and refused_fx(lambda: pack([t / "nope.wav"]), "not found")
                    and refused_fx(lambda: pack([]), "no WAV")
                    and refused_fx(lambda: pack([loud], max_total=900), "LSP_FXMAX"))
    count, o0, n0, o1, n1 = struct.unpack_from(">HIIII", dat, 4)
    return [
        ("fx: 'FX01', a count, then (offset, length) per sample in the order given",
         dat[:4] == b"FX01" and (count, o0, n0, o1, n1) == (2, 22, 1000, 22 + 1000 + 256, 500)),
        ("fx: a sample is normalised to 90 % of full scale: +100 of 128 becomes 114 (0.9 x 127); -8000 of 32768 becomes -114",
         set(dat[o0:o0 + n0]) == {114} and set(dat[o1:o1 + n1]) == {(-114) & 0xFF}),
        ("fx: 256 zero bytes follow each sample (one tick of padding) and the file ends with them",
         dat[o0 + n0:o0 + n0 + 256] == bytes(256) and len(dat) == o1 + n1 + 256),
        ("fx: stereo is mixed to mono", set(one[14:14 + 100]) == {114}),
        ("fx: a 6,258 Hz WAV is resampled to 12,517 Hz: twice as long (+-2)",
         abs(struct.unpack_from(">I", slow, 10)[0] - 2000) <= 2),
        ("fx: more samples than LSP_FXN (16), a missing file, no file and a file over the limit are refused",
         refusals),
    ]


def fat_files(img: bytes) -> dict[str, bytes]:
    """Independent FAT12 reader for the layout of st_blank.py: boot sector 1, FATs 2 x 5, root 7 sectors."""
    fat, root, data = 512, 11 * 512, 11 * 512 + 7 * 512 + 0 * 32
    def nxt(c: int) -> int:
        v = int.from_bytes(img[fat + c * 3 // 2:fat + c * 3 // 2 + 2], "little")
        return v >> 4 if c & 1 else v & 0xFFF
    out = {}
    for e in range(root, root + 112 * 32, 32):
        if img[e] in (0, 0xE5) or img[e + 11] & 0x10:
            continue
        name = img[e:e + 8].decode().strip() + "." + img[e + 8:e + 11].decode().strip()
        c, size, buf = int.from_bytes(img[e + 26:e + 28], "little"), int.from_bytes(img[e + 28:e + 32], "little"), b""
        while 2 <= c < 0xFF0:
            buf += img[data + (c - 2) * 1024:data + (c - 1) * 1024]
            c = nxt(c)
        out[name] = buf[:size]
    return out


def disk_checks() -> list[Check]:
    img = blank(["AUTO"])
    d = Disk(img)
    big, small = bytes(range(256)) * 20, b"hello"
    d.put("A.DAT", big)
    d.put("AUTO/B.PRG", small)
    n_before = sum(1 for c in range(2, d.ncl) if d.get(c) == 0)
    d.put("A.DAT", small)                                   # smaller: the old clusters are freed
    n_after = sum(1 for c in range(2, d.ncl) if d.get(c) == 0)
    files = fat_files(bytes(d.img))
    sub = Disk(blank(["AUTO"]))
    sub.put("AUTO/B.PRG", small)
    root_names = [n for n in fat_files(bytes(sub.img))]
    full = Disk(blank([]))
    return [
        ("disk: a blank 720 KB image is 1,440 sectors of 512 B, media byte $F9, folders listed as directories",
         len(img) == 1440 * 512 and img[512] == 0xF9 and img[11 * 512:11 * 512 + 4] == b"AUTO"),
        ("disk: files put in the root and in a folder read back, byte for byte, with the right size",
         files.get("A.DAT") == small and fat_files(bytes(Disk(blank(["AUTO"])).img)) == {}),
        ("disk: 5,120 B take 5 clusters of 1,024 B; replacing it with 5 B leaves one: 4 clusters are freed",
         n_after - n_before == 4),
        ("disk: a file in a folder is not in the root directory", root_names == []),
        ("disk: a missing folder, a full disk and a full directory are refused",
         _refused(lambda: d.put("NOPE/X.DAT", small), "folder NOPE not found")
         and _refused(lambda: full.put("BIG.DAT", bytes(711 * 1024 + 1)), "needs 712 clusters, 711 free")
         and _refused(lambda: _fill_root(Disk(blank([]))), "directory full")),
    ]


def _fill_root(d: Disk) -> None:
    for i in range(113):
        d.put(f"F{i}.DAT", b"x")


def _refused(fn: Callable[[], object], words: str) -> bool:
    try:
        fn()
    except DiskError as e:
        return words in str(e)
    return False


def demo_checks() -> list[Check]:
    fx = effects()
    with tempfile.TemporaryDirectory() as tmp:
        write_wav(Path(tmp) / "x.wav", fx["jump"])
        with wave.open(str(Path(tmp) / "x.wav")) as w:
            fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
    return [
        ("demo: make_demo is deterministic (two runs give the same module and effects)",
         module() == module() and effects() == fx),
        ("demo: the module is 1,084 + 3 patterns x 1,024 + 4 samples (1,400 + 64 + 600 + 32 B) = 6,252 B",
         len(module()) == 1084 + 3 * 1024 + 1400 + 64 + 600 + 32),
        ("demo: five effects as 8-bit mono 11,025 Hz WAVs, 0.18 s for the jump",
         len(fx) == 5 and fmt == (1, 1, 11025, int(11025 * 0.18))),
    ]


def cli_checks() -> list[Check]:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        bad = t / "bad.mod"
        bad.write_bytes(make_mod([{(0, 0): (1, 428, 7, 5)}], [0], [(bytes(300), 64, 0, 0, 0)]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc_bad = ste_main(["lsp_ste.py", str(bad), str(t / "o.dat")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc_ok = ste_main(["lsp_ste.py", str(ROOT / "assets/demo.mod"), str(t / "o.dat")])
            rc_wav = ref_main(["lsp_ref.py", str(t / "o.dat"), str(t / "o.wav"), "--ticks", "100"])
        with wave.open(str(t / "o.wav")) as w:
            fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
        made = (t / "o.dat").is_file() and not (t / "nope.dat").exists()
    return [
        ("cli: an unsupported effect gives exit code 1, the place, and the list of supported ones, and no output file",
         rc_bad == 1 and "pattern 0 row 0 channel 1: effect 705 is not supported" in err.getvalue()
         and "Fxx speed 1..31" in err.getvalue()),
        ("cli: the converter writes the file and says how many variants and ticks", rc_ok == 0 and made
         and "16 variants, 728 ticks (loop to 160)" in out.getvalue()),
        ("cli: the renderer writes 100 ticks x 252 B as 8-bit mono 12,517 Hz", rc_wav == 0 and fmt == (1, 1, 12517, 25200)),
    ]


def main() -> int:
    return run("tools tests", [fx_checks, disk_checks, demo_checks, cli_checks])


if __name__ == "__main__":
    sys.exit(main())
