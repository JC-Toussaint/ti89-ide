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
static char b89_pbuf[800] __attribute__((unused));   /* text of one PRINT */

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
typedef struct {
  short w, h, slabs;
  const unsigned long *data;
  const unsigned char *b8;    /* images at most 8 pixels wide: the same 4 tables in bytes */
} b89img;

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

/* ------------------------------------------------------------ tile maps
   MAP: draws the part of a 2D INTEGER array (tile numbers; < 0 or too large: nothing)
   seen from the pixel (sx, sy) of the map, with the images of a TILESET (same size). */
/* one row of an 8-pixel tile into a screen row: m = opaque pixels, v = pixels to set */
#define B89_PUT8(row, col, sh, m, v) do { \
    if ((col) >= 0) \
      (row)[col] = ((row)[col] & ~((m) >> (sh))) | ((v) >> (sh)); \
    if ((sh) && (col) + 1 < 30) \
      (row)[(col) + 1] = ((row)[(col) + 1] & ~(unsigned char)((m) << (8 - (sh)))) | \
                         (unsigned char)((v) << (8 - (sh))); \
  } while (0)

#define B89_MAPBUF 3600                 /* bytes: tables of the fast 8-pixel tiles */
static unsigned char b89_mapbuf[B89_MAPBUF];

