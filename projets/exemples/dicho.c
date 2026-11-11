// Program for TI-89 Titanium
#define USE_TI89          // target model
#define SAVE_SCREEN       // restore the screen when the program exits

#include <tigcclib.h>

/* Résoudre cos(x) = x par dichotomie : un exemple à suivre au débogueur (F6),
   en regardant a, b, milieu et tours évoluer dans l'onglet Variables.
   On cherche x entre a = 0 et b = 1 tel que f(x) = cos(x) - x = 0 : f(a) et
   f(b) sont de signes contraires, et l'on garde la moitié de l'intervalle où
   le signe change, jusqu'à une largeur de 1E-10.
   Sur TI-89, float (= double) est le flottant de la calculatrice : 14 chiffres
   significatifs, en BCD. */

#define PRECISION 1E-10

static int tours;                       /* nombre de moitiés prises */

static float f(float x)
{
    return cos(x) - x;
}

static float dichotomie(float a, float b)
{
    float milieu, fa;
    fa = f(a);
    while (b - a > PRECISION) {
        milieu = (a + b) / 2;
        if (fa * f(milieu) <= 0)        /* le signe change entre a et milieu */
            b = milieu;
        else {
            a = milieu;
            fa = f(a);
        }
        tours++;
    }
    return (a + b) / 2;
}

void _main(void)
{
    float x;
    clrscr();
    printf("cos(x) = x\n");
    x = dichotomie(0, 1);
    printf("x = %.12f\n", x);
    printf("f(x) = %.3e\n", f(x));
    printf("%d tours\n", tours);
    ngetchx();                          /* attend une touche */
}
