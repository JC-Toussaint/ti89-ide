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

/* ------------------------------------------------------------ screen
   Modes: SCREEN DIRECT (default), SCREEN BUFFERED (draw in a hidden screen, FLIP shows
   it), SCREEN GRAY4 [BUFFERED] (4 shades of gray: two planes, light and dark).
   Colours: 0 WHITE, 1 LIGHTGRAY, 2 DARKGRAY, 3 BLACK, 4 XOR. In grayscale, bit 0 of the
   colour is the light plane and bit 1 the dark plane; in black and white, every colour
   but WHITE draws black. */
static void *b89_buffer;          /* hidden screen of SCREEN BUFFERED */
#ifdef B89_GRAY                   /* defined by the compiler when the program uses GRAY4 */
static short b89_gray;            /* SCREEN GRAY4 */
static char *b89_gplanes;         /* hidden light + dark planes of SCREEN GRAY4 BUFFERED */
#define B89_LIGHT GrayGetPlane(LIGHT_PLANE)
#define B89_DARK GrayGetPlane(DARK_PLANE)
#else                             /* no grayscale: the grayscale library is not linked */
#define b89_gray 0
#define b89_gplanes ((char *)0)
#define B89_LIGHT ((void *)0)
#define B89_DARK ((void *)0)
#endif
static short b89_color = 3;       /* COLOR: default colour */
static unsigned long b89_next_frame;
static const SCR_RECT b89_clip = {{0, 0, 159, 99}};
static char b89_pbuf[800];        /* text of one PRINT */

B89_FN void b89_init(void)
{
  b89_old_ai1 = GetIntVec(AUTO_INT_1);
  SetIntVec(AUTO_INT_1, b89_tick_handler);
  FontSetSys(F_6x8);
  clrscr();
  randomize();
  b89_next_frame = b89_ticks;
}

/* plane where the drawing goes in grayscale: 0 light, 1 dark */
B89_FN void *b89_plane(short p)
{
  return b89_gplanes ? b89_gplanes + p * LCD_SIZE : p ? B89_DARK : B89_LIGHT;
}

/* the AMS port (target of the drawing and text functions) on another screen, keeping
   the text position */
B89_FN void b89_port(void *addr)
{
  SCR_STATE st;
  SaveScrState(&st);
  st.ScrAddr = addr;
  RestoreScrState(&st);
}

B89_FN void b89_leave_gray(void)
{
#ifdef B89_GRAY
  if (b89_gray) {
    if (b89_gplanes) { free(b89_gplanes); b89_gplanes = NULL; }
    GrayOff();
    b89_gray = 0;
  }
#endif
}

B89_FN void b89_exit(void)
{
  b89_leave_gray();
  if (b89_buffer) {
    PortRestore();
    free(b89_buffer);
    b89_buffer = NULL;
  }
  SetIntVec(AUTO_INT_1, b89_old_ai1);
  GKeyFlush();
}

B89_FN void b89_screen(short gray, short buffered)
{
  if (!gray)
    b89_leave_gray();
  if (b89_buffer && (gray || !buffered)) {
    PortRestore();
    free(b89_buffer);
    b89_buffer = NULL;
  }
  if (gray) {
#ifdef B89_GRAY
    if (!b89_gray) {
      if (!GrayOn())
        return;                                  /* not enough memory: stays in black and white */
      b89_gray = 1;
    }
    if (buffered && !b89_gplanes)
      b89_gplanes = calloc(2, LCD_SIZE);
    else if (!buffered && b89_gplanes) {
      free(b89_gplanes);
      b89_gplanes = NULL;
    }
    memset(b89_plane(0), 0, LCD_SIZE);           /* the grayscale screen starts empty */
    memset(b89_plane(1), 0, LCD_SIZE);
    PortSet(b89_plane(0), 239, 127);
    MoveTo(0, 0);
#endif
  } else if (buffered && !b89_buffer) {
    b89_buffer = malloc(LCD_SIZE);
    if (b89_buffer) {
      memcpy(b89_buffer, LCD_MEM, LCD_SIZE);     /* starts with what is on the screen */
      PortSet(b89_buffer, 239, 127);
    }
  }
}

B89_FN void b89_flip(void)
{
  if (b89_gplanes) {
    memcpy(B89_LIGHT, b89_gplanes, LCD_SIZE);
    memcpy(B89_DARK, b89_gplanes + LCD_SIZE, LCD_SIZE);
  } else if (b89_buffer)
    memcpy(LCD_MEM, b89_buffer, LCD_SIZE);
}

B89_FN void b89_cls(void)
{
  if (b89_gray) {
    memset(b89_plane(1), 0, LCD_SIZE);
    PortSet(b89_plane(0), 239, 127);
  }
  clrscr();
}

