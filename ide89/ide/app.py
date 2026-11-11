"""Fenêtre principale de l'IDE TI-89."""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .build import build
from .editor import CodeEditor, THEME
from . import realcalc
from .memview import MemoryView
from .regview import RegisterView
from .icons import make_icon
from PIL import ImageTk

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EMU_DIR = os.path.join(REPO_ROOT, "emu89")
# Image de la ROM de votre calculatrice (non fournie) : variable TI89_ROM ou ROM/ti89tv310.rom
ROM_PATH = os.environ.get("TI89_ROM", os.path.join(REPO_ROOT, "ROM", "ti89tv310.rom"))
sys.path.insert(0, EMU_DIR)
from ti89emu.session import Session, LoadError          # noqa: E402
from ti89emu.debugger import Debugger, IDLE, STARTING, RUNNING, PAUSED   # noqa: E402
from ti89emu.variables import VariableReader                            # noqa: E402
from ti89emu.asmvars import AsmVariableReader                           # noqa: E402
from ti89emu import dbginfo                                             # noqa: E402
from ti89emu.keyfeed import CHAR_MAP, KEYSYM_MAP          # noqa: E402

PROJECTS_DIR = os.path.join(REPO_ROOT, "projets")
HOLD_KEYS = {"Up": "up", "Down": "down", "Left": "left", "Right": "right"}
CONFIG_PATH = os.path.expanduser("~/.config/ide89.json")
LCD_SCALE = 2

TEMPLATE = """// Program for TI-89 Titanium
#define USE_TI89          // target model
#define SAVE_SCREEN       // restore the screen when the program exits

#include <tigcclib.h>

void _main(void)
{
  clrscr();
  printf("Hello!\\n");
  ngetchx();              // wait for a key
}
"""

