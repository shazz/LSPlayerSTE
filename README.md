# LSPlayerSTE

A light module player for the Atari STE, in 68000 assembly, with the Python tools that prepare the music.

It plays a ProTracker module (four channels) plus one channel of sound effects through the STE's 8-bit DMA
sound, mixed in software, for about 5 % of a frame. It was written for an STE enhancement of an old game
(that game's code and data are not part of this repository), and cleaned up so that it can be dropped into
other STE games.

**Inspired by Leonard's LSP (Light Speed Player, Amiga):** like LSP, the module is played off line into a
compact per-tick event stream, and the run-time player only follows that stream. The file format, the player
and the tools here are new and **not compatible with LSP**. This project is not affiliated with Leonard or LSP.

## How it works

In one sentence: everything a module player normally does each tick (reading patterns, effects, period maths,
resampling, volume) is done once, on the PC, and what is left for the 68000 is adding bytes.

```
 song.mod --lsp_ste.py--> LSPSTE.DAT --lsp_init (68000, once)--> bank  --lsp_vbl (68000, every VBL)--> DMA ring
           (PC, off line)  samples,       resample every variant    of      follow the stream, add five      looped by
                           event stream,  to 12,517 Hz, scale       ready   252-byte chunks as 63 longs      the STE
                           volume tables                            bytes                                     sound DMA
```

1. `tools/lsp_ste.py` reads a `.mod`, plays it off line tick by tick with ProTracker's rules (effects
   included), finds where the song loops, and writes `LSPSTE.DAT`: the source samples, a stream of "channel n
   now plays from this place" events, and volume tables. Every distinct (sample, period, volume) the song plays
   is a *variant*.
2. At start-up the 68000 loader builds the **bank**: every variant resampled to 12,517 Hz, scaled, and stored as
   a straight run of bytes (loops unrolled): the bytes the song reads of it and no more. It is built at run
   time because it is several times bigger than the file.
3. Once per VBL, `lsp_vbl` mixes one tick: it follows the stream, then adds five 252-byte chunks (four music
   channels, one effect) as 63 long words and writes the result into a ring buffer that the DMA loops over.
   No per-note work remains at run time: no period maths, no sample-end tests, no volume multiplies.

**Effects without run-time work.** The player has one kind of event: point a channel at a byte of the bank. A
new note points at the start of a variant. An arpeggio, a slide, a vibrato or a volume change points the
channel into *another* variant (the same sample at the new period or volume), at the byte that matches where
the note is in its sample, worked out off line. So a channel that changes pitch every tick costs one event
per tick (70 cycles) and nothing else. Two consequences: the mixer reads long words, so that byte is
even and a pitch change can land up to one output byte (80 us) from the exact place (a volume change alone
keeps its byte, except far into a loop, where the note is taken back to the loop's start like a pitch
change; inside a short loop the converter picks, among the turns of the loop, one that falls near an even
byte); and each period and volume a note passes through is a variant in the bank, which is why a looped
sample is re-entered near the start of its loop, so that such a variant holds one turn of the loop, not the
whole note.

The mixer matched `tools/lsp_ref.py` (a Python model that also renders WAV files) byte for byte in emulator
runs: about 1,400 ticks of the demo, and 7,302 ticks (a whole song and the start of its loop) of a module
with effects: see [TESTING.md](TESTING.md).

## Features

- Four ProTracker channels + one effects channel (`lsp_fx`), mono, 12,517 Hz, STE DMA mode `$81`.
- ProTracker effects: arpeggio, portamento up/down and to a note, vibrato, volume slides, sample offset,
  retrigger, note cut and delay, fine slides, volumes inside a note (list under Limits).
- The module is converted off line; it never needs to be parsed on the Atari. The converter refuses what the
  player cannot play and says where (pattern, row, channel) and which effects are supported.
