; src/lsp_config.s: every address and size of the LSPSTE player that a port may need to move.
; The defaults suit an STE with 1 MB: everything sits above $80000, and nothing is touched from $F4000 up
; (the stack of a program started from TOS is under $F8000). Change a line here, the rest follows.
; The player's code and variables are not here: they are part of your program, wherever you assemble them.
; Memory map with these defaults:
;   $81000-$8FFFF  effects: FX.DAT, one image, converted in place        LSP_FX, LSP_FXMAX
;   $90000-$907DB  DMA ring: 8 ticks, looped by the sound DMA              LSP_RING
;   $907E0-$908DB  one tick of silence ($80 bytes)                         LSP_SIL (right after the ring)
;   $91000-$A0FFF  LSPSTE.DAT as loaded (at most 64 KB)                    LSP_DAT, LSP_DATMAX
;   $A1000-$F3FFF  the bank the loader builds from it (at most 332 KB)     LSP_BANK, LSP_LIMIT
; If you move the file or bank areas, give tools/lsp_ste.py the matching --max-file and --max-bank.

LSP_TICK    equ     252                     ; bytes mixed per tick: fixed, converter and mixer agree on it
LSP_RINGTK  equ     8                       ; ticks in the ring: 8 = 2,016 bytes, the lead is 126..378 bytes (only 8 tested)
LSP_RINGSZ  equ     LSP_RINGTK*LSP_TICK
LSP_VERSION equ     1                       ; LSPSTE.DAT format version the player reads
LSP_MINTOS  equ     $0106                   ; lowest TOS os_version lsp_probe accepts: 1.06, the first STE TOS (cookie jar)

LSP_RING    equ     $90000                  ; even; the ring must not cross a 64 KB boundary
LSP_SIL     equ     LSP_RING+LSP_RINGSZ     ; LSP_TICK bytes of $80, written by lsp_clear
LSP_DAT     equ     $91000                  ; even
LSP_DATMAX  equ     $10000
LSP_BANK    equ     LSP_DAT+LSP_DATMAX      ; even; the bank follows the file area
LSP_LIMIT   equ     $F4000                  ; the bank must end below this, and the machine must have this much RAM

LSP_FX      equ     $81000                  ; even
LSP_FXMAX   equ     $F000                   ; FX.DAT, all of it, must end below the ring: LSP_FX+LSP_FXMAX <= LSP_RING
LSP_FXN     equ     16                      ; most samples in FX.DAT

        if (LSP_RINGTK<8)+(LSP_RINGTK&(LSP_RINGTK-1))
        fail    "LSP_RINGTK must be a power of two, 8 or more"
        endc
        if LSP_RING&1
        fail    "LSP_RING must be even (DMA addresses are words)"
        endc
        if (LSP_RING&$FFFF)+LSP_RINGSZ>$10000
        fail    "the ring crosses a 64 KB boundary (lsp_vbl reads the DMA position as 16 bits)"
        endc
        if (LSP_DAT&1)+(LSP_FX&1)+(LSP_BANK&1)
        fail    "LSP_DAT, LSP_FX and LSP_BANK must be even (the mixer reads longs)"
        endc
        if LSP_FX+LSP_FXMAX>LSP_RING
        fail    "the effects area runs into the ring"
        endc
        if LSP_SIL+LSP_TICK>LSP_DAT
        fail    "the ring and its silence tick run into the file area"
        endc
        if LSP_DAT+LSP_DATMAX>LSP_BANK
        fail    "the file area runs into the bank"
        endc
