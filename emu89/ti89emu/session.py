"""
Session d'exécution pour l'IDE : démarrage d'AMS, instantané, chargement et lancement
d'un programme .89z, écran LCD.
"""
import ctypes
import os

from .hardware import TI89Titanium, LCD_W, LCD_H, LCD_ADDR, LCD_STRIDE
from .core import ROM_BASE, REG_PC, REG_SR, REG_D0
from .keyfeed import KeyFeeder

_STUB_PATH = os.path.join(os.path.dirname(__file__), "stubs", "loadvar.bin")
_STUB_DONE = 0x50        # adresse (relative) de la boucle de fin
_STUB_PARAMS = 0x52      # adresse (relative) des paramètres

LCD_ON = (0x1E, 0x23, 0x1E)
LCD_OFF = (0xC4, 0xD4, 0xB4)
LCD_WINDOW = 18          # ticks moyennés pour l'affichage (2 cycles de gris de 9 ticks)
# Niveau 0..255 -> composantes R, V, B (dégradé écran éteint -> pixel noir)
_TR = [bytes(round(LCD_OFF[c] + (LCD_ON[c] - LCD_OFF[c]) * v / 255) for v in range(256))
       for c in range(3)]
_LUT = [b"".join(bytes(LCD_ON) if (b >> (7 - i)) & 1 else bytes(LCD_OFF) for i in range(8))
        for b in range(256)]

# Attributs Python de TI89Titanium qui font partie de l'état de la machine
_CALC_FIELDS = ("on_down", "halted", "wake_mask", "timer_initial", "timer_value",
                "osc2_acc", "fs_toggle", "rtc_offset", "ticks", "cycles", "tick_remaining")


class LoadError(Exception):
    pass


def read_89z(path):
    """Retourne (nom, données de la variable) d'un fichier .89z / .89p / .89y..."""
    with open(path, "rb") as f:
        d = f.read()
    if not d.startswith(b"**TI89**") or len(d) < 0x5A:
        raise LoadError(f"{os.path.basename(path)} is not a TI-89 file")
    name = d[0x40:0x48].split(b"\0")[0].decode("latin-1")
    data = d[0x56:-2]            # mot de longueur + contenu (étiquette de type à la fin)
    if (sum(data) & 0xFFFF) != int.from_bytes(d[-2:], "little"):
        raise LoadError("bad file checksum")
    return name, data


