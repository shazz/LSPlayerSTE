; src/lsp_bank.s: LSPSTE start-up, the heavy parts. a5 = LSP_DAT in all of them.
; lsp_bank: build the "bank" at LSP_BANK: every (sample, period, volume) the song plays, resampled to 12,517 Hz as
; a straight run of whole ticks. It is built here because it is several times the size of the file; the loop is
; mirrored bit for bit by interp() in tools/lsp_bank.py.
; lsp_fxset: check FX.DAT, fill the pointer table, scale the samples in place.

; Variant entry (12 bytes from 48(a5)): rendition offset.l, 16.16 step.l, ticks.w, volume table.w;
; the first long becomes the variant's address in the bank (what a stream event points at).
; Per output byte: a = src[i], b = src[i+1], v = a + ((b - a) * (frac >> 1) >> 15), out = table[v]; i.frac += step.
; Clobbers d0-d7, a0-a4.
lsp_bank:   lea     LSP_BANK,a1             ; a1 = output
        lea     48(a5),a4
        move.w  6(a5),-(a7)             ; variants left
.var:   movea.l a5,a0
        adda.l  (a4),a0                 ; a0 = rendition (signed bytes)
        move.l  a1,(a4)+
        move.l  (a4)+,d5
        movea.w d5,a2                   ; a2 = step fraction (added as a word below)
        clr.w   d5
        swap    d5                      ; d5 = step integer part
        move.w  (a4)+,d1                ; ticks
        subq.w  #1,d1
        move.w  (a4)+,d0
        lsl.w   #8,d0
        movea.l a5,a3
        adda.l  16(a5),a3
        adda.w  d0,a3
        lea     128(a3),a3              ; a3 = this volume's table, indexed by the signed sample
        moveq   #0,d4                   ; d4 = source index
        moveq   #0,d0                   ; d0 = fraction
.tick:  move.w  #LSP_TICK-1,d7
.smp:   move.b  0(a0,d4.l),d2
        ext.w   d2
        move.b  1(a0,d4.l),d3
        ext.w   d3
        sub.w   d2,d3
        move.w  d0,d6
        lsr.w   #1,d6
        muls.w  d6,d3
        add.l   d3,d3
        swap    d3
        add.w   d3,d2
        move.b  0(a3,d2.w),(a1)+
        add.w   a2,d0
        addx.l  d5,d4
        dbra    d7,.smp
        dbra    d1,.tick
        subq.w  #1,(a7)
        bne.s   .var
        addq.l  #2,a7
        rts

; In: d7.l = bytes of FX.DAT at LSP_FX (0 = none asked for, negative = it could not be read).
; Out: d0 = 0 good or none (lsp_fxn = the count), 3 bad (lsp_fxn = 0). The samples of FX.DAT (signed, full scale)
; become unsigned, scaled to the effects' share of the headroom, in place, through the 256-byte table of
; LSPSTE.DAT; their zero padding becomes silence ($80). Checked: magic, count, each sample at an even offset
; and wholly inside the file with a tick of padding after it (the mixer reads whole ticks).
; Pointer table lsp_fxptrs: start.l, end.l per sample. Clobbers d0-d7, a0-a3.
lsp_fxset:  lea     lsp_v(pc),a6
        clr.w   lsp_fxn-lsp_v(a6)
        tst.l   d7
        beq     .ok
        bmi     .bad
        lea     LSP_FX,a0
        cmpi.l  #'FX01',(a0)
        bne     .bad
        moveq   #0,d1
        move.w  4(a0),d1                ; count
        beq     .bad
        cmpi.w  #LSP_FXN,d1
        bhi     .bad
        move.l  d1,d0
        lsl.l   #3,d0
        addq.l  #6,d0                   ; the table's end = the first sample
        cmp.l   d7,d0
        bcc     .bad
        lea     6(a0),a1
        lea     lsp_fxptrs-lsp_v(a6),a2
        move.w  d1,d6
        subq.w  #1,d6
.ent:   move.l  (a1)+,d0                ; offset
        move.l  (a1)+,d2                ; length
        btst    #0,d0
        bne     .bad
        cmp.l   d7,d0
        bhi     .bad
        move.l  d7,d3
        sub.l   d0,d3
        subi.l  #LSP_TICK,d3            ; room after the offset, less the padding
        bcs     .bad
        cmp.l   d3,d2
        bhi     .bad
        add.l   a0,d0
        move.l  d0,(a2)+                ; start
        add.l   d2,d0
        move.l  d0,(a2)+                ; end
        dbra    d6,.ent
        move.w  d1,lsp_fxn-lsp_v(a6)
        lsl.w   #3,d1
        lea     6(a0,d1.w),a0           ; first sample byte
        movea.l a5,a3
        adda.l  20(a5),a3
        lea     128(a3),a3
        lea     LSP_FX,a1
        adda.l  d7,a1                   ; end of the file
.cv:    move.b  (a0),d0
        ext.w   d0
        move.b  0(a3,d0.w),(a0)+
        cmpa.l  a1,a0
        bne.s   .cv
.ok:    moveq   #0,d0
        rts
.bad:   moveq   #3,d0
        rts
