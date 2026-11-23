# Testing

What is checked, how, and what is not.

## 1. Python tools: unit tests, mutants, limits, lint

```sh
for t in tests/test_*.py; do python3 -I "$t"; done      # 140 checks: song 31, effects 37, voice 26, data 29, tools 17
python3 -I tests/mutants.py                              # 72 mutants (tests/mutant_list.py)
python3 -I tests/check_limits.py                         # no file over 200 lines, no function over 30
ruff check . && mypy --strict tools tests
```

Every expected value in the tests comes from a specification, not from running the code: the ProTracker
rules (a 300-byte one-shot at period 428 plays 453.1 output samples, so 2 ticks), the formats written in the
tool docstrings (header offsets, stream words, FAT12 layout read back by an independent reader in the test), or
the design of the demo song written in `tools/make_demo.py` (intro 160 ticks, loop 568, 728 ticks, 16 variants,
a 56,448-byte bank = 224 ticks x 252, every hold time worked out by hand: kick 9, hat 3, bass 10 or 12, lead 20
or 24). For the effects it is the ProTracker 2.3 replay routine: its period table, its vibrato table and the
tick each effect acts on give the period, the volume and the restarts of every tick, written out by hand in
each claim (`047` on C-2 is 428, 339, 285; `482` is +0 +2 +3 +2 0 -2 -3 -2). For the middle of a note it is the
rates: a variant at period p holds 3,546,895 / (p x 12,517) sample positions per byte, so a note that has
played 504 bytes at 428 goes on at byte 252 an octave up; the tests work these out with exact fractions, not
with the converter's fixed point. Each test prints its claim; run one to read them all.

| File | Covers |
|---|---|
| `tests/test_song.py` | what the converter accepts and refuses (with the place and the list of supported effects), tempo and break timing, loops, cuts, hold times, the stream encoding, the demo song's design |
| `tests/test_fx.py` | every effect on ProTracker's registers, tick by tick: `0xy 1xx 2xx 3xx 4xy 5xy 6xy 9xx Axy Cxx E0x E1x E2x E9x EAx EBx ECx EDx`, their memories and limits, notes without a sample number, the quirks kept (period after a vibrato row, `9xx` applied twice, the `1xx` wrap), and each refusal |
| `tests/test_voice.py` | where a note goes on after an effect (same byte for a volume, the matching byte for a pitch, the half sample of halved renditions, loops entered at their first turns), the events and the bytes read of each variant, variants that start inside a note, the loader's loop handling, a looped song with effects giving the same bytes every pass |
| `tests/test_data.py` | step and resampling maths, loop unrolling, volume tables, file layout (variants, renditions, targets), checksum, size and target checks, limits, the mixer's long adds and overflow refusal, hold, effect playback, gain and headroom, the demo's bank |
| `tests/test_tools.py` | `fx_pack` (layout, normalisation, resampling, stereo, refusals), the disk tools (round trip, replacement frees clusters, folder/disk/directory full), `make_demo` determinism, the converter and renderer command lines |

### Mutants

`tests/mutants.py` breaks one thing at a time in a temporary copy and requires the tests to fail. Result:
**72 of 72 killed** (`tests/mutant_list.py`). On the first run of the effects' mutants one survived and got a
test: a `9xx` note placed at the start of its variant (the registers were tested, the event was not). In
format version 1, three had survived and got tests: the rounding of the effects table (a sample of +-2), a
one-shot ending exactly at a tick boundary (effect channel not freed), and the file-size check (a file with
zeros appended has the same checksum).

