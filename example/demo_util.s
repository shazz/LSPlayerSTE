; example/demo_util.s: DEMO.PRG, printing and data.

; a0 = text ending in 0: Cconws. Clobbers d0-d2/a0-a2.
d_print:    pea     (a0)
        move.w  #9,-(a7)
        trap    #1
        addq.l  #6,a7
        rts

; d0.w = number: print it as five digits at the start of the line.
d_number:   lea     d_digits+5(pc),a0
        moveq   #4,d1
.d:     andi.l  #$FFFF,d0
        divu.w  #10,d0
        swap    d0
        addi.b  #'0',d0
        move.b  d0,-(a0)
        swap    d0
        dbra    d1,.d
        lea     d_line(pc),a0
        bra.s   d_print

d_ssp:      dc.l    0
d_oldvbl:   dc.l    0
d_held:     dc.w    0
d_frames:   dc.w    0
d_max:      dc.b    0
d_tacr:     dc.b    0
d_tadr:     dc.b    0
d_conterm:  dc.b    0
d_name:     dc.b    'LSPSTE.DAT',0
d_fxname:   dc.b    'FX.DAT',0
d_hello:    dc.b    13,10,'LSPSTE demo: loading, about 5 s...',13,10,0   ; 40 columns: the boot resolution
d_keys:     dc.b    '1-9 effects, Space hold, Esc quit',13,10,0
d_noste:    dc.b    'This needs an STE with 1 MB or more.',13,10,'Press a key.',13,10,0
d_nolsp:    dc.b    'LSPSTE.DAT is missing or bad.',13,10,'Press a key.',13,10,0
d_big:      dc.b    'The song does not fit the memory',13,10,'of lsp_config.s. Press a key.',13,10,0
d_nofx:     dc.b    'FX.DAT is missing or bad: no effects.',13,10,0
d_line:     dc.b    13,'mixer cycles/VBL (max of 50): '
d_digits:   dc.b    '00000 ',0
            even