class Session:
    def __init__(self, rom_path):
        self.calc = TI89Titanium(rom_path)
        self.keys = KeyFeeder(self.calc)
        self.snapshot = None
        self.ready = False           # AMS démarré et instantané pris
        self._boot_phase = 0
        with open(_STUB_PATH, "rb") as f:
            self._stub = f.read()
        self.calc.core.lib.core_lcd_reset(LCD_WINDOW)
        self._levels = ctypes.create_string_buffer(LCD_W * LCD_H)

    # ------------------------------------------------------------ exécution
    def tick(self):
        """Un tick d'émulation ; retourne False si le CPU s'est arrêté en cours de tick
        (point d'arrêt en mode débogage)."""
        self.keys.tick()
        done = self.calc.tick()
        if done:
            self.calc.core.lib.core_lcd_sample()     # échantillon pour la moyenne (gris)
        return done

    def boot_step(self, max_ticks=256):
        """Fait avancer le démarrage ; retourne True quand l'instantané est prêt."""
        c = self.calc
        for _ in range(max_ticks):
            if self._boot_phase == 0:            # installation d'AMS jusqu'au bureau
                self.tick()
                if c.halted and c.ticks > 256:
                    self.keys.type_keys(["home"])
                    self._boot_phase = 1
            elif self._boot_phase == 1:          # ouverture de l'écran Home
                self.tick()
                if not self.keys.busy():
                    self._settle = 64
                    self._boot_phase = 2
            elif self._boot_phase == 2:          # laisse AMS se stabiliser
                self.tick()
                self._settle -= 1
                if self._settle <= 0 and c.halted:
                    self.snapshot = self.save_state()
                    self.ready = True
                    self._boot_phase = 3
                    return True
            else:
                return True
        return False

    # ------------------------------------------------------------ instantanés
    def save_state(self):
        core, c = self.calc.core, self.calc
        ctx = ctypes.create_string_buffer(core.lib.core_context_size())
        core.lib.core_get_context(ctx)
        return {
            "ram": bytes(core.ram), "rom": bytes(core.rom), "ctx": ctx.raw,
            "irq": core.irq_pending(),
            "flash": (c.flash.mode, c.flash.status),
            "ports": (bytes(c.p600), bytes(c.p700), bytes(c.p710)),
            "fields": {k: getattr(c, k) for k in _CALC_FIELDS},
        }

    def restore_state(self, st=None):
        st = st or self.snapshot
        core, c = self.calc.core, self.calc
        core.debug = False
        core.skip_bp = False
        core.bp_hit = 0
        core.bp_clear_all()
        core.entry_watch(None)
        self.keys.clear()
        c.keys_down.clear()
        c.key_seen.clear()
        c.release_seen.clear()
        ctypes.memmove(core.ram, st["ram"], len(st["ram"]))
        ctypes.memmove(core.rom, st["rom"], len(st["rom"]))
        core.lib.core_set_context(ctypes.create_string_buffer(st["ctx"], len(st["ctx"])))
        core.lib.core_set_irq_pending(st["irq"])
        c.flash.mode, c.flash.status = st["flash"]
        core.flash_cmd_mode = c.flash.mode != c.flash.READ
        c.p600[:], c.p700[:], c.p710[:] = st["ports"]
        for k, v in st["fields"].items():
            setattr(c, k, v)

    # ------------------------------------------------------------ chargement
    def _free_flash_area(self, size):
        """Cherche une zone flash vierge (tout à $FF) pour y placer le chargeur.
        Les secteurs d'archive libres commencent par un mot d'état d'AMS ($FFFE) :
        on se place à +$1000 dans le secteur."""
        rom = self.calc.core.rom
        for sector in range(0x3E0000, 0x200000, -0x10000):
            off = sector + 0x1000
            if bytes(rom[off:off + size]) == b"\xff" * size:
                return off
        raise LoadError("no free flash area for the loader")

    def load_variable(self, name, data, timeout_s=5):
        """Crée la variable `name` (dossier courant) avec `data` dans la calculatrice."""
        c = self.calc
        core = c.core
        if not c.halted:
            raise LoadError("AMS is not idle")
        sym = b"\0" + name.encode("latin-1") + b"\0"
        size = 0x200 + len(data)
        off = self._free_flash_area(size)
        base = ROM_BASE + off
        rom = core.rom
        blob = bytearray(self._stub)
        name_addr = base + 0x100
        data_addr = base + 0x200
        blob[_STUB_PARAMS:_STUB_PARAMS + 12] = (len(data).to_bytes(4, "big")
                                               + (name_addr + len(sym) - 1).to_bytes(4, "big")
                                               + data_addr.to_bytes(4, "big"))
        ctypes.memmove(ctypes.addressof(rom) + off, bytes(blob), len(blob))
        ctypes.memmove(ctypes.addressof(rom) + off + 0x100, sym, len(sym))
        ctypes.memmove(ctypes.addressof(rom) + off + 0x200, bytes(data), len(data))

        ctx = ctypes.create_string_buffer(core.lib.core_context_size())
        core.lib.core_get_context(ctx)
        try:
            core.set_reg(REG_PC, base)
            c.halted = False
            done = base + _STUB_DONE
            for _ in range(int(timeout_s * 256)):
                c.tick()
                if core.reg(REG_PC) == done:
                    break
            else:
                raise LoadError("the loader did not finish")
            if core.reg(REG_D0) != 1:
                raise LoadError("AMS refused to create the variable (memory full?)")
        finally:
            core.lib.core_set_context(ctx)
            c.halted = True
            ctypes.memset(ctypes.addressof(rom) + off, 0xFF, size)

    def run_program(self, path):
        """Repart de l'instantané, charge le programme et tape « nom() » + ENTER."""
        if not self.ready:
            raise LoadError("the emulated calculator has not finished starting")
        name, data = read_89z(path)
        self.restore_state()
        self.load_variable(name, data)
        self.keys.type_keys(["clear"])
        self.keys.type_text(name + "()")
        self.keys.type_keys(["enter"])
        return name

    # ------------------------------------------------------------ mémoire
    def peek(self, addr, n):
        """Lit n octets à partir de addr (24 bits). Les zones non lisibles sans effet de
        bord (ports d'E/S, adresses non câblées) sont retournées à None."""
        ram, rom = self.calc.core.ram, self.calc.core.rom
        out = []
        for k in range(n):
            a = (addr + k) & 0xFFFFFF
            if a < 0x40000 or 0x200000 <= a < 0x600000:
                out.append(ram[a & 0x3FFFF])
            elif 0x800000 <= a < 0xC00000:
                out.append(rom[a - 0x800000])
            else:
                out.append(None)
        return out

    def poke(self, addr, value):
        """Écrit un octet en RAM. Retourne False si l'adresse n'est pas de la RAM."""
        a = addr & 0xFFFFFF
        if a < 0x40000 or 0x200000 <= a < 0x600000:
            self.calc.core.ram[a & 0x3FFFF] = value & 0xFF
            return True
        return False

    # ------------------------------------------------------------ écran
    def lcd_bytes(self):
        ram = self.calc.core.ram
        return bytes(ram[LCD_ADDR:LCD_ADDR + LCD_STRIDE * LCD_H])

    def lcd_levels(self):
        """Niveaux 0..255 des 160x100 pixels, moyennés dans le temps (niveaux de gris)."""
        self.calc.core.lib.core_lcd_levels(self._levels)
        return self._levels.raw

    @staticmethod
    def levels_ppm(levels):
        rgb = bytearray(len(levels) * 3)
        rgb[0::3] = levels.translate(_TR[0])
        rgb[1::3] = levels.translate(_TR[1])
        rgb[2::3] = levels.translate(_TR[2])
        return b"P6 %d %d 255\n" % (LCD_W, LCD_H) + bytes(rgb)

    @staticmethod
    def lcd_ppm(data):
        rows = []
        for y in range(LCD_H):
            line = data[y * LCD_STRIDE: y * LCD_STRIDE + LCD_W // 8]
            rows.append(b"".join(_LUT[b] for b in line))
        return b"P6 %d %d 255\n" % (LCD_W, LCD_H) + b"".join(rows)
