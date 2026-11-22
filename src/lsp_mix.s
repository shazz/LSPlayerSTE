; src/lsp_mix.s: LSPSTE, one tick (run-time, after lsp_api.s): take a posted start or stop and a posted effect, read
; the stream record that is due, mix 252 bytes at the ring's write position. a6 = lsp_v; d0-d7/a0-a5 lost.
; Stream (tools/lsp_seq.py), words: record = events << 8 | ticks to the next record, then per event
; channel << 14 | offset in LSPSTE.DAT of the variant's entry (its first long = address in the bank), 0 = silence;
; $FFFF = go on at the loop record (file offset at 28 of the header).
; Hold (lsp_hold sets lsp_hreq): the module's channels are silent for that tick, the stream does not advance and
; the channels keep their positions; the effects channel goes on.
lsp_tick:   movea.l a6,a1                   ; a1 = lsp_v for lsp_note
        move.w  lsp_req-lsp_v(a6),d0
        beq.s   .fxq
        clr.w   lsp_req-lsp_v(a6)
        move.l  #LSP_SIL,d1
        lea     lsp_ptr-lsp_v(a6),a0
        move.l  d1,(a0)+
        move.l  d1,(a0)+
        move.l  d1,(a0)+
        move.l  d1,(a0)+
        clr.w   lsp_play-lsp_v(a6)
        clr.w   lsp_held-lsp_v(a6)
        move.w  #$200,d1
        subq.w  #1,d0
        bne.s   .log                    ; stop
        move.w  #1,lsp_play-lsp_v(a6)   ; start: from the first record, at this tick
        move.w  #1,lsp_wait-lsp_v(a6)
        lea     LSP_DAT,a0
        adda.l  24(a0),a0
        move.l  a0,lsp_sptr-lsp_v(a6)
        move.w  #$100,d1
.log:   bsr     lsp_note
.fxq:   move.w  lsp_fxreq-lsp_v(a6),d0   ; an effect asked by lsp_fx: start it on channel 5
        bmi.s   .seq
        move.w  #-1,lsp_fxreq-lsp_v(a6)
        move.w  d0,d1                   ; its index is its log code
        lsl.w   #3,d0
        lea     lsp_fxptrs-lsp_v(a6),a0
        adda.w  d0,a0
        move.l  (a0)+,lsp_ptr+16-lsp_v(a6)
        move.l  (a0),lsp_fxend-lsp_v(a6)
        bsr     lsp_note
.seq:   moveq   #0,d4                   ; d4 = 1: held tick
        tst.w   lsp_play-lsp_v(a6)
        beq     .mix
        move.w  lsp_hreq-lsp_v(a6),d4
        cmp.w   lsp_held-lsp_v(a6),d4
        beq.s   .same
        move.w  d4,lsp_held-lsp_v(a6)
        move.w  #$301,d1
        sub.w   d4,d1                   ; $300 = held from this tick, $301 = released
        bsr     lsp_note
.same:  tst.w   d4
        bne.s   .mix
        subq.w  #1,lsp_wait-lsp_v(a6)
        bne.s   .mix
        movea.l lsp_sptr-lsp_v(a6),a0
        lea     LSP_DAT,a1
        move.w  (a0)+,d0
        bpl.s   .rec
        movea.l a1,a0                   ; $FFFF: the loop record
        adda.l  28(a1),a0
        move.w  (a0)+,d0
.rec:   moveq   #0,d1
        move.b  d0,d1
        move.w  d1,lsp_wait-lsp_v(a6)
        lsr.w   #8,d0                   ; events
        beq.s   .recx
        subq.w  #1,d0
.ev:    move.w  (a0)+,d1
        move.w  d1,d2
        rol.w   #2,d2
        andi.w  #3,d2
        lsl.w   #2,d2                   ; d2 = channel * 4
        move.l  #LSP_SIL,d3
        andi.w  #$3FFF,d1
        beq.s   .set
        move.l  0(a1,d1.w),d3           ; the variant's address
.set:   move.l  d3,lsp_ptr-lsp_v(a6,d2.w)
        dbra    d0,.ev
.recx:  move.l  a0,lsp_sptr-lsp_v(a6)
.mix:   move.l  #LSP_SIL,d5
        movem.l lsp_ptr-lsp_v(a6),a0-a4
        tst.w   d4
        beq.s   .live
        movea.l d5,a0                   ; held: the module's channels are silent, their pointers stay
        movea.l d5,a1
        movea.l d5,a2
        movea.l d5,a3
.live:  cmp.l   a0,d5                   ; nothing sounds on any channel?
        bne.s   .snd
        cmp.l   a1,d5
        bne.s   .snd
        cmp.l   a2,d5
        bne.s   .snd
        cmp.l   a3,d5
        bne.s   .snd
        cmp.l   a4,d5
        bne.s   .snd
        cmpi.w  #8,lsp_idle-lsp_v(a6)   ; the last 8 ticks were silent too: the ring is all silence already
        beq     .adv
        addq.w  #1,lsp_idle-lsp_v(a6)
        bra.s   .add
.snd:   clr.w   lsp_idle-lsp_v(a6)
.add:   lea     LSP_RING,a5
        adda.w  lsp_wpos-lsp_v(a6),a5
        move.l  #$02020200,d6
        move.l  #$80808080,d7
        rept    LSP_TICK/4
        move.l  (a0)+,d0
        add.l   (a1)+,d0
        add.l   (a2)+,d0
        add.l   (a3)+,d0
        add.l   (a4)+,d0
        sub.l   d6,d0
        eor.l   d7,d0
        move.l  d0,(a5)+
        endr
        lea     lsp_ptr-lsp_v(a6),a5    ; sounding channels move on one tick, silent ones stay on LSP_SIL
        tst.w   d4
        bne.s   .fx
        cmp.l   (a5),d5
        beq.s   .b1
        move.l  a0,(a5)
.b1:    cmp.l   4(a5),d5
        beq.s   .b2
        move.l  a1,4(a5)
.b2:    cmp.l   8(a5),d5
        beq.s   .b3
        move.l  a2,8(a5)
.b3:    cmp.l   12(a5),d5
        beq.s   .fx
        move.l  a3,12(a5)
.fx:    cmp.l   16(a5),d5
        beq.s   .adv
        move.l  a4,16(a5)
        cmpa.l  lsp_fxend-lsp_v(a6),a4  ; the effect has played out: its channel is silent again
        bcs.s   .adv
        move.l  d5,16(a5)
.adv:   move.w  lsp_wpos-lsp_v(a6),d0
        addi.w  #LSP_TICK,d0
        cmpi.w  #LSP_RINGSZ,d0
        bcs.s   .w
        moveq   #0,d0
.w:     move.w  d0,lsp_wpos-lsp_v(a6)
        addq.l  #1,lsp_ticks-lsp_v(a6)
        rts
