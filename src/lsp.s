; src/lsp.s: the LSPSTE player, one file to include:    include "lsp.s"      (assemble with -I <this folder>)
; LSPSTE: a light module player for the Atari STE, after the idea of Leonard's LSP (Light Speed Player, Amiga):
; the module is played off line into a per-tick event stream (tools/lsp_ste.py), the run-time only mixes. NOT
; compatible with LSP's files and not affiliated with it. It plays four module channels and one effects channel
; through the STE's 8-bit DMA, mono, 12,517 Hz (DMA mode $81): once per VBL it mixes one 252-byte tick.
;
; API. Supervisor mode unless it says "any mode". "Stack" is the most bytes pushed, return address included
; (counted from the code, 68000). Registers are kept unless a routine lists them as clobbered; the condition
; codes are never kept.
;
;   lsp_probe   Out: d0.l = 0 and Z set on an STE with the RAM of lsp_config.s, else 1. Clobbers d0, d1, a0. Stack 4.
;               Reads TOS variables: _sysbase ($4F2), phystop ($42E), cookie jar ($5A0), and trusts the jar only
;               if the OS header says TOS >= LSP_MINTOS (1.06) and the pointer is even and in RAM; _SND bit 1 is required.
;   lsp_init    In: a0 -> path of LSPSTE.DAT, a1 -> path of FX.DAT (0 = no effects), both 0-terminated, GEMDOS
;               paths. Out: d0.l = 0 ready; 1 not an STE (nothing touched); 2 LSPSTE.DAT missing or bad;
;               3 FX.DAT missing or bad (music works, lsp_fx does nothing); 4 song too big for lsp_config.s.
;               Loads both files, builds the bank (5 s for a 233 KB one at 8 MHz), clears the ring, enables
;               lsp_vbl. Clobbers d0. Stack 146 + GEMDOS. Call before the first lsp_vbl.
;   lsp_setup   As lsp_init, for a game that loads the files itself: LSPSTE.DAT at LSP_DAT and FX.DAT at LSP_FX,
;               In: d0.l = bytes of LSPSTE.DAT, d1.l = bytes of FX.DAT (0 = none). Out: d0.l as lsp_init (no 1).
;               Needs fresh images (it converts FX.DAT in place). Clobbers d0. Stack 86.
;   lsp_vbl     Once per VBL: keeps the ring about 1.5 ticks ahead of the DMA (one tick = 7.7k cycles). Does
;               nothing before a good lsp_init, and after lsp_stop. The first call starts the DMA. Stack 74
;               (+6 if an interrupt enters it).
;   lsp_start   Any mode. Start the module from its first tick, at the next tick mix.        Stack 8.
;   lsp_halt    Any mode. Stop the module; effects go on playing.                            Stack 8.
;   lsp_fx      Any mode. In: d0.w = effect sample index (0 = first WAV given to fx_pack.py); out of range or
;               no FX.DAT: ignored. Starts it at the next tick mix on the fifth channel; a second call
;               in the same tick replaces the first.                                         Stack 8.
;   lsp_hold    Any mode. Mute the module and freeze its position; effects go on. lsp_resume releases it.
;   lsp_resume  Any mode.                                                                    Stack 8.
;   lsp_stop    Module off, effects off, DMA off ($FF8901 = 0), ring cleared. lsp_vbl then does nothing until
;               lsp_start. Briefly raises the interrupt mask to 7. Stack 26.
; Variables: lsp_v and what follows it (lsp_rt.s). lsp_ticks (long) counts the ticks mixed.
        include "lsp_config.s"
        include "lsp_init.s"
        include "lsp_bank.s"
        include "lsp_rt.s"
        include "lsp_api.s"
        include "lsp_mix.s"
