"""
Panneau des registres 68000.

  - un sélecteur de format en tête : Hex, Dec (non signé), ±Dec (signé), Bin ;
  - un clic sur un registre affiche son détail en dessous : valeurs en .l / .w / .b
    (les trois tailles des instructions 68000), non signées et signées, binaire avec
    numéros de bits, caractères ASCII, symbole le plus proche pour une adresse ;
    pour SR : chaque bit nommé (T, S, masque d'interruption, X N Z V C).
Les valeurs modifiées depuis la pause précédente sont en jaune.
"""
import tkinter as tk

COL = {"bg": "#232428", "fg": "#d4d4d4", "muted": "#8b8f98", "changed": "#fbbf24",
       "sel": "#264f78", "btn": "#2b2d31", "btn_on": "#3b82f6", "ruler": "#5d616b"}
FONT = ("DejaVu Sans Mono", 9)
FORMATS = (("hex", "Hex"), ("dec", "Dec"), ("sdec", "±Dec"), ("bin", "Bin"))
ORDER = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]


def _signed(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def _bin(v, bits):
    s = f"{v & ((1 << bits) - 1):0{bits}b}"
    return " ".join(s[i:i + 4] for i in range(0, bits, 4))


class RegisterView(tk.Frame):
    def __init__(self, master, symbol_for=None):
        """symbol_for(adresse) -> « étiquette+décalage » ou None (pour A0-A7, PC)."""
        super().__init__(master, bg=COL["bg"])
        self.symbol_for = symbol_for or (lambda a: None)
        self.fmt = tk.StringVar(value="hex")
        self.selected = None
        self.cur = None             # registres affichés
        self.prev = {}              # registres à la pause précédente (pour le jaune)

        bar = tk.Frame(self, bg=COL["bg"])
        bar.pack(fill="x", padx=6, pady=(4, 2))
        tk.Label(bar, text="Format", bg=COL["bg"], fg=COL["muted"],
                 font=("DejaVu Sans", 9)).pack(side="left", padx=(0, 6))
        for key, label in FORMATS:
            tk.Radiobutton(bar, text=label, value=key, variable=self.fmt, indicatoron=0,
                           command=self._render, font=("DejaVu Sans", 9), width=5,
                           bg=COL["btn"], fg=COL["fg"], selectcolor=COL["btn_on"],
                           activebackground="#3a3d44", activeforeground="white",
                           relief="flat", bd=0, highlightthickness=0, pady=2
                           ).pack(side="left", padx=1)

        self.text = tk.Text(self, bg=COL["bg"], fg=COL["fg"], font=FONT, relief="flat",
                            height=10, width=46, state="disabled", cursor="hand2", wrap="none")
        self.text.pack(fill="x", padx=6)
        self.text.tag_configure("name", foreground=COL["muted"])
        self.text.tag_configure("changed", foreground=COL["changed"])
        self.text.tag_configure("selected", background=COL["sel"])
        self.text.bind("<MouseWheel>", lambda e: self.text.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.text.bind("<Button-4>", lambda e: self.text.yview_scroll(-1, "units"))
        self.text.bind("<Button-5>", lambda e: self.text.yview_scroll(1, "units"))

        tk.Frame(self, bg="#3a3c42", height=1).pack(fill="x", padx=6, pady=(4, 2))
        self.detail = tk.Text(self, bg=COL["bg"], fg=COL["fg"], font=FONT, relief="flat",
                              height=6, width=46, state="disabled", cursor="arrow", wrap="none")
        self.detail.pack(fill="x", padx=6, pady=(0, 4))
        self.detail.tag_configure("name", foreground=COL["muted"])
        self.detail.tag_configure("title", foreground="#93c5fd")
        self.detail.tag_configure("ruler", foreground=COL["ruler"])
        self.detail.tag_configure("changed", foreground=COL["changed"])
        self.show(None)

    # ------------------------------------------------------------ API
    def show(self, regs, new_pause=True):
        """Affiche les registres. new_pause : nouvelle pause du débogueur (le jaune
        compare alors avec la pause précédente)."""
        if regs is None:
            self.cur, self.prev = None, {}
        else:
            if new_pause:
                self.prev = dict(self.cur) if self.cur else {}
            self.cur = dict(regs)
        self._render()

    # ------------------------------------------------------------ affichage
    def _fmt(self, name, v):
        f = self.fmt.get()
        if name == "SR":
            v &= 0xFFFF
            return {"hex": f"{v:04X}", "dec": f"{v}", "sdec": f"{_signed(v, 16)}",
                    "bin": _bin(v, 16)}[f]
        if name == "PC":
            v &= 0xFFFFFF
            return {"hex": f"{v:06X}", "dec": f"{v}", "sdec": f"{v}", "bin": _bin(v, 24)}[f]
        return {"hex": f"{v:08X}", "dec": f"{v}", "sdec": f"{_signed(v, 32)}",
                "bin": _bin(v, 32)}[f]

    def _put(self, name, width=0):
        t = self.text
        v = self.cur[name]
        tags = [f"reg_{name}"]
        if self.prev and self.prev.get(name) != v:
            tags.append("changed")
        if name == self.selected:
            tags.append("selected")
        t.insert("end", f"{name:<3}", tuple(["name"] + tags))
        txt = self._fmt(name, v)
        t.insert("end", txt.rjust(width) if width and self.fmt.get() != "hex" else txt, tuple(tags))
        t.tag_bind(f"reg_{name}", "<Button-1>", lambda e, n=name: self._select(n))

    def _render(self):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if self.cur is None:
            t.insert("end", "\n  Available while the program\n  is paused (debugging).", "name")
            t.configure(state="disabled")
            self._render_detail()
            return
        f = self.fmt.get()
        if f == "bin":
            # Un registre par ligne (32 bits = 39 caractères)
            for name in ORDER + ["PC", "SR"]:
                self._put(name)
                if name == "SR":
                    t.insert("end", "\n" + " " * 3 + "T.S. .III ...X NZVC", "name")
                t.insert("end", "\n")
        else:
            w = 11 if f != "hex" else 0
            for i in range(8):
                self._put(f"D{i}", w)
                t.insert("end", "   ")
                self._put(f"A{i}", w)
                t.insert("end", "\n")
            self._put("PC", w)
            t.insert("end", "   ")
            self._put("SR", 6 if w else 0)
            sr = self.cur["SR"]
            flags = "  ".join(f"{n}={(sr >> b) & 1}" for n, b in
                              (("X", 4), ("N", 3), ("Z", 2), ("V", 1), ("C", 0)))
            t.insert("end", f"\n{flags}")
        t.configure(state="disabled")
        self._render_detail()

    def _select(self, name):
        self.selected = None if self.selected == name else name
        self._render()

    def _render_detail(self):
        d = self.detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        name = self.selected
        if self.cur is None or name is None:
            d.insert("end", "Click a register to see it in\nbinary, decimal (.b / .w / .l), ASCII.",
                     "name")
            d.configure(state="disabled")
            return
        v = self.cur[name]
        changed = "changed" if self.prev and self.prev.get(name) != v else ""
        if name == "SR":
            self._detail_sr(d, v & 0xFFFF, changed)
        else:
            bits = 24 if name == "PC" else 32
            v &= (1 << bits) - 1
            d.insert("end", f"{name} = ${v:0{bits // 4}X}", ("title", changed))
            sym = self.symbol_for(v) if name[0] in "AP" else None
            if sym:
                d.insert("end", f"   → {sym}", "name")       # adresse dans le programme
            else:
                raw = v.to_bytes(4, "big")
                asc = "".join(chr(c) if 32 <= c < 127 else "." for c in raw)
                d.insert("end", f"   ascii '{asc}'", "name")
            d.insert("end", "\n      unsigned      signed\n", "name")
            for suffix, b in ((".l", 32), (".w", 16), (".b", 8)):
                u = v & ((1 << b) - 1)
                d.insert("end", f"{suffix:<5} ", "name")
                d.insert("end", f"{u:<13} {_signed(u, b)}\n")
            d.insert("end", "bin ", "name")
            d.insert("end", _bin(v, bits))
        d.configure(state="disabled")

    def _detail_sr(self, d, sr, changed):
        def bit(n, b, desc, width):
            d.insert("end", f"{n}={(sr >> b) & 1} ")
            d.insert("end", f"{desc:<{width}}", "name")
        d.insert("end", f"SR = ${sr:04X}", ("title", changed))
        d.insert("end", "   status register, " + ("supervisor" if sr & 0x2000 else "user")
                 + " mode\n", "name")
        d.insert("end", "bin " + _bin(sr, 16) + "\n")
        d.insert("end", "    T.S. .III ...X NZVC\n", "ruler")
        bit("T", 15, "trace", 10); bit("S", 13, "supervisor", 12)
        d.insert("end", f"I={(sr >> 8) & 7} "); d.insert("end", "int. mask\n", "name")
        bit("X", 4, "extend", 10); bit("N", 3, "negative", 12); bit("Z", 2, "zero", 0)
        d.insert("end", "\n")
        bit("V", 1, "overflow", 10); bit("C", 0, "carry", 0)
