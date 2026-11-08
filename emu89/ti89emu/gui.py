"""
Interface tkinter de l'émulateur TI-89 Titanium.

- Écran LCD agrandi (x4 par défaut), clavier dessiné avec des étiquettes lisibles :
  touche principale en gros, fonction 2nd en bleu, fonction ◆ en vert, lettre ALPHA en blanc.
- Clavier du PC : on utilise le caractère produit (event.char), donc n'importe quelle
  disposition (AZERTY, QWERTY...) fonctionne. Chaque caractère est traduit en séquence
  de touches TI (ex. « { » -> 2nd puis « ( »).
- Souris : clic maintenu = touche maintenue (répétition automatique d'AMS).
"""
import time
import tkinter as tk
from tkinter import filedialog

from .hardware import TI89Titanium, LCD_W, LCD_H, LCD_ADDR, LCD_STRIDE, TICK_CYCLES

# --------------------------------------------------------------------------- couleurs
BG = "#2b2d31"
BEZEL = "#1b1c1f"
LCD_ON = (0x1E, 0x23, 0x1E)
LCD_OFF = (0xC4, 0xD4, 0xB4)
COL_2ND = "#7fb8ff"
COL_DIAM = "#a6dd6a"
COL_ALPHA = "#f0f0f0"

KEY_STYLES = {
    # nom du style : (fond, texte)
    "num": ("#1c1c1e", "#ffffff"),
    "op": ("#5b5e66", "#ffffff"),
    "fn": ("#45484f", "#ffffff"),
    "2nd": ("#6d9fd6", "#0d1b2a"),
    "diam": ("#b9de8c", "#1b2a0d"),
    "alpha": ("#d9d9d9", "#222222"),
    "apps": ("#1c1c1e", "#c792ea"),
    "enter": ("#5b5e66", "#ffffff"),
}

# --------------------------------------------------------------------------- clavier
# (identifiant TI, texte principal, 2nd, ◆, alpha, style, colonne, ligne, largeur en colonnes)
# Disposition de la TI-89 Titanium ; étiquettes relevées sur la façade.
LAYOUT = [
    ("f1", "F1", "F6", "Y=", "", "fn", 0, 0, 1),
    ("f2", "F2", "F7", "WINDOW", "", "fn", 1, 0, 1),
    ("f3", "F3", "F8", "GRAPH", "", "fn", 2, 0, 1),
    ("f4", "F4", "", "TBLSET", "", "fn", 3, 0, 1),
    ("f5", "F5", "", "TABLE", "", "fn", 4, 0, 1),

    ("2nd", "2nd", "", "CUT", "", "2nd", 0, 1, 1),
    ("shift", "↑", "", "COPY", "", "op", 1, 1, 1),
    ("esc", "ESC", "QUIT", "PASTE", "", "op", 2, 1, 1),
    ("diamond", "◆", "", "", "", "diam", 0, 2, 1),
    ("alpha", "ALPHA", "a-LOCK", "", "", "alpha", 1, 2, 1),
    ("apps", "APPS", "SWITCH", "", "", "apps", 2, 2, 1),

    ("home", "HOME", "CUSTOM", "", "", "op", 0, 3, 1),
    ("mode", "MODE", "▸", "_", "", "op", 1, 3, 1),
    ("catalog", "CATALOG", "i", "∞", "", "op", 2, 3, 1),
    ("backspace", "←", "INS", "DEL", "", "op", 3, 3, 1),
    ("clear", "CLEAR", "", "", "", "op", 4, 3, 1),

    ("x", "X", "LN", "eˣ", "", "op", 0, 4, 1),
    ("y", "Y", "SIN", "SIN⁻¹", "", "op", 1, 4, 1),
    ("z", "Z", "COS", "COS⁻¹", "", "op", 2, 4, 1),
    ("t", "T", "TAN", "TAN⁻¹", "", "op", 3, 4, 1),
    ("^", "^", "π", "θ", "", "op", 4, 4, 1),

    ("=", "=", "'", "≠", "A", "op", 0, 5, 1),
    ("(", "(", "{", "", "B", "op", 1, 5, 1),
    (")", ")", "}", "", "C", "op", 2, 5, 1),
    (",", ",", "[", "", "D", "op", 3, 5, 1),
    ("/", "÷", "]", "", "E", "op", 4, 5, 1),

    ("|", "|", "°", "", "F", "op", 0, 6, 1),
    ("7", "7", "∫", "", "G", "num", 1, 6, 1),
    ("8", "8", "d", "", "H", "num", 2, 6, 1),
    ("9", "9", ";", "", "I", "num", 3, 6, 1),
    ("*", "×", "√", "", "J", "op", 4, 6, 1),

    ("ee", "EE", "∠", "KEY", "K", "op", 0, 7, 1),
    ("4", "4", ":", "", "L", "num", 1, 7, 1),
    ("5", "5", "MATH", "", "M", "num", 2, 7, 1),
    ("6", "6", "MEM", "", "N", "num", 3, 7, 1),
    ("-", "−", "VAR-LINK", "", "O", "op", 4, 7, 1),

    ("sto", "STO▸", "RCL", "", "P", "op", 0, 8, 1),
    ("1", "1", "\"", "", "Q", "num", 1, 8, 1),
    ("2", "2", "\\", "", "R", "num", 2, 8, 1),
    ("3", "3", "UNITS", "", "S", "num", 3, 8, 1),
    ("+", "+", "CHAR", "", "U", "op", 4, 8, 1),

    ("on", "ON", "OFF", "", "", "op", 0, 9, 1),
    ("0", "0", "<", "", "V", "num", 1, 9, 1),
    (".", ".", ">", "", "W", "num", 2, 9, 1),
    ("(-)", "(−)", "ANS", "", "␣", "num", 3, 9, 1),
    ("enter", "ENTER", "ENTRY", "≈", "", "enter", 4, 9, 1),
]

