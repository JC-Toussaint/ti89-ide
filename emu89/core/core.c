/*
 * Cœur C de l'émulateur TI-89 Titanium (HW3).
 *
 * Contient uniquement ce qui est critique pour la vitesse : le CPU 68000
 * (Musashi) et le décodage d'adresses RAM/ROM. Tout le reste (ports d'E/S,
 * machine d'état de la flash, timers, clavier, LCD) est en Python et est
 * appelé via des callbacks ctypes.
 *
 * Carte mémoire Titanium (doc « TI HW guide », §2.4, §2.5, §3) :
 *   $000000-$03FFFF  RAM 256 Ko
 *   $040000-$1FFFFF  rien (la RAM n'est PAS répétée sur la Titanium, §2.4)
 *   $200000-$5FFFFF  miroirs (« ghosts ») de la RAM
 *   $600000-$7FFFFF  ports d'E/S       -> Python
 *   $800000-$BFFFFF  flash 4 Mo        -> tableau rom[], ou Python en mode commande
 *   $C00000-$FFFFFF  non mappé
 */
#include <stdint.h>
#include <string.h>
#include "m68k.h"

#define RAM_SIZE  0x40000u
#define ROM_SIZE  0x400000u
#define ROM_BASE  0x800000u

uint8_t ram[RAM_SIZE];
uint8_t rom[ROM_SIZE];

typedef unsigned (*rd_cb_t)(unsigned addr, int size);
typedef void (*wr_cb_t)(unsigned addr, int size, unsigned val);

static rd_cb_t io_read_cb, flash_read_cb;
static wr_cb_t io_write_cb, flash_write_cb;

/* Mis à 1 par Python quand la flash n'est plus en mode « lecture tableau »
 * (lecture du registre d'état ou des identifiants) : les lectures flash
 * passent alors par Python. */
int flash_cmd_mode = 0;

/* Interruptions en attente : bit n = auto-interruption de niveau n. */
static unsigned irq_pending = 0;

static void update_irq(void)
{
    int lvl;
    for (lvl = 7; lvl > 0; lvl--)
        if (irq_pending & (1u << lvl))
            break;
    m68k_set_irq(lvl);
}

int ti89_int_ack(int level)
{
    /* Les auto-interruptions de la TI sont considérées comme acquittées
     * dès qu'elles sont prises en compte par le CPU. */
    irq_pending &= ~(1u << level);
    update_irq();
    return M68K_INT_ACK_AUTOVECTOR;
}

/* ---- API exportée vers Python ---- */

void core_set_callbacks(rd_cb_t ior, wr_cb_t iow, rd_cb_t flr, wr_cb_t flw)
{
    io_read_cb = ior; io_write_cb = iow;
    flash_read_cb = flr; flash_write_cb = flw;
}

void core_raise_irq(int level) { irq_pending |= 1u << level; update_irq(); }
void core_clear_irq(int level) { irq_pending &= ~(1u << level); update_irq(); }
unsigned core_irq_pending(void) { return irq_pending; }

void core_init(void)
{
    m68k_init();
    m68k_set_cpu_type(M68K_CPU_TYPE_68000);
}

void core_reset(void)
{
    irq_pending = 0;
    update_irq();
    m68k_pulse_reset();
    /* Sur la Titanium, les vecteurs de reset sont lus au début de la flash. */
    m68k_set_reg(M68K_REG_SP, ((uint32_t)rom[0] << 24) | (rom[1] << 16) | (rom[2] << 8) | rom[3]);
    m68k_set_reg(M68K_REG_PC, ((uint32_t)rom[4] << 24) | (rom[5] << 16) | (rom[6] << 8) | rom[7]);
}

int core_run(int cycles) { return m68k_execute(cycles); }
extern int stop_request;
void core_end_timeslice(void) { m68k_end_timeslice(); stop_request = 1; }
unsigned core_get_reg(int reg) { return m68k_get_reg(NULL, (m68k_register_t)reg); }
void core_set_reg(int reg, unsigned v) { m68k_set_reg((m68k_register_t)reg, v); }

unsigned core_disassemble(char *buf, unsigned pc)
{
    return m68k_disassemble(buf, pc, M68K_CPU_TYPE_68000);
}

/* ---- Accès mémoire (appelés par Musashi) ---- */

/* Vrai si l'adresse (24 bits) tombe dans la RAM ou un de ses miroirs. */
static inline int is_ram(unsigned a)
{
    return a < RAM_SIZE || (a >= 0x200000 && a < 0x600000);
}