- Hold / resume (pause screens) that mutes the music and freezes it in place while effects go on.
- Start, halt and stop calls; effects can be fired from any context (main loop, VBL, any interrupt).
- Every address and size is an equate in one file, `src/lsp_config.s`, with assembly-time checks.
- STE probe (TOS version, cookie jar, `_SND` bit) so a game can fall back to its YM sound on other machines.
- Python 3 standard library only for the tools; `ruff` and `mypy --strict` clean.

## Limits

- **Supported module subset:** `M.K.` (4 channels), finetune 0, notes only on the ProTracker period table, and
  the effects `0xy` arpeggio, `1xx` `2xx` portamento, `3xx` tone portamento, `4xy` vibrato, `5xy` `6xy` (the
  same with a volume slide), `9xx` sample offset, `Axy` volume slide, `Bxx` position jump, `Cxx` volume,
  `Dxx` pattern break, `E0x` (the Amiga's filter: ignored), `E1x` `E2x` fine portamento, `E9x` retrigger,
  `EAx` `EBx` fine volume, `ECx` note cut, `EDx` note delay, `Fxx` with speed 1..31. They follow the
  ProTracker 2.3 replay routine, quirks included (HOWTO.md lists them).
  **Refused:** `7xy` tremolo, `8xx`, `E3x` glissando, `E4x`/`E7x` waveforms, `E5x` and sample finetune, `E6x`
  pattern loop, `EEx` pattern delay, `EFx` invert loop, `F00`, BPM tempo (`F20` and above), an arpeggio that
  goes above B-3, a sample number without a note while another sample plays, a period outside 57..4095. A
  looped sample must be replaced or cut (or silenced: `C00`) within the song's loop.
- **Pitch changes are placed to the nearest even output byte** (see How it works): at most 80 us off, usually
  much less inside short loops. On the song this was written for, the converter's output and an exact
  (floating-point) render of the same ProTracker registers correlate at 0.992.
- **Effects that remember** (`300`, `400`, `900`) can make the first pass of a song differ from the next ones,
  as in ProTracker; the stream then holds the song's start twice (once as played first, once as looped).
- **Rate:** 12,517 Hz mono. Samples played above about 17.7 kHz at their ProTracker pitch are resampled
  with a two-sample average first. No stereo, no 25/50 kHz mode.
- **Tempo:** a tick is 252 bytes, 12,517 / 252 = 49.67 ticks per second, so the song runs 0.66 % slower than
  a 50 Hz ProTracker tick.
- **Noise:** the five channels are added in a signed byte without overflow checks, so each music channel is
  scaled to about +-24 levels (the music peaks at 80, effects at 47, together at most 127). That costs about
  29 dB signal to noise: fine for chip music, not for hi-fi samples.
- **One effect at a time:** a second `lsp_fx` in the same tick replaces the first; a new effect replaces one
  still playing. Effects start 10 to 30 ms after the call (the mixer works about 1.5 ticks ahead of the DMA).
- **Hardware:** an STE (or STE mode of an emulator) with 1 MB and TOS 1.06 or newer (`LSP_MINTOS` in `src/lsp_config.s`). The default memory map needs RAM up to `$F4000`.
  Not run on real hardware, on a plain ST, or on a TT/Falcon (the probe would accept their `_SND` cookie but
  nothing there was tested). Only TOS 1.62 was used for the emulator runs; TOS 1.06 is accepted by the probe but was not run.
- **Untrusted files:** `lsp_init` checks size, magic, version, checksum, that the variants account for the
  bank, that their renditions lie in the file and that every target of the stream lies in the bank; it does
  not defend against a crafted `LSPSTE.DAT` (the header's own offsets are trusted, and the stream's target
  numbers are not checked against the table).
- The player programs the sound DMA registers and does not touch the Microwire/LMC1992 (volume, tone).

## Memory

Defaults (`src/lsp_config.s`), on a 1 MB STE:

| Area | Address | Size |
|---|---|---|
| Effects (`FX.DAT`, one image, converted in place) | `$81000` | up to 60 KB, 16 samples |
| DMA ring (8 ticks) + one silent tick | `$90000` | 2,016 + 252 B |
| `LSPSTE.DAT` as loaded | `$91000` | up to 64 KB |
| Bank, built at start | `$A1000` | up to 332 KB (end `$F4000`) |

The bank is the sum of the variants' sizes and depends on the module: 56 KB for the demo song, about
233 KB for a twelve-position song with 41 variants (plain notes, long held loops), 244 KB for a 25-position
song with arpeggios, vibrato, slides and volume changes inside notes (168 variants; its file is 50 KB). The
converter prints it, and `lsp_init` returns error 4
if the song does not fit. The run-time code and its variables (`lsp_v` to the end of `lsp_mix.s`: 2,322 bytes) are part of your program
wherever you assemble it; they use PC-relative addressing for their own data, so they assemble to identical bytes
at any address. The start-up code (`lsp_init`, `lsp_bank`) can be thrown away afterwards.

## Benchmarks

Cycles are 68000 cycles spent in `lsp_vbl` and the routines it calls (range `lsp_vbl` to the end of `lsp_mix`),
per VBL; a frame is 160,256 cycles. One tick is 63 long-word mixes of five channels.

**Measured on the demo in this repository** (Hatari 2.6.1, STE, TOS 1.62, `--compatible on --cpu-exact on`,
ShirazMCP `profile_raw`, one frame per call, 150 frames for each of the first two rows, 100 for the third):

| Case | Average | Worst | Average % of frame | Worst % of frame |
|---|---|---|---|---|
| Music only | 7,452 | 8,316 | 4.65 % | 5.19 % |
| Music + an effect (re-posted every frame, so one is always playing) | 7,810 | 8,336 | 4.87 % | 5.20 % |
| Silent (after `lsp_halt`, ring all silence: no mixing) | 934 | 996 | 0.58 % | 0.62 % |

Those three rows are from format version 1 (before the module effects). **Format version 2**, same method, 300
frames a row (two runs of 150; the version 1 code re-measured in the same session for comparison):

| Case | Average | Worst | Average % of frame | Worst % of frame |
|---|---|---|---|---|
| Demo, music only, version 1 code | 7,497 | 8,232 | 4.68 % | 5.14 % |
| Demo, music only, version 2 code | 7,491 | 8,160 | 4.67 % | 5.09 % |
| A song with effects (arpeggio, vibrato, slides, volume changes: up to 4 events a tick), music only, 500 frames | 7,836 | 8,256 | 4.89 % | 5.15 % |

An event costs 70 cycles now (114 before; both counted from 68000 timings, not measured): the mix itself is
unchanged, so a song with effects costs what its events cost, at most four a tick.

The cheapest frame of the music runs is 524 cycles: about one VBL in 130 mixes nothing, because the DMA plays
250.3 bytes per 1/50 s and a tick is 252. Averages move with the window and with how the code lines up with the
ST's 4-cycle bus slots (an `add.l (An)+` costs 14 or 16 cycles): two other 100-frame runs of the music gave
6,996 and 7,738. Nothing in the demo ever needed two ticks in one VBL; forced in the game build it cost 14,876
(9.3 %).

**Measured in the game the player was written for** (Metro-Cross STE build, course 8, 100 frames, taken from the
development notes; this includes the game's own glue code around `lsp_vbl`, and the player has since been
reworked for release, which was not re-measured in the game):

| Case | Average | Worst | Average % | Worst % |
|---|---|---|---|---|
| Music + effects, whole run-time block | 7,954 | 8,352 | 4.96 % | 5.21 % |
| `lsp_vbl` alone | 7,716 | - | 4.8 % | - |
| Module silent | 1,149 | - | 0.72 % | - |

**Compared with another STE player.** Uko's [STE_FullScreen_MOD_Play](https://github.com/Uko-TAL/STE_FullScreen_MOD_Play)
(The Arctic Land, 2019-2020) is built for fullscreen demos: fixed CPU time, stereo, six modes trading memory
and sound for speed. Both players were measured the same way (Hatari 2.6.1, STE, TOS 1.62, 4 MB, `profile_raw`
one frame per call), Uko's at 12,517 Hz over `mp_read_song` + `mp_premix` + `mp_mix` (100 frames a mode),
LSPSTE over `lsp_vbl` to the end of `lsp_mix` (150 frames, music only). The module is Uko's own `ILLUSION.MOD`.
LSPSTE needed a 4 MB memory map for it (file area 256 KB at `$100000`, bank to `$3C0000`): its file is
160 KB and its bank 1.48 MB.

| Player, mode | Volume command `Cxx` | Average | Worst | Average % of frame |
|---|---|---|---|---|
| **LSPSTE** (mono, 4 channels + 1 effects channel) | yes | **7,726** | **8,200** | **4.82 %** |
| Uko, 0 classical | no | 26,388 | 27,036 | 16.47 % |
| Uko, 1 classical | yes | 39,023 | 39,748 | 24.35 % |
| Uko, 2 oversampling | no | 13,825 | 14,776 | 8.63 % |
| Uko, 3 oversampling | yes | 26,461 | 27,572 | 16.51 % |
| Uko, 4 extreme (6-bit samples) | no | 8,708 | 9,352 | 5.43 % |
| Uko, 5 extreme (6-bit samples) | yes | 18,538 | 19,652 | 11.57 % |

Uko's figures are within about a point of the ones in his source (they count the mix alone; these include his
per-frame song reading). On this repository's demo module his modes cost the same within 5 %. What the numbers
leave out: Uko's player is stereo and takes the same time every frame (what a fullscreen demo needs), but plays
only the `Fxx` and `Cxx` commands; its extreme modes need about 900 KB for Illusion. LSPSTE is mono, varies
by a few hundred cycles from frame to frame, plays the effects listed under Limits, and its memory grows with
the number of (sample, period, volume) combinations the song uses.

