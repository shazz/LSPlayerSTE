# HOWTO: put the player into an existing STE game

Two jobs: (A) convert your module and sound effects, (B) wire the player into the game. The API reference
(registers, clobbers, stack) is at the top of [`src/lsp.s`](src/lsp.s); numbers are in the README's
[Benchmarks](README.md#benchmarks). Snippets are 68000 in rg-asm/Devpac syntax.

## A. Prepare the data

### A1. The module

Convert with `python3 -I tools/lsp_ste.py song.mod build/LSPSTE.DAT`. It prints the size of the file, the bank the
loader will build, the variant and tick counts, the loop point and the music level, for example
`4316 B + 56448 B bank built at start, 16 variants, 728 ticks (loop to 160), gain 0.3255, music -76..79`.

**What the player accepts.** A 4-channel `M.K.` module, finetune 0 on every sample used, notes only on the
ProTracker period table, and these effects, played as the ProTracker 2.3 replay routine plays them:

| Effect | Meaning here |
|---|---|
| `0xy` | arpeggio: the note, x and y semitones above it, one per tick |
| `1xx` `2xx` | portamento up (stops at B-3, period 113) and down (stops at C-1, 856), xx per tick after the first |
| `3xx` | tone portamento to the note on its row (that note does not restart); `300` goes on with the last speed |
| `4xy` | vibrato, speed x, depth y; a `0` digit keeps the last value |
| `5xy` `6xy` | go on with the last `3xx` / `4xy`, and slide the volume as `Axy` |
| `9xx` | start the sample xx * 256 bytes in; `900` uses the last offset |
| `Axy` | volume slide: up by x or down by y per tick after the first |
| `Bxx` | position jump (this is how a song loops) |
| `Cxx` | volume, on a note's row or inside a note; `C00` silences the channel (the note runs on unheard) |
| `Dxx` | pattern break (the row is decimal, as in ProTracker) |
| `E1x` `E2x` | fine portamento up / down, once on the row's first tick |
| `E9x` | restart the sample every x ticks |
| `EAx` `EBx` | fine volume up / down, once |
| `ECx` | volume 0 on tick x |
| `EDx` | start the note on tick x |
| `E0x` | the Amiga's filter: accepted, does nothing |
| `Fxx` with `01`..`1F` | speed in ticks per row |

A note without a sample number restarts the channel's last sample at its current volume; a sample number
without a note puts the volume back to the sample's own. Only the rows the song really plays are checked;
rows after a `Dxx` or `Bxx` may hold anything.

**ProTracker's quirks are kept**, because modules are written against them: slides and vibrato do nothing on
a row's first tick; after an arpeggio or a vibrato the note is back on its own period at the next row, except
that a row with only `9xx`, `Bxx`, `Cxx`, `Dxx` or `Fxx` keeps the bent period for its first tick (a row with
only `Exx` for all its ticks);
a `1xx` step larger than the period itself wraps to a very low note instead of stopping at 113 (and is refused
if that note is left sounding into the next row: its period is then outside 57..4095); `9xx` on a row with a note moves
the start twice for the notes that follow without a sample number; the memory of `3xx`, `4xy` and `9xx`
is empty the first time the song is played and not when it loops, so a `400` before the first `4xy` only
sounds from the second pass (the converter then keeps both versions of that part: the stream gets longer).

**Refusals, and what to do in the tracker.** The converter stops at the first problem and says where
(`pattern`, `row`, `channel` are as the tracker numbers them, channel 1 to 4):

| Message (shortened) | Cause | Fix |
|---|---|---|
| `effect 705 is not supported; the player has 0xy arpeggio, ...` | an effect not in the table: `7xy` tremolo, `8xx`, `E3x`..`E8x`, `EEx`, `EFx`, `F00` | remove it; replace a tremolo by `Cxx` on the rows, `E6x` loops by copied rows or a `Bxx`, `EEx` by empty rows |
| `effect F7D is not supported ...` | `F20` and above is a BPM tempo | use speed values 1..31 (default speed 6; rows are 16th notes, so change the speed or edit the pattern length to change feel) |
| `arpeggio 047 goes above B-3` | the arpeggio's top note is outside ProTracker's table (the Amiga plays garbage there) | lower the note or the arpeggio |
| `period 430 is not in the ProTracker table` | a note off the table (some trackers allow finer pitches) | snap it to a table note |
| `period 40 is outside 57..4095` | a vibrato or a wrapped slide left the range the player resamples | reduce it |
| `a note without a sample (no sample number on this channel yet, or 9xx ran past its end)` | the first note of a channel has no sample number, or `9xx` points past the sample | give the note its sample number; lower the offset |
| `sample number 3 without a note while sample 2 plays` | ProTracker would swap the samples at the end of the loop | put the note with it, or cut the channel first |
| `sample N has finetune F (only 0)` | finetune set | set it to 0 and re-pitch the note |
| `sample N is empty` | note uses an empty slot | fill or remove |
| `looped sample S is never replaced or cut (it would play for ever)` | a looped sample is still sounding when the song loops, with nothing after it | add a `C00` or another note on that channel inside the loop |
| `not a 4-channel ProTracker module (tag ..., want b'M.K.')` | 6/8 channels, `FLT4`, other formats | save as 4-channel ProTracker `.mod` |
| `the song does not loop within 65536 rows` | no `Bxx` to a repeated position and no wrap | add the jump back to the loop start |
| `LSPSTE.DAT would be N B: more than ...` / `the bank would be N B ...` | too big for the areas in `lsp_config.s` | see below |

**Size.** Each distinct (sample, period, volume) is a variant; its bank space is what the song reads of it.
For a plain note that is the longest time it sounds before being replaced or cut: a note held for 8 rows at
speed 6 costs 48 x 252 = 12 KB. A note bent by effects is cheaper per variant but has more of them: every
period and volume it passes through holds one turn of the sample's loop (or, for a one-shot, the pieces that
are played), one tick, and the longest time the note then stays unchanged. So a vibrato on a 16-byte chip
loop costs 0.5 to 0.8 KB per period it touches, on a 4 KB loop that loop's length at each pitch on top: keep
deep vibratos and long volume slides for short loops. To shrink the bank: cut notes early with `C00`, use fewer pitches of a looped
sample, shorten held notes. The file itself (64 KB at most with the default memory map) holds every sample
once, a second time at half rate if it is played above 17.7 kHz, 256 B per distinct volume, and the stream:
2 B per event.

