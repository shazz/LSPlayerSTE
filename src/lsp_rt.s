; src/lsp_rt.s: LSPSTE run-time, variables and the VBL routine. Everything from lsp_v to the end of lsp_mix.s is
; position independent for its own data (PC-relative); it uses the absolute addresses of lsp_config.s only.
; Per VBL (lsp_vbl): keep the DMA ring LSP_LEAD bytes ahead of the DMA's read position by mixing one tick
; (LSP_TICK = 252 bytes) of five channels: four from the module's event stream, the fifth for the effects samples.
; A tick is 252 bytes and the DMA plays about 250 per VBL, so the lead grows from about 128 to LSP_LEAD and about
; one VBL in 130 mixes nothing; two ticks in a VBL only happen when fewer than LSP_LOW bytes are left (a VBL
; came more than 7 ms late or was lost). The output is a function of the tick number alone: tools/lsp_ref.py gives
; the same bytes (lsp_log holds what the reference cannot know: when the module was started, stopped or held and
; when an effect started).
; Mixing: every channel is unsigned (silence $80), added as 63 longs. The converter keeps the true sum of the
; five signed samples in -128..127, so each byte column adds up to 512..767 and carries exactly 2 into the next
; byte: `- $02020200` removes the carries and 4 x $80 of bias, `eor $80808080` the fifth: signed bytes.
LSP_LEAD    equ     LSP_TICK*3/2            ; mix when fewer bytes than this are ahead of the DMA
LSP_LOW     equ     LSP_TICK/8              ; mix twice when fewer than this were ahead

lsp_v:                                  ; variables (a6 in the routines below)
lsp_ok:     dc.w    0                       ; 1 = lsp_setup succeeded
lsp_on:     dc.w    0                       ; 1 = lsp_vbl works: set by lsp_setup and lsp_start, cleared by lsp_stop
lsp_req:    dc.w    0                       ; posted by lsp_start / lsp_halt, taken at the next tick: 1 = start, 2 = stop
lsp_fxreq:  dc.w    -1                      ; posted by lsp_fx: sample index, -1 = none
lsp_dma:    dc.w    0                       ; 1 = the DMA runs on the ring
lsp_wpos:   dc.w    0                       ; ring offset of the next tick
lsp_play:   dc.w    0                       ; 1 = the module plays
lsp_held:   dc.w    0                       ; 1 = it is held (lsp_hold)
lsp_hreq:   dc.w    0                       ; 1 = lsp_hold asked, 0 = lsp_resume
lsp_wait:   dc.w    0                       ; ticks to the next stream record
lsp_idle:   dc.w    0                       ; silent ticks in a row (8 = the whole ring is silence: no mixing)
lsp_lost:   dc.w    0                       ; times the lead was lost (ring underrun) and the ring re-placed
lsp_low:    dc.w    $7FFF                   ; smallest and largest lead seen at a VBL (bytes)
lsp_high:   dc.w    0
lsp_logn:   dc.w    0                       ; log entries written (the log keeps the last 32)
lsp_fxn:    dc.w    0                       ; samples in FX.DAT, 0 = none
lsp_ticks:  dc.l    0                       ; ticks mixed
lsp_sptr:   dc.l    0                       ; next stream record
lsp_fxend:  dc.l    0                       ; end of the effect sample on channel 5
lsp_ptr:    dcb.l   5,LSP_SIL               ; what each channel plays next (LSP_SIL = nothing)
lsp_fxptrs: ds.l    LSP_FXN*2               ; per effect sample: start, end (absolute), filled by lsp_setup
lsp_log:    ds.b    32*8                    ; (tick.l, code.w, 0.w): $100 start, $200 stop, $300/$301 hold on/off,
                                        ; 0..15 effect sample started

; d1.w = code: log it with the tick it applies to. a1 = lsp_v. Clobbers d0, a0.
lsp_note:   move.w  lsp_logn-lsp_v(a1),d0
        addq.w  #1,lsp_logn-lsp_v(a1)
        andi.w  #31,d0
        lsl.w   #3,d0
        lea     lsp_log(pc),a0
        adda.w  d0,a0
        move.l  lsp_ticks-lsp_v(a1),(a0)+
        move.w  d1,(a0)
        rts

; Every VBL (supervisor). All registers kept.
lsp_vbl:    movem.l d0-d7/a0-a6,-(a7)
        lea     lsp_v(pc),a6
        tst.w   lsp_on-lsp_v(a6)
        beq     .x
        lea     ($FFFF8900).w,a0
        tst.w   lsp_dma-lsp_v(a6)
        bne.s   .rd
        clr.b   1(a0)                   ; first VBL: the DMA loops over the ring, mono 12,517 Hz
        move.l  #LSP_RING,d0
        move.b  d0,7(a0)
        lsr.w   #8,d0
        move.b  d0,5(a0)
        swap    d0
        move.b  d0,3(a0)
        move.l  #LSP_RING+LSP_RINGSZ,d0
        move.b  d0,$13(a0)
        lsr.w   #8,d0
        move.b  d0,$11(a0)
        swap    d0
        move.b  d0,$F(a0)
        move.b  #$81,$21(a0)
        move.b  #3,1(a0)
        move.w  #2*LSP_TICK,lsp_wpos-lsp_v(a6)
        move.w  #1,lsp_dma-lsp_v(a6)
.rd:    movep.w $B(a0),d0               ; the DMA's read address, middle and low bytes, until read twice the same
        movep.w $B(a0),d1
        cmp.w   d0,d1
        bne.s   .rd
        subi.w  #LSP_RING&$FFFF,d0
        cmpi.w  #LSP_RINGSZ,d0
        bcs.s   .in
        subi.w  #LSP_RINGSZ,d0
.in:    move.w  lsp_wpos-lsp_v(a6),d7
        sub.w   d0,d7
        bpl.s   .lead
        addi.w  #LSP_RINGSZ,d7
.lead:  cmpi.w  #LSP_RINGSZ/2,d7        ; d7 = bytes ahead of the DMA; half a ring or more = it overtook us
        bcc.s   .lost
        cmp.w   lsp_low-lsp_v(a6),d7
        bcc.s   .l1
        move.w  d7,lsp_low-lsp_v(a6)
.l1:    cmp.w   lsp_high-lsp_v(a6),d7
        bls.s   .l2
        move.w  d7,lsp_high-lsp_v(a6)
.l2:    cmpi.w  #LSP_LEAD,d7
        bcc.s   .x
        move.w  d7,-(a7)
        bsr     lsp_tick
        cmpi.w  #LSP_LOW,(a7)+
        bcc.s   .x
.one:   bsr     lsp_tick                ; nearly caught: one more
.x:     movem.l (a7)+,d0-d7/a0-a6
        rts
.lost:  addq.w  #1,lsp_lost-lsp_v(a6)   ; put the next tick two ticks after the one the DMA is in
        andi.l  #$FFFF,d0
        divu.w  #LSP_TICK,d0
        addq.w  #2,d0
        andi.w  #LSP_RINGTK-1,d0
        mulu.w  #LSP_TICK,d0
        move.w  d0,lsp_wpos-lsp_v(a6)
        bra.s   .one
