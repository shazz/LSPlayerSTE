; src/lsp_check.s: LSPSTE start-up, the checks on LSPSTE.DAT before anything is built from it.
; In: d0.l = bytes read of LSPSTE.DAT. Out: d0 = 0 (Z set) good, 2 bad, 4 does not fit; a5 = LSP_DAT.
; Checked: size, magic, version, tick, checksum; every variant's rendition and volume table exist; every
; rendition lies inside the file and has a loop length of 1..end (0 would hang the loader); the variants account
; for the whole bank (so the builder cannot write outside it); every target is even and has a whole tick of the
; bank after it (so the mixer cannot read outside it). The header's own offsets are trusted once the checksum
; holds: a crafted file is not defended against.
; Clobbers d0-d5, a0.
lsp_check:  lea     LSP_DAT,a5
        tst.l   d0
        ble     .bad
        cmpi.l  #48,d0
        bcs     .bad
        cmpi.l  #'LSP1',(a5)
        bne     .bad
        cmpi.w  #LSP_VERSION,4(a5)
        bne     .bad
        cmp.l   8(a5),d0                    ; the file's own size
        bne     .bad
        cmpi.w  #LSP_TICK,34(a5)
        bne     .bad
        tst.w   6(a5)
        beq     .bad
        move.l  d0,d3
        lea     48(a5),a0
        move.l  d0,d1
        subi.l  #48,d1
        moveq   #0,d0
        moveq   #0,d2
.sum:   move.b  (a0)+,d2                    ; checksum: the bytes after the header
        add.l   d2,d0
        subq.l  #1,d1
        bne.s   .sum
        cmp.l   40(a5),d0
        bne     .bad
        move.l  44(a5),d5
        sub.l   36(a5),d5
        divu.w  #12,d5                      ; d5.w = renditions
        lea     48(a5),a0
        move.w  6(a5),d1
        subq.w  #1,d1
        moveq   #0,d4                       ; long words of all variants
        moveq   #0,d0
.var:   cmp.w   (a0),d5                     ; its rendition exists
        bls     .bad
        move.w  2(a0),d0                    ; its volume table exists
        cmp.w   32(a5),d0
        bcc     .bad
        move.w  14(a0),d0
        add.l   d0,d4
        lea     16(a0),a0
        dbra    d1,.var
        movea.l a5,a0
        adda.l  36(a5),a0
        subq.w  #1,d5
.rnd:   move.l  (a0)+,d0                    ; data + end = the last sample read: inside the file
        add.l   (a0)+,d0
        cmp.l   d3,d0
        bcc     .bad
        move.l  (a0)+,d0                    ; loop length: 1..end
        beq     .bad
        cmp.l   -8(a0),d0
        bhi     .bad
        dbra    d5,.rnd
        move.l  12(a5),d2
        cmpi.l  #LSP_LIMIT-LSP_BANK,d2
        bhi     .big
        lsl.l   #2,d4
        cmp.l   d2,d4
        bne     .bad
        subi.l  #LSP_TICK,d2                ; d2 = the last place a tick can start in the bank
        bcs     .bad
        movea.l a5,a0
        adda.l  44(a5),a0
        move.l  16(a5),d1
        sub.l   44(a5),d1
        lsr.l   #2,d1                       ; targets, entry 0 (silence) included
        beq     .bad
        addq.l  #4,a0
        bra.s   .tnx
.tgt:   move.l  (a0)+,d0
        btst    #0,d0
        bne     .bad
        cmp.l   d2,d0
        bhi     .bad
.tnx:   subq.l  #1,d1
        bne.s   .tgt
        moveq   #0,d0
        rts
.big:   moveq   #4,d0
        rts
.bad:   moveq   #2,d0
        rts