| Mutants | Break |
|---|---|
| NTSC clock, tick of 256 bytes, interpolation fraction not halved, tables not rounded | pitch, tick, resampling, scaling |
| one-shot length rounded down, stop event one tick late, a loop that ends at the sample's end | note and loop ends |
| all runs of a variant in one piece, size not rounded to long words, only the first tick of a run kept, a target that forgets where its variant starts, a target past the bank accepted | bank and targets |
| `B` jumps one position too far, event count or target in the wrong bits, loop not moved back, loop moved back into the intro | song flow, stream |
| any period, BPM tempo, tremolo, `E6x`, a sample swap, a note without a sample accepted; `E0x` refused | refusals |
| `0xy` notes swapped; `1xx`/`2xx` swapped, other limits; `E1x` on every tick; `3xx` past its target, wrong way, speed forgotten; a note with `5xy` restarts | pitch effects |
| `4xy` twice as deep, never negative, half speed, memory lost, not restarted by a note; `6xy` without its vibrato; a row always back on the note's period | vibrato |
| `Axy` digits' priority, below 0; `5xy`/`6xy` without the slide; `Cxx` above 64; `EAx`/`EBx` swapped; `ECx` a tick late | volume effects |
| `EDx` does not wait, or the note also starts at once; `E9x` only once; `9xx` moved once, forgets, not reset by a sample number, or the note placed at byte 0 | restarts |
| the half sample of halved renditions forgotten (two places), entry rounded down, a loop always entered at its first turn, turns of the loop not taken off, a volume change not followed, volume 0 not silent | the middle of a note |
| wrong carry constant, hold does not freeze, effect a tick too long | reference mixer |
| wrong checksum, file size not checked, headroom passed, no limit on the gain | file, gain |
| effects at full scale, padding shorter than a tick, replaced file keeps its clusters, wrong media byte, the demo's last bar | other tools |

