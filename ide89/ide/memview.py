"""Vue mémoire (vidage hexadécimal) de la calculatrice émulée."""
import re
import tkinter as tk
from tkinter import ttk, simpledialog

BYTES_PER_ROW = 16
ROWS = 16
COL = {"bg": "#232428", "fg": "#d4d4d4", "muted": "#8b8f98", "addr": "#569cd6",
       "changed": "#fbbf24", "ascii": "#ce9178", "err": "#f87171", "unmapped": "#55585f"}

REG_NAMES = {f"d{i}": f"D{i}" for i in range(8)}
REG_NAMES.update({f"a{i}": f"A{i}" for i in range(8)})
REG_NAMES.update({"sp": "A7", "pc": "PC", "usp": "USP", "ssp": "SSP"})


class MemoryView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=COL["bg"])
        self.app = app
        self.base = 0x4C00
        self.ref_ram = None             # copie de la RAM à la pause précédente (octets en jaune)

        bar = tk.Frame(self, bg=COL["bg"])
        bar.pack(fill="x", padx=4, pady=(4, 2))
        tk.Label(bar, text="Address", bg=COL["bg"], fg=COL["muted"],
                 font=("DejaVu Sans", 9)).pack(side="left")
        self.expr = tk.StringVar(value="4C00")
        e = tk.Entry(bar, textvariable=self.expr, width=22, bg="#1e1f22", fg=COL["fg"],
                     insertbackground="white", relief="flat", font=("DejaVu Sans Mono", 10))
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda ev: self.go())
        ttk.Button(bar, text="Go", style="Small.TButton", command=self.go).pack(side="left")
        self.follow = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Follow", variable=self.follow, bg=COL["bg"], fg=COL["muted"],
                       selectcolor="#1e1f22", activebackground=COL["bg"], activeforeground="white",
                       font=("DejaVu Sans", 9), bd=0, highlightthickness=0).pack(side="left", padx=6)
        for name in ("SP", "A0", "A1", "A2", "A3", "A4", "A5", "A6", "PC", "LCD"):
            ttk.Button(bar, text=name, style="Small.TButton", width=4,
                       command=lambda n=name: self.go("4C00" if n == "LCD" else n.lower())
                       ).pack(side="left", padx=1)
        self.msg = tk.Label(bar, text="", bg=COL["bg"], fg=COL["err"], font=("DejaVu Sans", 9))
        self.msg.pack(side="left", padx=8)

        self.text = tk.Text(self, bg=COL["bg"], fg=COL["fg"], font=("DejaVu Sans Mono", 10),
                            relief="flat", wrap="none", height=ROWS, cursor="arrow")
        self.text.pack(fill="both", expand=True, padx=4)
        self.text.tag_configure("addr", foreground=COL["addr"])
        self.text.tag_configure("changed", foreground=COL["changed"])
        self.text.tag_configure("ascii", foreground=COL["ascii"])
        self.text.tag_configure("unmapped", foreground=COL["unmapped"])
        self.text.bind("<MouseWheel>", lambda ev: self.scroll(-1 if ev.delta > 0 else 1))
        self.text.bind("<Button-4>", lambda ev: self.scroll(-1))
        self.text.bind("<Button-5>", lambda ev: self.scroll(1))
        self.text.bind("<Prior>", lambda ev: self.scroll(-ROWS))
        self.text.bind("<Next>", lambda ev: self.scroll(ROWS))
        self.text.bind("<Double-Button-1>", self._edit)
        self.text.bind("<Key>", lambda ev: "break" if ev.keysym not in ("Prior", "Next") else None)
        tk.Label(self, text="Double-click a byte to change it (RAM only).  Mouse wheel / PgUp / PgDn "
                            "to scroll.  Address: hex (4C00, $4C00, 0x4C00), register (a0, sp, pc), "
                            "label or global variable, e.g. a6-8.",
                 bg=COL["bg"], fg=COL["muted"], font=("DejaVu Sans", 8), anchor="w").pack(fill="x", padx=4)

    # ------------------------------------------------------------ adresses
    def _symbols(self):
        d = self.app.debugger
        if d.info is None or d.base is None:
            return {}
        return {k.lower(): (d.base + v) & 0xFFFFFF for k, v in d.info.symbols.items()}

    def evaluate(self, expr):
        regs = self.app.debugger.registers() if self.app.session.ready else {}
        syms = self._symbols()
        total = 0
        for sign, term in re.findall(r"([+-]?)\s*([^+\-\s]+)", expr.strip()):
            t = term.lower()
            if t in REG_NAMES and regs:
                v = regs[REG_NAMES[t]]
            elif t in syms:
                v = syms[t]
            else:
                t = t[1:] if t.startswith("$") else t
                t = t[2:] if t.startswith("0x") else t
                if not re.fullmatch(r"[0-9a-f]+", t):
                    raise ValueError(f"unknown name or number: {term}")
                v = int(t, 16)
            total = total - v if sign == "-" else total + v
        return total & 0xFFFFFF

    def go(self, expr=None):
        if expr is not None:
            self.expr.set(expr)
        try:
            self.base = self.evaluate(self.expr.get()) & ~0xF
            self.msg.configure(text="")
        except ValueError as e:
            self.msg.configure(text=str(e))
            return
        self.refresh()

    def scroll(self, rows):
        self.follow.set(False)
        self.base = (self.base + rows * BYTES_PER_ROW) & 0xFFFFF0
        self.refresh()
        return "break"

    # ------------------------------------------------------------ affichage
    def refresh(self, paused=False):
        """Redessine. paused=True : appelé à une pause du débogueur ; les octets de RAM
        modifiés depuis la pause précédente sont affichés en jaune."""
        s = self.app.session
        if not s.ready:
            return
        if self.follow.get():
            try:
                self.base = self.evaluate(self.expr.get()) & ~0xF
            except ValueError:
                pass
        data = s.peek(self.base, BYTES_PER_ROW * ROWS)
        ref = self.ref_ram
        t = self.text
        y = t.yview()[0]
        t.delete("1.0", "end")
        for r in range(ROWS):
            a0 = (self.base + r * BYTES_PER_ROW) & 0xFFFFFF
            t.insert("end", f"${a0:06X}  ", "addr")
            row = data[r * BYTES_PER_ROW:(r + 1) * BYTES_PER_ROW]
            for k, b in enumerate(row):
                a = (a0 + k) & 0xFFFFFF
                if b is None:
                    t.insert("end", "-- ", "unmapped")
                else:
                    is_ram = a < 0x40000 or 0x200000 <= a < 0x600000
                    changed = ref is not None and is_ram and ref[a & 0x3FFFF] != b
                    t.insert("end", f"{b:02X} ", "changed" if changed else "")
                if k == 7:
                    t.insert("end", " ")
            t.insert("end", " ")
            asc = "".join(chr(b) if b is not None and 32 <= b < 127 else "." for b in row)
            t.insert("end", asc + "\n", "ascii")
        t.yview_moveto(y)
        if paused:
            self.ref_ram = bytes(s.calc.core.ram)

    def reset(self):
        self.ref_ram = None

    # ------------------------------------------------------------ édition
    def _edit(self, event):
        idx = self.text.index(f"@{event.x},{event.y}")
        line, col = (int(x) for x in idx.split("."))
        # « $XXXXXX  » = 9 caractères, puis 3 caractères par octet (+1 après le 8e)
        c = col - 9
        if c < 0:
            return "break"
        k = c // 3 if c < 24 else (c - 1) // 3
        if not 0 <= k < BYTES_PER_ROW:
            return "break"
        addr = (self.base + (line - 1) * BYTES_PER_ROW + k) & 0xFFFFFF
        old = self.app.session.peek(addr, 1)[0]
        if old is None:
            return "break"
        val = simpledialog.askstring("Change memory", f"New value for ${addr:06X} "
                                                      f"(hex, currently {old:02X}):",
                                     parent=self)
        if val:
            try:
                v = int(val.strip().lstrip("$").removeprefix("0x"), 16)
                if not 0 <= v <= 0xFF:
                    raise ValueError
            except ValueError:
                self.msg.configure(text=f"invalid byte value: {val}")
                return "break"
            if not self.app.session.poke(addr, v):
                self.msg.configure(text="only RAM can be changed")
                return "break"
            self.refresh()
            if self.app.debugger.state != "idle":
                self.app._show_registers(self.app.debugger.registers())
        return "break"
