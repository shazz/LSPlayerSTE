; src/lsp_api.s: LSPSTE, the calls a program makes after lsp_init (documented in lsp.s). The "any mode" ones only
; write a word that the next tick takes, so they are safe from the main program, a VBL or any interrupt.
; Position independent for its own data.

lsp_start:  move.l  a0,-(a7)
        lea     lsp_v(pc),a0
        tst.w   lsp_ok-lsp_v(a0)
        beq.s   .x                      ; not set up (or it failed): do nothing
        move.w  #1,lsp_on-lsp_v(a0)
        move.w  #1,lsp_req-lsp_v(a0)
.x:     movea.l (a7)+,a0
        rts

lsp_halt:   move.l  a0,-(a7)
        lea     lsp_v(pc),a0
        tst.w   lsp_ok-lsp_v(a0)
        beq.s   .x
        move.w  #2,lsp_req-lsp_v(a0)
.x:     movea.l (a7)+,a0
        rts

; d0.w = effect sample index; out of range (or no FX.DAT: lsp_fxn = 0) is ignored.
lsp_fx:     move.l  a0,-(a7)
        lea     lsp_v(pc),a0
        cmp.w   lsp_fxn-lsp_v(a0),d0
        bcc.s   .x
        move.w  d0,lsp_fxreq-lsp_v(a0)
.x:     movea.l (a7)+,a0
        rts

lsp_hold:   move.l  a0,-(a7)
        lea     lsp_v(pc),a0
        move.w  #1,lsp_hreq-lsp_v(a0)
        movea.l (a7)+,a0
        rts

lsp_resume: move.l  a0,-(a7)
        lea     lsp_v(pc),a0
        clr.w   lsp_hreq-lsp_v(a0)
        movea.l (a7)+,a0
        rts

; Supervisor. Interrupts masked meanwhile, so an lsp_vbl cannot run on half-reset state.
lsp_stop:   movem.l d0-d1/a0-a1,-(a7)
        move.w  sr,-(a7)
        ori.w   #$0700,sr
        clr.b   ($FFFF8901).w           ; DMA off
        lea     lsp_v(pc),a1
        clr.w   lsp_on-lsp_v(a1)
        clr.w   lsp_dma-lsp_v(a1)
        clr.w   lsp_req-lsp_v(a1)
        clr.w   lsp_play-lsp_v(a1)
        clr.w   lsp_held-lsp_v(a1)
        clr.w   lsp_hreq-lsp_v(a1)
        clr.w   lsp_idle-lsp_v(a1)
        move.w  #-1,lsp_fxreq-lsp_v(a1)
        move.l  #LSP_SIL,d0
        lea     lsp_ptr-lsp_v(a1),a0
        move.l  d0,(a0)+
        move.l  d0,(a0)+
        move.l  d0,(a0)+
        move.l  d0,(a0)+
        move.l  d0,(a0)+
        move.w  #$200,d1
        bsr     lsp_note
        lea     LSP_RING,a0             ; ring = silence (signed 0), then one tick of silent channel ($80)
        move.w  #LSP_RINGSZ/4-1,d0
.ring:  clr.l   (a0)+
        dbra    d0,.ring
        move.w  #LSP_TICK/4-1,d0
.sil:   move.l  #$80808080,(a0)+
        dbra    d0,.sil
        move.w  (a7)+,sr
        movem.l (a7)+,d0-d1/a0-a1
        rts
