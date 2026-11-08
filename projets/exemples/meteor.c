// Meteor Dodge - example game for the TI-89 Titanium (GCC4TI)
//
// Move the ship with LEFT / RIGHT and dodge the falling meteors.
// The longer you survive, the faster and more numerous they get.
//   ENTER : start / play again        ESC : quit
//
// Techniques shown:
//   - 8x8 and 16x8 sprites (ClipSprite8 / Sprite16)
//   - double buffering: everything is drawn in a hidden screen, then copied
//     to the real one in one go (no flicker)
//   - direct keyboard reading with _keytest (several keys at once, no delay)
//   - a steady frame rate driven by the 256 Hz auto-interrupt 1

#define USE_TI89
#define SAVE_SCREEN

#include <tigcclib.h>

#define MAX_ROCKS   12
#define SHIP_Y      90          // ship row (the screen is 160x100)
#define SHIP_W      16
#define FRAME_TICKS 8           // 256 Hz / 8 = 32 frames per second

// ---------------------------------------------------------------- sprites
// 1 bit = 1 black pixel, most significant bit on the left.
static const unsigned short ship_sprite[8] = {
  0x0180,   // .......##.......
  0x03C0,   // ......####......
  0x03C0,   // ......####......
  0x07E0,   // .....######.....
  0x0FF0,   // ....########....
  0x1FF8,   // ...##########...
  0x3E7C,   // ..#####..#####..
  0x6006,   // .##..........##.
};

static const unsigned char rock_sprite[8] = {
  0x3C,     // ..####..
  0x7E,     // .######.
  0xDF,     // ##.#####
  0xFF,     // ########
  0xF7,     // ####.###
  0xFF,     // ########
  0x7E,     // .######.
  0x3C,     // ..####..
};

static const unsigned char boom_sprite[8] = {
  0x91, 0x52, 0x3C, 0xFE, 0x3F, 0x3C, 0x4A, 0x89,
};

typedef struct {
  short x;          // column (pixels)
  short y;          // row, in 1/4 of a pixel (smooth speeds)
  short speed;      // 1/4 pixels per frame
  short active;
} Rock;

// ---------------------------------------------------------------- timing
// Auto-interrupt 1 fires 256 times per second. We replace the AMS handler
// (which scans the keyboard) by ours, which just counts.
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
  while (_keytest(RR_ENTER) || _keytest(RR_ESC))
    ;
}

// ---------------------------------------------------------------- drawing
static void show(void *screen)
{
  memcpy(LCD_MEM, screen, LCD_SIZE);       // hidden screen -> real screen
}

static void draw_centered(short y, const char *text, short font)
{
  FontSetSys(font);
  DrawStr((160 - DrawStrWidth(text, font)) / 2, y, text, A_NORMAL);
}

static void draw_stars(unsigned long frame)
{
  // a few scrolling pixels in the background
  for (short i = 0; i < 16; i++) {
    short x = (i * 37 + 11) % 160;
    short y = (short)((i * 23 + frame / (1 + (i & 3))) % 100);
    DrawPix(x, y, A_NORMAL);
  }
}

// ---------------------------------------------------------------- screens
// Returns 1 to play, 0 to quit.
static short title_screen(void *screen, unsigned long best)
{
  char buf[32];
  unsigned short next = ticks;
  unsigned long frame = 0;

  wait_keys_released();
  for (;;) {
    memset(screen, 0, LCD_SIZE);
    draw_stars(frame++);
    draw_centered(14, "METEOR DODGE", F_8x10);
    Sprite16(72, 34, 8, ship_sprite, screen, SPRT_OR);
    ClipSprite8(40, 30 + (short)(frame / 4 % 8), 8, rock_sprite, screen, SPRT_OR);
    ClipSprite8(112, 38 - (short)(frame / 4 % 8), 8, rock_sprite, screen, SPRT_OR);
    draw_centered(52, "LEFT / RIGHT: move", F_6x8);
    draw_centered(64, "ENTER: play   ESC: quit", F_4x6);
    if (best) {
      sprintf(buf, "Best score: %lu", best);
      draw_centered(78, buf, F_4x6);
    }
    show(screen);
    if (_keytest(RR_ENTER)) return 1;
    if (_keytest(RR_ESC)) return 0;
    wait_frame(&next);
  }
}