# Caractère tapé au clavier du PC -> séquence de touches TI
CHAR_MAP = {
    "+": ["+"], "-": ["-"], "*": ["*"], "/": ["/"], "^": ["^"], "=": ["="],
    "(": ["("], ")": [")"], ",": [","], ".": ["."], "|": ["|"],
    "{": ["2nd", "("], "}": ["2nd", ")"], "[": ["2nd", ","], "]": ["2nd", "/"],
    "'": ["2nd", "="], '"': ["2nd", "1"], ":": ["2nd", "4"], ";": ["2nd", "9"],
    "\\": ["2nd", "2"], "<": ["2nd", "0"], ">": ["2nd", "."], "°": ["2nd", "|"],
    "_": ["diamond", "mode"], " ": ["alpha", "(-)"], "π": ["2nd", "^"],
}
ALPHA_KEYS = {
    "a": "=", "b": "(", "c": ")", "d": ",", "e": "/", "f": "|", "g": "7", "h": "8",
    "i": "9", "j": "*", "k": "ee", "l": "4", "m": "5", "n": "6", "o": "-", "p": "sto",
    "q": "1", "r": "2", "s": "3", "u": "+", "v": "0", "w": ".",
}
for _c in "0123456789":
    CHAR_MAP[_c] = [_c]
for _c, _k in ALPHA_KEYS.items():
    CHAR_MAP[_c] = ["alpha", _k]
    CHAR_MAP[_c.upper()] = ["shift", _k]
for _c in "xyzt":
    CHAR_MAP[_c] = [_c]
    CHAR_MAP[_c.upper()] = ["shift", _c]

# Touches spéciales du PC (keysym) -> séquence de touches TI
KEYSYM_MAP = {
    "Return": ["enter"], "KP_Enter": ["enter"], "BackSpace": ["backspace"],
    "Delete": ["diamond", "backspace"], "Escape": ["esc"],
    "Up": ["up"], "Down": ["down"], "Left": ["left"], "Right": ["right"],
    "F1": ["f1"], "F2": ["f2"], "F3": ["f3"], "F4": ["f4"], "F5": ["f5"],
    "F6": ["2nd", "f1"], "F7": ["2nd", "f2"], "F8": ["2nd", "f3"],
    "F9": ["apps"], "F10": ["mode"], "F11": ["catalog"], "F12": ["on"],
    "Home": ["home"], "Tab": ["sto"], "End": ["clear"],
    "KP_Add": ["+"], "KP_Subtract": ["-"], "KP_Multiply": ["*"], "KP_Divide": ["/"],
    "KP_Decimal": ["."], "KP_Separator": ["."],
}
for _i in range(10):
    KEYSYM_MAP[f"KP_{_i}"] = [str(_i)]