**Speed and tempo.** A tick is 252 bytes at 12,517 Hz, so 49.67 ticks per second: ProTracker speed 6 at 125 BPM
(50 ticks/s) plays 0.66 % slow. The tempo cannot change except through `Fxx` speed.

**Level.** The converter scales the music so the loudest moment of the whole song peaks at 80 of 127, and
reserves the rest for the effect channel (`--music-peak`, `--fx-peak`; they must add up to 127 or less).

**Check the result.** Render the converted data with the Python reference mixer and listen:

```sh
python3 -I tools/lsp_ref.py build/LSPSTE.DAT /tmp/song.wav --ticks 3000
python3 -I tools/lsp_ref.py build/LSPSTE.DAT /tmp/song.wav --ticks 3000 --fx build/FX.DAT 100:0 400:2
```

`--ticks` is how many ticks to render (3000 is 60 s; the song loops); `--fx FILE TICK:INDEX ...` fires effects at
those ticks. The output is 8-bit mono 12,517 Hz, exactly the bytes the 68000 code writes to the ring. Compare it
with your tracker's own render for pitch, balance and tempo (about 0.66 % slow, and the bass/lead levels follow
the volume tables). The 68000 mixer matched this render byte for byte in the emulator (see TESTING.md).

### A2. The effects

```sh
python3 -I tools/fx_pack.py build/FX.DAT jump.wav hit.wav coin.wav     # index 0 = jump, 1 = hit, 2 = coin
```

Any PCM WAV, 8 or 16 bit, mono or stereo, any rate; each is mixed to mono, low-passed, resampled to 12,517 Hz
and normalised to 90 % of full scale (the player then scales it to its share of the headroom). At most 16 samples
(`LSP_FXN`) and 60 KB in all (`LSP_FXMAX`); a message names the limit if you pass it. A 0.3 s effect at
12,517 Hz is about 3.8 KB. Only one effect plays at a time.

## B. Put the player into the game

### B1. Add the source and reserve memory

Copy `src/` next to your sources and `include "lsp.s"` once (assemble with `-I` pointing at that folder). It
brings code and variables (about 3.5 KB with the start-up code), and the equates of `lsp_config.s`.

The player needs these blocks of RAM that nothing else may touch while it runs (defaults on a 1 MB STE):

