// Programme pour TI-89 Titanium
#define USE_TI89          // modèle visé
#define SAVE_SCREEN       // restaure l'écran à la fin du programme

#include <tigcclib.h>

void _main(void)
{
  int i;
  clrscr();
  printf("Bonjour !\n");
  for (i=0; i<10; i++){
    printf("%d\n", i);
    }
  ngetchx();              // attend une touche
}