# Octet LCD (8 pixels) -> 8 pixels RGB
_PIXEL_LUT = [b"".join(bytes(LCD_ON) if (_b >> (7 - _i)) & 1 else bytes(LCD_OFF) for _i in range(8))
              for _b in range(256)]

# Une touche tapée au clavier du PC reste enfoncée au moins PRESS_TICKS (en 1/256 s)
# ET jusqu'à ce qu'AMS l'ait lue MIN_SEEN fois sur le port clavier : si AMS est occupé
# (interruptions masquées), la touche n'est donc pas perdue. Sécurité : PRESS_MAX_TICKS.
PRESS_TICKS = 8
MIN_SEEN = 6
PRESS_MAX_TICKS = 512
RELEASE_TICKS = 8     # pause minimale entre deux touches
# Avant la touche suivante, on attend qu'AMS soit revenu en attente de touche
# (CPU en veille via $600005), au plus RELEASE_MAX_TICKS.
RELEASE_MAX_TICKS = 256


class EmulatorApp:
    def __init__(self, rom_path, scale=4):
        self.calc = TI89Titanium(rom_path)
        self.scale = scale
        self.root = tk.Tk()
        self.root.title("TI-89 Titanium — émulateur Python")
        self.root.configure(bg=BG)
        self.turbo = False
        self.booting = True          # pleine vitesse jusqu'à la fin de l'installation d'AMS
        self.key_queue = []          # séquence de (touche) à taper
        self.key_state = None        # [touche, ticks restants appuyée, ticks restants relâchée]
        self.mouse_key = None
        self.pending_release = None  # [touche, ticks] clic relâché avant qu'AMS l'ait lu
        self.last_lcd = None
        self.emu_ticks_target = 0.0
        self.last_wall = time.perf_counter()
        self.speed_samples = []
        self._build_ui()
        self.root.bind("<KeyPress>", self.on_pc_key)
        self.root.after(1, self.loop)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="both", expand=True, padx=16, pady=12)

        left = tk.Frame(top, bg=BG)
        left.pack(side="left", anchor="n")
        bezel = tk.Frame(left, bg=BEZEL, padx=14, pady=14)
        bezel.pack()
        self.lcd_label = tk.Label(bezel, bg="#c4d4b4", bd=0)
        self.lcd_label.pack()

        bar = tk.Frame(left, bg=BG)
        bar.pack(fill="x", pady=(10, 0))
        btn = dict(bg="#3a3d44", fg="white", activebackground="#50545d",
                   activeforeground="white", relief="flat", padx=10, pady=4,
                   font=("DejaVu Sans", 10))
        tk.Button(bar, text="Reset", command=self.do_reset, **btn).pack(side="left")
        self.turbo_btn = tk.Button(bar, text="Turbo : non", command=self.toggle_turbo, **btn)
        self.turbo_btn.pack(side="left", padx=6)
        tk.Button(bar, text="Capture PNG", command=self.do_screenshot, **btn).pack(side="left")
        self.status = tk.Label(left, text="", bg=BG, fg="#a0a4ad",
                               font=("DejaVu Sans Mono", 10), anchor="w")
        self.status.pack(fill="x", pady=(8, 0))
        legend = tk.Frame(left, bg=BG)
        legend.pack(fill="x", pady=(8, 0))
        for txt, col in (("2nd", COL_2ND), ("◆", COL_DIAM), ("ALPHA", COL_ALPHA)):
            tk.Label(legend, text=f"■ {txt}", bg=BG, fg=col,
                     font=("DejaVu Sans", 10, "bold")).pack(side="left", padx=(0, 14))
        tk.Label(left, text="Clavier du PC : tapez directement (AZERTY ou QWERTY).\n"
                            "Entrée=ENTER  Échap=ESC  Suppr=DEL  F1-F5  F6-F8=2nd F1-F3\n"
                            "F9=APPS  F10=MODE  F11=CATALOG  F12=ON  Début=HOME  Tab=STO▸",
                 bg=BG, fg="#7d818a", font=("DejaVu Sans", 9), justify="left"
                 ).pack(anchor="w", pady=(8, 0))

        self.kb = tk.Canvas(top, bg=BG, highlightthickness=0)
        self.kb.pack(side="left", padx=(20, 0), anchor="n")
        self._draw_keyboard()

    def _draw_keyboard(self):
        kw, kh = 92, 40          # taille d'une touche
        gx, top_lbl = 14, 20     # espace horizontal, hauteur des étiquettes au-dessus
        pitch_y = kh + top_lbl + 6
        cv = self.kb
        f_main = ("DejaVu Sans", 13, "bold")
        f_small = ("DejaVu Sans", 9, "bold")
        self.key_items = {}

        def rounded(x0, y0, x1, y1, r, **kw_):
            pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
                   x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
            return cv.create_polygon(pts, smooth=True, **kw_)

        def draw_key(kid, main, s2, sd, sa, style, x0, y0, w, h, main_font=f_main):
            fill, fg = KEY_STYLES[style]
            shape = rounded(x0, y0, x0 + w, y0 + h, 12, fill=fill, outline="#0e0f11", width=2)
            text = cv.create_text(x0 + w / 2, y0 + h / 2, text=main, fill=fg, font=main_font)
            ly = y0 - 10
            if s2:
                cv.create_text(x0 + 2, ly, text=s2, fill=COL_2ND, font=f_small, anchor="w")
            if sd:
                cv.create_text(x0 + w - (14 if sa else 2), ly, text=sd, fill=COL_DIAM,
                               font=f_small, anchor="e")
            if sa:
                cv.create_text(x0 + w - 2, ly, text=sa, fill=COL_ALPHA, font=f_small, anchor="e")
            for item in (shape, text):
                cv.tag_bind(item, "<ButtonPress-1>", lambda e, k=kid: self.mouse_down(k))
                cv.tag_bind(item, "<ButtonRelease-1>", lambda e, k=kid: self.mouse_up(k))
            self.key_items[kid] = (shape, fill)

        x_org, y_org = 4, top_lbl
        for kid, main, s2, sd, sa, style, col, row, span in LAYOUT:
            x0 = x_org + col * (kw + gx)
            y0 = y_org + row * pitch_y
            draw_key(kid, main, s2, sd, sa, style, x0, y0, kw * span + gx * (span - 1), kh)

        # Pavé de flèches (colonnes 3-4, lignes 1-2)
        cx = x_org + 3 * (kw + gx) + (2 * kw + gx) / 2
        cy = y_org + 1 * pitch_y + (pitch_y + kh) / 2
        aw, ah = 56, 34
        arrows = [("up", "▲", cx - aw / 2, cy - ah - 14),
                  ("down", "▼", cx - aw / 2, cy + 14),
                  ("left", "◀", cx - aw - 14, cy - ah / 2),
                  ("right", "▶", cx + 14, cy - ah / 2)]
        for kid, sym, x0, y0 in arrows:
            draw_key(kid, sym, "", "", "", "op", x0, y0, aw, ah, ("DejaVu Sans", 12, "bold"))

        width = x_org + 5 * kw + 4 * gx + 6
        height = y_org + 10 * pitch_y
        cv.configure(width=width, height=height)

    def _highlight(self, kid, on):
        if kid in self.key_items:
            shape, fill = self.key_items[kid]
            self.kb.itemconfigure(shape, fill="#e8b84a" if on else fill)

    # ------------------------------------------------------------ entrées
    def mouse_down(self, kid):
        if self.pending_release:
            self._release_pending()
        self.mouse_key = kid
        self.calc.key_down(kid)
        self._highlight(kid, True)

    def mouse_up(self, kid):
        kid = self.mouse_key
        if not kid:
            return
        self.mouse_key = None
        if self.calc.key_seen_count(kid) >= MIN_SEEN:
            self.calc.key_up(kid)
            self._highlight(kid, False)
        else:
            # Clic trop bref : AMS ne l'a pas encore lu (il était peut-être occupé).
            # On garde la touche enfoncée jusqu'à ce qu'il l'ait vue.
            self.pending_release = [kid, 0]

    def _release_pending(self):
        kid = self.pending_release[0]
        self.calc.key_up(kid)
        self._highlight(kid, False)
        self.pending_release = None

    def _input_tick(self):
        """Appelé avant chaque tick d'émulation : gère clics et touches tapées."""
        pr = self.pending_release
        if pr:
            pr[1] += 1
            if self.calc.key_seen_count(pr[0]) >= MIN_SEEN or pr[1] >= PRESS_MAX_TICKS:
                self._release_pending()
        self._process_key_queue()

    def on_pc_key(self, event):
        seq = KEYSYM_MAP.get(event.keysym)
        if seq is None and event.char:
            seq = CHAR_MAP.get(event.char)
        if seq:
            self.key_queue.extend(seq)
            return "break"
        return None

    def _process_key_queue(self):
        st = self.key_state
        if st is None:
            if not self.key_queue:
                return
            kid = self.key_queue.pop(0)
            self.calc.key_down(kid)
            self._highlight(kid, True)
            self.key_state = [kid, 0, RELEASE_TICKS, True]
            return
        if st[3]:                                   # touche encore enfoncée
            st[1] += 1
            seen = self.calc.key_seen_count(st[0])
            if (st[1] >= PRESS_TICKS and seen >= MIN_SEEN) or st[1] >= PRESS_MAX_TICKS:
                self.calc.key_up(st[0])
                self._highlight(st[0], False)
                st[3] = False
        else:
            st[2] -= 1
            if (st[2] <= 0 and self.calc.halted) or st[2] <= RELEASE_TICKS - RELEASE_MAX_TICKS:
                self.key_state = None

    # ------------------------------------------------------------ boutons
    def do_reset(self):
        self.calc.reset()
        self.booting = True

    def toggle_turbo(self):
        self.turbo = not self.turbo
        self.turbo_btn.configure(text=f"Turbo : {'oui' if self.turbo else 'non'}")

    def do_screenshot(self):
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("Image PNG", "*.png")])
        if path:
            from .screenshot import save_png
            save_png(path, self.calc.lcd_pixels(), scale=self.scale)

    # ------------------------------------------------------------ boucle
    def loop(self):
        now = time.perf_counter()
        dt = min(now - self.last_wall, 0.25)
        self.last_wall = now
        fast = self.turbo or self.booting
        t_start = time.perf_counter()
        ran = 0
        if fast:
            # Pleine vitesse pendant ~30 ms par image
            while time.perf_counter() - t_start < 0.03:
                self._input_tick()
                self.calc.tick()
                ran += 1
            self.emu_ticks_target = 0.0
            if self.booting and self.calc.halted and self.calc.ticks > 256:
                self.booting = False     # AMS est arrivé au bureau, retour au temps réel
        else:
            self.emu_ticks_target += dt * 256
            while self.emu_ticks_target >= 1 and time.perf_counter() - t_start < 0.05:
                self._input_tick()
                self.calc.tick()
                self.emu_ticks_target -= 1
                ran += 1
            self.emu_ticks_target = min(self.emu_ticks_target, 64)
        self._refresh_lcd()
        self.speed_samples.append((dt, ran))
        if len(self.speed_samples) >= 30:
            tot_dt = sum(s[0] for s in self.speed_samples) or 1e-9
            tot_ticks = sum(s[1] for s in self.speed_samples)
            self.speed_samples.clear()
            mode = "démarrage" if self.booting else ("turbo" if self.turbo else "temps réel")
            self.status.configure(
                text=f"Vitesse : {tot_ticks / 256 / tot_dt:5.2f}x  ({mode})   "
                     f"PC=${self.calc.core.pc:06X}  {'veille' if self.calc.halted else 'actif'}")
        self.root.after(16, self.loop)

    def _refresh_lcd(self):
        data = self.calc.lcd_bytes()
        if data == self.last_lcd:
            return
        self.last_lcd = data
        lut = _PIXEL_LUT
        rows = []
        for y in range(LCD_H):
            line = data[y * LCD_STRIDE: y * LCD_STRIDE + LCD_W // 8]
            rows.append(b"".join(lut[b] for b in line))
        ppm = b"P6 %d %d 255\n" % (LCD_W, LCD_H) + b"".join(rows)
        img = tk.PhotoImage(data=ppm, format="PPM").zoom(self.scale, self.scale)
        self.lcd_label.configure(image=img)
        self.lcd_label.image = img

    def run(self):
        self.root.mainloop()
