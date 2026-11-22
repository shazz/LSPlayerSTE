; src/lsp_init.s: LSPSTE start-up: machine check, load, check, set-up. Supervisor mode (low memory is read), GEMDOS
; available for lsp_init. Error codes: see lsp.s.

; Out: d0.l = 0 and Z set on an STE with LSP_LIMIT bytes of RAM at least, else d0 = 1. Clobbers d0, d1, a0.
; _sysbase -> the OS header, os_version at +2 (at least LSP_MINTOS): TOS before 1.06 has no cookie jar and leaves
; junk in $5A0.
; The jar is read for 64 cookies at most.
lsp_probe:  cmpi.l  #LSP_LIMIT,($42E).w         ; phystop
        bcs.s   .no
        move.l  ($4F2).w,d0                 ; _sysbase
        beq.s   .no
        btst    #0,d0
        bne.s   .no
        cmpi.l  #$1000000,d0
        bcc.s   .no
        movea.l d0,a0
        cmpi.w  #LSP_MINTOS,2(a0)            ; os_version
        bcs.s   .no
        move.l  ($5A0).w,d0                 ; _p_cookies
        beq.s   .no
        btst    #0,d0
        bne.s   .no
        cmpi.l  #$800,d0                    ; not in the vectors and system variables
        bcs.s   .no
        cmp.l   ($42E).w,d0                 ; inside RAM
        bcc.s   .no
        movea.l d0,a0
        moveq   #63,d1
.c:     move.l  (a0)+,d0
        beq.s   .no                         ; end of the jar
        cmpi.l  #'_SND',d0
        beq.s   .snd
        addq.l  #4,a0
        dbra    d1,.c
.no:    moveq   #1,d0
        rts
.snd:   btst    #1,3(a0)                    ; 8-bit DMA sound
        beq.s   .no
        moveq   #0,d0
        rts

; In: a0 -> 0-terminated path, a1 = where to read, d0.l = most bytes. Out: d0.l = bytes read, negative = error
; (a GEMDOS code). Clobbers d0-d4, a0-a2.
lsp_read:   move.l  d0,d4
        clr.w   -(a7)
        pea     (a0)
        move.w  #$3D,-(a7)                  ; Fopen, read only
        trap    #1
        addq.l  #8,a7
        move.l  d0,d3
        bmi.s   .out
        pea     (a1)
        move.l  d4,-(a7)
        move.w  d3,-(a7)
        move.w  #$3F,-(a7)                  ; Fread
        trap    #1
        lea     12(a7),a7
        move.l  d0,d4
        move.w  d3,-(a7)
        move.w  #$3E,-(a7)                  ; Fclose
        trap    #1
        addq.l  #4,a7
        move.l  d4,d0
.out:   rts

lsp_init:   movem.l d1-d7/a0-a6,-(a7)
        movea.l a0,a3
        movea.l a1,a4
        bsr     lsp_probe
        bne.s   .out
        movea.l a3,a0
        lea     LSP_DAT,a1
        move.l  #LSP_DATMAX,d0
        bsr     lsp_read
        move.l  d0,d6
        moveq   #0,d7                       ; no effects asked for
        move.l  a4,d0
        beq.s   .set
        movea.l a4,a0
        lea     LSP_FX,a1
        move.l  #LSP_FXMAX,d0
        bsr     lsp_read
        move.l  d0,d7
        bgt.s   .set
        moveq   #-1,d7                      ; empty or unreadable: an error, not "none"
.set:   move.l  d6,d0
        move.l  d7,d1
        bsr     lsp_setup
.out:   movem.l (a7)+,d1-d7/a0-a6
        rts

lsp_setup:  movem.l d1-d7/a0-a6,-(a7)
        move.l  d1,d7
        bsr     lsp_stop                    ; DMA off, state reset: safe on a second call
        lea     lsp_v(pc),a6
        clr.w   lsp_ok-lsp_v(a6)
        bsr     lsp_check
        bne.s   .out
        move.l  d7,-(a7)                    ; lsp_bank uses every data register
        bsr     lsp_bank
        move.l  (a7)+,d7
        bsr     lsp_fxset
        lea     lsp_v(pc),a6
        move.w  #1,lsp_ok-lsp_v(a6)
        move.w  #1,lsp_on-lsp_v(a6)
.out:   movem.l (a7)+,d1-d7/a0-a6
        rts

; In: d0.l = bytes read of LSPSTE.DAT. Out: d0 = 0 (Z set) good, 2 bad, 4 does not fit; a5 = LSP_DAT.
; Checked: size, magic, version, tick, checksum, and that the variants account for the whole bank (so the
; builder cannot write outside it). A crafted file can still make the stream point outside: not defended.
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
        lea     48(a5),a0
        move.w  6(a5),d1
        subq.w  #1,d1
        moveq   #0,d4                       ; ticks of all variants
        moveq   #0,d5
.var:   cmp.l   (a0),d3                     ; its rendition starts inside the file
        bls     .bad
        move.w  8(a0),d5
        add.l   d5,d4
        move.w  10(a0),d0                   ; its volume table exists
        cmp.w   32(a5),d0
        bcc     .bad
        lea     12(a0),a0
        dbra    d1,.var
        cmpi.l  #LSP_LIMIT-LSP_BANK,12(a5)
        bhi     .big
        cmpi.l  #$FFFF,d4
        bhi     .bad
        mulu.w  #LSP_TICK,d4
        cmp.l   12(a5),d4
        bne     .bad
        moveq   #0,d0
        rts
.big:   moveq   #4,d0
        rts
.bad:   moveq   #2,d0
        rts
