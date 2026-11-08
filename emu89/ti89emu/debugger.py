"""
Débogueur au niveau du source C pour les programmes compilés avec `tigcc -g -O0`.

Principe :
  - le programme est lancé normalement (Session.run_program) avec le CPU en mode debug ;
  - le cœur C s'arrête quand le PC arrive en RAM sur le début du programme : on connaît
    alors son adresse de chargement (`base`) ; adresse réelle = base + décalage DWARF ;
  - points d'arrêt utilisateur = adresses de début des lignes C ;
  - pas à pas = points d'arrêt temporaires sur TOUS les débuts de ligne, avec une
    condition sur la pile (A6 = cadre de la fonction en -O0, SP) pour « ligne suivante »
    et « sortir ».
"""
from .core import REG_PC, REG_SR, REG_D0, REG_A0, REG_SP, REG_USP, REG_ISP
from . import dbginfo

IDLE, STARTING, RUNNING, PAUSED = "idle", "starting", "running", "paused"
REG_A6 = REG_A0 + 6


class Debugger:
    def __init__(self, session):
        self.session = session
        self.state = IDLE
        self.info = None
        self.base = None
        self.user_lines = set()
        self.mode = "continue"
        self.ref = None
        self.stop_reason = ""
        self.stop_at_main = True

    @property
    def core(self):
        return self.session.calc.core

    # ------------------------------------------------------------ démarrage
    def start(self, program_path, dbg_path, source_path, lines, info=None):
        self.info = info if info is not None else dbginfo.load(dbg_path, source_path)
        if not self.info.lines:
            raise ValueError("no line information for this file")
        self.user_lines = set(lines)
        self.base = None
        name = self.session.run_program(program_path)
        core = self.core
        core.debug = True
        core.bp_clear_all()
        core.entry_watch(self.info.text[:8])
        self.state = STARTING
        self.mode = "continue"
        return name

    def stop(self):
        self.session.restore_state()
        self.state = IDLE
        self.base = None

    # ------------------------------------------------------------ adresses
    def addr_of(self, off):
        return (self.base + off) & 0xFFFFFF

    def offset(self, pc=None):
        if self.base is None:
            return None
        pc = self.core.pc if pc is None else pc
        off = pc - self.base
        return off if 0 <= off < self.info.text_size else None

    def current_line(self):
        off = self.offset()
        return None if off is None else self.info.line_for(off)

    def _user_bp_addrs(self):
        addrs = set()
        for ln in self.user_lines:
            for off in self.info.line_addrs.get(ln, ()):
                addrs.add(self.addr_of(off))
        return addrs

    def _install(self, temp_all_lines=False, extra=()):
        core = self.core
        core.bp_clear_all()
        for a in self._user_bp_addrs():
            core.bp_set(a)
        if temp_all_lines:
            for off in self.info.statement_addrs():
                core.bp_set(self.addr_of(off))
        for a in extra:
            core.bp_set(a)

    def _read32(self, addr):
        ram = self.core.ram
        a = addr & 0x3FFFF
        return (ram[a] << 24) | (ram[a + 1] << 16) | (ram[a + 2] << 8) | ram[a + 3]

    def set_breakpoints(self, lines):
        self.user_lines = set(lines)
        if self.base is not None and self.state in (RUNNING, PAUSED):
            self._install(temp_all_lines=self.mode != "continue" and self.state == RUNNING)

    # ------------------------------------------------------------ reprise
    def cfa(self):
        """Identifiant du cadre de la fonction courante (adresse de pile à son entrée).
        En -O0, GCC fait « link a6 » dès l'entrée : avant, CFA = SP+4 ; après, CFA = A6+8.
        Plus le CFA est grand, plus l'appel est ancien (la pile descend)."""
        c = self.core
        if self.info.is_asm:
            return c.reg(REG_SP)
        off = self.offset()
        if off is not None and any(lo == off for _, lo, _ in self.info.functions):
            return c.reg(REG_SP) + 4
        return c.reg(REG_A6) + 8

    def _regs_ref(self):
        c = self.core
        return {"pc": c.pc, "cfa": self.cfa(), "line": self.current_line()}

    def resume(self, mode="continue"):
        if self.state != PAUSED:
            return
        if self.info.is_asm and mode != "continue":
            return self._asm_resume(mode)
        self.mode = mode
        self.ref = self._regs_ref()
        if mode == "out":
            # Adresse de retour de la fonction courante : juste sous le CFA
            self.ref["ret"] = self._read32(self.ref["cfa"] - 4) & 0xFFFFFF
            self._install(extra=[self.ref["ret"]])
        else:
            self._install(temp_all_lines=mode != "continue")
        self.core.skip_bp = True
        self.state = RUNNING

    def pause(self):
        if self.state == RUNNING:
            self.state = PAUSED
            self.stop_reason = "paused"

    # ------------------------------------------------------------ arrêts
    def on_stop(self):
        """Appelé quand le cœur s'est arrêté (bp_hit). Retourne True si on se met en pause."""
        core = self.core
        pc = core.pc
        if core.bp_hit == 2:                       # entrée du programme
            self.base = pc
            self.state = RUNNING
            if self.stop_at_main and not self.user_lines:
                # Pas de point d'arrêt : arrêt à la première ligne exécutée de votre code
                # (C : début de _main ; assembleur : première instruction)
                self.mode = "into"
                self.ref = {"pc": -1, "cfa": 0, "line": None}
                self._install(temp_all_lines=True)
            else:
                self.mode = "continue"
                self._install()
            return False
        if self.mode == "asm_ret":
            if pc in self._user_bp_addrs() and pc != self.ref["ret"]:
                self.state, self.stop_reason = PAUSED, "breakpoint"
                self._install()
                return True
            if pc == self.ref["ret"] and core.reg(REG_SP) >= self.ref["sp"]:
                # L'appel est terminé : on reprend le pas à pas instruction par instruction
                self.mode = self.ref["parent"]
                self._install()
                self.state = RUNNING
                return False
            core.skip_bp = True
            return False
        off = self.offset(pc)
        is_user = pc in self._user_bp_addrs()
        is_stmt = off is not None and off in set(self.info.statement_addrs())
        stop = False
        if is_user and (self.mode == "continue" or pc != self.ref["pc"]
                        or self.cfa() != self.ref["cfa"]):    # même ligne, autre appel (récursion)
            stop, self.stop_reason = True, "breakpoint"
        elif is_stmt and self.mode != "continue":
            cfa = self.cfa()
            if self.mode == "into":
                stop = pc != self.ref["pc"]
            elif self.mode == "over":        # même appel de fonction, ou un appelant
                stop = pc != self.ref["pc"] and cfa >= self.ref["cfa"]
            if stop:
                self.stop_reason = "step"
        elif self.mode == "out" and pc == self.ref.get("ret"):
            # Retour à l'appelant : la pile est remontée au-dessus du cadre de départ
            if core.reg(REG_SP) >= self.ref["cfa"]:
                stop, self.stop_reason = True, "step out"
        if stop:
            self.state = PAUSED
            self._install()                        # retire les points temporaires
            return True
        core.skip_bp = True                        # on continue
        return False

    # ------------------------------------------------------------ assembleur
    # En assembleur il n'y a pas de fonctions déclarées : le pas à pas suit les instructions.
    #   into : une instruction (entre dans les sous-programmes)
    #   over : jusqu'à la ligne suivante ; les jsr/bsr sont exécutés d'un bloc
    #   out  : jusqu'au retour (rts/rtr/rte) du sous-programme en cours
    def _instr(self, pc):
        n, txt = self.core.disassemble(pc)
        return n, txt.split()[0].lower() if txt.split() else ""

    def _single_step(self):
        core = self.core
        core.skip_bp = True
        core.run(1)                 # exactement une instruction (mode debug)

    def _asm_resume(self, mode):
        core = self.core
        self.ref = {"pc": core.pc, "sp": core.reg(REG_SP), "line": self.current_line()}
        if mode == "into":
            self._single_step()
            self.stop_reason = "step"
            return                  # reste en pause
        self.mode = "asm_" + mode
        self.state = RUNNING
        self._install()

    def asm_step(self, budget=20000):
        """Fait avancer un pas à pas assembleur (over/out). Appelé par l'IDE à chaque image.
        Retourne True si on s'est mis en pause."""
        core = self.core
        stmts = set(self.info.statement_addrs())
        user = self._user_bp_addrs()
        for _ in range(budget):
            pc = core.pc
            off = self.offset(pc)
            if pc != self.ref["pc"]:
                if pc in user:
                    self.state, self.stop_reason = PAUSED, "breakpoint"
                    return True
                if self.mode == "asm_over" and off is not None and off in stmts:
                    self.state, self.stop_reason = PAUSED, "step"
                    return True
            n, op = self._instr(pc)
            if op in ("jsr", "bsr", "bsr.s", "bsr.w") or op.startswith(("jsr", "bsr")):
                # Appel : on l'exécute d'un bloc jusqu'à l'instruction suivante
                self.ref.update(ret=(pc + n) & 0xFFFFFF, sp=core.reg(REG_SP),
                                parent=self.mode)
                self._single_step()                 # entre dans l'appel
                self.mode = "asm_ret"
                self._install(extra=[self.ref["ret"]])
                return False                        # l'IDE continue en exécution normale
            if self.mode == "asm_out" and op in ("rts", "rtr", "rte"):
                self._single_step()
                self.state, self.stop_reason = PAUSED, "step out"
                return True
            self._single_step()
        return False

    # ------------------------------------------------------------ registres
    def registers(self):
        c = self.core
        regs = {f"D{i}": c.reg(REG_D0 + i) for i in range(8)}
        regs.update({f"A{i}": c.reg(REG_A0 + i) for i in range(8)})
        regs["PC"] = c.pc
        regs["SR"] = c.reg(REG_SR)
        regs["USP"] = c.reg(REG_USP)
        regs["SSP"] = c.reg(REG_ISP)
        return regs

    def disassembly(self, before=6, after=10):
        """Liste (adresse, texte, ligne C, est_pc) autour du PC."""
        c = self.core
        pc = c.pc
        # Pour revenir en arrière, on part du début de la ligne C courante si possible
        start = pc
        off = self.offset(pc)
        if off is not None:
            starts = [a for a in self.info.statement_addrs() if a <= off]
            if starts:
                k = max(0, len(starts) - 3)
                start = self.addr_of(starts[k])
        out = []
        a = start
        for _ in range(before + after):
            n, txt = c.disassemble(a)
            o = self.offset(a)
            ln = None
            if o is not None and o in self.info.statement_addrs():
                ln = self.info.line_for(o)
            out.append((a, txt, ln, a == pc))
            a += max(n, 2)
        return out