**Start-up and memory (demo module, 8 MHz, cycle counts from the same profiler):**

| Item | Value |
|---|---|
| Bank build (`lsp_bank`) | 10.51 M cycles, 1.31 s (186 cycles a byte) |
| `LSPSTE.DAT` check (size, checksum, variants, targets) | 0.16 M cycles, 0.02 s |
| `FX.DAT` check and scaling | 1.01 M cycles, 0.13 s |
| Reading the files | not measured (floppy emulation time is not meaningful) |
| `lsp_stop` (ring clear, interrupts masked) | about 17,500 cycles (2.2 ms), computed, not measured |
| DMA ring + silent tick | 2,016 + 252 = 2,268 B |
| Bank (16 variants, 224 ticks x 252 B) | 56,448 B |
| `LSPSTE.DAT` as loaded | 4,316 B |
| FX area (`FX.DAT`, 5 samples) | 21,098 B |
| Run-time code and variables | 2,322 B (start-up code 920 B more) |
| Total RAM for the demo | about 86 KB |

The bank depends on the module (the sum of its variants): 56 KB for the demo song; 244 KB for the song with
effects above, built in 45.7 M cycles (5.7 s), its 50 KB file checked in 1.9 M cycles (0.23 s).

## Repository layout

```
src/        the player: lsp.s (include this), lsp_config.s, lsp_init.s, lsp_check.s, lsp_bank.s, lsp_rt.s,
            lsp_api.s, lsp_mix.s
tools/      converter, effects packer, reference mixer, demo generator, disk tools (Python 3, stdlib only)
tests/      unit tests, mutation check, size limits (no file over 200 lines, no function over 30)
example/    demo.s: a complete small program that uses the player
assets/     the demo's module and sound effects (made by tools/make_demo.py; original, free to use)
HOWTO.md    step-by-step integration into a game, module and effects preparation
build.sh    tests + data + assemble + disk image
```

