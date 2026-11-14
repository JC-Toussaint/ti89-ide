// DCA (anti-aircraft defence) - example game for the TI-89 Titanium (GCC4TI)
//
// Aim the gun with LEFT / RIGHT and fire with UP. Shoot down the planes before
// their bombs hit you; bombs can be shot down too. You have 3 guns.
//   ENTER : start / play again        ESC : quit
//
// Techniques shown:
//   - fixed-point positions and speeds (1/16 pixel), aiming with a sine table
//   - several kinds of objects at once (planes, bombs, shells, explosions)
//   - sprites that enter and leave the screen (ClipSprite16), mirrored at startup
//   - double buffering, direct keyboard reading, steady frame rate (256 Hz timer)

#define USE_TI89
#define SAVE_SCREEN

#include <tigcclib.h>

#define FRAME_TICKS  8           // 256 Hz / 8 = 32 frames per second
#define GROUND_Y     93          // the ground line
#define GUN_X        80          // pivot of the barrel
#define GUN_Y        88
#define BARREL       11          // barrel length (pixels)
#define MAX_PLANES   5
#define MAX_BOMBS    6
#define MAX_SHELLS   5
#define MAX_BOOMS    8
#define SHELL_SPEED  80          // 1/16 pixel per frame (5 pixels)
#define RELOAD       6           // frames between two shots
#define ANGLE_MIN    12          // barrel angle: 256 units per turn, 64 = straight up
#define ANGLE_MAX    116

static const SCR_RECT clip = {{0, 0, 159, 99}};

// ---------------------------------------------------------------- sprites
// 1 bit = 1 black pixel, most significant bit on the left.
static const unsigned short plane_right[8] = {
  0x6000,   // .##.............
  0x7020,   // .###......#.....
  0x7FF8,   // .############...
  0xFFFE,   // ###############.
  0x7FFC,   // .#############..
  0x03C0,   // ......####......
  0x0180,   // .......##.......
  0x0000,
};
static unsigned short plane_left[8];       // mirror image, made at startup

static const unsigned short gun_sprite[8] = {
  0x07E0,   // .....######.....
  0x1FF8,   // ...##########...
  0x3FFC,   // ..############..
  0x7FFE,   // .##############.
  0x7FFE,
  0xFFFF,   // ################
  0xFFFF,
  0xFFFF,
};

static const unsigned char bomb_sprite[6] = {
  0x40,     // .#......
  0xE0,     // ###.....
  0xE0,
  0xE0,
  0x40,
  0xA0,     // #.#.....  (fins)
};

// ---------------------------------------------------------------- sines
// sin(i * 2pi / 256) * 16384 for i = 0..64; the rest by symmetry.
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

// ---------------------------------------------------------------- objects
// Positions and speeds in 1/16 pixel.
typedef struct { short active, x, y, vx, bomb_left; } Plane;
typedef struct { short active, x, y, vx, vy; } Mover;       // bombs and shells
typedef struct { short active, x, y, age, size; } Boom;

static Plane planes[MAX_PLANES];
static Mover bombs[MAX_BOMBS], shells[MAX_SHELLS];
static Boom booms[MAX_BOOMS];

static void explode(short x, short y, short size)
{
  for (short i = 0; i < MAX_BOOMS; i++)
    if (!booms[i].active) {
      booms[i] = (Boom){1, x, y, 0, size};
      return;
    }
}

// ---------------------------------------------------------------- timing
static volatile unsigned short ticks;

DEFINE_INT_HANDLER(tick_handler)
{
  ticks++;
}

static void wait_frame(unsigned short *next)
{
  while ((short)(ticks - *next) < 0)
    ;
  *next += FRAME_TICKS;
}

static void wait_keys_released(void)
{
  while (_keytest(RR_ENTER) || _keytest(RR_ESC) || _keytest(RR_UP))
    ;
}