/* PRINT: in grayscale the text is written in black, on both planes at the same place */
B89_FN void b89_puts(const char *s)
{
  if (b89_gray) {
    SCR_STATE st;
    SaveScrState(&st);
    st.ScrAddr = b89_plane(1);
    RestoreScrState(&st);
    printf("%s", s);
    st.ScrAddr = b89_plane(0);
    RestoreScrState(&st);
  }
  printf("%s", s);
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

/* ------------------------------------------------------------ drawing (clipped)
   B89_DRAW(colour, statement): runs the statement with 'attr' set for each plane
   (grayscale) or once (black and white). Colour -1: the COLOR in use. */
B89_FN short b89_attr(short color, short plane)
{
  if (color == 4)
    return A_XOR;
  if (plane < 0)
    return color ? A_NORMAL : A_REVERSE;
  return (color >> plane) & 1 ? A_NORMAL : A_REVERSE;
}

#define B89_DRAW(color, STATEMENT) do { \
    short b89_c_ = (color) < 0 ? b89_color : (color), attr; \
    if (b89_gray) { \
      PortSet(b89_plane(1), 239, 127); attr = b89_attr(b89_c_, 1); STATEMENT; \
      PortSet(b89_plane(0), 239, 127); attr = b89_attr(b89_c_, 0); STATEMENT; \
    } else { attr = b89_attr(b89_c_, -1); STATEMENT; } \
  } while (0)

B89_FN void b89_pset(short x, short y, short color)
{
  if (x >= 0 && x < 160 && y >= 0 && y < 100)
    B89_DRAW(color, DrawPix(x, y, attr));
}

B89_FN void b89_line(short x1, short y1, short x2, short y2, short color)
{
  B89_DRAW(color, DrawClipLine(&(WIN_RECT){x1, y1, x2, y2}, &b89_clip, attr));
}

B89_FN void b89_box(short x1, short y1, short x2, short y2, short color, short fill)
{
  short t;
  if (x1 > x2) { t = x1; x1 = x2; x2 = t; }
  if (y1 > y2) { t = y1; y1 = y2; y2 = t; }
  if (fill) {
    if (x2 < 0 || y2 < 0 || x1 > 159 || y1 > 99)
      return;
    if (x1 < 0) x1 = 0;
    if (y1 < 0) y1 = 0;
    if (x2 > 159) x2 = 159;
    if (y2 > 99) y2 = 99;
    B89_DRAW(color, ScrRectFill(&(SCR_RECT){{x1, y1, x2, y2}}, &b89_clip, attr));
  } else
    B89_DRAW(color, DrawClipRect(&(WIN_RECT){x1, y1, x2, y2}, &b89_clip, attr));
}

B89_FN void b89_circle(short x, short y, short r, short color, short fill)
{
  if (r <= 0)
    return;
  if (fill) {                         /* a disc: one horizontal line per row */
    short dy, dx = r;
    long r2 = (long)r * r + r;        /* + r: rounder edges */
    for (dy = 0; dy <= r; dy++) {
      while (dx > 0 && (long)dx * dx + (long)dy * dy > r2)
        dx--;
      B89_DRAW(color, DrawClipLine(&(WIN_RECT){x - dx, y - dy, x + dx, y - dy}, &b89_clip, attr));
      if (dy)
        B89_DRAW(color, DrawClipLine(&(WIN_RECT){x - dx, y + dy, x + dx, y + dy}, &b89_clip, attr));
    }
  } else
    B89_DRAW(color, DrawClipEllipse(x, y, r, r, &b89_clip, attr));
}

B89_FN void b89_locate(short row, short col)
{
  MoveTo((col - 1) * 6, (row - 1) * 8);
}

/* ------------------------------------------------------------ sprites (IMAGE ... END IMAGE)
   An image is cut in columns of 32 pixels; for each column, 4 tables of h rows:
   mask (0 = opaque pixel), light plane, dark plane, black and white. */
typedef struct { short w, h, slabs; const unsigned long *data; } b89img;

B89_FN void b89_sprite(const b89img *im, short x, short y, short xor)
{
  short s, h = im->h;
  const unsigned long *d = im->data;
  if (y >= 100 || y + h <= 0 || x >= 160 || x + im->w <= 0)
    return;
  for (s = 0; s < im->slabs; s++, d += 4 * h, x += 32) {
    if (x >= 160 || x + 32 <= 0)
      continue;
    if (b89_gray) {
      short p;
      for (p = 0; p < 2; p++) {
        void *pl = b89_plane(p);
        if (!xor)
          ClipSprite32(x, y, h, d, pl, SPRT_AND);
        ClipSprite32(x, y, h, d + (1 + p) * h, pl, xor ? SPRT_XOR : SPRT_OR);
      }
    } else {
      void *scr = b89_buffer ? b89_buffer : LCD_MEM;
      if (!xor)
        ClipSprite32(x, y, h, d, scr, SPRT_AND);
      ClipSprite32(x, y, h, d + 3 * h, scr, xor ? SPRT_XOR : SPRT_OR);
    }
  }
}

B89_FN short b89_opaque(const b89img *im, short x, short y)     /* pixel of the image */
{
  return !((im->data[(x >> 5) * 4 * im->h + y] >> (31 - (x & 31))) & 1);
}

