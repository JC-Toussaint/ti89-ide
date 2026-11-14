/* Basic89 runtime: included by the C code generated from a .b89 program.
   Everything is static: only what the program uses ends up in the .89z. */
#ifndef B89RT_H
#define B89RT_H

#define USE_TI89
#define SAVE_SCREEN
#include <tigcclib.h>

/* a program uses only some of these functions: no "defined but not used" warnings */
#define B89_FN static __attribute__((unused))

/* ------------------------------------------------------------ timer (256 Hz) */
static volatile unsigned long b89_ticks;
static INT_HANDLER b89_old_ai1;

/* Auto-interrupt 1 counts, then calls the AMS handler (which reads the keyboard):
   GETKEY / WAITKEY keep working. */
DEFINE_INT_HANDLER(b89_tick_handler)
{
  b89_ticks++;
  ExecuteHandler(b89_old_ai1);
}

/* ------------------------------------------------------------ screen */
static void *b89_buffer;          /* hidden screen of SCREEN BUFFERED */
static unsigned long b89_next_frame;
static const SCR_RECT b89_clip = {{0, 0, 159, 99}};

B89_FN void b89_init(void)
{
  b89_old_ai1 = GetIntVec(AUTO_INT_1);
  SetIntVec(AUTO_INT_1, b89_tick_handler);
  FontSetSys(F_6x8);
  clrscr();
  randomize();
  b89_next_frame = b89_ticks;
}

B89_FN void b89_exit(void)
{
  if (b89_buffer) {
    PortRestore();
    free(b89_buffer);
    b89_buffer = NULL;
  }
  SetIntVec(AUTO_INT_1, b89_old_ai1);
  GKeyFlush();
}

B89_FN void b89_screen(short buffered)
{
  if (buffered && !b89_buffer) {
    b89_buffer = calloc(1, LCD_SIZE);
    if (b89_buffer)
      PortSet(b89_buffer, 239, 127);
  } else if (!buffered && b89_buffer) {
    PortRestore();
    free(b89_buffer);
    b89_buffer = NULL;
  }
}

B89_FN void b89_flip(void)
{
  if (b89_buffer)
    memcpy(LCD_MEM, b89_buffer, LCD_SIZE);
}

/* WAITKEY / GETKEY: show the hidden screen first (SCREEN BUFFERED), otherwise the
   program would wait in front of an empty screen */
B89_FN short b89_getkey(void)
{
  b89_flip();
  return ngetchx();
}

B89_FN void b89_waitframe(short fps)
{
  if (fps < 1)
    fps = 1;
  b89_next_frame += 256 / fps;
  if ((long)(b89_ticks - b89_next_frame) > 256)   /* far behind: do not try to catch up */
    b89_next_frame = b89_ticks;
  while ((long)(b89_ticks - b89_next_frame) < 0)
    ;
}

B89_FN void b89_delay(long ms)
{
  unsigned long end = b89_ticks + ms * 256 / 1000;
  while ((long)(b89_ticks - end) < 0)
    ;
}

/* ------------------------------------------------------------ drawing (clipped) */
B89_FN void b89_pset(short x, short y, short color)
{
  if (x >= 0 && x < 160 && y >= 0 && y < 100)
    DrawPix(x, y, color);
}

B89_FN void b89_line(short x1, short y1, short x2, short y2, short color)
{
  DrawClipLine(&(WIN_RECT){x1, y1, x2, y2}, &b89_clip, color);
}

B89_FN void b89_box(short x1, short y1, short x2, short y2, short color, short fill)
{
  short t;
  if (x1 > x2) { t = x1; x1 = x2; x2 = t; }
  if (y1 > y2) { t = y1; y1 = y2; y2 = t; }
  if (fill) {
    if (x2 < 0 || y2 < 0 || x1 > 159 || y1 > 99)
      return;
    ScrRectFill(&(SCR_RECT){{x1 < 0 ? 0 : x1, y1 < 0 ? 0 : y1,
                             x2 > 159 ? 159 : x2, y2 > 99 ? 99 : y2}}, &b89_clip,
                color == A_XOR ? A_XOR : color == A_REVERSE ? A_REVERSE : A_NORMAL);
  } else
    DrawClipRect(&(WIN_RECT){x1, y1, x2, y2}, &b89_clip, color);
}

B89_FN void b89_circle(short x, short y, short r, short color)
{
  if (r > 0)
    DrawClipEllipse(x, y, r, r, &b89_clip, color);
}

B89_FN void b89_locate(short row, short col)
{
  MoveTo((col - 1) * 6, (row - 1) * 8);
}

/* ------------------------------------------------------------ math */
static const short b89_qsin[65] = {
      0,   402,   804,  1205,  1606,  2006,  2404,  2801,
   3196,  3590,  3981,  4370,  4756,  5139,  5520,  5897,
   6270,  6639,  7005,  7366,  7723,  8076,  8423,  8765,
   9102,  9434,  9760, 10080, 10394, 10702, 11003, 11297,
  11585, 11866, 12140, 12406, 12665, 12916, 13160, 13395,
  13623, 13842, 14053, 14256, 14449, 14635, 14811, 14978,
  15137, 15286, 15426, 15557, 15679, 15791, 15893, 15986,
  16069, 16143, 16207, 16261, 16305, 16340, 16364, 16379,
  16384,
};