class Tooltip:
    """Infobulle affichée au survol d'un widget."""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e):
        self.job = self.widget.after(400, self._show)

    def _show(self):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 4
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#111214", fg="#e5e7eb", padx=8, pady=3,
                 font=("DejaVu Sans", 9), relief="solid", bd=1).pack()

    def _hide(self, _e=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


GAS_TEMPLATE = '| Assembly program for TI-89 Titanium (GNU as syntax)\n| Comments start with "|". Registers are written %d0, %a7...\n\n        .include "os.h"                 | AMS ROM call numbers\n\n        .xdef   _ti89                   | target models: TI-89 and TI-89 Titanium\n        .xdef   _ti89ti\n        .xdef   _tigcc_native\n        .xdef   __ref_all___nostub      | standalone program (no kernel)\n        .xdef   __ref_all___startup_code | startup code that calls __main\n        .xdef   __ref_all___set_file_in_use_bit\n        .xdef   __ref_all___save_screen | restore the screen at exit\n        .xdef   __main                  | entry point (C name: _main)\n\n| Call an AMS ROM function: rom_call ScreenClear\n        .macro  rom_call name\n        movea.l 0xC8,%a0\n        movea.l (\\name*4,%a0),%a0\n        jsr     (%a0)\n        .endm\n\n        .text\n__main:\n        rom_call ScreenClear\n        move.w  #1,-(%sp)               | A_NORMAL\n        pea     message(%pc)\n        move.w  #10,-(%sp)              | y\n        move.w  #10,-(%sp)              | x\n        rom_call DrawStr                | DrawStr(10, 10, message, A_NORMAL)\n        lea     10(%sp),%sp\n        rom_call ngetchx                | wait for a key\n        rts\n\nmessage:\n        .asciz  "Hello from assembly!"\n        .even\n'

A68K_TEMPLATE = '; Assembly program for TI-89 Titanium (A68k syntax)\n; Comments start with ";". Registers are written d0, a7...\n; In _nostub mode the program starts at the first instruction of the file.\n\n        include "os.h"                  ; AMS ROM call numbers, ROM_CALL macro,\n                                        ; and the _nostub/_ti89 symbols\n        xdef    _nostub                 ; standalone program (no kernel)\n        xdef    _ti89                   ; target model (TI-89 / TI-89 Titanium)\n\nstart:\n        movem.l d3-d7/a2-a6,-(sp)       ; registers AMS expects to be preserved\n        lea     -3840(sp),sp            ; save the screen (240x128 bits = 3840 bytes)\n        movea.l sp,a1\n        lea     LCD_MEM,a0\n        move.w  #3840/4-1,d0\n\\save:  move.l  (a0)+,(a1)+\n        dbra    d0,\\save\n\n        ROM_CALL ScreenClear\n        move.w  #1,-(sp)                ; A_NORMAL\n        pea     message(pc)\n        move.w  #10,-(sp)               ; y\n        move.w  #10,-(sp)               ; x\n        ROM_CALL DrawStr                ; DrawStr(10, 10, message, A_NORMAL)\n        lea     10(sp),sp\n        ROM_CALL ngetchx                ; wait for a key\n\n        movea.l sp,a1                   ; restore the screen\n        lea     LCD_MEM,a0\n        move.w  #3840/4-1,d0\n\\rest:  move.l  (a1)+,(a0)+\n        dbra    d0,\\rest\n        lea     3840(sp),sp\n        movem.l (sp)+,d3-d7/a2-a6\n        rts\n\nmessage:\n        dc.b    "Hello from assembly!",0\n        even\n        end\n'

TEMPLATES = {"c": (TEMPLATE, ".c"), "gas": (GAS_TEMPLATE, ".s"), "a68k": (A68K_TEMPLATE, ".asm")}
LANG_NAMES = {"c": "C", "gas": "assembly (GNU as)", "a68k": "assembly (A68k)"}


# Noms déjà utilisés par AMS (commandes et fonctions) : un programme portant ce nom
# provoque une erreur « Syntax » au lancement. Liste des cas les plus courants.
RESERVED_NAMES = set("""
abs and ans approx archive augment avgrc bldata ceiling cfactor char circle clrdraw clrerr
clrgraph clrhome clrio clrtable colnorm comdenom conj copyvar cos cosh crossp csolve cubicreg
cumsum custmoff custmon custom cycle czeros define delfold delvar deriv det diag dialog dim
disp dispg disphome disptbl dotp drawfunc drawinv drawparm drawpol drawslp else elseif end
endfor endfunc endif endloop endprgm endtry endwhile entry exact exit exp expand expr factor
fill floor fnoff fnon for format fpart func gcd get getcalc getconfg getdate getfold getkey
getmode gettime getunits goto graph identity if imag input inputstr instring int intdiv
integral ipart isprime item lbl lcm left limit line linehorz linetan linevert list ln local
lock log loop lu main mat max mean median mid min mod moveVar newdata newfold newlist newmat
newpic newplot newprob not nsolve ord or output part pause pi plotsoff plotson polar prgm
product prompt propfrac ptchg ptoff pton pttext pxlchg pxlcrcl pxlhorz pxlline pxloff pxlon
pxltest pxltext pxlvert rand randmat randnorm randpoly randseed rclgdb rclpic real ref
remain rename request return right root rotate round rowadd rowdim rownorm rowswap rref
send sendcalc sendchat seq setdate setfold setgraph setmode settable settime setunits
shade shift showstat sign simult sin sinh solve sortA sortD sqrt stdev stogdb stopic stop
string style subMat sum system table tan tanh taylor text then title try tstep unarchiv
unlock when while xor xorpic zeros zoombox zoomstd
""".lower().split())


# Niveaux d'optimisation des versions finales (Build, Run, Send). Debug utilise toujours -O0.
OPT_LEVELS = {
    "-O2": ("Speed", "optimized for speed (default)"),
    "-Os": ("Size", "optimized for size: smaller program, uses less calculator memory"),
    "-O0": ("None", "no optimization: largest and slowest, like the debug build"),
}


def language_of(path):
    ext = os.path.splitext(path or "")[1].lower()
    return {".s": "gas", ".asm": "a68k"}.get(ext, "c")


UI = {"bg": "#2b2d31", "panel": "#232428", "fg": "#d4d4d4", "muted": "#8b8f98",
      "accent": "#3b82f6", "ok": "#4ade80", "err": "#f87171", "warn": "#fbbf24"}


class IdeApp:
    def __init__(self, path=None):
        self.root = tk.Tk()
        self.root.title("IDE TI-89")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{min(1400, sw - 40)}x{min(860, sh - 90)}+10+10")
        self.root.configure(bg=UI["bg"])
        self.path = None
        self.dirty = False
        self.build_queue = queue.Queue()
        self.building = False
        self.last_build = None
        self.after_build = None          # action à lancer après une compilation réussie
        self.session = Session(ROM_PATH)
        self.debugger = Debugger(self.session)
        self.running = None              # nom du programme en cours d'exécution
        self.last_lcd = None
        self.emu_debt = 0.0
        self.last_wall = time.perf_counter()
        self.opt_level = tk.StringVar(value=self._load_config().get("optimize", "-O2"))
        if self.opt_level.get() not in OPT_LEVELS:
            self.opt_level.set("-O2")
        self._style()
        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(10, self._emu_loop)
        start = path or self._load_config().get("last_file")
        if start and os.path.exists(start):
            self.open_file(start)
        else:
            self.new_file()

    # ------------------------------------------------------------ apparence
    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=UI["bg"], foreground=UI["fg"], fieldbackground=UI["panel"],
                    bordercolor="#3a3c42", lightcolor=UI["bg"], darkcolor=UI["bg"],
                    font=("DejaVu Sans", 10))
        s.configure("TNotebook", background=UI["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", background=UI["panel"], foreground=UI["muted"], padding=(12, 4))
        s.map("TNotebook.Tab", background=[("selected", UI["bg"])],
              foreground=[("selected", UI["fg"])])
        s.configure("Treeview", background=UI["panel"], fieldbackground=UI["panel"],
                    foreground=UI["fg"], rowheight=24, borderwidth=0)
        s.configure("Treeview.Heading", background=UI["bg"], foreground=UI["muted"], relief="flat")
        s.map("Treeview", background=[("selected", "#264f78")])
        s.configure("TPanedwindow", background="#18191c")
        s.configure("Tool.TButton", background="#3a3d44", foreground="white", padding=(10, 5),
                    borderwidth=0)
        s.map("Tool.TButton", background=[("active", "#50545d"), ("disabled", "#2e3035")],
              foreground=[("disabled", "#6b707a")])
        s.configure("Primary.TButton", background=UI["accent"], foreground="white",
                    padding=(12, 5), borderwidth=0)
        s.map("Primary.TButton", background=[("active", "#2563eb")])
        s.configure("Small.TButton", background="#3a3d44", foreground="white", padding=(5, 4),
                    borderwidth=0, font=("DejaVu Sans", 9))
        s.map("Small.TButton", background=[("active", "#50545d"), ("disabled", "#2e3035")],
              foreground=[("disabled", "#6b707a")])
        s.configure("SmallPrimary.TButton", background=UI["accent"], foreground="white",
                    padding=(8, 4), borderwidth=0, font=("DejaVu Sans", 9, "bold"))
        s.map("SmallPrimary.TButton", background=[("active", "#2563eb"), ("disabled", "#2e3035")],
              foreground=[("disabled", "#6b707a")])
        s.configure("Debug.TButton", background="#7c3aed", foreground="white",
                    padding=(8, 4), borderwidth=0, font=("DejaVu Sans", 9, "bold"))
        s.map("Debug.TButton", background=[("active", "#6d28d9"), ("disabled", "#2e3035")],
              foreground=[("disabled", "#6b707a")])
        s.configure("Icon.TButton", background=UI["bg"], padding=(5, 4), borderwidth=0,
                    relief="flat", anchor="center")
        s.map("Icon.TButton", background=[("active", "#3a3d44"), ("disabled", UI["bg"])])
        s.configure("IconRun.TButton", background=UI["bg"], padding=(1, 0), borderwidth=0,
                    relief="flat", anchor="center")
        s.map("IconRun.TButton", background=[("active", UI["bg"]), ("disabled", UI["bg"])])
        s.configure("Panel.TLabelframe", background=UI["panel"], bordercolor="#3a3c42")
        s.configure("Panel.TLabelframe.Label", background=UI["panel"], foreground=UI["muted"],
                    font=("DejaVu Sans", 10, "bold"))

    def _build_ui(self):
        # Barre d'outils
        bar = tk.Frame(self.root, bg=UI["bg"], pady=6, padx=8)
        bar.pack(fill="x")
        self._icons = []                       # références : Tk oublie sinon les images

        def picture(name, color, size, badge=None):
            img = ImageTk.PhotoImage(make_icon(name, color, size, badge))
            self._icons.append(img)
            return img

        def btn(name, tip, cmd, state="normal", pad=(1, 0), run=False):
            # Icônes au trait : claire si actif, grisée si désactivé ; « Run » sur fond bleu
            if run:
                normal = picture(name, "#ffffff", 30, badge="#2563eb")
                hover = picture(name, "#ffffff", 30, badge="#1d4ed8")
                off = picture(name, "#6b707a", 30, badge="#33353b")
                image = [normal, "disabled", off, "active", hover]
                style = "IconRun.TButton"
            else:
                normal = picture(name, "#e5e7eb", 22)
                off = picture(name, "#55585f", 22)
                image = [normal, "disabled", off]
                style = "Icon.TButton"
            b = ttk.Button(bar, image=image, style=style, command=cmd, state=state, takefocus=0)
            b.pack(side="left", padx=pad)
            Tooltip(b, tip)
            return b

        def sep():
            tk.Frame(bar, width=1, bg="#45484f").pack(side="left", fill="y", padx=10, pady=4)

        self._build_menu()
        # Fichiers
        btn("new", "New  (Ctrl+N)", self.new_file, pad=(0, 1))
        btn("open", "Open…  (Ctrl+O)", self.open_dialog)
        btn("save", "Save  (Ctrl+S)", self.save)
        sep()
        # Construction et exécution
        self.btn_build = btn("build", "Build  (F7)", self.compile)
        self.btn_run = btn("run", "Run in emulator  (F5)", self.run_program, "disabled",
                           pad=(4, 4), run=True)
        self.btn_debug = btn("debug", "Debug  (F6)", self.debug_program, state="disabled")
        self.btn_stop = btn("stop", "Stop  (Shift+F5)", self.stop_program, state="disabled")
        sep()
        # Contrôle de l'exécution (débogueur)
        self.btn_cont = btn("continue", "Continue  (F5)", lambda: self.dbg_resume("continue"),
                            state="disabled")
        self.btn_pause = btn("pause", "Pause", self.dbg_pause, state="disabled")
        self.btn_over = btn("step_over", "Step Over  (F10)", lambda: self.dbg_resume("over"),
                            state="disabled")
        self.btn_into = btn("step_into", "Step Into  (F11)", lambda: self.dbg_resume("into"),
                            state="disabled")
        self.btn_out = btn("step_out", "Step Out  (Shift+F11)", lambda: self.dbg_resume("out"),
                           state="disabled")
        sep()
        # Outils
        self.btn_send = btn("send", "Send to TI-89 via USB  (Ctrl+T)", self.send_to_calc)

        # Zone principale : gauche (éditeur + problèmes) / droite (écran, registres, variables)
        main = ttk.Panedwindow(self.root, orient="horizontal")
        left = ttk.Panedwindow(main, orient="vertical")
        main.add(left, weight=3)

        self.editor = CodeEditor(left, on_change=self._on_change, on_cursor=self._on_cursor,
                                 on_gutter_click=self.toggle_breakpoint)
        left.add(self.editor, weight=4)

        bottom = ttk.Notebook(left)
        left.add(bottom, weight=1)
        # Onglet Problèmes
        pf = tk.Frame(bottom, bg=UI["panel"])
        self.problems = ttk.Treeview(pf, columns=("type", "ligne", "message"), show="headings",
                                     selectmode="browse")
        for col, title, w, st in (("type", "Type", 120, False), ("ligne", "Line", 70, False),
                                  ("message", "Message", 800, True)):
            self.problems.heading(col, text=title, anchor="w")
            self.problems.column(col, width=w, stretch=st, anchor="w")
        self.problems.tag_configure("error", foreground=UI["err"])
        self.problems.tag_configure("warning", foreground=UI["warn"])
        self.problems.tag_configure("note", foreground=UI["muted"])
        self.problems.pack(fill="both", expand=True)
        self.problems.bind("<<TreeviewSelect>>", self._on_problem_select)
        bottom.add(pf, text="Problems")
        # Onglet Sortie du compilateur
        of = tk.Frame(bottom, bg=UI["panel"])
        self.output = tk.Text(of, bg=UI["panel"], fg=UI["fg"], font=("DejaVu Sans Mono", 10),
                              relief="flat", height=8, wrap="word", state="disabled")
        self.output.pack(fill="both", expand=True)
        bottom.add(of, text="Output")
        vf = tk.Frame(bottom, bg=UI["panel"])
        self.vars = ttk.Treeview(vf, columns=("valeur", "type"), selectmode="browse")
        self.vars.heading("#0", text="Name", anchor="w")
        self.vars.heading("valeur", text="Value", anchor="w")
        self.vars.heading("type", text="Type", anchor="w")
        self.vars.column("#0", width=200, stretch=False)
        self.vars.column("valeur", width=420, stretch=True)
        self.vars.column("type", width=160, stretch=False)
        self.vars.tag_configure("changed", foreground="#fbbf24")
        self.vars.tag_configure("error", foreground=UI["err"])
        self.vars.tag_configure("group", foreground="#c4b5fd")
        vsb = ttk.Scrollbar(vf, orient="vertical", command=self.vars.yview)
        self.vars.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.vars.pack(fill="both", expand=True)
        self.vars.bind("<<TreeviewOpen>>", self._on_var_open)
        self.vars.bind("<<TreeviewClose>>", self._on_var_close)
        self.var_kids = {}          # iid -> fonction qui produit les enfants
        self.var_expanded = {"L", "G", "C"}
        self.prev_vals = {}
        self.var_reader = None
        bottom.add(vf, text="Variables")
        df = tk.Frame(bottom, bg=UI["panel"])
        self.disasm = tk.Text(df, bg=UI["panel"], fg=UI["fg"], font=("DejaVu Sans Mono", 10),
                              relief="flat", height=8, wrap="none", state="disabled")
        self.disasm.tag_configure("pc", background="#4b4b18", foreground="#ffffff")
        self.disasm.tag_configure("src", foreground="#6a9955")
        self.disasm.pack(fill="both", expand=True)
        bottom.add(df, text="Disassembly")
        self.memview = MemoryView(bottom, self)
        bottom.add(self.memview, text="Memory")
        self.bottom = bottom
        self.mem_tick = 0.0

        right = tk.Frame(main, bg=UI["bg"], width=360)
        main.add(right, weight=1)
        # Écran de la TI-89 : clic dessus = le clavier du PC va à la calculatrice
        lf = ttk.Labelframe(right, text="TI-89 Screen", style="Panel.TLabelframe")
        lf.pack(fill="x", padx=6, pady=(6, 0))
        self.lcd = tk.Label(lf, bg="#c4d4b4", bd=0, takefocus=1, highlightthickness=3,
                            highlightbackground="#c4d4b4", highlightcolor="#c4d4b4")
        self._blank = tk.PhotoImage(width=160 * LCD_SCALE, height=100 * LCD_SCALE)
        self.lcd.configure(image=self._blank)
        self.lcd.pack(padx=6, pady=(6, 2))
        self.lcd.bind("<Button-1>", lambda e: self.lcd.focus_set())
        self.lcd.bind("<KeyPress>", self._on_lcd_key)
        self.lcd.bind("<KeyRelease>", self._on_lcd_key_release)
        self.held = {}              # flèches maintenues : touche TI -> id de relâchement différé
        self.lcd.bind("<FocusIn>", lambda e: self._lcd_hint())
        self.lcd.bind("<FocusOut>", lambda e: self._lcd_hint())
        self.emu_status = tk.Label(lf, text="Starting the emulated calculator…",
                                   bg=UI["panel"], fg=UI["muted"], font=("DejaVu Sans", 9),
                                   anchor="w", justify="left")
        self.emu_status.pack(fill="x", padx=6, pady=(0, 6))
        rf = ttk.Labelframe(right, text="68000 Registers", style="Panel.TLabelframe")
        rf.pack(fill="x", padx=6, pady=(6, 0))
        self.regview = RegisterView(rf, symbol_for=self._symbol_for)
        self.regview.pack(fill="x", padx=0, pady=(0, 2))
        self.prev_regs = {}
        # Barre d'état
        status = tk.Frame(self.root, bg="#18191c")
        status.pack(fill="x", side="bottom")
        self.status = tk.Label(status, text="", bg="#18191c", fg=UI["muted"], anchor="w",
                               font=("DejaVu Sans", 10), padx=8, pady=3)
        self.status.pack(side="left", fill="x", expand=True)
        self.cursor_label = tk.Label(status, text="", bg="#18191c", fg=UI["muted"],
                                     font=("DejaVu Sans", 10), padx=8)
        self.cursor_label.pack(side="right")
        self.opt_label = tk.Label(status, text="", bg="#18191c", fg="#93c5fd", cursor="hand2",
                                  font=("DejaVu Sans Mono", 9, "bold"), padx=8)
        self.opt_label.pack(side="right")
        self.opt_label.bind("<Button-1>", lambda e: self._opt_cycle())
        self.opt_tip = Tooltip(self.opt_label, "")
        self._opt_show()
        self.file_label = tk.Label(status, text="", bg="#18191c", fg="#5d616b",
                                   font=("DejaVu Sans", 9), padx=8)
        self.file_label.pack(side="right")
        main.pack(fill="both", expand=True)   # après la barre d'état, pour qu'elle reste visible

    def _build_menu(self):
        mopts = dict(tearoff=0, bg="#2b2d31", fg="#d4d4d4", activebackground="#3b82f6",
                     activeforeground="white", disabledforeground="#6b707a", bd=0)
        bar = tk.Menu(self.root, **mopts)
        f = tk.Menu(bar, **mopts)
        f.add_command(label="New C Program", accelerator="Ctrl+N", command=self.new_file)
        f.add_command(label="New Assembly Program (GNU as)", command=lambda: self.new_file("gas"))
        f.add_command(label="New Assembly Program (A68k)", command=lambda: self.new_file("a68k"))
        f.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_dialog)
        f.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        f.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self.save_as)
        f.add_separator()
        f.add_command(label="Quit", command=self.quit)
        bar.add_cascade(label="File", menu=f)
        p = tk.Menu(bar, **mopts)
        p.add_command(label="Build", accelerator="F7", command=self.compile)
        p.add_command(label="Run in Emulator", accelerator="F5", command=self.run_program)
        p.add_command(label="Debug", accelerator="F6", command=self.debug_program)
        p.add_command(label="Stop", accelerator="Shift+F5", command=self.stop_program)
        om = tk.Menu(p, **mopts)
        for level, (label, _tip) in OPT_LEVELS.items():
            om.add_radiobutton(label=f"{label}  ({level})", value=level, variable=self.opt_level,
                               command=self._opt_changed, selectcolor="#3b82f6")
        p.add_cascade(label="Optimization", menu=om)
        p.add_separator()
        p.add_command(label="Send to TI-89 (USB)", accelerator="Ctrl+T",
                      command=self.send_to_calc)
        bar.add_cascade(label="Program", menu=p)
        d = tk.Menu(bar, **mopts)
        d.add_command(label="Continue", accelerator="F5", command=lambda: self.dbg_resume("continue"))
        d.add_command(label="Pause", command=self.dbg_pause)
        d.add_command(label="Step Over", accelerator="F10", command=lambda: self.dbg_resume("over"))
        d.add_command(label="Step Into", accelerator="F11",
                      command=lambda: self.dbg_resume("into"))
        d.add_command(label="Step Out", accelerator="Shift+F11",
                      command=lambda: self.dbg_resume("out"))
        d.add_separator()
        d.add_command(label="Toggle Breakpoint", accelerator="F9",
                      command=lambda: self.toggle_breakpoint(
                          int(self.editor.text.index("insert").split(".")[0])))
        bar.add_cascade(label="Debug", menu=d)
        self.root.configure(menu=bar)

    def _bind_keys(self):
        r = self.root
        r.bind("<F7>", lambda e: self.compile())
        r.bind("<F5>", lambda e: self.dbg_resume("continue") if self._paused() else self.run_program())
        r.bind("<F6>", lambda e: self.debug_program())
        r.bind("<F9>", lambda e: self.toggle_breakpoint(int(self.editor.text.index("insert").split(".")[0])))
        r.bind("<F10>", lambda e: self.dbg_resume("over"))
        r.bind("<F11>", lambda e: self.dbg_resume("into"))
        r.bind("<Shift-F11>", lambda e: self.dbg_resume("out"))
        r.bind("<Shift-F5>", lambda e: self.stop_program())
        r.bind("<Control-b>", lambda e: self.compile())
        r.bind("<Control-s>", lambda e: self.save())
        r.bind("<Control-S>", lambda e: self.save_as())
        r.bind("<Control-o>", lambda e: self.open_dialog())
        r.bind("<Control-n>", lambda e: self.new_file())
        r.bind("<Control-t>", lambda e: self.send_to_calc())

    # ------------------------------------------------------------ fichiers
    def _load_config(self):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_config(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump({"last_file": self.path, "optimize": self.opt_level.get()}, f)
        except OSError:
            pass

    def _confirm_discard(self):
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel("Unsaved changes",
                                      "Save your changes before continuing?")
        if r is None:
            return False
        if r:
            return self.save()
        return True

    def new_file(self, lang="c"):
        if not self._confirm_discard():
            return
        self.path = None
        self.new_lang = lang
        self.editor.language = lang
        self.editor.set(TEMPLATES[lang][0])
        self._set_dirty(False)
        self._clear_problems()
        self._set_status(f"New {LANG_NAMES[lang]} program. Save it (Ctrl+S), then build (F7).")

    def open_dialog(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(initialdir=self._dir(), title="Open a program",
                                       filetypes=[("Sources (C, assembly)", "*.c *.h *.s *.asm"), ("C source", "*.c *.h"),
                                                  ("GNU as assembly", "*.s"), ("A68k assembly", "*.asm"),
                                                  ("All files", "*")])
        if p:
            self.open_file(p)

    def open_file(self, p):
        self.editor.language = language_of(p)
        with open(p, encoding="utf-8", errors="replace") as f:
            self.editor.set(f.read())
        self.path = os.path.abspath(p)
        self._set_dirty(False)
        self._clear_problems()
        self._save_config()
        self._set_status(f"Opened: {self.path}")

    def save(self):
        if not self.path:
            return self.save_as()
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.editor.get())
        self._set_dirty(False)
        self._save_config()
        self._set_status(f"Saved: {self.path}")
        return True

    def save_as(self):
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        lang = language_of(self.path) if self.path else getattr(self, "new_lang", "c")
        ext = TEMPLATES[lang][1]
        p = filedialog.asksaveasfilename(initialdir=self._dir(), defaultextension=ext,
                                         title="Save the program",
                                         filetypes=[(f"{LANG_NAMES[lang]} source", "*" + ext)])
        if not p:
            return False
        name = os.path.splitext(os.path.basename(p))[0]
        if not name.isidentifier() or len(name) > 8:
            messagebox.showwarning("Program name",
                                   "On the TI-89, a program name has at most 8 characters "
                                   "(letters, digits, _) and starts with a letter.\n"
                                   f"\"{name}\" is not valid.")
            return False
        if name.lower() in RESERVED_NAMES:
            messagebox.showwarning("Program name",
                                   f"\"{name}\" is a TI-89 command or function name: "
                                   "the calculator would refuse to run the program "
                                   "(Syntax error). Please choose another name.")
            return False
        self.path = os.path.abspath(p)
        return self.save()

    def _dir(self):
        return os.path.dirname(self.path) if self.path else PROJECTS_DIR

    def _set_dirty(self, d):
        self.dirty = d
        name = os.path.basename(self.path) if self.path else "untitled.c"
        self.root.title(f"{'● ' if d else ''}{name} — IDE TI-89")
        if self.path:
            parts = self.path.split(os.sep)
            shown = os.sep.join(parts[-2:]) if len(parts) > 2 else self.path
            self.file_label.configure(text="…/" + shown)
        else:
            self.file_label.configure(text="(not saved)")

    def _on_change(self):
        if not self.dirty:
            self._set_dirty(True)

    def _on_cursor(self, line, col):
        self.cursor_label.configure(text=f"Ln {line}, Col {col}")

    def quit(self):
        if self._confirm_discard():
            self.root.destroy()

    # ------------------------------------------------------------ compilation
    def compile(self, optimize=None):
        optimize = optimize or self.opt_level.get()
        if self.building:
            return
        if not self.save():
            return
        self.building = True
        self.btn_build.configure(state="disabled")
        self._clear_problems()
        self._set_status("Building…")
        path = self.path
        def work():
            res = build(path, optimize=optimize)
            res.opt = optimize
            self.build_queue.put(res)
        threading.Thread(target=work, daemon=True).start()
        self.root.after(50, self._poll_build)

    def _poll_build(self):
        try:
            res = self.build_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, self._poll_build)
            return
        self.building = False
        self.btn_build.configure(state="normal")
        self.last_build = res
        self._show_build(res)
        action, self.after_build = self.after_build, None
        self.debug_building = False
        if action and res.ok:
            action()
        self._opt_show()

    def _show_build(self, res):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", res.output)
        self.output.configure(state="disabled")
        order = {"error": 0, "warning": 1, "note": 2}
        msgs = sorted(res.messages, key=lambda m: (order.get(m.severity, 3), m.line))
        for m in msgs:
            self.problems.insert("", "end", values=(m.severity, m.line or "", m.text),
                                 tags=(m.severity,))
            if m.line and m.severity in ("error", "warning"):
                self.editor.mark_line(m.line, "error_line" if m.severity == "error" else "warning_line")
        n_err = sum(m.severity == "error" for m in msgs)
        n_warn = sum(m.severity == "warning" for m in msgs)
        if res.ok:
            extra = f", {n_warn} warning(s)" if n_warn else ""
            self._set_status(f"✔ Built: {os.path.basename(res.program)} "
                             f"({res.size} bytes, {getattr(res, 'opt', '')}){extra}",
                             UI["ok"])
        else:
            self._set_status(f"✘ Build failed: {n_err} error(s), {n_warn} warning(s)", UI["err"])
            first = next((m for m in msgs if m.severity == "error" and m.line), None)
            if first:
                self.editor.goto_line(first.line)
        if msgs:
            self.bottom.select(0)

    def _clear_problems(self):
        self.problems.delete(*self.problems.get_children())
        self.editor.clear_marks()

    def _on_problem_select(self, event):
        sel = self.problems.selection()
        if not sel:
            return
        line = self.problems.item(sel[0], "values")[1]
        if line:
            self.editor.goto_line(int(line))

    def _set_status(self, text, color=None):
        self.status.configure(text=text, fg=color or UI["muted"])

    # ------------------------------------------------------------ exécution
    def _needs_build(self, opt=None):
        opt = opt or self.opt_level.get()
        b = self.last_build
        if self.dirty or not b or not b.ok or not os.path.exists(b.program):
            return True
        if getattr(b, "opt", None) != opt:
            return True
        return os.path.getmtime(self.path) > os.path.getmtime(b.program)

    def run_program(self):
        if not self.session.ready:
            self._set_status("The emulated calculator is still starting, try again in a moment.")
            return
        if self.building:
            return
        if self.debugger.state != IDLE:
            self._end_debug()
        if self._needs_build():
            self.after_build = self._launch
            self.compile()
        else:
            self._launch()

    def _release_held(self):
        for k, pending in list(self.held.items()):
            if pending:
                self.root.after_cancel(pending)
        self.held.clear()

    def _launch(self):
        self._release_held()
        try:
            name = self.session.run_program(self.last_build.program)
        except (LoadError, OSError) as e:
            self._set_status(f"✘ Cannot run: {e}", UI["err"])
            return
        self.running = name
        self._update_buttons()
        self.lcd.focus_set()
        self._set_status(f"▶ {name}() started in the emulated calculator. "
                         "Your keyboard now types on the TI-89 (click the editor to get it back).",
                         UI["ok"])

    def stop_program(self):
        self._release_held()
        if self.debugger.state != IDLE:
            self._end_debug()
        elif self.session.ready:
            self.session.restore_state()
        self.running = None
        self._update_buttons()
        self._set_status("Program stopped; calculator reset to the Home screen.")

    # ------------------------------------------------------------ vraie calculatrice
    def send_to_calc(self):
        if self.building or getattr(self, "sending", False):
            return
        if self._needs_build():
            self.after_build = self._start_send
            self.compile()
        else:
            self._start_send()

    def _start_send(self):
        self.sending = True
        self.btn_send.configure(state="disabled")
        path = self.last_build.program
        name = os.path.splitext(os.path.basename(path))[0]
        q = queue.Queue()

        def work():
            try:
                realcalc.send_to_calculator(path, progress=lambda m: q.put(("info", m)))
                q.put(("ok", name))
            except realcalc.SendError as e:
                q.put(("err", str(e)))
            except Exception as e:                       # bibliothèque absente, etc.
                q.put(("err", f"{type(e).__name__} : {e}"))

        def poll():
            try:
                while True:
                    kind, msg = q.get_nowait()
                    if kind == "info":
                        self._set_status("→ " + msg, "#93c5fd")
                        continue
                    self.sending = False
                    self.btn_send.configure(state="normal")
                    if kind == "ok":
                        self._set_status(f"✔ {msg} sent to the TI-89 Titanium. On the calculator, "
                                         f"type {msg}() on the Home screen.", UI["ok"])
                    else:
                        self._set_status("✘ Send failed: " + msg.splitlines()[0], UI["err"])
                        self._show_text_in_output("Sending to the TI-89 Titanium: failed\n\n" + msg)
                    return
            except queue.Empty:
                self.root.after(100, poll)

        self._set_status("→ Looking for the calculator…", "#93c5fd")
        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, poll)

    def _show_text_in_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")
        self.bottom.select(1)

    # ------------------------------------------------------------ débogage
    def debug_program(self):
        if not self.session.ready:
            self._set_status("The emulated calculator is still starting, try again in a moment.")
            return
        if self.building:
            return
        if self.debugger.state != IDLE:
            self._end_debug()
        # Le débogage se fait sur une compilation sans optimisation (-O0) :
        # le code suit alors fidèlement les lignes C et les variables restent en mémoire.
        if self._needs_build("-O0"):
            self.after_build = self._launch_debug
            self.debug_building = True          # l'indicateur affiche « -O0 debug »
            self._opt_show()
            self.compile("-O0")
        else:
            self._launch_debug()

    def _launch_debug(self):
        self._release_held()
        b = self.last_build
        lang = language_of(self.path)
        info = None
        try:
            if lang == "a68k":
                if not b.listing:
                    self._set_status("✘ No A68k listing for debugging", UI["err"])
                    return
                info = dbginfo.from_a68k_listing(b.listing, self.path, b.program)
            elif not b.debug:
                self._set_status("✘ No debug information (.dbg)", UI["err"])
                return
            name = self.debugger.start(b.program, b.debug, self.path, set(), info=info)
        except (LoadError, OSError, ValueError) as e:
            self._set_status(f"✘ Cannot debug: {e}", UI["err"])
            return
        # Recale les points d'arrêt sur des lignes qui portent du code
        bps = set()
        for ln in self.editor.breakpoints:
            snap = self.debugger.info.breakable_line(ln)
            if snap:
                bps.add(snap)
        self.editor.breakpoints = bps
        self.editor.redraw_gutter()
        self.debugger.user_lines = set(bps)
        self.running = name
        self.prev_regs = {}
        self.prev_vals = {}
        if self.debugger.info.is_asm:
            # Assembleur : données étiquetées et constantes lues dans le source
            self.var_reader = None
            self.asm_var_reader = AsmVariableReader(self.debugger, self.editor.get(),
                                                    language_of(self.path))
        else:
            self.var_reader = VariableReader(self.debugger)
            self.asm_var_reader = None
        self.memview.reset()
        self._update_buttons()
        first = "the first instruction" if self.debugger.info.is_asm else "the first line of _main"
        where = "the first breakpoint" if bps else first
        self._set_status(f"🐞 Debugging {name}(): running to {where}…", "#c4b5fd")

    def _end_debug(self):
        self.debugger.stop()
        self.editor.clear_marks("exec_line")
        self._show_registers(None)
        self._show_disasm(None)
        self._show_variables(clear=True)
        self.running = None
        self._update_buttons()

    def _paused(self):
        return self.debugger.state == PAUSED

    def dbg_resume(self, mode):
        d = self.debugger
        if d.state == IDLE:
            if mode != "continue":
                self.debug_program()          # F10/F11 démarre le débogage
            return
        if d.state != PAUSED:
            return
        if mode == "out" and d.offset() is None:
            self._set_status("Step Out only works inside your own code.", UI["warn"])
            return
        d.resume(mode)
        if d.state == PAUSED:                 # pas d'une instruction (assembleur) : déjà fait
            self._on_debug_paused()
            return
        self.editor.clear_marks("exec_line")
        self._update_buttons()
        self._set_status("▶ Running…" if mode == "continue" else "▶ Stepping…", "#c4b5fd")

    def dbg_pause(self):
        if self.debugger.state == RUNNING:
            self.debugger.pause()
            self._on_debug_paused()

    def toggle_breakpoint(self, line):
        bps = self.editor.breakpoints
        if line in bps:
            bps.discard(line)
        else:
            info = self.debugger.info if self.debugger.state != IDLE else None
            if info:
                snap = info.breakable_line(line)
                if snap is None:
                    self._set_status(f"No code at line {line} or after it.", UI["warn"])
                    return
                line = snap
            bps.add(line)
        self.editor.redraw_gutter()
        if self.debugger.state != IDLE:
            self.debugger.set_breakpoints(bps)

    def _on_debug_paused(self):
        d = self.debugger
        line = d.current_line()
        self.editor.clear_marks("exec_line")
        regs = d.registers()
        if line:
            self.editor.mark_line(line, "exec_line")
            self.editor.text.see(f"{line}.0")
            if d.info.is_asm:
                lbl = self._asm_label_above(line)
                where = f" — after label {lbl}" if lbl else ""
            else:
                fn = d.info.function_for(d.offset())
                fn = fn[1:] if fn and fn.startswith("__") else fn
                where = f" — in {fn}()" if fn else ""
            self._set_status(f"‖ Paused at line {line} ({d.stop_reason}){where}", "#fbbf24")
        else:
            self._set_status(f"‖ Paused inside AMS (PC=${regs['PC']:06X}), outside your program. "
                             "F10/F11: go to the next line of your code.", "#fbbf24")
        self._show_registers(regs)
        self._show_disasm(d.disassembly())
        self._show_variables()
        self.memview.refresh(paused=True)
        if self.bottom.index("current") not in (2, 3, 4):
            self.bottom.select(2)
        self._update_buttons()

    def _asm_label_above(self, line):
        """Étiquette (non locale) la plus proche au-dessus de la ligne, en assembleur."""
        import re
        lines = self.editor.get().split("\n")
        for i in range(min(line, len(lines)) - 1, -1, -1):
            m = re.match(r"^([A-Za-z_][\w.]*):?(?:\s|$)", lines[i])
            if m and not lines[i].lstrip().startswith((";", "|", "*")):
                return m.group(1)
        return None

    def _opt_show(self):
        level = self.opt_level.get()
        label, tip = OPT_LEVELS[level]
        if getattr(self, "debug_building", False) or self.debugger.state != IDLE:
            # Session de débogage : le programme est compilé sans optimisation
            self.opt_label.configure(text="-O0 debug", fg="#c4b5fd")
            self.opt_tip.text = ("Debugging: the program is built with -O0 (no optimization),\n"
                                 "so that stepping follows the C lines and variables stay in memory.\n"
                                 f"Build / Run / Send use your setting: {label} ({level}).")
            return
        self.opt_label.configure(text=level, fg="#93c5fd")
        self.opt_tip.text = (f"Optimization: {label} ({level}), {tip}.\n"
                             "Used by Build, Run and Send. Debug always uses -O0.\n"
                             "Click to change (or Program > Optimization).")

    def _opt_changed(self):
        self._opt_show()
        self._save_config()
        level = self.opt_level.get()
        self._set_status(f"Optimization: {OPT_LEVELS[level][0]} ({level}). "
                         "The next Build / Run / Send will rebuild with it.")

    def _opt_cycle(self):
        levels = list(OPT_LEVELS)
        self.opt_level.set(levels[(levels.index(self.opt_level.get()) + 1) % len(levels)])
        self._opt_changed()

    def _update_buttons(self):
        if hasattr(self, "opt_label"):
            self._opt_show()
        st = self.debugger.state
        ready = self.session.ready
        def en(b, on):
            b.configure(state="normal" if on else "disabled")
        en(self.btn_run, ready)
        en(self.btn_debug, ready)
        en(self.btn_stop, ready and (self.running is not None or st != IDLE))
        en(self.btn_cont, st == PAUSED)
        en(self.btn_pause, st == RUNNING)
        en(self.btn_over, st == PAUSED)
        en(self.btn_into, st == PAUSED)
        en(self.btn_out, st == PAUSED)

    def _show_registers(self, regs, new_pause=True):
        self.regview.show(regs, new_pause)

    def _symbol_for(self, addr):
        """« étiquette+décalage » si l'adresse tombe dans le programme débogué."""
        d = self.debugger
        if d.state == IDLE or d.base is None or d.info is None:
            return None
        off = addr - d.base
        if not 0 <= off < d.info.text_size + 0x1000:
            return None
        best = None
        for name, v in d.info.symbols.items():
            if v <= off and (best is None or v > best[1] or
                             (v == best[1] and name.startswith("_") < best[0].startswith("_"))):
                best = (name, v)
        if best is None:
            return None
        return best[0] if off == best[1] else f"{best[0]}+{off - best[1]}"

    # ------------------------------------------------------------ variables
    def _show_variables(self, clear=False):
        tv = self.vars
        tv.delete(*tv.get_children())
        self.var_kids.clear()
        if clear:
            return
        if self.var_reader is None:
            ar = getattr(self, "asm_var_reader", None)
            if ar is None or self.debugger.state == IDLE:
                return
            self._new_vals = {}
            data, consts = ar.data_nodes(), ar.const_nodes()
            tv.insert("", "end", iid="D", text="Data (labels)", open=True, tags=("group",),
                      values=("" if data else "no dc / ds / .byte / .word... data in the source", ""))
            for n in data:
                self._insert_var("D", n)
            tv.insert("", "end", iid="C", text="Constants (equ)", open="C" in self.var_expanded,
                      tags=("group",))
            for n in consts:
                self._insert_var("C", n)
            for iid in sorted(self.var_expanded, key=lambda x: x.count("/")):
                if tv.exists(iid) and iid not in ("D", "C"):
                    self._populate(iid)
                    tv.item(iid, open=True)
            self.prev_vals.update(self._new_vals)
            return
        self._new_vals = {}
        fn, loc = self.var_reader.locals()
        if fn:
            tv.insert("", "end", iid="L", text=f"Locals — {fn}()", open=True, tags=("group",))
            for n in loc:
                self._insert_var("L", n)
        tv.insert("", "end", iid="G", text="Globals", open="G" in self.var_expanded, tags=("group",))
        for n in self.var_reader.globals():
            self._insert_var("G", n)
        # Redéplie ce qui l'était (les parents d'abord)
        for iid in sorted(self.var_expanded, key=lambda x: x.count("/") + x.count(".")):
            if tv.exists(iid) and iid not in ("L", "G"):
                self._populate(iid)
                tv.item(iid, open=True)
        self.prev_vals.update(self._new_vals)

    def _insert_var(self, parent, n):
        tags = []
        if n.error:
            tags.append("error")
        elif n.path in self.prev_vals and self.prev_vals[n.path] != n.value:
            tags.append("changed")
        self._new_vals[n.path] = n.value
        if self.vars.exists(n.path):
            return
        self.vars.insert(parent, "end", iid=n.path, text=n.name, values=(n.value, n.type_name),
                         tags=tags)
        if n.children:
            self.var_kids[n.path] = n.children
            self.vars.insert(n.path, "end", iid=n.path + "#…", text="…")

    def _populate(self, iid):
        kids = self.var_kids.pop(iid, None)
        if kids is None:
            return
        if self.vars.exists(iid + "#…"):
            self.vars.delete(iid + "#…")
        try:
            for n in kids():
                self._insert_var(iid, n)
        except Exception as e:
            self.vars.insert(iid, "end", text=f"‹{e}›", tags=("error",))

    def _on_var_open(self, event):
        iid = self.vars.focus()
        self.var_expanded.add(iid)
        self._populate(iid)
        self.prev_vals.update(getattr(self, "_new_vals", {}))

    def _on_var_close(self, event):
        self.var_expanded.discard(self.vars.focus())

    def _show_disasm(self, lines):
        t = self.disasm
        t.configure(state="normal")
        t.delete("1.0", "end")
        for addr, txt, ln, cur in lines or ():
            mark = "=>" if cur else "  "
            t.insert("end", f"{mark} ${addr:06X}  {txt:<34}", "pc" if cur else "")
            if ln:
                t.insert("end", f"; line {ln}", "src")
            t.insert("end", "\n")
        t.configure(state="disabled")

    def _on_lcd_key(self, event):
        if self.debugger.state != IDLE and event.keysym in ("F5", "F6", "F9", "F10", "F11"):
            return None      # laissé aux raccourcis du débogueur
        if event.keysym in HOLD_KEYS and self.session.ready:
            # Flèches : transmises en direct, enfoncées tant que la touche du PC l'est
            # (indispensable pour les jeux)
            k = HOLD_KEYS[event.keysym]
            pending = self.held.get(k)
            if pending:                         # répétition automatique du clavier : on ignore
                self.root.after_cancel(pending)
                self.held[k] = None
            elif k not in self.held:
                self.held[k] = None
                self.session.calc.key_down(k)
            return "break"
        seq = KEYSYM_MAP.get(event.keysym)
        if seq is None and event.char:
            seq = CHAR_MAP.get(event.char)
        if seq and self.session.ready:
            self.session.keys.type_keys(seq)
        return "break"      # n'envoie pas la touche aux raccourcis de l'IDE (F5, F7...)

    def _on_lcd_key_release(self, event):
        k = HOLD_KEYS.get(event.keysym)
        if k in self.held:
            # Relâchement différé : la répétition automatique envoie relâché/enfoncé en rafale
            def release(k=k):
                self.held.pop(k, None)
                self.session.calc.key_up(k)
            self.held[k] = self.root.after(60, release)
        return "break"

    def _lcd_hint(self):
        if not self.session.ready:
            return
        if self.root.focus_get() is self.lcd:
            txt = "⌨ Keyboard → TI-89\nEnter=ENTER  Esc=ESC  Home=HOME  F1…F5"
        else:
            txt = "Click the screen to type\non the TI-89 keyboard."
        self.emu_status.configure(text=txt)

    def _emu_loop(self):
        s = self.session
        now = time.perf_counter()
        dt = min(now - self.last_wall, 0.25)
        self.last_wall = now
        t0 = now
        if not s.ready:
            # Démarrage d'AMS à pleine vitesse (environ 1 s), sans bloquer l'interface
            while time.perf_counter() - t0 < 0.03:
                if s.boot_step(64):
                    self._update_buttons()
                    self._lcd_hint()
                    break
        if s.ready and self.debugger.state != PAUSED:
            # Frappe automatique (lancement du programme) : pleine vitesse ; sinon temps réel
            fast = s.keys.busy() and len(s.keys.queue) > 2
            if fast:
                while time.perf_counter() - t0 < 0.03 and s.keys.busy():
                    if not self._emu_tick():
                        break
                self.emu_debt = 0.0
            else:
                self.emu_debt = min(self.emu_debt + dt * 256, 64)
                while self.emu_debt >= 1 and time.perf_counter() - t0 < 0.04:
                    if not self._emu_tick():
                        self.emu_debt = 0.0
                        break
                    self.emu_debt -= 1
        self._refresh_lcd()
        if (s.ready and self.debugger.state != PAUSED and now - self.mem_tick > 0.5
                and self.bottom.index("current") == 4):
            self.mem_tick = now
            self.memview.refresh()
        self.root.after(15, self._emu_loop)

    def _emu_tick(self):
        """Un tick d'émulation ; retourne False si le débogueur vient de se mettre en pause."""
        s = self.session
        d = self.debugger
        if d.state == RUNNING and d.mode in ("asm_over", "asm_out"):
            if d.asm_step():
                self._on_debug_paused()
                return False
            return True
        done = s.tick()
        if done is False and s.calc.core.bp_hit:
            if self.debugger.state in (STARTING, RUNNING) and self.debugger.on_stop():
                self._on_debug_paused()
                return False
        return True

    def _refresh_lcd(self):
        # Image moyennée dans le temps : rend les niveaux de gris comme sur la vraie
        # calculatrice (alternance rapide de plusieurs images)
        data = self.session.lcd_levels() if self.session.ready else self.session.lcd_bytes()
        if data == self.last_lcd:
            return
        self.last_lcd = data
        ppm = (self.session.levels_ppm(data) if self.session.ready
               else self.session.lcd_ppm(data))
        img = tk.PhotoImage(data=ppm, format="PPM")
        if LCD_SCALE > 1:
            img = img.zoom(LCD_SCALE, LCD_SCALE)
        self.lcd.configure(image=img)
        self.lcd.image = img

    def run(self):
        self.root.mainloop()
