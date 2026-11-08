/* Configuration Musashi pour l'émulateur TI-89 Titanium : 68000 uniquement. */
#ifndef TI89CONF_H
#define TI89CONF_H
#define M68K_EMULATE_010     M68K_OPT_OFF
#define M68K_EMULATE_EC020   M68K_OPT_OFF
#define M68K_EMULATE_020     M68K_OPT_OFF
#define M68K_EMULATE_030     M68K_OPT_OFF
#define M68K_EMULATE_040     M68K_OPT_OFF
#define M68K_EMULATE_PMMU    M68K_OPT_OFF
#define M68K_EMULATE_INT_ACK M68K_OPT_SPECIFY_HANDLER
#define M68K_INT_ACK_CALLBACK(A) ti89_int_ack(A)
int ti89_int_ack(int level);
#include "m68kconf.h"
#endif
