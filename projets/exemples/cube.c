// Rotating 3D cube - example for the TI-89 Titanium (GCC4TI)
//
//   F1    : hidden faces removed / wireframe (all 12 edges)
//   ENTER : pause / resume (rotation and timer)
//   F2    : reset the timer
//   ESC   : quit
//
// The top line shows the timer (minutes:seconds.tenths) and the number of
// frames drawn per second.
//
// Techniques shown:
//   - fixed-point arithmetic (no floating point): sines in 1/16384 units,
//     integer 16x16->32 bit multiplications, which the 68000 does in one instruction
//   - 3D rotation matrix, perspective projection
//   - hidden faces: back-face culling with the sign of a 2D cross product
//   - double buffering: draw in a hidden screen, then copy it to the LCD
//   - a 256 Hz timer driven by auto-interrupt 1

#define USE_TI89
#define SAVE_SCREEN

#include <tigcclib.h>

#define SIZE    22              // half the cube edge (screen units, before perspective)
#define FIX     64              // the vertices are kept in 1/64 units (precision)
#define DIST    150             // distance from the eye to the centre of the cube
#define FOV     150             // projection factor (zoom)
#define CX      80              // centre of the drawing on the screen
#define CY      50

// ---------------------------------------------------------------- sine table
// sin(i * 2pi / 256) * 16384 for i = 0..64 (a quarter of a turn); the rest by symmetry.
static const short quarter_sin[65] = {
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

// angle: 256 units per turn
static short qsin(unsigned char a)
{
  if (a < 64)  return  quarter_sin[a];
  if (a < 128) return  quarter_sin[128 - a];
  if (a < 192) return -quarter_sin[a - 128];
  return -quarter_sin[256 - a];
}

static short qcos(unsigned char a)
{
  return qsin((unsigned char)(a + 64));
}

// product of two numbers in 1/16384 units
static short qmul(short a, short b)
{
  return (short)(((long)a * b) >> 14);
}

// ---------------------------------------------------------------- the cube
// Vertex i: bit 0 = x, bit 1 = y, bit 2 = z (0 = -SIZE, 1 = +SIZE).
// Each face lists its 4 vertices counterclockwise seen from outside the cube.
static const unsigned char faces[6][4] = {
  {0, 4, 6, 2},   // x-
  {1, 3, 7, 5},   // x+
  {0, 1, 5, 4},   // y-
  {2, 6, 7, 3},   // y+
  {0, 2, 3, 1},   // z-
  {4, 5, 7, 6},   // z+
};

static short sx[8], sy[8];      // projected vertices (screen pixels)

// Rotates the 8 vertices (angles ax, ay, az) and projects them on the screen.
static void transform(unsigned char ax, unsigned char ay, unsigned char az)
{
  short cxa = qcos(ax), sxa = qsin(ax);
  short cya = qcos(ay), sya = qsin(ay);
  short cza = qcos(az), sza = qsin(az);
  // rotation matrix R = Rz * Ry * Rx, in 1/16384 units
  short m00 = qmul(cya, cza);
  short m01 = qmul(qmul(sxa, sya), cza) - qmul(cxa, sza);
  short m02 = qmul(qmul(cxa, sya), cza) + qmul(sxa, sza);
  short m10 = qmul(cya, sza);
  short m11 = qmul(qmul(sxa, sya), sza) + qmul(cxa, cza);
  short m12 = qmul(qmul(cxa, sya), sza) - qmul(sxa, cza);
  short m20 = -sya;
  short m21 = qmul(sxa, cya);
  short m22 = qmul(cxa, cya);

  for (short i = 0; i < 8; i++) {
    short x = (i & 1) ? SIZE * FIX : -SIZE * FIX;
    short y = (i & 2) ? SIZE * FIX : -SIZE * FIX;
    short z = (i & 4) ? SIZE * FIX : -SIZE * FIX;
    short rx = (short)(((long)m00 * x + (long)m01 * y + (long)m02 * z) >> 14);
    short ry = (short)(((long)m10 * x + (long)m11 * y + (long)m12 * z) >> 14);
    short rz = (short)(((long)m20 * x + (long)m21 * y + (long)m22 * z) >> 14);
    // perspective: the eye is at z = -DIST, looking towards +z
    short depth = rz + DIST * FIX;
    sx[i] = CX + (short)((long)rx * FOV / depth);
    sy[i] = CY - (short)((long)ry * FOV / depth);   // screen y goes down
  }
}

static void line(short a, short b)
{
  DrawLine(sx[a], sy[a], sx[b], sy[b], A_NORMAL);
}

static void draw_wireframe(void)
{
  // the 12 edges join the vertices that differ by exactly one bit
  for (short i = 0; i < 8; i++)
    for (short bit = 1; bit < 8; bit <<= 1)
      if (!(i & bit))
        line(i, i | bit);
}

static void draw_hidden_faces(void)
{
  for (short f = 0; f < 6; f++) {
    const unsigned char *v = faces[f];
    // 2D cross product of two sides of the projected face: its sign tells whether
    // the face turns its front (visible) or its back (hidden) towards the eye.
    long cross = (long)(sx[v[1]] - sx[v[0]]) * (sy[v[2]] - sy[v[0]])
               - (long)(sy[v[1]] - sy[v[0]]) * (sx[v[2]] - sx[v[0]]);
    if (cross < 0)
      continue;
    line(v[0], v[1]);
    line(v[1], v[2]);
    line(v[2], v[3]);
    line(v[3], v[0]);
  }
}

// ---------------------------------------------------------------- timer
// Auto-interrupt 1 fires 256 times per second. We replace the AMS handler
// (which scans the keyboard) by ours, which just counts.
static volatile unsigned long ticks;

DEFINE_INT_HANDLER(tick_handler)
{
  ticks++;
}

// ---------------------------------------------------------------- main
void _main(void)
{
  void *screen = malloc(LCD_SIZE);
  if (!screen)
    return;

  INT_HANDLER old_int1 = GetIntVec(AUTO_INT_1);
  INT_HANDLER old_int5 = GetIntVec(AUTO_INT_5);
  SetIntVec(AUTO_INT_1, tick_handler);     // our 256 Hz counter
  SetIntVec(AUTO_INT_5, DUMMY_HANDLER);    // AMS timer (auto power-off...) paused
  PortSet(screen, 239, 127);               // drawing functions draw into 'screen'
  FontSetSys(F_4x6);

  unsigned char ax = 0, ay = 0, az = 0;    // rotation angles (256 units per turn)
  short hidden = 1;                        // 1: hidden faces removed
  short paused = 0;
  unsigned long elapsed = 0;               // timer, in 1/256 s
  unsigned long last = ticks;
  unsigned long fps_start = ticks;
  short frames = 0, fps = 0;
  short f1_was = 0, f2_was = 0, enter_was = 0;
  char buf[40];

  // wait until the keys used to start the program are released
  while (_keytest(RR_ENTER) || _keytest(RR_ESC))
    ;

  for (;;) {
    // ---- keys (each press is taken once)
    short f1 = _keytest(RR_F1), f2 = _keytest(RR_F2), enter = _keytest(RR_ENTER);
    if (f1 && !f1_was) hidden = !hidden;
    if (f2 && !f2_was) elapsed = 0;
    if (enter && !enter_was) paused = !paused;
    f1_was = f1; f2_was = f2; enter_was = enter;
    if (_keytest(RR_ESC))
      break;

    // ---- time
    unsigned long now = ticks;
    if (!paused)
      elapsed += now - last;
    last = now;
    if (now - fps_start >= 256) {          // frames drawn during the last second
      fps = frames;
      frames = 0;
      fps_start = now;
    }

    // ---- drawing
    memset(screen, 0, LCD_SIZE);
    transform(ax, ay, az);
    if (hidden)
      draw_hidden_faces();
    else
      draw_wireframe();

    unsigned long tenths = elapsed * 10 / 256;
    sprintf(buf, "%02lu:%02lu.%lu", tenths / 600, tenths / 10 % 60, tenths % 10);
    DrawStr(0, 0, buf, A_NORMAL);
    sprintf(buf, "%d fps", fps);
    DrawStr(160 - DrawStrWidth(buf, F_4x6), 0, buf, A_NORMAL);
    DrawStr(0, 94, hidden ? "F1:wireframe" : "F1:hidden faces", A_NORMAL);
    DrawStr(70, 94, paused ? "ENTER:go F2:0 ESC" : "ENTER:pause F2:0 ESC", A_NORMAL);
    if (paused)
      DrawStr(66, 0, "PAUSE", A_NORMAL);
    memcpy(LCD_MEM, screen, LCD_SIZE);     // hidden screen -> real screen
    frames++;

    // ---- rotation: a different speed around each axis
    if (!paused) {
      ax += 2;
      ay += 3;
      az += 1;
    }
  }

  PortRestore();
  SetIntVec(AUTO_INT_1, old_int1);
  SetIntVec(AUTO_INT_5, old_int5);
  free(screen);
  GKeyFlush();                             // forget keys pressed in the program
}