B89_FN void b89_map(const short *grid, short rows, short cols,
                    const b89img *const *tiles, short ntiles, short sx, short sy, short opaque)
{
  short tw = tiles[0]->w, th = tiles[0]->h;
  short c0 = sx >= 0 ? sx / tw : -((-sx + tw - 1) / tw);
  short r0 = sy >= 0 ? sy / th : -((-sy + th - 1) / th);
  short x0 = c0 * tw - sx, y0 = r0 * th - sy;
  short r, c, x, y;
  unsigned char *scr = b89_buffer ? b89_buffer : LCD_MEM, *pl0 = 0, *pl1 = 0;
  if (b89_gray) {
    pl0 = b89_plane(0);
    pl1 = b89_plane(1);
  }
  if (tw == 8 && tiles[0]->b8 && (long)ntiles * th * 6 <= B89_MAPBUF) {
    /* Fast path, tiles 8 pixels wide: every tile of the map has the same shift inside
       the screen bytes. Each tile row is shifted once into tables of bytes (left and
       right byte of: pixels kept, pixels set in the light plane or in black and white,
       pixels set in the dark plane); then a tile row costs 2 bytes ANDed and ORed per
       plane, without any shift or multiplication. */
    short sh = x0 & 7, tn = ntiles * th, t, k;
    short colbase = x0 >> 3;                     /* -1 or 0 */
    unsigned char *tmh = b89_mapbuf, *tml = tmh + tn, *tlh = tml + tn, *tll = tlh + tn,
                  *tdh = tll + tn, *tdl = tdh + tn;
    for (t = 0; t < ntiles; t++) {
      const unsigned char *d = tiles[t]->b8;
      for (k = 0; k < th; k++) {
        short i = t * th + k;
        unsigned short mw = ~((unsigned short)(unsigned char)~d[k] << (8 - sh));
        unsigned short lw = (unsigned short)d[(b89_gray ? 1 : 3) * th + k] << (8 - sh);
        unsigned short dw = (unsigned short)d[2 * th + k] << (8 - sh);
        tmh[i] = mw >> 8; tml[i] = mw;
        tlh[i] = lw >> 8; tll[i] = lw;
        tdh[i] = dw >> 8; tdl[i] = dw;
      }
    }
    if (opaque && 6L * tn + th <= B89_MAPBUF) {
      /* Tiles without transparent pixels: each screen byte is made from the two tiles
         under it and written without reading the screen, column of bytes by column of
         bytes (a cell without tile, or outside the map, is white). */
      unsigned char *zero = tmh + 6 * tn;          /* th bytes at 0: no tile */
      memset(zero, 0, th);
      for (r = r0, y = y0; y < 100; r++, y += th) {
        short k0, k1, b, pl;
        const short *gr;
        short toffs[22];
        if (r < 0 || r >= rows)
          continue;
        k0 = y < 0 ? -y : 0;
        k1 = y + th > 100 ? 100 - y : th;
        gr = grid + (long)r * cols;
        for (b = 0; b < 22; b++) {                 /* tile numbers of this row */
          short cc = c0 + b;
          t = cc >= 0 && cc < cols ? gr[cc] : -1;
          toffs[b] = t >= 0 && t < ntiles ? t * th : -1;
        }
        for (pl = 0; pl < (b89_gray ? 2 : 1); pl++) {
          const unsigned char *hi = pl ? tdh : tlh, *lo = pl ? tdl : tll;
          unsigned char *base = (pl ? pl1 : (b89_gray ? pl0 : scr)) + (y + k0) * 30;
          short n0 = k1 - k0;
          /* screen byte b: high byte of tile column b - colbase, low byte of the
             column before */
          for (b = 0; b < 20; b++) {
            short jh = b - colbase, n = n0;
            const unsigned char *hp = toffs[jh] >= 0 ? hi + toffs[jh] + k0 : zero;
            unsigned char *o = base + b;
            if (sh) {
              const unsigned char *lp = jh > 0 && toffs[jh - 1] >= 0 ? lo + toffs[jh - 1] + k0 : zero;
              for (; n > 0; n--, o += 30)
                *o = *hp++ | *lp++;
            } else
              for (; n > 0; n--, o += 30)
                *o = *hp++;
          }
        }
      }
      return;
    }
    for (r = r0, y = y0; y < 100; r++, y += th) {
      short k0, k1, n0, j, toff;
      const short *gr;
      unsigned char *row0, *row1;
      if (r < 0 || r >= rows)
        continue;
      k0 = y < 0 ? -y : 0;
      k1 = y + th > 100 ? 100 - y : th;
      n0 = k1 - k0;
      gr = grid + (long)r * cols;
      row0 = (b89_gray ? pl0 : scr) + (y + k0) * 30 + colbase;
      row1 = pl1 + (y + k0) * 30 + colbase;
      for (j = 0, c = c0; c < cols && colbase + j < 20; j++, c++) {
        short col = colbase + j, n = n0;
        unsigned char *p0 = row0 + j, *p1 = row1 + j;
        const unsigned char *qa, *qb, *qe, *qf, *qg, *qh;
        if (c < 0)
          continue;
        t = gr[c];
        if (t < 0 || t >= ntiles)
          continue;
        toff = t * th + k0;
        qa = tmh + toff; qb = tml + toff; qe = tlh + toff; qf = tll + toff; qg = tdh + toff; qh = tdl + toff;
        if (b89_gray) {
          if (!sh)                                   /* aligned: one byte per row */
            for (; n > 0; n--, p0 += 30, p1 += 30) {
              unsigned char mm = *qa++;
              *p0 = (*p0 & mm) | *qe++;
              *p1 = (*p1 & mm) | *qg++;
            }
          else if (col >= 0)                         /* two bytes per row */
            for (; n > 0; n--, p0 += 30, p1 += 30) {
              unsigned char m0 = *qa++, m1 = *qb++;
              p0[0] = (p0[0] & m0) | *qe++;
              p0[1] = (p0[1] & m1) | *qf++;
              p1[0] = (p1[0] & m0) | *qg++;
              p1[1] = (p1[1] & m1) | *qh++;
            }
          else                                       /* left edge: right byte only */
            for (; n > 0; n--, p0 += 30, p1 += 30) {
              unsigned char m1 = *qb++;
              p0[1] = (p0[1] & m1) | *qf++;
              p1[1] = (p1[1] & m1) | *qh++;
            }
        } else {
          if (!sh)
            for (; n > 0; n--, p0 += 30)
              *p0 = (*p0 & *qa++) | *qe++;
          else if (col >= 0)
            for (; n > 0; n--, p0 += 30) {
              p0[0] = (p0[0] & *qa++) | *qe++;
              p0[1] = (p0[1] & *qb++) | *qf++;
            }
          else
            for (; n > 0; n--, p0 += 30)
              p0[1] = (p0[1] & *qb++) | *qf++;
        }
      }
    }
    return;
  }
  for (r = r0, y = y0; y < 100; r++, y += th) {
    if (r < 0 || r >= rows)
      continue;
    for (c = c0, x = x0; x < 160; c++, x += tw) {
      short t;
      const b89img *im;
      if (c < 0 || c >= cols)
        continue;
      t = grid[(long)r * cols + c];
      if (t < 0 || t >= ntiles)
        continue;
      im = tiles[t];
      if (im->b8) {                      /* 8-pixel tile: bytes written directly */
        const unsigned char *d = im->b8;
        short h = im->h, k, sh = x & 7, col = x >> 3;
        for (k = 0; k < h; k++) {
          short yy = y + k;
          unsigned char m;
          if (yy < 0 || yy >= 100)
            continue;
          m = ~d[k];
          if (b89_gray) {
            B89_PUT8(pl0 + yy * 30, col, sh, m, d[h + k]);
            B89_PUT8(pl1 + yy * 30, col, sh, m, d[2 * h + k]);
          } else
            B89_PUT8(scr + yy * 30, col, sh, m, d[3 * h + k]);
        }
      } else
        b89_sprite(im, x, y, 0);
    }
  }
}