static inline unsigned rd8(unsigned a)
{
    a &= 0xFFFFFF;
    if (is_ram(a)) return ram[a & (RAM_SIZE - 1)];
    if (a < 0x600000) return 0;
    if (a < ROM_BASE) return io_read_cb(a, 1) & 0xFF;
    if (a < ROM_BASE + ROM_SIZE) {
        if (flash_cmd_mode) return flash_read_cb(a, 1) & 0xFF;
        return rom[a - ROM_BASE];
    }
    return 0xFF;
}

static inline unsigned rd16(unsigned a)
{
    a &= 0xFFFFFF;
    if (is_ram(a)) {
        unsigned o = a & (RAM_SIZE - 1);
        return (ram[o] << 8) | ram[(o + 1) & (RAM_SIZE - 1)];
    }
    if (a < 0x600000) return 0;
    if (a < ROM_BASE) return io_read_cb(a, 2) & 0xFFFF;
    if (a < ROM_BASE + ROM_SIZE) {
        if (flash_cmd_mode) return flash_read_cb(a, 2) & 0xFFFF;
        unsigned o = a - ROM_BASE;
        return (rom[o] << 8) | rom[o + 1];
    }
    return 0xFFFF;
}

static inline void wr8(unsigned a, unsigned v)
{
    a &= 0xFFFFFF;
    if (is_ram(a)) { ram[a & (RAM_SIZE - 1)] = (uint8_t)v; return; }
    if (a < 0x600000) return;
    if (a < ROM_BASE) { io_write_cb(a, 1, v & 0xFF); return; }
    if (a < ROM_BASE + ROM_SIZE) { flash_write_cb(a, 1, v & 0xFF); return; }
}

static inline void wr16(unsigned a, unsigned v)
{
    a &= 0xFFFFFF;
    if (is_ram(a)) {
        unsigned o = a & (RAM_SIZE - 1);
        ram[o] = (uint8_t)(v >> 8);
        ram[(o + 1) & (RAM_SIZE - 1)] = (uint8_t)v;
        return;
    }
    if (a < 0x600000) return;
    if (a < ROM_BASE) { io_write_cb(a, 2, v & 0xFFFF); return; }
    if (a < ROM_BASE + ROM_SIZE) { flash_write_cb(a, 2, v & 0xFFFF); return; }
}

unsigned int m68k_read_memory_8(unsigned int a)  { return rd8(a); }
unsigned int m68k_read_memory_16(unsigned int a) { return rd16(a); }
unsigned int m68k_read_memory_32(unsigned int a) { return (rd16(a) << 16) | rd16(a + 2); }
void m68k_write_memory_8(unsigned int a, unsigned int v)  { wr8(a, v); }
void m68k_write_memory_16(unsigned int a, unsigned int v) { wr16(a, v); }
void m68k_write_memory_32(unsigned int a, unsigned int v) { wr16(a, v >> 16); wr16(a + 2, v & 0xFFFF); }

/* Lectures sans effet de bord pour le désassembleur. */
static unsigned peek16(unsigned a)
{
    a &= 0xFFFFFF;
    if (is_ram(a)) { unsigned o = a & (RAM_SIZE - 1); return (ram[o] << 8) | ram[(o + 1) & (RAM_SIZE - 1)]; }
    if (a >= ROM_BASE && a < ROM_BASE + ROM_SIZE) { unsigned o = a - ROM_BASE; return (rom[o] << 8) | rom[o + 1]; }
    return 0;
}
unsigned int m68k_read_disassembler_8(unsigned int a)  { return peek16(a & ~1u) >> ((a & 1) ? 0 : 8) & 0xFF; }
unsigned int m68k_read_disassembler_16(unsigned int a) { return peek16(a); }
unsigned int m68k_read_disassembler_32(unsigned int a) { return (peek16(a) << 16) | peek16(a + 2); }

/* ---- Instantanés (sauvegarde/restauration de l'état complet) ---- */
unsigned core_context_size(void) { return m68k_context_size(); }
void core_get_context(void *dst) { m68k_get_context(dst); }
void core_set_context(const void *src) { m68k_set_context((void *)src); }
void core_set_irq_pending(unsigned v) { irq_pending = v; update_irq(); }

/* ---- Débogage : points d'arrêt et détection de l'entrée du programme ---- */

static uint8_t bp_map[1 << 21];        /* 1 bit par adresse sur 24 bits */
int bp_hit = 0;                        /* mis à 1 quand l'exécution s'est arrêtée sur un point d'arrêt */
int stop_request = 0;                  /* demande d'arrêt (veille du CPU via $600005...) */
static int entry_watch = 0;            /* attendre que le PC arrive sur le début du programme */
static uint8_t entry_pattern[8];