`ruff check` and `mypy --strict` pass on 23 files. The tests were run with Python 3.11, 3.12 and 3.14 (3.10 is
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

The first four rows are from format version 1 (before the module effects); the others from version 2, with
the demo and with a 25-position module that uses arpeggio, portamento, vibrato, volume slides and volumes
inside notes on short and long loops (not part of this repository; its stream is 6,720 ticks and loops to
tick 1,920; 168 variants, 603 targets, 6,182 events, four in a tick at most).

| Run | Result |
|---|---|
| Music only, from a fresh boot | 424 ticks compared, 106,848 bytes identical, 0 different |
| Music with keys: effects 1..5 (and 6..9, ignored), hold and release | 1,398 ticks, 352,296 bytes identical, 0 different, 25 logged events replayed, the lead never below 128 bytes, ring never lost |
| Final build, made by `./build.sh` in a fresh `git clone`, music with keys | 1,397 ticks, 352,044 bytes identical, 0 different, 48 events replayed. (A first attempt showed 1,983 different bytes in its first step: the emulator had been left running, so the variables and the ring were read at different moments. Paused, 0.) |
| Bank built by `lsp_bank` | all 56,448 bytes equal `lsp_dat.expand()` (checked on the first build and again on the final one) |
| Version 2, demo, music with keys (75 steps) | 529 ticks compared, 133,308 bytes identical, 0 different, 12 events replayed; bank: all 56,448 bytes equal |
| Version 2, the module with effects, music only, 1,050 steps from a fresh boot | 7,302 ticks compared: the whole stream and 621 ticks after its jump back to the loop; 1,840,104 bytes identical, 0 different, lead 126..504 bytes, ring never lost |
| Version 2, the module with effects, bank built by `lsp_bank` | all 244,280 bytes equal `lsp_dat.expand()` (variants that start inside a note, with a first fraction, and loops the loader goes back in) |

Version 2 against version 1: for the demo song the bank (56,448 bytes) and the reference render of the intro
and three passes of the loop (469,728 bytes) are byte for byte those of the version 1 tools (pinned from the
commit before, compared after); only the file changed (4,316 B instead of 19,646 B: loops are no longer
unrolled in it). The same for the song of the game the player was written for (12 positions, 41 variants,
effects `B C D F` only; not in this repository): its bank (233,352 bytes) is identical, and so are the 6,720
ticks of its render (intro and three passes); its stream is 15 ticks shorter, because the loop is now found
15 ticks earlier, and its file 37,512 B instead of 43,484.

Reads past a variant: the 68000 and the reference would agree on them (both would play the next bytes of the
bank), so the reference player was walked over the intro and three passes of the loop (21,120 ticks for the
module with effects; also the demo and the game's song), checking that every tick a channel reads lies inside
the variant its last event pointed into: none outside. `tests/test_voice.py` does the same on two small songs.

First pass: in that module 24 ticks of the first pass have other periods than the same ticks of the next
passes (a `401` whose vibrato speed comes from a `41F` further on: empty the first time, remembered the next);
that is why its stream holds the first ten positions twice. ProTracker's rule that a row starts on the note's
period only "if the row before was empty" was checked in the original 68000 routine (`TST.L` on the whole
stored cell, sample number included); the C port read first ignores the sample number there.

Because the reference replays the player's own log, a bug that stops an event from being logged is invisible
to this comparison; the run also checks the number of events against the keys sent (12 expected in 75 steps).

Audio: a 6 s recording (`SDL_AUDIODRIVER=dummy`, debugger `setopt --sound 50066`) against the reference, in 0.5 s
windows, normalised: median correlation -0.981, worst window -0.902 on the first build, -0.979 and -0.905 on the
final one (the sign is Hatari's output, as seen on every recording made with it).

Audio, version 2, the module with effects: two recordings one after the other, 30 s (ticks 228 to 1,720: the
arpeggios) and 25 s (ticks 1,725 to 2,970: the vibrato and the slides), same method: 59 windows with median
-0.980 and worst -0.908, and 49 windows with median -0.98 and worst -0.93; none under 0.9. (The song plays
each of its first patterns twice, so the search for the recording's place in the render must not be limited
to the first seconds: limited to them, it locked one pattern early and whole channels then looked missing.)
The spectrogram of the second recording shows the vibrato and the slide as continuous lines, with no broadband
line at the ticks where the pitch changes.

The effects themselves, version 2: an independent floating-point render (Paula's rule: each channel keeps its
place in the sample, the period sets the rate, linear interpolation), driven by the same per-tick registers,
against the converter's reference render of the whole 6,720-tick stream: correlation 0.992 (median of 0.5 s
windows 0.998, worst 0.90), residual 2.4 levels RMS for a signal of 19 (the same comparison on the demo, which
has no effects: 0.998, residual 1.6). Steps between consecutive bytes, reference minus float render: 1.78 RMS
at the 3,209 tick starts that carry events, 1.48 at the others, 1.57 inside ticks; largest 12.7 at an event,
15.5 inside a tick: the events add no click above the noise of the 8-bit mix. Where a note is entered
(distance from the exact place, in output bytes): 0.04 on average and 0.24 at most on the 16-byte chip loop,
0.08 and 0.34 on the 32-byte one, 0.09 and 0.51 on the 2 KB loop, exact on the one-shots but for two entries
(0.32). This checks the placing and the resampling, not the
ProTracker rules: both renders use `lsp_pt.py`.

Quit path (the demo's `Esc`, run on the final build): VBL vector back to `$E00802`, `$FF8901` = 0, conterm
(`$484`) back to `$07` (it was `$06` while running).
ShirazMCP sends the `Esc` key as the character `1`, so this run retargeted the demo's key in RAM (`cmpi.b #27`
patched to `'1'`): that `Esc` gives ASCII 27 is TOS behaviour, not measured here.

Probe: the minimum TOS is the equate `LSP_MINTOS` (`$0106`, the first STE TOS); the demo boots and passes it on TOS 1.62. TOS 1.06 itself and a refusing TOS were not run.

CPU (the README's Benchmarks table is from the same method, `profile_raw` one frame per call): Hatari's profiler over `lsp_vbl` to the end of `lsp_mix`, 100 frames: 692,276 cycles in 100 calls (6,923 per
call, 4.32 % of 160,256) in one run and 699,796 (6,998, 4.37 %) in another run of the same code.
Version 2, music only, two runs of 150 frames each: the demo 7,491 and 7,490 on average, worst 8,160 (the
version 1 code, re-measured the same day the same way: 7,491 and 7,502, worst 8,232); the module with effects,
two runs of 250 frames over its vibrato and slide pattern and the next: 7,840 and 7,832, worst 8,224 and 8,256.
Start-up: `lsp_bank` 10.51 M cycles for the demo's 56 KB and 45.67 M for 244 KB (186 cycles a byte; version 1:
172), `lsp_check` 0.16 M and 1.87 M.

### Failure modes (demo disk variants, one boot each)

| Variant | Outcome |
|---|---|
| no `FX.DAT`; `FX.DAT` with a wrong magic | message "no effects", music plays, keys ignored (error 3) |
| no `LSPSTE.DAT`; one byte of `LSPSTE.DAT` changed (checksum) | "missing or bad", nothing touched (error 2) |
| a song whose bank is about 390 KB with a 27 KB file | "does not fit the memory" (error 4) |
| `--machine st` | not testable: Hatari switches to STE because TOS 1.62 is STE-only |
| version 2, files changed by hand with the checksum put right: a target past the last whole tick of the bank; an odd target; a rendition with loop length 0 (the loader would never leave its loop); a variant naming rendition 99; version 1 in the header | each refused at start, the player never runs (the unchanged file runs); for the loop length 0 the screen was read: "LSPSTE.DAT is missing or bad" (error 2) |

### Assembly mutants

Fifteen edits to `src/` (version 2; the first eight are those of version 1, run again), each assembled into a
disk, booted and compared as above with 75 steps: the first eight on the demo with keys, the others on the
module with effects, where the bank the loader built is compared too. A mutant is killed if a byte of the bank
or of the ring differs, if fewer than 50 ticks could be compared, if the logged-event count is not the
expected one (12 with keys, 2 without), if the lead drops below 120 bytes or the ring is lost, or if the
program crashes. **14 of 15 killed**, the survivor is an equivalent mutant (below).

| Mutant (file) | Result |
|---|---|
| carry constant `$02020200` -> `$02020202` (`lsp_mix.s`) | killed: 33,327 bytes differ |
| hold ignored, `lsp_hreq` never read (`lsp_mix.s`) | killed by the event count only: ring identical, 10 events logged instead of 12 |
| effect table stride 4 instead of 8 (`lsp_mix.s`) | killed: 24,086 bytes differ |
| stream wait counts down by 2 (`lsp_mix.s`) | killed: 102,574 bytes differ |
| effect end test inverted (`lsp_mix.s`) | killed: 23,409 bytes differ |
| interpolation fraction quartered (`lsp_bank.s`) | killed: 21,260 bytes of the bank and 53,303 of the ring differ |
| effects scaled with a music volume table (`lsp_bank.s`) | killed: 24,184 bytes differ |
| first tick written one tick ahead instead of two (`lsp_rt.s`) | **survived**: the output is the same; the lead settles at 128..378 bytes as before, only its first-VBL peak drops from 504 to 378. An equivalent mutant for the output, not a correctness test of that constant |
| event: channel number times 2 instead of 4 (`lsp_mix.s`) | killed: address error at the first event (a pointer lands on an odd address) |
| event: every target taken from the next table entry (`lsp_mix.s`) | killed: the program crashes within the first steps |
| loader never goes back at the end of a loop (`lsp_bank.s`) | killed: 128,676 bytes of the bank and 8,174 of the ring differ |
| a variant's first fraction ignored (`lsp_bank.s`) | killed by the bank only: 9,670 bytes differ (in variants not played in the first 521 ticks) |
| a variant's first sample ignored (`lsp_bank.s`) | killed by the bank only: 28,693 bytes differ |
| targets two bytes late (`lsp_bank.s`) | killed: 103,880 bytes differ |
| three bytes made per long word (`lsp_bank.s`) | killed: 215,019 bytes of the bank and 124,070 of the ring differ |

`lsp_check.s` has no mutants of its own: its refusals are the failure-mode runs above.

### Position independence

`lsp_v` to the end of `lsp_mix.s` (2,322 bytes in version 2) assembled raw at `$10000` and at `$50000` gives
identical files, so the run-time code has no absolute reference to its own labels.

## 3. Not tested

- A plain ST, TOS 1.00 to 1.04 (the stale cookie-jar pointer case the probe guards against), a 512 KB machine,
  a TT or a Falcon, and real hardware (including the Microwire/LMC1992 defaults).
- A crafted `LSPSTE.DAT` beyond the five cases above (see README, Limits): the header's own offsets are trusted.
- The effects against a real ProTracker or Amiga recording. Their rules were taken from the ProTracker 2.3
  replay routine (read in its pt2-clone port and in the 68000 source of PT2.3F) and tested against hand-worked values; a misreading of
  that source would be in both. Sample finetune, `7xy`, `E3x`..`E8x`, `EEx`, `EFx` are refused, not played.
- Songs with effects other than the one module above in the emulator. Periods off the table (reached by slides
  or vibrato) were played only as far as that module and the unit tests go (a `1xx` wrap to 3,961, vibrato around
  the table's notes): the limits 57 and 4,095 themselves were not.
- `LSP_RINGTK` other than 8 and layouts other than the defaults in `src/lsp_config.s` (the assembly-time checks
  were exercised with four deliberately wrong configurations; no other layout was run).
- A VBL late enough to need two ticks, and the lost-lead resync, were not forced in this repository. They were
  forced once in the game build this player comes from and recovered there; the VBL routine's logic is the
  same here, with one added test (player on).
- The Python tools on Windows, and on Python 3.10 (CI only).