/* MAPROW: fills a row of the map from a text: 0-9 and a-z (10-35) are tile numbers,
   any other character (. or space) is -1 (empty) */
B89_FN void b89_maprow(short *grid, short rows, short cols, long row, const char *s)
{
  short c;
  if (row < 0 || row >= rows)
    return;
  for (c = 0; c < cols && s[c]; c++) {
    char ch = s[c];
    grid[row * cols + c] = ch >= '0' && ch <= '9' ? ch - '0'
                         : ch >= 'a' && ch <= 'z' ? ch - 'a' + 10
                         : ch >= 'A' && ch <= 'Z' ? ch - 'A' + 10 : -1;
  }
}

/* ------------------------------------------------------------ sound
   The TI-89 has no speaker: the sound is a square wave on the two wires of the 2.5 mm
   link port (I/O), heard with earphones plugged into it through an adapter.
   $60000C bit 6 disables the link controller, then $60000E bits 0-1 drive the wires.
   The half-period is a busy loop counted in CPU cycles (12 MHz). */
#define B89_LINKCTL (*(volatile unsigned char *)0x60000C)
#define B89_LINKWIRES (*(volatile unsigned char *)0x60000E)

#define B89_TONE_OVERHEAD 60             /* cycles of a half-period outside b89_spin */

B89_FN void b89_spin(unsigned short n)         /* about 10 cycles per turn */
{
  if (n)
    asm volatile ("subq.w #1,%0\n1:\tdbra %0,1b" : "+d" (n));
}

B89_FN void b89_tone(long freq, long ms)
{
  unsigned long periods;
  unsigned char ctl;
  unsigned short n, sr;
  if (ms <= 0)
    return;
  if (freq < 20 || freq > 20000) {               /* silence */
    b89_delay(ms);
    return;
  }
  /* interrupts are off during the note (exact pitch): the length is counted in periods,
     and the 256 Hz timer is moved on by the same time afterwards */
  n = (unsigned short)((6000000L / freq - B89_TONE_OVERHEAD) / 10);   /* half-period */
  periods = freq * ms / 1000;
  ctl = B89_LINKCTL;
  B89_LINKCTL = ctl | 0x40;                      /* direct control of the wires */
  if (b89_gray) {
    /* grayscale needs its interrupt: timed by the 256 Hz counter, and the loop is
       shortened by the time the interrupts take (pitch within a few %) */
    unsigned long end = b89_ticks + ms * 256 / 1000;
    n = n * 5 / 6;                               /* the grayscale interrupt takes ~1/6 */
    while ((long)(b89_ticks - end) < 0) {
      B89_LINKWIRES = 3;
      b89_spin(n);
      B89_LINKWIRES = 0;
      b89_spin(n);
    }
  } else {
    sr = OSSetSR(0x0700);
    for (; periods; periods--) {
      B89_LINKWIRES = 3;
      b89_spin(n);
      B89_LINKWIRES = 0;
      b89_spin(n);
    }
    OSSetSR(sr);
    b89_ticks += ms * 256 / 1000;
  }
  B89_LINKWIRES = 0;
  B89_LINKCTL = ctl;
  b89_next_frame = b89_ticks;
}

/* PLAY "T120 O4 L4 C D E8 F#8 G2. R4 > C": notes A-G (# or + sharp, - flat) with an
   optional length (1 whole, 2, 4 quarter, 8, 16, 32) and a dot (x 1.5); R or P rest;
   O octave (0-7), > and < octave up/down, L default length, T tempo (quarter notes per
   minute). */
B89_FN void b89_play(const char *s)
{
  /* octave 4 in 1/10 Hz: C C# D D# E F F# G G# A A# B */
  static const unsigned short f4[12] = {2616, 2772, 2937, 3111, 3296, 3492,
                                        3700, 3920, 4153, 4400, 4662, 4939};
  static const signed char pos[7] = {9, 11, 0, 2, 4, 5, 7};    /* A B C D E F G */
  short octave = 4, len = 4, tempo = 120;
  while (*s) {
    char c = *s++;
    short num = 0, has = 0, note = -1, dots = 0;
    if (c >= 'a' && c <= 'z')
      c -= 32;
    if (c >= 'A' && c <= 'G') {
      note = pos[c - 'A'];
      if (*s == '#' || *s == '+') { note++; s++; }
      else if (*s == '-') { note--; s++; }
    } else if (c != 'R' && c != 'P' && c != 'O' && c != 'L' && c != 'T' && c != '>' && c != '<')
      continue;                                  /* spaces and unknown characters */
    while (*s >= '0' && *s <= '9') { num = num * 10 + (*s++ - '0'); has = 1; }
    while (*s == '.') { dots++; s++; }
    if (c == 'O') { if (has && num <= 7) octave = num; continue; }
    if (c == '>') { if (octave < 7) octave++; continue; }
    if (c == '<') { if (octave > 0) octave--; continue; }
    if (c == 'L') { if (has && num >= 1 && num <= 64) len = num; continue; }
    if (c == 'T') { if (has && num >= 20 && num <= 400) tempo = num; continue; }
    {
      short l = has && num >= 1 && num <= 64 ? num : len;
      long ms = 240000L / ((long)tempo * l);     /* whole note = 4 beats */
      if (dots) ms += ms / 2;
      if (c == 'R' || c == 'P')                  /* rest */
        b89_delay(ms);
      else {
        short o = octave;
        long f;
        if (note < 0) { note += 12; o--; }
        if (note > 11) { note -= 12; o++; }
        f = f4[note];
        f = o >= 4 ? f << (o - 4) : f >> (4 - o);
        b89_tone((f + 5) / 10, ms - ms / 8);    /* a short silence between notes */
        b89_delay(ms / 8);
      }
    }
  }
}