| Block | Default | Size |
|---|---|---|
| effects image | `LSP_FX` `$81000` | `FX.DAT` size, at most 60 KB |
| DMA ring + silent tick | `LSP_RING` `$90000` | 2,268 B (must not cross a 64 KB boundary) |
| file image | `LSP_DAT` `$91000` | `LSPSTE.DAT` size, at most 64 KB |
| bank | `LSP_BANK` `$A1000` | the converter prints it; the end must be below `LSP_LIMIT` `$F4000` |

If the game only uses the first 512 KB of a 1 MB machine, the defaults are free: use them. If the game takes
the whole of the RAM it finds, reserve the block before the game claims memory (a small loader that lowers the
memory top it hands over, or an early `Malloc`/`Mxalloc` of one contiguous block), then edit the equates in
`lsp_config.s` to that block: all addresses even, areas not overlapping (the file checks this at assembly), and
`LSP_LIMIT` = the end of your block, because `lsp_probe` demands that much RAM. Tell the converter if you shrink
the areas: `--max-file` = `LSP_DATMAX`, `--max-bank` = `LSP_LIMIT - LSP_BANK`. The addresses are assembly-time
constants, so the block must sit at a fixed address. A 512 KB machine cannot run the default layout and is
treated as "not an STE" by the probe.

**A song too big for 1 MB (the 4 MB layout).** The converter refuses a song that does not fit and prints the
sizes it needs ("LSPSTE.DAT would be 160240 B: more than the 65536 B the player's file area holds", or the
bank). A song with many long samples played at many pitches (lots of notes, vibrato, slides) is the usual
cause. On a machine with more RAM, move the file and bank areas above 1 MB; the effects area and the ring
can stay where they are. Three lines of `lsp_config.s`:

```
LSP_DAT     equ     $100000                 ; file area at 1 MB
LSP_DATMAX  equ     $40000                  ; 256 KB of file
LSP_LIMIT   equ     $3C0000                 ; bank from $140000 up to here: 2.5 MB
```

and the matching converter call (`--max-file` = `LSP_DATMAX`, `--max-bank` = `LSP_LIMIT - LSP_BANK`):

```sh
python3 -I tools/lsp_ste.py --max-file 262144 --max-bank 2621440 song.mod LSPSTE.DAT
```

Measured: `ILLUSION.MOD` (from Uko's STE_FullScreen_MOD_Play) needs a 160 KB file and a 1.48 MB bank. With
this layout on a 4 MB STE in Hatari it played at 7,726 cycles a VBL on average, 8,200 at worst (the same cost as
a small song: the mix does not depend on the bank size), after a bank build of about 34 s at 8 MHz (186 cycles
a byte, computed). Two things to know: `lsp_probe` demands RAM up to `LSP_LIMIT`, so this build refuses 1 MB
and 2 MB machines (it says "not an STE": keep the default layout for songs that fit it); and the bank build
time grows with the bank, so show something on screen while `lsp_init` runs.

### B2. Initialise at start-up (supervisor mode)

`lsp_probe` and `lsp_init` read TOS variables in low memory, so call them in supervisor mode.

```
        lea     lsp_name(pc),a0         ; "LSPSTE.DAT",0  (a GEMDOS path)
        lea     fx_name(pc),a1          ; "FX.DAT",0      (or suba.l a1,a1: no effects)
        bsr     lsp_init
        tst.l   d0
        beq.s   .ready                  ; 0: all loaded
        cmpi.l  #3,d0
        beq.s   .ready                  ; 3: music works, FX.DAT bad: lsp_fx will do nothing
        clr.w   use_lsp                 ; 1: not an STE (or TOS older than 1.06), 2: bad file, 4: too big
        bra.s   .done                   ;    -> keep the game's YM sound
.ready: move.w  #1,use_lsp
.done:
```

`lsp_init` loads both files, checks them, builds the bank (1.3 s for a 56 KB bank, 5.7 s for 244 KB at 8 MHz)
and clears the ring. If the game loads files its own way, put them at `LSP_DAT` and `LSP_FX` and call
`lsp_setup` with the sizes in d0 and d1 instead. Neither is to be called twice on the same images.

### B3. Call `lsp_vbl` once per VBL

In the game's VBL handler, after the time-critical work:

```
game_vbl:
        ...                             ; raster set-up etc.
        tst.w   use_lsp
        beq.s   .noplayer
        bsr     lsp_vbl                 ; keeps all registers, ~7.5k cycles, 74 bytes of stack
.noplayer:
        ...
```

`lsp_vbl` saves and restores every register, uses at most 74 bytes of stack (80 if an interrupt enters it
directly), and never changes the status register, so it runs at the interrupt level of its caller.
From the VBL (level 4), MFP interrupts (level 6, so Timer B rasters) still preempt it; the HBL (level 2) is held
off for the 7k to 8k cycles (about 15 scanlines) a tick takes. So: if the game uses the HBL for rasters, call
it after the last raster line, or from a Timer B/C/D interrupt at a quiet scanline (lower the mask yourself if
it should be interruptible, and call from one place only: it is not re-entrant). A level-6 interrupt can be
delayed by up to about 140 cycles (the 15-register `movem`, or the `divu` of the rare resync path); that figure is
computed from 68000 timings, not measured. The first call starts the DMA (frame registers, mode `$81`, loop on
the ring); it does not touch the Microwire/LMC1992 volume. It tolerates a late VBL up to about 7 ms; later than
that it resynchronises (one glitch).

The game must not use the sound DMA for anything else while the player runs.

### B4. Map the sound-effect triggers to `lsp_fx`

Wherever the game starts a sound effect, load the sample index (its position on the `fx_pack.py` line) and call:

```
        moveq   #1,d0                   ; index 1 = hit.wav
        bsr     lsp_fx                  ; any mode, any context; out of range or no FX.DAT: ignored
```

or, if the game's trigger is "play sound n" with its own table, keep a byte table `snd_to_fx` (255 = leave it to the
YM) and call `lsp_fx` only for mapped ones. `lsp_fx` only writes a word that the next tick takes, so it is safe
from the main loop, from the VBL and from other interrupts. One effect plays at a time: a second call in
the same tick replaces the first, and a new effect replaces one still playing. An effect starts 10 to 30 ms
after the call.

