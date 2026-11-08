"""Accès au cœur C (libti89core.so) via ctypes."""
import ctypes
import os

_LIB_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "libti89core.so")

RD_CB = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_uint, ctypes.c_int)
WR_CB = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_int, ctypes.c_uint)

# Numéros de registres Musashi (enum m68k_register_t dans m68k.h)
REG_D0, REG_A0 = 0, 8
REG_A7 = 15
REG_PC, REG_SR, REG_SP, REG_USP, REG_ISP = 16, 17, 18, 19, 20

RAM_SIZE = 0x40000
ROM_SIZE = 0x400000
ROM_BASE = 0x800000


class Core:
    """Interface mince vers le CPU et les mémoires du cœur C."""

    def __init__(self):
        lib = ctypes.CDLL(os.path.abspath(_LIB_PATH))
        self.lib = lib
        lib.core_run.restype = ctypes.c_int
        lib.core_run.argtypes = [ctypes.c_int]
        lib.core_get_reg.restype = ctypes.c_uint
        lib.core_get_reg.argtypes = [ctypes.c_int]
        lib.core_set_reg.argtypes = [ctypes.c_int, ctypes.c_uint]
        lib.core_raise_irq.argtypes = [ctypes.c_int]
        lib.core_clear_irq.argtypes = [ctypes.c_int]
        lib.core_irq_pending.restype = ctypes.c_uint
        lib.core_disassemble.restype = ctypes.c_uint
        lib.core_disassemble.argtypes = [ctypes.c_char_p, ctypes.c_uint]
        # Vues directes (sans copie) sur la RAM et la flash du cœur C
        self.ram = (ctypes.c_uint8 * RAM_SIZE).in_dll(lib, "ram")
        self.rom = (ctypes.c_uint8 * ROM_SIZE).in_dll(lib, "rom")
        self._flash_cmd_mode = ctypes.c_int.in_dll(lib, "flash_cmd_mode")
        self._bp_hit = ctypes.c_int.in_dll(lib, "bp_hit")
        lib.core_run_debug.restype = ctypes.c_int
        lib.core_run_debug.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.core_bp_set.argtypes = [ctypes.c_uint]
        lib.core_bp_clear.argtypes = [ctypes.c_uint]
        lib.core_entry_watch.argtypes = [ctypes.c_int, ctypes.c_char_p]
        self._callbacks = None
        # Débogage : en mode debug, l'exécution passe par core_run_debug (arrêts possibles)
        self.debug = False
        self.skip_bp = False     # reprise : ne pas s'arrêter sur l'instruction courante
        self.bp_hit = 0          # 1 = point d'arrêt, 2 = entrée du programme détectée
        lib.core_init()

    def set_callbacks(self, io_read, io_write, flash_read, flash_write):
        # Les objets CFUNCTYPE doivent rester référencés tant que le cœur tourne.
        self._callbacks = (RD_CB(io_read), WR_CB(io_write),
                           RD_CB(flash_read), WR_CB(flash_write))
        self.lib.core_set_callbacks(*self._callbacks)

    def load_rom(self, data: bytes):
        if len(data) != ROM_SIZE:
            raise ValueError(f"ROM de {len(data)} octets, {ROM_SIZE} attendus")
        ctypes.memmove(self.rom, data, ROM_SIZE)

    @property
    def flash_cmd_mode(self):
        return self._flash_cmd_mode.value

    @flash_cmd_mode.setter
    def flash_cmd_mode(self, v):
        self._flash_cmd_mode.value = 1 if v else 0

    def reset(self):
        self.lib.core_reset()

    def run(self, cycles):
        if not self.debug:
            return self.lib.core_run(cycles)
        n = self.lib.core_run_debug(cycles, 1 if self.skip_bp else 0)
        self.skip_bp = False
        self.bp_hit = self._bp_hit.value
        return n

    def bp_clear_all(self):
        self.lib.core_bp_clear_all()

    def bp_set(self, addr):
        self.lib.core_bp_set(addr)

    def entry_watch(self, pattern=None):
        """Arrêt quand le PC arrive en RAM sur un code commençant par `pattern` (8 octets)."""
        if pattern is None:
            self.lib.core_entry_watch(0, b"\0" * 8)
        else:
            self.lib.core_entry_watch(1, bytes(pattern[:8]).ljust(8, b"\0"))

    def end_timeslice(self):
        self.lib.core_end_timeslice()

    def raise_irq(self, level):
        self.lib.core_raise_irq(level)

    def clear_irq(self, level):
        self.lib.core_clear_irq(level)

    def irq_pending(self):
        return self.lib.core_irq_pending()

    def reg(self, r):
        return self.lib.core_get_reg(r)

    def set_reg(self, r, v):
        self.lib.core_set_reg(r, v)

    @property
    def pc(self):
        return self.reg(REG_PC)

    def disassemble(self, pc):
        buf = ctypes.create_string_buffer(128)
        n = self.lib.core_disassemble(buf, pc)
        return n, buf.value.decode("ascii", "replace")