/* ------------------------------------------------------------ saving (SAVE / LOAD)
   SAVE writes the bytes of the listed variables into a calculator variable of type OTH
   (shown as "B89" in the VAR-LINK screen) and archives it in flash memory, where it stays
   even after a RAM reset. LOAD reads it back only if the size matches (a save made by
   another version of the program, with other variables, is ignored).
   Layout of the variable: size (2 bytes), the data, 0 "B89" 0, OTH tag ($F8). */
#define B89_OTH_TAG 0xF8

B89_FN void b89_symname(char *buf, const char *name)   /* "\0name\0" -> SYM_STR at its end */
{
  short i;
  buf[0] = 0;
  for (i = 0; name[i] && i < 8; i++)
    buf[i + 1] = name[i] >= 'A' && name[i] <= 'Z' ? name[i] + 32 : name[i];
  buf[i + 1] = 0;
}
#define B89_SYM(buf) ((SYM_STR)((buf) + 1 + strlen((buf) + 1)))

B89_FN void b89_kill(const char *name)
{
  char buf[12];
  SYM_ENTRY *e;
  b89_symname(buf, name);
  e = SymFindPtr(B89_SYM(buf), 0);
  if (!e)
    return;
  if (e->flags.flags_n & SF_ARCHIVED)
    EM_moveSymFromExtMem(B89_SYM(buf), HS_NULL);
  SymDel(B89_SYM(buf));
}

B89_FN short b89_exists(const char *name)
{
  char buf[12];
  b89_symname(buf, name);
  return SymFindPtr(B89_SYM(buf), 0) != NULL;
}

B89_FN short b89_save(const char *name, const void *const *ptrs, const short *sizes, short n)
{
  char buf[12];
  long total = 0;
  short i;
  HSym hs;
  HANDLE h;
  unsigned char *p;
  for (i = 0; i < n; i++)
    total += sizes[i];
  if (total + 8 > 65000L)
    return 0;
  b89_kill(name);
  b89_symname(buf, name);
  hs = SymAdd(B89_SYM(buf));
  if (!hs.folder)
    return 0;
  h = HeapAlloc(total + 8);
  if (!h) {
    SymDel(B89_SYM(buf));
    return 0;
  }
  DerefSym(hs)->handle = h;
  p = HeapDeref(h);
  *(unsigned short *)p = total + 6;
  p += 2;
  for (i = 0; i < n; i++) {
    memcpy(p, ptrs[i], sizes[i]);
    p += sizes[i];
  }
  p[0] = 0; p[1] = 'B'; p[2] = '8'; p[3] = '9'; p[4] = 0; p[5] = B89_OTH_TAG;
  EM_moveSymToExtMem(B89_SYM(buf), HS_NULL);   /* archive (stays in RAM if it fails) */
  return 1;
}

B89_FN short b89_load(const char *name, void *const *ptrs, const short *sizes, short n)
{
  char buf[12];
  long total = 0;
  short i;
  SYM_ENTRY *e;
  const unsigned char *p;
  for (i = 0; i < n; i++)
    total += sizes[i];
  b89_symname(buf, name);
  e = SymFindPtr(B89_SYM(buf), 0);
  if (!e || !e->handle)
    return 0;
  p = HeapDeref(e->handle);
  if (*(const unsigned short *)p != total + 6 || p[2 + total + 1] != 'B' ||
      p[2 + total + 2] != '8' || p[2 + total + 3] != '9')
    return 0;                                  /* not a save of these variables */
  p += 2;
  for (i = 0; i < n; i++) {
    memcpy(ptrs[i], p, sizes[i]);
    p += sizes[i];
  }
  return 1;
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
