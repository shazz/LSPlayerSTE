# Testing

What is checked, how, and what is not.

## 1. Python tools: unit tests, mutants, limits, lint

```sh
for t in tests/test_*.py; do python3 -I "$t"; done      # 76 checks: song 33, data 26, tools 17
python3 -I tests/mutants.py                              # 24 mutants
python3 -I tests/check_limits.py                         # no file over 200 lines, no function over 30
ruff check . && mypy --strict tools tests
```

Every expected value in the tests comes from a specification, not from running the code: the ProTracker
rules (a 300-byte one-shot at period 428 plays 453.1 output samples, so 2 ticks), the formats written in the
tool docstrings (header offsets, stream words, FAT12 layout read back by an independent reader in the test), or
the design of the demo song written in `tools/make_demo.py` (intro 160 ticks, loop 568, 728 ticks, 16 variants,
a 56,448-byte bank = 224 ticks x 252, every hold time worked out by hand: kick 9, hat 3, bass 10 or 12, lead 20
or 24). Each test prints its claim; run one to read them all.

| File | Covers |
|---|---|
| `tests/test_song.py` | what the converter accepts and refuses (with the place and the list of supported effects), tempo and break timing, loops, cuts, hold times, the stream encoding, the demo song's design |
| `tests/test_data.py` | step and resampling maths, loop unrolling, volume tables, file layout, checksum and size checks, limits, the mixer's long adds and overflow refusal, hold, effect playback, gain and headroom, the demo's bank |
| `tests/test_tools.py` | `fx_pack` (layout, normalisation, resampling, stereo, refusals), the disk tools (round trip, replacement frees clusters, folder/disk/directory full), `make_demo` determinism, the converter and renderer command lines |

### Mutants

`tests/mutants.py` breaks one thing at a time in a temporary copy and requires the tests to fail. Result:
**24 of 24 killed.** Three survived on the first run and got tests: the rounding of the effects table (a
sample of +-2), a one-shot ending exactly at a tick boundary (effect channel not freed), and the file-size check
(a file with zeros appended has the same checksum).

| Mutant | Breaks |
|---|---|
| NTSC clock instead of PAL | every pitch |
| tick of 256 bytes | tick length |
| interpolation fraction not halved | resampling |
| volume table / effects table not rounded | scaling |
| one-shot length rounded down | note end |
| stop event one tick late | note end |
| `B` jumps one position too far | song flow |
| hold time = shortest, not longest | bank size |
| event count in the wrong bits | stream |
| `C00` does not cut | effects |
| any period accepted / BPM tempo accepted | refusals |
| wrong carry constant in the reference mix | mixer |
| hold does not freeze the song | hold |
| effect plays a tick too long | effect end |
| wrong checksum / file size not checked | file checks |
| music may pass its headroom | gain |
| effects at full scale / padding shorter than a tick | `fx_pack` |
| replaced file keeps its clusters | disk tool |
| wrong media byte | disk tool |
| last bar of the demo does not end in silence | demo design |

`ruff check` and `mypy --strict` pass on 18 files. The tests were run with Python 3.11, 3.12 and 3.14 (3.10 is
what `.github/workflows/test.yml` adds; that workflow has not run yet).

## 2. The 68000 code: compared with the reference in an emulator

The assembly is not unit-testable on a host, so it is run in Hatari 2.6.1 (STE, TOS 1.62, 1 MB,
`--compatible on --cpu-exact on`) and its output is compared with `tools/lsp_ref.py`.

Method: the demo leaves the address of the player's variables in the long at `$80000`. A script drives Hatari
through a debugger/remote interface (ShirazMCP, not part of this repository), steps 7 VBLs at a time (the ring
holds 8 ticks, so none is missed), reads the variables, the 32-entry log (`lsp_log`: tick and code for start,
stop, hold, release and each effect start) and the ring at `$90000`, replays the log in the reference player and
compares every new 252-byte tick. The reference learns from the log only what it cannot know (when an effect
was started, when the module was held). Keys are sent through the debugger (`1`..`9`, `Space`).

| Run | Result |
|---|---|
| Music only, from a fresh boot | 424 ticks compared, 106,848 bytes identical, 0 different |
| Music with keys: effects 1..5 (and 6..9, ignored), hold and release | 1,398 ticks, 352,296 bytes identical, 0 different, 25 logged events replayed, the lead never below 128 bytes, ring never lost |
| Final build, made by `./build.sh` in a fresh `git clone`, music with keys | 1,397 ticks, 352,044 bytes identical, 0 different, 48 events replayed. (A first attempt showed 1,983 different bytes in its first step: the emulator had been left running, so the variables and the ring were read at different moments. Paused, 0.) |
| Bank built by `lsp_bank` | all 56,448 bytes equal `lsp_dat.expand()` (checked on the first build and again on the final one) |

