"""
Matériel de la TI-89 Titanium (HW3), d'après « TI HW guide » (Doc/TI HW guide.pdf).

Le CPU et la RAM/ROM sont dans le cœur C (core.py). Ce module émule :
  - les ports d'E/S $600000 (§5.1-5.19), $700000 (§5.20-5.29), $710000 (RTC HW3, §5.30-5.34)
  - la flash (commandes Sharp, §6.5)
  - les auto-interruptions 1, 2, 5, 6 (§4) et le timer programmable (§6.6)
  - la matrice clavier (§6.3) et le mode veille ($600005)
"""
import time
import calendar

from .core import Core, ROM_BASE, ROM_SIZE

CPU_HZ = 12_000_000          # OSC1 (HW2/3) ~12 MHz
OSC2_HZ = 1 << 19            # OSC2 (HW2/3) = 2^19 Hz
AI1_OSC2_TICKS = 1 << 11     # AI1 déclenchée à OSC2/2^11 = 256 Hz
TICK_CYCLES = CPU_HZ * AI1_OSC2_TICKS // OSC2_HZ   # cycles CPU entre deux AI1

LCD_ADDR = 0x4C00            # le contrôleur HW2/3 « espionne » $4C00-$5BFF (§5.27)
LCD_W, LCD_H = 160, 100
LCD_STRIDE = 30              # 240 pixels logiques par ligne

# Epoch de la RTC HW3 : secondes depuis le 1er janvier 1997 00:00:00 (§5.30)
RTC_EPOCH = calendar.timegm((1997, 1, 1, 0, 0, 0, 0, 0, 0))

# Matrice clavier TI-89 (§6.3) : nom -> (ligne, bit de colonne)
KEYS = {}
_MATRIX = [
    ["up", "left", "down", "right", "2nd", "shift", "diamond", "alpha"],
    ["enter", "+", "-", "*", "/", "^", "clear", "f5"],
    ["(-)", "3", "6", "9", ",", "t", "backspace", "f4"],
    [".", "2", "5", "8", ")", "z", "catalog", "f3"],
    ["0", "1", "4", "7", "(", "y", "mode", "f2"],
    ["apps", "sto", "ee", "|", "=", "x", "home", "f1"],
    ["esc"],
]
for _row, _names in enumerate(_MATRIX):
    for _bit, _name in enumerate(_names):
        KEYS[_name] = (_row, _bit)


class Flash:
    """Flash Sharp LH28F320 : 4 Mo en $800000, secteurs de 64 Ko (§6.5)."""

    READ, STATUS, PROGRAM, ERASE_SETUP, READ_ID = range(5)
    SECTOR = 0x10000
    BOOT_END = ROM_BASE + 0x10000     # secteur de boot toujours protégé en écriture

    def __init__(self, core: Core):
        self.core = core
        self.mode = self.READ
        self.status = 0x80
        self.writes = 0
        self.erases = 0

    def _set_mode(self, mode):
        self.mode = mode
        self.core.flash_cmd_mode = mode != self.READ

    def read(self, addr, size):
        if self.mode == self.READ_ID:
            # Identifiants fabricant / composant (Sharp LH28F320BF)
            off = (addr - ROM_BASE) & 0xFF
            val = 0xB0 if off < 2 else 0xE9
        else:
            val = self.status
        return (val << 8) | val if size == 2 else val

    def write(self, addr, size, val):
        if self.mode == self.PROGRAM:
            self._program(addr, size, val)
            self._set_mode(self.STATUS)
            return
        cmd = val & 0xFF
        if self.mode == self.ERASE_SETUP:
            if cmd == 0xD0:
                self._erase(addr)
            self._set_mode(self.STATUS)
            return
        if cmd in (0x10, 0x40):
            self._set_mode(self.PROGRAM)
        elif cmd == 0x20:
            self._set_mode(self.ERASE_SETUP)
        elif cmd == 0x50:
            self.status = 0x80
        elif cmd == 0x70:
            self._set_mode(self.STATUS)
        elif cmd == 0x90:
            self._set_mode(self.READ_ID)
        elif cmd == 0xFF:
            self._set_mode(self.READ)

    def _program(self, addr, size, val):
        if addr < self.BOOT_END:
            return
        rom = self.core.rom
        off = addr - ROM_BASE
        # Programmer une flash ne peut que faire passer des bits de 1 à 0.
        if size == 2:
            rom[off] &= (val >> 8) & 0xFF
            rom[off + 1] &= val & 0xFF
        else:
            rom[off] &= val & 0xFF
        self.writes += 1

    def _erase(self, addr):
        if addr < self.BOOT_END:
            return
        start = (addr - ROM_BASE) & ~(self.SECTOR - 1)
        rom = self.core.rom
        for i in range(start, start + self.SECTOR):
            rom[i] = 0xFF
        self.erases += 1