// ---------------------------------------------------------------- drawing
static void show(void *screen)
{
  memcpy(LCD_MEM, screen, LCD_SIZE);
}

static void draw_centered(short y, const char *text, short font)
{
  FontSetSys(font);
  DrawStr((160 - DrawStrWidth(text, font)) / 2, y, text, A_NORMAL);
}

static void draw_gun(unsigned char angle, short visible)
{
  DrawLine(0, GROUND_Y, 159, GROUND_Y, A_NORMAL);
  if (!visible)
    return;
  short ex = GUN_X + (short)(((long)qcos(angle) * BARREL) >> 14);
  short ey = GUN_Y - (short)(((long)qsin(angle) * BARREL) >> 14);
  DrawLine(GUN_X, GUN_Y, ex, ey, A_NORMAL);           // a barrel 2 pixels thick
  DrawLine(GUN_X, GUN_Y - 1, ex, ey - 1, A_NORMAL);
}

// ---------------------------------------------------------------- screens
static short title_screen(void *screen, unsigned long best)
{
  char buf[32];
  unsigned short next = ticks;
  unsigned char angle = 40;
  short dir = 1;

  wait_keys_released();
  for (;;) {
    memset(screen, 0, LCD_SIZE);
    draw_centered(6, "D.C.A.", F_8x10);
    draw_centered(18, "anti-aircraft defence", F_4x6);
    draw_centered(32, "LEFT / RIGHT: aim", F_6x8);
    draw_centered(42, "UP: fire", F_6x8);
    draw_centered(56, "ENTER: play   ESC: quit", F_4x6);
    if (best) {
      sprintf(buf, "Best score: %lu", best);
      draw_centered(64, buf, F_4x6);
    }
    angle += dir;                          // the gun sweeps the sky
    if (angle <= ANGLE_MIN || angle >= ANGLE_MAX)
      dir = -dir;
    draw_gun(angle, 1);
    Sprite16(GUN_X - 8, GROUND_Y - 8, 8, gun_sprite, screen, SPRT_OR);
    show(screen);
    if (_keytest(RR_ENTER)) return 1;
    if (_keytest(RR_ESC)) return 0;
    wait_frame(&next);
  }
}

static short game_over(void *screen, unsigned long score, unsigned long best)
{
  char buf[32];
  unsigned short next = ticks + 128;       // small pause before accepting keys

  ScrRectFill(&(SCR_RECT){{20, 26, 139, 74}}, &clip, A_REVERSE);
  DrawClipRect(&(WIN_RECT){20, 26, 139, 74}, &clip, A_NORMAL);
  draw_centered(31, "GAME OVER", F_8x10);
  sprintf(buf, "Score: %lu", score);
  draw_centered(46, buf, F_6x8);
  sprintf(buf, score > best ? "New best score!" : "Best: %lu", best);
  draw_centered(57, buf, F_4x6);
  draw_centered(66, "ENTER: again  ESC: quit", F_4x6);
  show(screen);

  while ((short)(ticks - next) < 0)
    ;
  wait_keys_released();
  for (;;) {
    if (_keytest(RR_ENTER)) return 1;
    if (_keytest(RR_ESC)) return 0;
  }
}

