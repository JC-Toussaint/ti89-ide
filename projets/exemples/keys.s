| Key Codes - example 68000 assembly program for the TI-89 Titanium (GNU as syntax)
|
| Shows the AMS code of every key you press, a counter and the last 5 codes.
| ESC quits.
|
| GNU as syntax used by GCC4TI:
|   - registers are written %d0..%d7, %a0..%a7 (%sp = %a7), %pc
|   - immediate values start with #, comments with |
|   - the entry point is __main (it is _main in C), called by the startup code
|
| Techniques shown:
|   - variables in memory (labels at the end of the file), shown in the
|     Variables tab of the debugger
|   - writing a variable: the 68000 cannot WRITE with a PC-relative address,
|     so we first take its address with  lea var(%pc),%a0  then write (%a0)
|   - an array: shifting the history of the last 5 key codes with (a0)+
|   - calling AMS functions, including sprintf which takes a variable number
|     of parameters (pushed from the last to the first, removed after the call)

        .include "os.h"                 | AMS ROM call numbers

        .xdef   _ti89                   | target models: TI-89 and TI-89 Titanium
        .xdef   _ti89ti
        .xdef   _tigcc_native
        .xdef   __ref_all___nostub      | standalone program (no kernel)
        .xdef   __ref_all___startup_code | startup code that calls __main
        .xdef   __ref_all___set_file_in_use_bit
        .xdef   __ref_all___save_screen | restore the screen at exit
        .xdef   __main                  | entry point (C name: _main)

        .set    KEY_ESC, 264            | code returned by ngetchx for ESC
        .set    A_NORMAL, 1             | drawing attributes
        .set    A_REPLACE, 4            | (text erases what is below)
        .set    F_6x8, 1                | fonts
        .set    F_8x10, 2
        .set    HISTORY, 5              | number of codes kept

| Call an AMS ROM function:  rom_call ScreenClear   (uses %a0)
        .macro  rom_call name
        movea.l 0xC8,%a0                | AMS ROM call table
        movea.l (\name*4,%a0),%a0
        jsr     (%a0)
        .endm

| Draw a string:  draw_str x, y, label   (with A_REPLACE)
        .macro  draw_str x, y, text
        move.w  #A_REPLACE,-(%sp)
        pea     \text(%pc)
        move.w  #\y,-(%sp)
        move.w  #\x,-(%sp)
        rom_call DrawStr                | DrawStr(x, y, text, A_REPLACE)
        lea     10(%sp),%sp
        .endm

        .text
__main:
        movem.l %d3-%d4/%a2,-(%sp)      | registers we use and must preserve

        rom_call ScreenClear
        move.w  #F_8x10,-(%sp)
        rom_call FontSetSys             | big font for the title
        addq.l  #2,%sp
        draw_str 30, 2, title
        move.w  #F_6x8,-(%sp)
        rom_call FontSetSys
        addq.l  #2,%sp
        draw_str 4, 16, help
        move.w  #A_NORMAL,-(%sp)        | separator: DrawLine(0, 26, 159, 26, A_NORMAL)
        move.w  #26,-(%sp)
        move.w  #159,-(%sp)
        move.w  #26,-(%sp)
        clr.w   -(%sp)
        rom_call DrawLine
        lea     10(%sp),%sp

key_loop:
        rom_call ngetchx                | wait for a key; its code in %d0
        move.w  %d0,%d3                 | keep it (%d3 is preserved by AMS)
        cmpi.w  #KEY_ESC,%d3
        beq     quit

        | --- variables: count++, last_key = code
        lea     count(%pc),%a0
        addq.w  #1,(%a0)
        lea     last_key(%pc),%a0
        move.w  %d3,(%a0)

        | --- history: shift left by one element, add the new code at the end
        lea     history(%pc),%a0
        moveq   #HISTORY-2,%d4
1:      move.w  2(%a0),(%a0)+           | history[i] = history[i+1]
        dbra    %d4,1b                  | (1b = local label "1" backwards)
        move.w  %d3,(%a0)               | history[HISTORY-1] = code

        | --- line 1: sprintf(buffer, "Key #%u: code %u  ($%04X)", count, code, code)
        move.w  %d3,-(%sp)
        move.w  %d3,-(%sp)
        move.w  count(%pc),-(%sp)       | reading PC-relative is allowed
        pea     fmt_key(%pc)
        pea     buffer(%pc)
        rom_call sprintf
        lea     14(%sp),%sp             | 3 words + 2 pointers = 14 bytes
        draw_str 4, 40, buffer

        | --- line 2: the last 5 codes, oldest first
        |     sprintf(buffer, "Last: %u %u %u %u %u", history[0..4])
        lea     history(%pc),%a2
        move.w  8(%a2),-(%sp)           | history[4] = last parameter
        move.w  6(%a2),-(%sp)
        move.w  4(%a2),-(%sp)
        move.w  2(%a2),-(%sp)
        move.w  (%a2),-(%sp)            | history[0] = first value
        pea     fmt_hist(%pc)
        pea     buffer(%pc)
        rom_call sprintf
        lea     18(%sp),%sp             | 5 words + 2 pointers = 18 bytes
        draw_str 4, 56, buffer

        bra     key_loop

quit:
        movem.l (%sp)+,%d3-%d4/%a2
        rts                             | back to AMS (the startup code restores the screen)

| ---------------------------------------------------------------- data
title:  .asciz  "KEY CODES"
help:   .asciz  "Press keys, ESC quits"
fmt_key:
        .asciz  "Key #%u: code %u ($%04X)   "
fmt_hist:
        .asciz  "Last: %u %u %u %u %u      "
        .even
count:  .word   0                       | number of keys pressed
last_key:
        .word   0                       | code of the last key
history:
        .word   0,0,0,0,0               | last 5 codes (oldest first)
buffer: .space  40                      | text built by sprintf