/* sine of an angle in 1/256 of a turn, result in 1/16384 */
B89_FN short b89_isin(short angle)
{
  unsigned char a = (unsigned char)angle;
  if (a < 64)  return  b89_qsin[a];
  if (a < 128) return  b89_qsin[128 - a];
  if (a < 192) return -b89_qsin[a - 128];
  return -b89_qsin[256 - a];
}

B89_FN short b89_icos(short angle)
{
  return b89_isin(angle + 64);
}

B89_FN long b89_abs(long x) { return x < 0 ? -x : x; }
B89_FN long b89_min(long a, long b) { return a < b ? a : b; }
B89_FN long b89_max(long a, long b) { return a > b ? a : b; }
B89_FN short b89_rnd(short n) { return n > 0 ? random(n) : 0; }

/* ------------------------------------------------------------ FIXED (16.16 fixed point)
   A FIXED is a long holding value * 65536: range -32768 .. 32767.99998, step 1/65536.
   The 68000 multiplies 16 x 16 bits in one instruction: the products are built from
   16-bit halves, without 64-bit arithmetic. */
typedef long b89fixed;

B89_FN b89fixed b89_fmul(b89fixed a, b89fixed b)
{
  short neg = 0;
  unsigned long ua, ub, r;
  unsigned short ah, al, bh, bl;
  if (a < 0) { ua = -a; neg = 1; } else ua = a;
  if (b < 0) { ub = -b; neg ^= 1; } else ub = b;
  ah = ua >> 16; al = ua; bh = ub >> 16; bl = ub;
  r = (((unsigned long)ah * bh) << 16) + (unsigned long)ah * bl + (unsigned long)al * bh
      + (((unsigned long)al * bl) >> 16);
  return neg ? -(long)r : (long)r;
}

B89_FN b89fixed b89_fdiv(b89fixed a, b89fixed b)
{
  short neg = 0, i;
  unsigned long ua, ub, q, r;
  if (a < 0) { ua = -a; neg = 1; } else ua = a;
  if (b < 0) { ub = -b; neg ^= 1; } else ub = b;
  if (ub == 0)                                /* division by 0: largest value */
    return neg ? -0x7FFFFFFFL : 0x7FFFFFFFL;
  q = ua / ub;
  r = ua % ub;
  for (i = 0; i < 16; i++) {                  /* 16 more bits of quotient */
    r <<= 1;
    q <<= 1;
    if (r >= ub) { r -= ub; q |= 1; }
  }
  return neg ? -(long)q : (long)q;
}

B89_FN b89fixed b89_fsqrt(b89fixed a)
{
  unsigned long x = a, root = 0, rem = 0, test;
  short i;
  if (a <= 0)
    return 0;
  for (i = 0; i < 24; i++) {                  /* 2 bits of x per step: 16.16 -> 16.16 */
    rem = (rem << 2) | (x >> 30);
    x <<= 2;
    root <<= 1;
    test = (root << 1) + 1;
    if (rem >= test) { rem -= test; root++; }
  }
  return root;
}

/* SIN / COS of an angle in radians (FIXED): table of 256 steps per turn, with a linear
   interpolation between two steps (error below 0.0002) */
B89_FN b89fixed b89_fsin_steps(b89fixed t)       /* t: angle in steps (16.16) */
{
  short i = (short)(t >> 16);
  long f = t & 0xFFFF;
  long s0 = b89_isin(i), s1 = b89_isin(i + 1);   /* 1/16384 */
  return (s0 << 2) + (((s1 - s0) * f) >> 14);
}

B89_FN b89fixed b89_fsin(b89fixed a)
{
  return b89_fsin_steps(b89_fmul(a, 2670177L));  /* 256 / (2 pi) = 40.7437 */
}

B89_FN b89fixed b89_fcos(b89fixed a)
{
  return b89_fsin_steps(b89_fmul(a, 2670177L) + (64L << 16));
}

/* text of a FIXED for PRINT: up to 4 decimals, without useless zeros */
B89_FN const char *b89_fstr(b89fixed v)
{
  static char bufs[4][16];
  static short k;
  char *b = bufs[k = (k + 1) & 3], *e;
  unsigned long u = v < 0 ? -v : v;
  unsigned long ip = u >> 16;
  unsigned long fr = ((u & 0xFFFF) * 10000 + 32768) >> 16;
  if (fr >= 10000) { ip++; fr -= 10000; }
  sprintf(b, "%s%lu.%04lu", v < 0 && (ip || fr) ? "-" : "", ip, fr);
  e = b + strlen(b) - 1;
  while (*e == '0') *e-- = 0;
  if (*e == '.') *e = 0;
  return b;
}

#endif