// ---------------------------------------------------------------- game
// Plays one game; returns the score.
static unsigned long play(void *screen)
{
  unsigned char angle = 64;                // straight up
  short reload = 0, lives = 3, hurt = 0, spawn = 32, over = 0;
  unsigned long score = 0, frame = 0;
  unsigned short next;
  char buf[32];

  memset(planes, 0, sizeof planes);
  memset(bombs, 0, sizeof bombs);
  memset(shells, 0, sizeof shells);
  memset(booms, 0, sizeof booms);
  srand(ticks);                            // depends on when ENTER was pressed
  wait_keys_released();
  next = ticks;

  for (;; frame++) {
    short level = 1 + (short)(score / 100);

    // --- keys (they can be held)
    if (_keytest(RR_ESC))
      return score;
    if (!over) {
      if (_keytest(RR_LEFT) && angle < ANGLE_MAX)
        angle += 2;
      if (_keytest(RR_RIGHT) && angle > ANGLE_MIN)
        angle -= 2;
      if (reload > 0)
        reload--;
      else if (_keytest(RR_UP)) {
        for (short i = 0; i < MAX_SHELLS; i++)
          if (!shells[i].active) {
            short c = qcos(angle), s = qsin(angle);
            shells[i] = (Mover){1,
              (GUN_X << 4) + (short)(((long)c * BARREL * 16) >> 14),
              (GUN_Y << 4) - (short)(((long)s * BARREL * 16) >> 14),
              (short)(((long)c * SHELL_SPEED) >> 14),
              -(short)(((long)s * SHELL_SPEED) >> 14)};
            reload = RELOAD;
            break;
          }
      }
    }

    // --- a new plane from time to time, more often at higher levels
    if (--spawn <= 0) {
      for (short i = 0; i < MAX_PLANES; i++)
        if (!planes[i].active) {
          short speed = 12 + random(8) + 3 * level;
          short from_left = random(2);
          planes[i] = (Plane){1, from_left ? -16 * 16 : 160 * 16, (8 + random(44)) * 16,
                              from_left ? speed : -speed, 1};
          break;
        }
      spawn = 50 - 4 * level + random(30);
      if (spawn < 12)
        spawn = 12;
    }

    memset(screen, 0, LCD_SIZE);

    // --- planes
    for (short i = 0; i < MAX_PLANES; i++) {
      Plane *p = &planes[i];
      if (!p->active)
        continue;
      p->x += p->vx;
      short x = p->x >> 4, y = p->y >> 4;
      if (x < -16 || x > 160) {            // flew away
        p->active = 0;
        continue;
      }
      // drop the bomb somewhere above the screen, more likely near the gun
      if (p->bomb_left && x > 4 && x < 140 && random(abs(x + 8 - GUN_X) / 4 + 8) == 0) {
        for (short b = 0; b < MAX_BOMBS; b++)
          if (!bombs[b].active) {
            bombs[b] = (Mover){1, p->x + 7 * 16, p->y + 8 * 16, p->vx / 2, 0};
            p->bomb_left = 0;
            break;
          }
      }
      ClipSprite16(x, y, 8, p->vx > 0 ? plane_right : plane_left, screen, SPRT_OR);
    }

    // --- shells: move, leave the screen, or hit a plane or a bomb
    for (short i = 0; i < MAX_SHELLS; i++) {
      Mover *s = &shells[i];
      if (!s->active)
        continue;
      s->x += s->vx;
      s->y += s->vy;
      short x = s->x >> 4, y = s->y >> 4;
      if (x < 0 || x > 159 || y < 0) {
        s->active = 0;
        continue;
      }
      for (short k = 0; k < MAX_PLANES && s->active; k++) {
        Plane *p = &planes[k];
        short px = p->x >> 4, py = p->y >> 4;
        if (p->active && x >= px && x < px + 16 && y >= py - 1 && y < py + 8) {
          p->active = s->active = 0;
          explode(px + 8, py + 4, 9);
          score += 10;
        }
      }
      for (short k = 0; k < MAX_BOMBS && s->active; k++) {
        Mover *b = &bombs[k];
        short bx = b->x >> 4, by = b->y >> 4;
        if (b->active && x >= bx - 2 && x <= bx + 4 && y >= by - 2 && y <= by + 7) {
          b->active = s->active = 0;
          explode(bx + 1, by + 3, 5);
          score += 5;
        }
      }
      if (s->active) {
        DrawPix(x, y, A_NORMAL);           // a shell is a 2x2 dot
        DrawPix(x + 1, y, A_NORMAL);
        DrawPix(x, y + 1, A_NORMAL);
        DrawPix(x + 1, y + 1, A_NORMAL);
      }
    }

    // --- bombs: fall faster and faster, hit the ground or the gun
    for (short i = 0; i < MAX_BOMBS; i++) {
      Mover *b = &bombs[i];
      if (!b->active)
        continue;
      b->vy += 1 + level / 3;              // gravity
      b->x += b->vx;
      b->y += b->vy;
      short x = b->x >> 4, y = b->y >> 4;
      if (y + 6 >= GROUND_Y - 6 && !over && !hurt && x + 3 >= GUN_X - 7 && x <= GUN_X + 7) {
        b->active = 0;                     // the gun is hit
        explode(GUN_X, GROUND_Y - 4, 14);
        hurt = 64;                         // 2 seconds without being hit again
        if (--lives == 0)
          over = 64;                       // let the explosion play, then stop
        continue;
      }
      if (y + 6 >= GROUND_Y) {
        b->active = 0;
        explode(x + 1, GROUND_Y - 2, 5);
        continue;
      }
      ClipSprite8(x, y, 6, bomb_sprite, screen, SPRT_OR);
    }

    // --- explosions: a circle that grows, then a ring that fades
    for (short i = 0; i < MAX_BOOMS; i++) {
      Boom *e = &booms[i];
      if (!e->active)
        continue;
      short r = e->age < e->size / 2 ? e->age * 2 : e->size;
      DrawClipEllipse(e->x, e->y, r, r, &clip, A_NORMAL);
      if (e->age & 1)
        DrawClipEllipse(e->x, e->y, r / 2, r / 2, &clip, A_NORMAL);
      if (++e->age > e->size)
        e->active = 0;
    }

    // --- the gun (blinks after being hit) and the score line
    short visible = lives > 0 && !(hurt & 4);
    draw_gun(angle, visible);
    if (visible)
      Sprite16(GUN_X - 8, GROUND_Y - 8, 8, gun_sprite, screen, SPRT_OR);
    if (hurt)
      hurt--;
    FontSetSys(F_4x6);
    sprintf(buf, "Score %lu", score);
    DrawStr(2, 1, buf, A_NORMAL);
    sprintf(buf, "Level %d", level);
    DrawStr(66, 1, buf, A_NORMAL);
    for (short i = 0; i < lives; i++)      // one small gun per life left
      ClipSprite8(150 - 8 * i, 1, 3, (const unsigned char[]){0x30, 0x78, 0xFC}, screen, SPRT_OR);
    show(screen);

    if (over && --over == 0)
      return score;
    wait_frame(&next);
  }
}