Because the reference replays the player's own log, a bug that stops an event from being logged is invisible
to this comparison; the run also checks the number of events against the keys sent (12 expected in 75 steps).

Audio: a 6 s recording (`SDL_AUDIODRIVER=dummy`, debugger `setopt --sound 50066`) against the reference, in 0.5 s
windows, normalised: median correlation -0.981, worst window -0.902 on the first build, -0.979 and -0.905 on the
final one (the sign is Hatari's output, as seen on every recording made with it).

Quit path (the demo's `Esc`, run on the final build): VBL vector back to `$E00802`, `$FF8901` = 0, conterm
(`$484`) back to `$07` (it was `$06` while running).
ShirazMCP sends the `Esc` key as the character `1`, so this run retargeted the demo's key in RAM (`cmpi.b #27`
patched to `'1'`): that `Esc` gives ASCII 27 is TOS behaviour, not measured here.

Probe: the minimum TOS is the equate `LSP_MINTOS` (`$0106`, the first STE TOS); the demo boots and passes it on TOS 1.62. TOS 1.06 itself and a refusing TOS were not run.

CPU (the README's Benchmarks table is from the same method, `profile_raw` one frame per call): Hatari's profiler over `lsp_vbl` to the end of `lsp_mix`, 100 frames: 692,276 cycles in 100 calls (6,923 per
call, 4.32 % of 160,256) in one run and 699,796 (6,998, 4.37 %) in another run of the same code.

### Failure modes (demo disk variants, one boot each)

| Variant | Outcome |
|---|---|
| no `FX.DAT`; `FX.DAT` with a wrong magic | message "no effects", music plays, keys ignored (error 3) |
| no `LSPSTE.DAT`; one byte of `LSPSTE.DAT` changed (checksum) | "missing or bad", nothing touched (error 2) |
| a song whose bank is about 390 KB with a 27 KB file | "does not fit the memory" (error 4) |
| `--machine st` | not testable: Hatari switches to STE because TOS 1.62 is STE-only |

### Assembly mutants

Eight edits to `src/`, each assembled into a disk, booted and compared as above with 75 steps and keys. A mutant
is killed if any byte differs, if fewer than 50 ticks could be compared, if the logged-event count is not the
expected 12, or if the lead drops below 120 bytes or the ring is lost. **7 of 8 killed**, the survivor is an
equivalent mutant (below).

| Mutant (file) | Result |
|---|---|
| carry constant `$02020200` -> `$02020202` (`lsp_mix.s`) | killed: 33,327 bytes differ |
| hold ignored, `lsp_hreq` never read (`lsp_mix.s`) | killed by the event count only: ring identical, 10 events logged instead of 12 |
| effect table stride 4 instead of 8 (`lsp_mix.s`) | killed: 24,086 bytes differ |
| stream wait counts down by 2 (`lsp_mix.s`) | killed: 102,826 bytes differ |
| effect end test inverted (`lsp_mix.s`) | killed |
| interpolation fraction quartered (`lsp_bank.s`) | killed: 52,767 bytes differ |
| effects scaled with a music volume table (`lsp_bank.s`) | killed |
| first tick written one tick ahead instead of two (`lsp_rt.s`) | **survived**: the output is the same; the lead settles at 128..378 bytes as before, only its first-VBL peak drops from 504 to 378. An equivalent mutant for the output, not a correctness test of that constant |

### Position independence

`lsp_v` to the end of `lsp_mix.s` (2,332 bytes) assembled raw at `$10000` and at `$50000` gives identical
files, so the run-time code has no absolute reference to its own labels.

## 3. Not tested

- A plain ST, TOS 1.00 to 1.04 (the stale cookie-jar pointer case the probe guards against), a 512 KB machine,
  a TT or a Falcon, and real hardware (including the Microwire/LMC1992 defaults).
- A crafted `LSPSTE.DAT` (see README, Limits).
- `LSP_RINGTK` other than 8 and layouts other than the defaults in `src/lsp_config.s` (the assembly-time checks
  were exercised with four deliberately wrong configurations; no other layout was run).
- A VBL late enough to need two ticks, and the lost-lead resync, were not forced in this repository. They were
  forced once in the game build this player comes from and recovered there; the VBL routine's logic is the
  same here, with one added test (player on).
- The Python tools on Windows, and on Python 3.10 (CI only).