/* COLLIDE: do two images, drawn at these places, have an opaque pixel in common? */
B89_FN short b89_collide(const b89img *a, short ax, short ay, const b89img *b, short bx, short by)
{
  short x0 = ax > bx ? ax : bx, y0 = ay > by ? ay : by;
  short x1 = ax + a->w < bx + b->w ? ax + a->w : bx + b->w;
  short y1 = ay + a->h < by + b->h ? ay + a->h : by + b->h;
  short x, y;
  for (y = y0; y < y1; y++)
    for (x = x0; x < x1; x++)
      if (b89_opaque(a, x - ax, y - ay) && b89_opaque(b, x - bx, y - by))
        return 1;
  return 0;
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

/* ------------------------------------------------------------ STRING
   A STRING variable is a char array of fixed size (256 bytes, or STRING * n). Results of
   string expressions go to temporary buffers (b89_tN, 256 bytes) chosen by the compiler.
   Assignments copy, and cut what does not fit. */
#define B89_STRMAX 255

B89_FN char *b89_sset(char *d, short cap, const char *s)    /* cap: size of d with the 0 */
{
  short n = strlen(s);
  if (n > cap - 1)
    n = cap - 1;
  memmove(d, s, n);
  d[n] = 0;
  return d;
}

B89_FN char *b89_sappend(char *d, short cap, const char *s)
{
  short l = strlen(d);
  b89_sset(d + l, cap - l, s);
  return d;
}

B89_FN const char *b89_cat(char *t, const char *a, const char *b)
{
  b89_sset(t, B89_STRMAX + 1, a);
  return b89_sappend(t, B89_STRMAX + 1, b);
}

B89_FN const char *b89_left(char *t, const char *s, long n)
{
  long l = strlen(s);
  if (n < 0) n = 0;
  if (n > l) n = l;
  memmove(t, s, n);
  t[n] = 0;
  return t;
}

B89_FN const char *b89_right(char *t, const char *s, long n)
{
  long l = strlen(s);
  if (n < 0) n = 0;
  if (n > l) n = l;
  return b89_sset(t, B89_STRMAX + 1, s + l - n);
}

B89_FN const char *b89_mid(char *t, const char *s, long start, long n)   /* start: 1 = first */
{
  long l = strlen(s);
  if (start < 1) start = 1;
  if (start > l) { t[0] = 0; return t; }
  return b89_left(t, s + start - 1, n < 0 ? l : n);
}

B89_FN const char *b89_str(char *t, long v)
{
  sprintf(t, "%ld", v);
  return t;
}

B89_FN const char *b89_chr(char *t, long c)
{
  t[0] = (char)c;
  t[1] = 0;
  return t;
}

B89_FN const char *b89_ucase(char *t, const char *s)
{
  char *d = t;
  for (; *s; s++)
    *d++ = (*s >= 'a' && *s <= 'z') ? *s - 32 : *s;
  *d = 0;
  return t;
}

B89_FN const char *b89_lcase(char *t, const char *s)
{
  char *d = t;
  for (; *s; s++)
    *d++ = (*s >= 'A' && *s <= 'Z') ? *s + 32 : *s;
  *d = 0;
  return t;
}

B89_FN long b89_instr(const char *s, const char *f)        /* position (1 = first) or 0 */
{
  const char *p = strstr(s, f);
  return p ? p - s + 1 : 0;
}

/* INPUT: typed on the real screen (also in SCREEN BUFFERED / GRAY4 modes; in grayscale
   the typed text is dark gray) */
B89_FN void b89_input(char *d, short cap)
{
  b89_flip();
  if (b89_gray)
    b89_port(B89_DARK);
  else if (b89_buffer)
    b89_port(LCD_MEM);
  getsn(d, cap);
  putchar('\n');                             /* like PRINT: next line */
  if (b89_gplanes) {                         /* the hidden screen gets what was typed */
    memcpy(b89_gplanes, B89_LIGHT, LCD_SIZE);
    memcpy(b89_gplanes + LCD_SIZE, B89_DARK, LCD_SIZE);
  } else if (b89_buffer)
    memcpy(b89_buffer, LCD_MEM, LCD_SIZE);
  if (b89_gray)
    b89_port(b89_plane(0));
  else if (b89_buffer)
    b89_port(b89_buffer);
}

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

/* number written in a string ("-12.5"): FIXED value (VAL of a decimal, INPUT) */
B89_FN b89fixed b89_fval(const char *s)
{
  short neg = 0;
  unsigned long ip = 0, fr = 0, div = 1;
  while (*s == ' ') s++;
  if (*s == '-') { neg = 1; s++; } else if (*s == '+') s++;
  while (*s >= '0' && *s <= '9') ip = ip * 10 + (*s++ - '0');
  if (*s == '.') {
    s++;
    while (*s >= '0' && *s <= '9' && div < 10000) { fr = fr * 10 + (*s++ - '0'); div *= 10; }
  }
  {
    long v = (long)(ip << 16) + (long)((fr * 65536 + div / 2) / div);
    return neg ? -v : v;
  }
}

B89_FN long b89_input_long(void)
{
  char b[24];
  b89_input(b, sizeof b);
  return atol(b);
}

B89_FN b89fixed b89_input_fixed(void)
{
  char b[24];
  b89_input(b, sizeof b);
  return b89_fval(b);
}

#endif
