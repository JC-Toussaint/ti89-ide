; Bounce - example 68000 assembly program for the TI-89 Titanium (A68k syntax)
;
; A ball bounces around the screen. ESC quits.
;
; Techniques shown:
;   - drawing directly in the LCD memory ($4C00, 30 bytes per row of 240 pixels,
;     160 of them visible), with an 8x8 sprite drawn in XOR mode: drawing it
;     twice at the same place erases it
;   - computing a pixel address with shifts: address = $4C00 + y*30 + x/8
;   - calling AMS functions (ROM_CALL) and reading their result in d0
;   - loops (dbra), comparisons, subroutines (bsr / rts)
;
; Registers used in the main loop:
;   d4 = x (0..152)   d5 = y (0..92)   d6 = dx (+1/-1)   d7 = dy (+1/-1)

        include "os.h"                  ; AMS ROM call numbers and ROM_CALL macro

        xdef    _nostub                 ; standalone program: starts at the first instruction
        xdef    _ti89                   ; target model (TI-89 / TI-89 Titanium)

LCD_SIZE equ    3840                    ; screen memory size: 240x128 pixels / 8
KEY_ESC equ     264                     ; key code returned by ngetchx for ESC
MAX_X   equ     160-8                   ; right-most x of the 8x8 ball
MAX_Y   equ     100-8                   ; lowest y of the ball

start:
        movem.l d3-d7/a2-a6,-(sp)       ; registers AMS expects to be preserved

        ; --- save the screen on the stack (3840 bytes) to restore it at the end
        lea     -LCD_SIZE(sp),sp
        movea.l sp,a1
        lea     LCD_MEM,a0
        move.w  #LCD_SIZE/4-1,d0
\save:  move.l  (a0)+,(a1)+
        dbra    d0,\save

        ROM_CALL ScreenClear            ; clear the screen
        bsr     draw_frame              ; draw a border

        moveq   #20,d4                  ; x = 20
        moveq   #10,d5                  ; y = 10
        moveq   #1,d6                   ; dx = +1
        moveq   #1,d7                   ; dy = +1

loop:
        bsr     draw_ball               ; draw (XOR)
        bsr     delay
        bsr     draw_ball               ; erase: the same XOR again

        ; --- move and bounce on the edges
        add.w   d6,d4                   ; x += dx
        beq.s   \flipx                  ; reached x = 0
        cmpi.w  #MAX_X,d4
        blt.s   \okx                    ; still inside
\flipx: neg.w   d6                      ; dx = -dx
\okx:
        add.w   d7,d5                   ; y += dy
        beq.s   \flipy
        cmpi.w  #MAX_Y,d5
        blt.s   \oky
\flipy: neg.w   d7
\oky:

        ; --- keyboard: kbhit() returns non-zero if a key is waiting
        ROM_CALL kbhit
        tst.w   d0
        beq.s   loop                    ; no key: next frame
        ROM_CALL ngetchx                ; read the key code in d0
        cmpi.w  #KEY_ESC,d0
        bne.s   loop                    ; not ESC: keep bouncing

        ; --- restore the screen and return to AMS
        movea.l sp,a1
        lea     LCD_MEM,a0
        move.w  #LCD_SIZE/4-1,d0
\rest:  move.l  (a1)+,(a0)+
        dbra    d0,\rest
        lea     LCD_SIZE(sp),sp
        movem.l (sp)+,d3-d7/a2-a6
        rts

;------------------------------------------------------------------------------
; draw_ball: XOR the 8x8 ball at (d4, d5) directly in the LCD memory.
; The ball can start in the middle of a byte: each sprite row is shifted
; right by (x mod 8) into a 16-bit word, then written as two bytes (a word
; access at an odd address would crash a real 68000).
; Uses d0-d3/a0-a1.
;------------------------------------------------------------------------------
draw_ball:
        move.w  d5,d0                   ; d0 = y
        mulu.w  #30,d0                  ; d0 = y * 30 (bytes per row)
        move.w  d4,d1
        lsr.w   #3,d1                   ; d1 = x / 8
        add.w   d1,d0
        lea     LCD_MEM,a0
        adda.w  d0,a0                   ; a0 = address of the top-left byte
        move.w  d4,d2
        andi.w  #7,d2                   ; d2 = x mod 8 (shift)
        lea     ball(pc),a1
        moveq   #8-1,d3                 ; 8 rows
\row:   moveq   #0,d0
        move.b  (a1)+,d0                ; sprite row
        lsl.w   #8,d0                   ; to the high byte...
        lsr.w   d2,d0                   ; ...then shift right by x mod 8
        move.w  d0,d1
        lsr.w   #8,d1
        eor.b   d1,(a0)                 ; left byte
        eor.b   d0,1(a0)                ; right byte
        lea     30(a0),a0               ; next screen row
        dbra    d3,\row
        rts

;------------------------------------------------------------------------------
; draw_frame: a rectangle around the visible screen, with AMS DrawLine.
; DrawLine(x0, y0, x1, y1, attr): parameters pushed from the last to the first.
;------------------------------------------------------------------------------
draw_frame:
        lea     lines(pc),a2
        moveq   #4-1,d3                 ; 4 lines
\line:  move.w  #1,-(sp)                ; attr = A_NORMAL
        move.w  6(a2),-(sp)             ; y1
        move.w  4(a2),-(sp)             ; x1
        move.w  2(a2),-(sp)             ; y0
        move.w  (a2),-(sp)              ; x0
        ROM_CALL DrawLine
        lea     10(sp),sp               ; remove the parameters
        addq.l  #8,a2
        dbra    d3,\line
        rts

;------------------------------------------------------------------------------
; delay: busy loop (about 1/60 s on the 12 MHz CPU)
;------------------------------------------------------------------------------
delay:
        move.w  #20000,d0
\wait:  dbra    d0,\wait
        rts

;------------------------------------------------------------------------------
; data
;------------------------------------------------------------------------------
ball:   dc.b    %00111100
        dc.b    %01111110
        dc.b    %11011111
        dc.b    %10111111
        dc.b    %11111111
        dc.b    %11111111
        dc.b    %01111110
        dc.b    %00111100

        even
lines:  dc.w    0,0,159,0               ; top
        dc.w    0,99,159,99             ; bottom
        dc.w    0,0,0,99                ; left
        dc.w    159,0,159,99            ; right

        end