// ---------------------------------------------------------------- main
void _main(void)
{
  void *screen = malloc(LCD_SIZE);
  unsigned long best = 0;

  if (!screen)
    return;
  for (short i = 0; i < 8; i++) {          // mirror image of the plane
    unsigned short v = plane_right[i], m = 0;
    for (short b = 0; b < 16; b++)
      if (v & (1 << b))
        m |= 0x8000 >> b;
    plane_left[i] = m;
  }

  INT_HANDLER old_int1 = GetIntVec(AUTO_INT_1);
  INT_HANDLER old_int5 = GetIntVec(AUTO_INT_5);
  SetIntVec(AUTO_INT_1, tick_handler);     // our 256 Hz counter
  SetIntVec(AUTO_INT_5, DUMMY_HANDLER);    // AMS timer (auto power-off...) paused
  PortSet(screen, 239, 127);               // drawing functions draw into 'screen'

  if (title_screen(screen, best)) {
    for (;;) {
      unsigned long score = play(screen);
      short again = game_over(screen, score, best);
      if (score > best)
        best = score;
      if (!again || !title_screen(screen, best))
        break;
    }
  }

  wait_keys_released();
  PortRestore();
  SetIntVec(AUTO_INT_1, old_int1);
  SetIntVec(AUTO_INT_5, old_int5);
  free(screen);
  GKeyFlush();                             // forget keys pressed during the game
}