// Plays one game; returns the score.
static unsigned long play(void *screen)
{
  Rock rocks[MAX_ROCKS];
  short ship_x = (160 - SHIP_W) / 2;
  short spawn_delay = 0;
  unsigned long score = 0;
  unsigned short next;
  char buf[24];

  memset(rocks, 0, sizeof rocks);
  srand(ticks);                            // depends on when ENTER was pressed
  wait_keys_released();
  next = ticks;

  for (;;) {
    // --- input (keys can be held, several at once)
    if (_keytest(RR_ESC))
      return score;
    if (_keytest(RR_LEFT) && ship_x > 0)
      ship_x -= 3;
    if (_keytest(RR_RIGHT) && ship_x < 160 - SHIP_W)
      ship_x += 3;

    // --- new meteors: more and more often, faster and faster
    if (--spawn_delay <= 0) {
      for (short i = 0; i < MAX_ROCKS; i++) {
        if (!rocks[i].active) {
          rocks[i].active = 1;
          rocks[i].x = random(160 - 8);
          rocks[i].y = -8 * 4;
          rocks[i].speed = 4 + random(4) + (short)(score / 150);
          break;
        }
      }
      spawn_delay = 18 - (short)(score / 100);
      if (spawn_delay < 4)
        spawn_delay = 4;
    }

    // --- draw the hidden screen
    memset(screen, 0, LCD_SIZE);
    draw_stars(score);
    for (short i = 0; i < MAX_ROCKS; i++) {
      Rock *r = &rocks[i];
      if (!r->active)
        continue;
      r->y += r->speed;
      short y = r->y / 4;
      if (y >= 100) {                      // left the screen
        r->active = 0;
        continue;
      }
      ClipSprite8(r->x, y, 8, rock_sprite, screen, SPRT_OR);

      // collision: slightly smaller boxes than the sprites, to be fair
      if (y + 6 >= SHIP_Y + 2 && y + 1 <= SHIP_Y + 7 &&
          r->x + 6 >= ship_x + 3 && r->x + 1 <= ship_x + SHIP_W - 4) {
        Sprite16(ship_x, SHIP_Y, 8, ship_sprite, screen, SPRT_OR);
        ClipSprite8(ship_x + 4, SHIP_Y - 4, 8, boom_sprite, screen, SPRT_XOR);
        show(screen);
        return score;
      }
    }
    Sprite16(ship_x, SHIP_Y, 8, ship_sprite, screen, SPRT_OR);

    FontSetSys(F_4x6);
    sprintf(buf, "%lu", score / 4);
    DrawStr(2, 1, buf, A_NORMAL);
    show(screen);

    score++;
    wait_frame(&next);
  }
}

static short game_over(void *screen, unsigned long score, unsigned long best)
{
  char buf[32];
  unsigned short next = ticks + 128;       // small pause before accepting keys

  ScrRectFill(&(SCR_RECT){{20, 26, 139, 74}}, &(SCR_RECT){{0, 0, 159, 99}}, A_REVERSE);
  DrawClipRect(&(WIN_RECT){20, 26, 139, 74}, &(SCR_RECT){{0, 0, 159, 99}}, A_NORMAL);
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

// ---------------------------------------------------------------- main
void _main(void)
{
  void *screen = malloc(LCD_SIZE);
  unsigned long best = 0;

  if (!screen)
    return;

  INT_HANDLER old_int1 = GetIntVec(AUTO_INT_1);
  INT_HANDLER old_int5 = GetIntVec(AUTO_INT_5);
  SetIntVec(AUTO_INT_1, tick_handler);     // our 256 Hz counter
  SetIntVec(AUTO_INT_5, DUMMY_HANDLER);    // AMS timer (auto power-off...) paused
  PortSet(screen, 239, 127);               // drawing functions draw into 'screen'

  if (title_screen(screen, best)) {
    for (;;) {
      unsigned long score = play(screen) / 4;
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