void core_bp_clear_all(void) { memset(bp_map, 0, sizeof bp_map); }
void core_bp_set(unsigned a) { a &= 0xFFFFFF; bp_map[a >> 3] |= (uint8_t)(1u << (a & 7)); }
void core_bp_clear(unsigned a) { a &= 0xFFFFFF; bp_map[a >> 3] &= (uint8_t)~(1u << (a & 7)); }

void core_entry_watch(int on, const uint8_t *pattern)
{
    entry_watch = on;
    if (on) memcpy(entry_pattern, pattern, sizeof entry_pattern);
}

static int at_program_entry(unsigned pc)
{
    unsigned i;
    if (!entry_watch || pc >= RAM_SIZE) return 0;
    for (i = 0; i < sizeof entry_pattern; i++)
        if (ram[(pc + i) & (RAM_SIZE - 1)] != entry_pattern[i]) return 0;
    return 1;
}

/* Exécute instruction par instruction en s'arrêtant AVANT une adresse marquée.
 * skip_first : ne pas s'arrêter sur l'instruction courante (reprise après un arrêt). */
int core_run_debug(int cycles, int skip_first)
{
    int used = 0;
    bp_hit = 0;
    stop_request = 0;
    while (used < cycles) {
        unsigned pc = m68k_get_reg(NULL, M68K_REG_PC) & 0xFFFFFF;
        if (!skip_first) {
            if ((bp_map[pc >> 3] >> (pc & 7)) & 1) { bp_hit = 1; break; }
            if (at_program_entry(pc)) { bp_hit = 2; entry_watch = 0; break; }
        }
        skip_first = 0;
        used += m68k_execute(1);
        if (stop_request) { stop_request = 0; break; }
    }
    return used;
}

/* ---- Écran : moyenne temporelle (niveaux de gris) ----
 * Les niveaux de gris de la TI sont obtenus en alternant rapidement plusieurs images
 * en $4C00. On échantillonne l'écran à chaque tick (256 Hz) et on affiche, pour chaque
 * pixel, la proportion du temps où il était allumé sur les LCD_WINDOW derniers ticks. */
#define LCD_ADDR 0x4C00
#define LCD_STRIDE 30
#define LCD_W 160
#define LCD_H 100
#define LCD_ROWBYTES (LCD_W / 8)
#define LCD_FRAME (LCD_ROWBYTES * LCD_H)
#define LCD_MAXWIN 64

static uint8_t lcd_ring[LCD_MAXWIN][LCD_FRAME];
static uint8_t lcd_cnt[LCD_W * LCD_H];
static int lcd_window = 18, lcd_pos = 0, lcd_filled = 0;

void core_lcd_reset(int window)
{
    if (window < 1) window = 1;
    if (window > LCD_MAXWIN) window = LCD_MAXWIN;
    lcd_window = window;
    lcd_pos = lcd_filled = 0;
    memset(lcd_cnt, 0, sizeof lcd_cnt);
}

void core_lcd_sample(void)
{
    uint8_t *slot = lcd_ring[lcd_pos];
    int y, x, i;
    for (y = 0; y < LCD_H; y++) {
        const uint8_t *src = &ram[LCD_ADDR + y * LCD_STRIDE];
        uint8_t *dst = &slot[y * LCD_ROWBYTES];
        for (i = 0; i < LCD_ROWBYTES; i++) {
            uint8_t nb = src[i];
            uint8_t ob = (lcd_filled == lcd_window) ? dst[i] : 0;
            if (nb != ob) {
                uint8_t *c = &lcd_cnt[y * LCD_W + i * 8];
                for (x = 0; x < 8; x++) {
                    int bit = 7 - x;
                    c[x] += ((nb >> bit) & 1) - ((ob >> bit) & 1);
                }
            }
            dst[i] = nb;
        }
    }
    lcd_pos = (lcd_pos + 1) % lcd_window;
    if (lcd_filled < lcd_window) lcd_filled++;
}

/* Niveaux 0 (éteint) .. 255 (noir) pour les 160x100 pixels. */
void core_lcd_levels(uint8_t *out)
{
    int i, n = lcd_filled ? lcd_filled : 1;
    for (i = 0; i < LCD_W * LCD_H; i++)
        out[i] = (uint8_t)((lcd_cnt[i] * 255 + n / 2) / n);
}