### B5. Start and stop the music from the game's music calls

```
play_song:                              ; the game's own "start song d0"
        cmpi.w  #SONG_MAIN,d0
        bne.s   .other
        tst.w   use_lsp
        beq.s   .ym                     ; no player: the game's YM player as before
        bsr     lsp_start               ; any mode; from the first tick
        rts
.other: bsr     lsp_halt                ; other tune: the module stops, effects go on
.ym:    ...                             ; the game's YM code
stop_music:
        bsr     lsp_halt                ; any mode (harmless without a good init)
        ...
```

The player never touches the YM chip: silence or stop the game's own YM music yourself when the module takes over
(the two sound together on the STE otherwise). For a loading screen or a mode that needs the DMA, call `lsp_stop`
(supervisor; DMA off, ring cleared, interrupts masked for about 2 ms); `lsp_vbl` then does nothing until the next
`lsp_start`. `lsp_start`, `lsp_halt`, `lsp_hold`, `lsp_resume` and `lsp_fx` do nothing before a good init.

### B6. Pause

```
        bsr     lsp_hold                ; module muted, position frozen; effects still play (menu sounds)
        ...
        bsr     lsp_resume              ; continues where it stopped
```

### B7. Not an STE, or TOS older than 1.06

`lsp_probe` (called by `lsp_init`) returns 1 and touches nothing unless: RAM reaches `LSP_LIMIT`; `_sysbase` is
even and its OS header says TOS 1.06 or newer (`LSP_MINTOS` in `lsp_config.s`); the cookie-jar pointer is even and
inside RAM (the jar is read for at most 64 cookies); and `_SND` has bit 1 (8-bit DMA sound). Keep the
game's YM sound path whenever `use_lsp` is zero, as in the snippets above. Calling `lsp_vbl`, `lsp_fx` and the
others without a good init is harmless, but silent. The threshold is 1.06, the first STE TOS
(the first with a cookie jar); the emulator runs used TOS 1.62, so 1.06 and 1.60 machines are accepted but untested.
Raise `LSP_MINTOS` to `$0162` to admit only what was tested. Plain STs, TT and Falcon were not tested either.

### B8. Quick checklist

1. Converter run clean; render a WAV and listen.
2. `lsp_config.s` matches the memory you reserved; the build passes its assembly-time checks.
3. `lsp_init` in supervisor mode before the first `lsp_vbl`; `use_lsp` flag set from its result.
4. One `lsp_vbl` per frame, not from two places.
5. Every effect trigger and music call mapped; YM music silenced when the module plays.
6. Test on an STE (or Hatari STE) with TOS 1.62 and 1 MB, with and without `FX.DAT`, and on a machine that fails the probe.

`example/demo.s` is a complete small program doing B2, B3, B4, B5 (start), B6 and shutdown.
