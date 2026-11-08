#define USE_TI89
#define SAVE_SCREEN
#include <tigcclib.h>

static unsigned char smile[8] = {0x3C,0x42,0xA5,0x81,0xA5,0x99,0x42,0x3C};

void _main(void)
{
  int i;
  ClrScr();
  FontSetSys(F_8x10);
  DrawStr(30, 2, "Graphics!", A_NORMAL);
  FontSetSys(F_4x6);
  DrawStr(2, 92, "lines, circles, sprites", A_NORMAL);
  for (i = 0; i < 160; i += 10)
    DrawLine(80, 50, i, 14, A_NORMAL);
  DrawClipEllipse(30, 55, 20, 20, &(SCR_RECT){{0, 0, 159, 99}}, A_NORMAL);
  DrawClipEllipse(130, 55, 25, 15, &(SCR_RECT){{0, 0, 159, 99}}, A_NORMAL);
  for (i = 0; i < 6; i++)
    Sprite8(52 + i * 10, 70, 8, smile, LCD_MEM, SPRT_XOR);
  ScrRectFill(&(SCR_RECT){{100, 75, 150, 85}}, ScrRect, A_NORMAL);
  ngetchx();
}
