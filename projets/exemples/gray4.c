#define USE_TI89
#define SAVE_SCREEN
#include <tigcclib.h>

void _main(void)
{
  if (!GrayOn()) return;
  // 4 bands: white, light gray, dark gray, black
  SetPlane(LIGHT_PLANE); ClrScr();
  SetPlane(DARK_PLANE); ClrScr();
  SetPlane(LIGHT_PLANE);
  ScrRectFill(&(SCR_RECT){{40, 10, 79, 89}}, ScrRect, A_NORMAL);
  ScrRectFill(&(SCR_RECT){{120, 10, 159, 89}}, ScrRect, A_NORMAL);
  SetPlane(DARK_PLANE);
  ScrRectFill(&(SCR_RECT){{80, 10, 159, 89}}, ScrRect, A_NORMAL);
  DrawStr(2, 92, "white  light  dark  black", A_NORMAL);
  SetPlane(LIGHT_PLANE);
  DrawStr(2, 92, "white  light  dark  black", A_NORMAL);
  ngetchx();
  GrayOff();
}