class TI89Titanium:
    def __init__(self, rom_path):
        self.core = Core()
        with open(rom_path, "rb") as f:
            self.core.load_rom(f.read())
        self.flash = Flash(self.core)
        self.core.set_callbacks(self.io_read, self.io_write,
                                self.flash.read, self.flash.write)

        self.p600 = bytearray(0x20)
        self.p700 = bytearray(0x100)
        self.p710 = bytearray(0x100)
        self.keys_down = set()       # (ligne, bit)
        self.key_seen = {}           # (ligne, bit) -> nb de lectures du port clavier qui l'ont vue
        self.release_seen = {}       # (ligne, bit) -> nb de lectures qui l'ont vue relâchée
        self.on_down = False
        self.halted = False
        self.wake_mask = 0
        self.timer_initial = 0xCC
        self.timer_value = 0xCC
        self.osc2_acc = 0
        self.fs_toggle = 0
        self.rtc_offset = 0          # décalage RTC émulée - horloge de l'hôte
        self.ticks = 0
        self.cycles = 0
        self.tick_remaining = 0      # cycles restant à exécuter dans le tick en cours
        self.unknown_io = {}         # ports lus/écrits non émulés (diagnostic)
        self.reset()

    # ------------------------------------------------------------------ reset
    def reset(self):
        p = self.p600
        p[0x00] = 0x00
        p[0x01] = 0x04
        p[0x03] = 0xFF
        p[0x0C] = 0x8D
        p[0x10], p[0x11] = 0x09, 0x80
        p[0x15] = 0x1B
        p[0x17] = 0xCC
        p[0x18] = 0x80
        p[0x1C] = 0x21
        p[0x1D] = 0x80
        self.p700[0x1F] = 0x07
        self.p710[0x5F] = 0x83
        self.timer_initial = self.timer_value = 0xCC
        self.halted = False
        local_now = time.time() + (time.localtime().tm_gmtoff or 0)
        self.rtc_offset = local_now - time.time()
        self.core.reset()

    # ------------------------------------------------------------- E/S
    def io_read(self, addr, size):
        if size == 1:
            return self._io_read8(addr)
        if size == 2:
            return (self._io_read8(addr) << 8) | self._io_read8(addr + 1)
        return 0

    def io_write(self, addr, size, val):
        if size == 2:
            self._io_write8(addr, (val >> 8) & 0xFF)
            self._io_write8(addr + 1, val & 0xFF)
        else:
            self._io_write8(addr, val & 0xFF)

    def _note_unknown(self, addr, kind):
        key = (addr, kind)
        self.unknown_io[key] = self.unknown_io.get(key, 0) + 1

    def _rtc_seconds(self):
        return int(time.time() + self.rtc_offset - RTC_EPOCH) & 0xFFFFFFFF

    def _io_read8(self, addr):
        if addr < 0x700000:
            port = addr & 0x1F               # les ports $600000 sont répétés
            p = self.p600
            if port == 0x00:
                return p[0] | 0x04           # bit 2 : tension batterie correcte
            if port == 0x0D:
                return 0x40                  # lien : tampon d'émission vide, rien reçu
            if port == 0x0F:
                return 0x00
            if port == 0x17:
                return self.timer_value
            if port == 0x1A:
                return 0x00 if self.on_down else 0x02
            if port == 0x1B:
                return self._read_keyboard()
            return p[port]
        if addr < 0x700100:
            port = addr & 0xFF
            if port == 0x1D:
                return (self.p700[0x1D] & 0x02) | (self.fs_toggle << 7) | 0x09
            return self.p700[port]
        if 0x710000 <= addr < 0x710100:
            port = addr & 0xFF
            if 0x46 <= port <= 0x49:
                secs = self._rtc_seconds()
                return (secs >> (8 * (0x49 - port))) & 0xFF
            if port == 0x45:
                return int((time.time() % 1) * 16) & 0x0F
            if port == 0x5F:
                return 0x80 | (self.p710[0x5F] & 0x03)
            self._note_unknown(addr, "r")
            return self.p710[port]
        self._note_unknown(addr, "r")
        return 0

    def _io_write8(self, addr, val):
        if addr < 0x700000:
            port = addr & 0x1F
            p = self.p600
            if port == 0x05:
                # Mise en veille du CPU jusqu'à une interruption autorisée
                self.wake_mask = val & 0x1F
                self.halted = True
                self.core.end_timeslice()
                return
            if port == 0x17:
                self.timer_initial = self.timer_value = val
            elif port == 0x1A:
                self.core.clear_irq(6)
            elif port == 0x1B:
                self.core.clear_irq(2)
            p[port] = val
            return
        if addr < 0x700100:
            port = addr & 0xFF
            if port < 0x10:                  # §5.24 : $700008-F miroirs de $700000-7
                self.p700[port & 0x07] = val
                self.p700[(port & 0x07) | 0x08] = val
            else:
                self.p700[port] = val
            return
        if 0x710000 <= addr < 0x710100:
            port = addr & 0xFF
            if port == 0x5F:
                old = self.p710[0x5F]
                if (old & 0x02) and not (val & 0x02):
                    # Front descendant : chargement de l'heure écrite en $710040
                    r = self.p710
                    secs = (r[0x40] << 24) | (r[0x41] << 16) | (r[0x42] << 8) | r[0x43]
                    self.rtc_offset = RTC_EPOCH + secs - time.time()
            else:
                self._note_unknown(addr, "w")
            self.p710[port] = val
            return
        self._note_unknown(addr, "w")

    # ------------------------------------------------------------- clavier
    def _row_mask(self):
        return ((self.p600[0x18] << 8) | self.p600[0x19]) & 0x3FF

    def _read_keyboard(self):
        mask = self._row_mask()
        cols = 0
        for rc in self.keys_down:
            row, bit = rc
            if not (mask >> row) & 1:
                cols |= 1 << bit
                self.key_seen[rc] = self.key_seen.get(rc, 0) + 1
        for rc in self.release_seen:
            if not (mask >> rc[0]) & 1:
                self.release_seen[rc] += 1
        return (~cols) & 0xFF

    def key_release_seen_count(self, name):
        """Nombre de lectures du clavier qui ont vu cette touche relâchée."""
        if name == "on":
            return 1 << 30
        return self.release_seen.get(KEYS[name], 1 << 30)

    def key_seen_count(self, name):
        """Nombre de fois qu'AMS a lu cette touche enfoncée depuis l'appui."""
        if name == "on":
            return 1 << 30
        return self.key_seen.get(KEYS[name], 0)

    def key_down(self, name):
        if name == "on":
            if not self.on_down:
                self.on_down = True
                self._interrupt(6)
            return
        rc = KEYS[name]
        if rc not in self.keys_down:
            self.keys_down.add(rc)
            self.key_seen[rc] = 0
            self.release_seen.pop(rc, None)
            self._interrupt(2)

    def key_up(self, name):
        if name == "on":
            self.on_down = False
        else:
            self.keys_down.discard(KEYS[name])
            self.key_seen.pop(KEYS[name], None)
            self.release_seen[KEYS[name]] = 0

    # ------------------------------------------------------- interruptions
    def _interrupt(self, level):
        self.core.raise_irq(level)
        if self.halted and (level == 6 or level == 7 or (self.wake_mask >> (level - 1)) & 1):
            self.halted = False

    def _timers(self):
        ctrl = self.p600[0x15]
        if not ctrl & 0x02:                  # OSC2 arrêté
            return
        if not ctrl & 0x80:
            self._interrupt(1)
        if ctrl & 0x08:                      # incrémentation du timer $600017
            shift = (5, 9, 12, 18)[(ctrl >> 4) & 3]
            self.osc2_acc += AI1_OSC2_TICKS
            n = self.osc2_acc >> shift
            self.osc2_acc -= n << shift
            for _ in range(n):
                if self.timer_value == 0:
                    self.timer_value = self.timer_initial
                else:
                    self.timer_value = (self.timer_value + 1) & 0xFF
                    if self.timer_value == 0 and not ctrl & 0x80:
                        self._interrupt(5)

    # ------------------------------------------------------- exécution
    def tick(self):
        """Exécute 1/256 s d'émulation (une période de l'AI1).

        Retourne False si l'exécution s'est arrêtée en cours de tick (point d'arrêt en
        mode débogage) : un appel ultérieur reprend le même tick là où il en était."""
        if self.tick_remaining <= 0:
            self.tick_remaining = TICK_CYCLES
        core = self.core
        while self.tick_remaining > 0 and not self.halted:
            n = core.run(self.tick_remaining)
            self.tick_remaining -= max(n, 0)
            if core.debug and core.bp_hit:
                return False
            if n <= 0:
                break
        self.tick_remaining = 0
        self.cycles += TICK_CYCLES
        self.ticks += 1
        self.fs_toggle ^= 1
        self._timers()
        return True

    def run_seconds(self, seconds):
        for _ in range(int(seconds * 256)):
            self.tick()

    # ------------------------------------------------------------- LCD
    def lcd_pixels(self):
        """Retourne l'écran sous forme de 100 lignes de 160 booléens (True = noir)."""
        ram = self.core.ram
        rows = []
        for y in range(LCD_H):
            base = LCD_ADDR + y * LCD_STRIDE
            line = bytes(ram[base:base + LCD_W // 8])
            rows.append([(line[x >> 3] >> (7 - (x & 7))) & 1 == 1 for x in range(LCD_W)])
        return rows

    def lcd_bytes(self):
        ram = self.core.ram
        return bytes(ram[LCD_ADDR:LCD_ADDR + LCD_STRIDE * LCD_H])
