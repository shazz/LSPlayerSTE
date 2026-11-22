; example/demo.s: DEMO.PRG, a small program that plays LSPSTE.DAT with effects from FX.DAT (build.sh makes both).
; Run from the AUTO folder of a disk with the two files in its root, or from the desktop on an STE with 1 MB.
; Keys: 1..9 = effect sample 0..8 on the fifth channel, Space = hold / release the module, Esc = quit.
; The number on screen is the largest cost of lsp_vbl over the last 50 VBLs in CPU cycles, timed with MFP timer A
; (delay mode, /16: 52.2 cycles a count, so a VBL above 13,300 cycles wraps). Interrupts that fall inside the call,
; such as TOS's 200 Hz timer, are counted too. Quit puts back the VBL vector, timer A, the key click (off while
; it runs: it would sound on every key) and stops the DMA.
; The address of the player's variables is left in the long at $80000, for a debugger (see TESTING.md).
TACR        equ     $FFFFFA19
TADR        equ     $FFFFFA1F
KEY_ESC     equ     27

start:  clr.l   -(a7)
        move.w  #$20,-(a7)              ; Super: supervisor mode for the whole run
        trap    #1
        addq.l  #6,a7
        move.l  d0,d_ssp
        move.b  ($484).w,d_conterm      ; conterm: bit 0 = key click
        bclr    #0,($484).w
        bsr     lsp_probe               ; reads TOS variables: supervisor only
        lea     d_noste(pc),a0
        bne     d_fail
        lea     d_hello(pc),a0
        bsr     d_print
        lea     d_name(pc),a0
        lea     d_fxname(pc),a1
        bsr     lsp_init
        tst.l   d0
        beq.s   .ready
        cmpi.l  #3,d0                   ; no effects is not fatal
        beq.s   .nofx
        lea     d_nolsp(pc),a0
        cmpi.l  #4,d0
        bne     d_fail
        lea     d_big(pc),a0
        bra     d_fail
.nofx:  lea     d_nofx(pc),a0
        bsr     d_print
.ready: move.l  #lsp_v,($80000).l
        bsr     lsp_start
        move.b  TACR,d_tacr
        move.b  TADR,d_tadr
        move.l  ($70).w,d_oldvbl
        move.l  #d_vbl,($70).w
        lea     d_keys(pc),a0
        bsr     d_print
.loop:  move.w  #$0B,-(a7)              ; Cconis
        trap    #1
        addq.l  #2,a7
        tst.w   d0
        beq.s   .show
        move.w  #7,-(a7)                ; Crawcin
        trap    #1
        addq.l  #2,a7
        cmpi.b  #KEY_ESC,d0
        beq.s   .quit
        cmpi.b  #' ',d0
        bne.s   .digit
        eori.w  #1,d_held
        beq.s   .rel
        bsr     lsp_hold
        bra.s   .loop
.rel:   bsr     lsp_resume
        bra.s   .loop
.digit: subi.b  #'1',d0
        ext.w   d0
        bsr     lsp_fx                  ; an index outside FX.DAT is ignored
        bra.s   .loop
.show:  cmpi.w  #50,d_frames
        bcs.s   .loop
        clr.w   d_frames
        moveq   #0,d0
        move.b  d_max(pc),d0
        clr.b   d_max
        mulu.w  #5222,d0                ; counts * 52.22 cycles
        divu.w  #100,d0
        bsr     d_number
        bra.s   .loop
.quit:  move.w  sr,-(a7)
        ori.w   #$0700,sr
        move.l  d_oldvbl(pc),($70).w
        bsr     lsp_stop                ; DMA off
        clr.b   TACR
        move.b  d_tadr(pc),TADR
        move.b  d_tacr(pc),TACR
        move.w  (a7)+,sr
        bra.s   d_exit
d_fail: bsr     d_print                 ; a0 = why: print it, wait for a key, leave
        move.w  #7,-(a7)
        trap    #1
        addq.l  #2,a7
d_exit: move.b  d_conterm(pc),($484).w
        move.l  d_ssp(pc),-(a7)
        move.w  #$20,-(a7)              ; back to user mode
        trap    #1
        addq.l  #6,a7
        clr.w   -(a7)                   ; Pterm0
        trap    #1

; Every VBL, before the system's handler: the mixer, timed.
d_vbl:  move.l  d0,-(a7)
        clr.b   TACR
        move.b  #255,TADR
        move.b  #3,TACR                 ; delay mode, 2.4576 MHz / 16
        bsr     lsp_vbl
        clr.b   TACR
        move.b  TADR,d0
        not.b   d0                      ; counts used
        cmp.b   d_max(pc),d0
        bls.s   .n
        move.b  d0,d_max
.n:     addq.w  #1,d_frames
        move.l  (a7)+,d0
        move.l  d_oldvbl(pc),-(a7)
        rts

        include "demo_util.s"
        include "lsp.s"