## Build

Needs Python 3.10 or newer and [`rg-asm`](https://www.reservoir-gods.com/tools/rg-asm/readme.html) (the Reservoir Gods universal 680x0 assembler for the Atari, MIT or
Apache-2.0; tested with 0.9.29). Put it on `PATH` or set `RG_ASM=/path/to/rg-asm`.

```sh
./build.sh          # tests, demo data, assemble, build/lsplayer_demo.st
```

This runs the tests, converts `assets/demo.mod` to `build/LSPSTE.DAT`, packs the effects into `build/FX.DAT`,
assembles `example/demo.s` to `build/DEMO.PRG` (`rg-asm -m 68000 -q --no-opt-size -Werror`) and writes a 720 KB
disk with `AUTO/DEMO.PRG` and the two data files in its root. Boot it on an STE with 1 MB (Hatari:
`--machine ste --memsize 1 --tos <TOS 1.62> --disk-a build/lsplayer_demo.st`). The demo prints a
message if the machine is not an STE, loads for a couple of seconds, plays the song and shows the cost of the
mixer. Keys: `1` to `5` play the five effects (`6` to `9` do nothing), `Space` holds and releases the module,
`Esc` quits and restores the VBL vector, the timer, the DMA and the keyclick.

Tools (all `python3 -I tools/<name>.py`, usage in each file's docstring): `lsp_ste.py` (module to
`LSPSTE.DAT`), `fx_pack.py` (WAV files to `FX.DAT`), `lsp_ref.py` (reference mixer, renders a WAV),
`make_demo.py` (the demo's data), `st_blank.py` and `st_put.py` (disk images), `lsp_mod.py`, `lsp_pt.py`
(ProTracker's effects), `lsp_seq.py`, `lsp_voice.py` (where a note goes on after an effect), `lsp_bank.py`,
`lsp_dat.py` (the converter's parts). Your own song:

```sh
python3 -I tools/lsp_ste.py song.mod build/LSPSTE.DAT
python3 -I tools/fx_pack.py build/FX.DAT jump.wav hit.wav        # sample 0 = jump.wav, 1 = hit.wav, ...
```

## API

Full register, clobber and stack documentation is at the top of [`src/lsp.s`](src/lsp.s). Include that one file
(`include "lsp.s"`, assemble with `-I src`).

| Call | Mode | What it does |
|---|---|---|
| `lsp_probe` | supervisor | d0 = 0 on an STE with enough RAM, else 1 |
| `lsp_init` | supervisor | a0 = path of `LSPSTE.DAT`, a1 = path of `FX.DAT` or 0; loads, checks, builds; d0 = error code |
| `lsp_setup` | supervisor | the same for files your own loader put at `LSP_DAT` and `LSP_FX` (d0, d1 = sizes) |
| `lsp_vbl` | supervisor | call once per VBL; does nothing before a good init and after `lsp_stop` |
| `lsp_start` / `lsp_halt` | any | start the module from its beginning / stop it, effects go on |
| `lsp_fx` | any | d0.w = effect index; ignored if out of range |
| `lsp_hold` / `lsp_resume` | any | mute and freeze the module / release it |
| `lsp_stop` | supervisor | everything off, DMA off, ring cleared; `lsp_start` re-arms |

`lsp_init` errors: 1 not an STE (nothing touched), 2 `LSPSTE.DAT` missing or bad, 3 `FX.DAT` missing or bad
(the music works, `lsp_fx` does nothing), 4 the song does not fit the memory of `src/lsp_config.s`.
`example/demo.s` is a complete small caller.

## Using it in a game

[HOWTO.md](HOWTO.md) is the step-by-step guide: reserving memory, init at start-up, calling `lsp_vbl` from the
game's VBL without disturbing rasters, mapping sound-effect triggers to `lsp_fx`, starting and stopping the music,
pause, the fallback on other machines, and how to convert a module and pack effects.

## Verification

The converter and the tools have unit tests; the 68000 code is checked against the reference in an emulator.
Details, the list of mutants and the run numbers are in [TESTING.md](TESTING.md).

## Credits and licence

- The idea of playing the module off line and following a per-tick stream is Leonard's, from LSP (Light Speed
  Player) on the Amiga. No code or file format from LSP is used.
- Assembled with rg-asm by Reservoir Gods. Emulator runs used Hatari.
- Licence: MIT, see [LICENSE](LICENSE). Copyright (c) 2026 shazz.
