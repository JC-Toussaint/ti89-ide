"""Éditeur de code C : numéros de ligne, coloration syntaxique, indentation automatique."""
import re
import tkinter as tk
from .fonts import SANS, MONO
import tkinter.font as tkfont

THEME = {
    "bg": "#1e1f22", "fg": "#d4d4d4", "gutter_bg": "#26282c", "gutter_fg": "#6b707a",
    "cursor": "#ffffff", "select": "#264f78", "current_line": "#2a2d33",
    "keyword": "#569cd6", "type": "#4ec9b0", "preproc": "#c586c0", "string": "#ce9178",
    "comment": "#6a9955", "number": "#b5cea8", "error_line": "#5a1d1d",
    "warning_line": "#4d3d14", "exec_line": "#1d5c3d", "breakpoint": "#e51400",
    "exec_arrow": "#4ade80", "label": "#dcdcaa", "register": "#4ec9b0", "mnemonic": "#569cd6",
}

KEYWORDS = ("auto break case continue default do else enum extern for goto if inline "
            "register return sizeof static struct switch typedef union volatile while asm").split()
TYPES = ("void char short int long float double signed unsigned const "
         "BOOL HANDLE ESI SYM_ENTRY SCR_RECT WINDOW INT_HANDLER").split()

_TOKEN_RE = re.compile(
    r"(?P<comment>//[^\n]*|/\*.*?(?:\*/|\Z))"
    r"|(?P<string>\"(?:\\.|[^\"\\\n])*\"?|'(?:\\.|[^'\\\n])*'?)"
    r"|(?P<preproc>^[ \t]*#[^\n]*)"
    r"|(?P<number>\b(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)[uUlLfF]*\b)"
    r"|(?P<word>\b[A-Za-z_]\w*\b)",
    re.S | re.M)
_KW = set(KEYWORDS)
_TY = set(TYPES)

# --- Assembleur GNU as (syntaxe TIGCC : registres %d0, commentaires « | »)
_GAS_LINE_RE = re.compile(
    r"^(?P<label>[ \t]*[A-Za-z_.$][\w.$]*:)?[ \t]*(?P<mnem>\.?[A-Za-z_][\w.]*)?")
_GAS_TOKEN_RE = re.compile(
    r"(?P<comment>\|[^\n]*|/\*.*?(?:\*/|\Z)|^[ \t]*#[^\n]*)"
    r"|(?P<string>\"(?:\\.|[^\"\\\n])*\"?|'(?:\\.|[^'\\\n])')"
    r"|(?P<register>%[A-Za-z][A-Za-z0-9]*)"
    r"|(?P<number>#?-?(?:0[xX][0-9a-fA-F]+|\$[0-9a-fA-F]+|0[bB][01]+|\b\d+\b))",
    re.S | re.M)

# --- Assembleur A68k (syntaxe Motorola : registres d0, commentaires « ; » ou « * » en colonne 1)
_A68K_LINE_RE = re.compile(
    r"^(?P<label>[A-Za-z_.\\@][\w.\\@:]*:?)?[ \t]+(?P<mnem>[A-Za-z_][\w.]*)?")
_A68K_TOKEN_RE = re.compile(
    r"(?P<comment>;[^\n]*|^\*[^\n]*)"
    r"|(?P<string>\"[^\"\n]*\"?|'[^'\n]*'?)"
    r"|(?P<register>\b(?:[dDaA][0-7]|[sS][pP]|[pP][cC]|[sS][rR]|[cC][cC][rR]|[uU][sS][pP])\b)"
    r"|(?P<number>#?-?(?:\$[0-9a-fA-F]+|%[01]+|\b\d+\b))",
    re.M)
_ASM_DIRECTIVES = {"include", "xdef", "xref", "equ", "set", "dc", "dc.b", "dc.w", "dc.l", "ds",
                   "ds.b", "ds.w", "ds.l", "even", "end", "macro", "endm", "section", "cseg",
                   "dseg", "bss", "org", "rorg", "align", "if", "ifd", "ifnd", "else", "endc",
                   "rept", "endr", "incbin", "opt", "public", "cnop", "rom_call", "rom_call2"}


class CodeEditor(tk.Frame):
    """Zone de texte avec marge (numéros de ligne + points d'arrêt)."""

    def __init__(self, master, on_change=None, on_cursor=None, on_gutter_click=None):
        super().__init__(master, bg=THEME["bg"])
        self.on_change = on_change
        self.on_cursor = on_cursor
        self.on_gutter_click = on_gutter_click
        self.font = tkfont.Font(family=MONO, size=11)
        self.breakpoints = set()
        self.language = "c"          # "c", "gas" (GNU as) ou "a68k"
        self.exec_line = None        # ligne où le programme est en pause (flèche dans la marge)
        self._hl_job = None

        self.gutter = tk.Canvas(self, width=56, bg=THEME["gutter_bg"], highlightthickness=0)
        self.gutter.pack(side="left", fill="y")
        self.vbar = tk.Scrollbar(self, orient="vertical")
        self.vbar.pack(side="right", fill="y")
        self.text = tk.Text(
            self, font=self.font, undo=True, maxundo=-1, wrap="none",
            bg=THEME["bg"], fg=THEME["fg"], insertbackground=THEME["cursor"],
            selectbackground=THEME["select"], relief="flat", padx=8, pady=4,
            tabs=(self.font.measure("  "),), yscrollcommand=self._on_yscroll,
            borderwidth=0, highlightthickness=0, insertwidth=2)
        self.text.pack(side="left", fill="both", expand=True)
        self.vbar.configure(command=self.text.yview)

        t = self.text
        for tag in ("comment", "string", "preproc", "number", "keyword", "type",
                    "label", "register", "mnemonic"):
            t.tag_configure(tag, foreground=THEME[tag])
        t.tag_configure("current_line", background=THEME["current_line"])
        t.tag_configure("error_line", background=THEME["error_line"])
        t.tag_configure("warning_line", background=THEME["warning_line"])
        t.tag_configure("exec_line", background=THEME["exec_line"])
        t.tag_raise("sel")
        for tag in ("error_line", "warning_line", "exec_line"):
            t.tag_lower(tag)
        t.tag_lower("current_line")

        t.bind("<<Modified>>", self._on_modified)
        t.bind("<KeyRelease>", lambda e: self._cursor_moved())
        t.bind("<ButtonRelease-1>", lambda e: self._cursor_moved())
        t.bind("<Return>", self._auto_indent)
        t.bind("<Tab>", self._tab)
        t.bind("<ISO_Left_Tab>", self._untab)
        t.bind("<Configure>", lambda e: self.redraw_gutter())
        t.bind("<Control-z>", lambda e: self._undo())
        t.bind("<Control-y>", lambda e: self._redo())
        t.bind("<Control-Z>", lambda e: self._redo())
        self.gutter.bind("<Button-1>", self._gutter_click)

    # --------------------------------------------------------------- contenu
    def get(self):
        return self.text.get("1.0", "end-1c")

    def set(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.text.mark_set("insert", "1.0")
        self.highlight()
        self._cursor_moved()

    def goto_line(self, line):
        self.text.mark_set("insert", f"{line}.0")
        self.text.see(f"{line}.0")
        self.text.focus_set()
        self._cursor_moved()

    # ---------------------------------------------------------- marquages
    def clear_marks(self, *tags):
        for tag in tags or ("error_line", "warning_line"):
            self.text.tag_remove(tag, "1.0", "end")
        if "exec_line" in tags:
            self.exec_line = None
            self.redraw_gutter()

    def mark_line(self, line, tag):
        self.text.tag_add(tag, f"{line}.0", f"{line}.0 lineend+1c")
        if tag == "exec_line":
            self.exec_line = line
            self.redraw_gutter()

    # ------------------------------------------------------------- édition
    def _undo(self):
        try:
            self.text.edit_undo()
        except tk.TclError:
            pass
        return "break"

    def _redo(self):
        try:
            self.text.edit_redo()
        except tk.TclError:
            pass
        return "break"

    def _auto_indent(self, event):
        t = self.text
        line = t.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", line).group(0)
        if line.rstrip().endswith("{"):
            indent += "  "
        t.insert("insert", "\n" + indent)
        t.see("insert")
        return "break"

    def _tab(self, event):
        t = self.text
        if t.tag_ranges("sel"):
            first = int(t.index("sel.first").split(".")[0])
            last = int(t.index("sel.last").split(".")[0])
            for ln in range(first, last + 1):
                t.insert(f"{ln}.0", "  ")
        else:
            t.insert("insert", "  ")
        return "break"

    def _untab(self, event):
        t = self.text
        if t.tag_ranges("sel"):
            first = int(t.index("sel.first").split(".")[0])
            last = int(t.index("sel.last").split(".")[0])
        else:
            first = last = int(t.index("insert").split(".")[0])
        for ln in range(first, last + 1):
            if t.get(f"{ln}.0", f"{ln}.2") == "  ":
                t.delete(f"{ln}.0", f"{ln}.2")
        return "break"

    # ------------------------------------------------------- notifications
    def _on_modified(self, event=None):
        if self.text.edit_modified():
            if self.on_change:
                self.on_change()
            if self._hl_job:
                self.after_cancel(self._hl_job)
            self._hl_job = self.after(150, self.highlight)
            self.text.edit_modified(False)
            self.redraw_gutter()

    def _cursor_moved(self):
        t = self.text
        t.tag_remove("current_line", "1.0", "end")
        t.tag_add("current_line", "insert linestart", "insert lineend+1c")
        if self.on_cursor:
            line, col = t.index("insert").split(".")
            self.on_cursor(int(line), int(col) + 1)

    def _on_yscroll(self, first, last):
        self.vbar.set(first, last)
        self.redraw_gutter()

    # ------------------------------------------------------- coloration
    def set_language(self, lang):
        self.language = lang
        self.highlight()

    def _highlight_asm(self, content):
        t = self.text
        gas = self.language == "gas"
        line_re = _GAS_LINE_RE if gas else _A68K_LINE_RE
        tok_re = _GAS_TOKEN_RE if gas else _A68K_TOKEN_RE
        # Étiquettes et mnémoniques / directives (en début de ligne)
        pos = 0
        for line in content.split("\n"):
            stripped = line.lstrip()
            if stripped and not stripped.startswith((";", "|", "*" if not gas else "\0", "#")):
                m = line_re.match(line)
                if m:
                    if m.group("label") and m.group("label").strip():
                        t.tag_add("label", f"1.0+{pos + m.start('label')}c", f"1.0+{pos + m.end('label')}c")
                    mn = m.group("mnem")
                    if mn:
                        low = mn.lower()
                        tag = "preproc" if (low.startswith(".") or low in _ASM_DIRECTIVES
                                            or low.split(".")[0] in _ASM_DIRECTIVES) else "mnemonic"
                        t.tag_add(tag, f"1.0+{pos + m.start('mnem')}c", f"1.0+{pos + m.end('mnem')}c")
            pos += len(line) + 1
        for m in tok_re.finditer(content):
            kind = m.lastgroup
            if kind in ("label",):
                continue
            t.tag_add(kind, f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        t.tag_raise("comment")
        t.tag_raise("sel")

    def highlight(self):
        self._hl_job = None
        t = self.text
        content = self.get()
        for tag in ("comment", "string", "preproc", "number", "keyword", "type",
                    "label", "register", "mnemonic"):
            t.tag_remove(tag, "1.0", "end")
        if self.language in ("gas", "a68k"):
            return self._highlight_asm(content)
        for m in _TOKEN_RE.finditer(content):
            kind = m.lastgroup
            if kind == "word":
                w = m.group()
                kind = "keyword" if w in _KW else "type" if w in _TY else None
                if not kind:
                    continue
            t.tag_add(kind, f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    # ---------------------------------------------------------- marge
    def redraw_gutter(self):
        g = self.gutter
        g.delete("all")
        t = self.text
        idx = t.index("@0,0")
        while True:
            dline = t.dlineinfo(idx)
            if dline is None:
                break
            y = dline[1] + dline[3] // 2
            ln = int(idx.split(".")[0])
            if ln in self.breakpoints:
                g.create_oval(6, y - 6, 18, y + 6, fill=THEME["breakpoint"], outline="")
            if ln == self.exec_line:
                g.create_polygon(4, y - 6, 4, y + 6, 20, y, fill=THEME["exec_arrow"], outline="")
            g.create_text(50, y, anchor="e", text=str(ln), fill=THEME["gutter_fg"],
                          font=self.font)
            nxt = t.index(f"{idx}+1line")
            if nxt == idx:
                break
            idx = nxt

    def _gutter_click(self, event):
        idx = self.text.index(f"@0,{event.y}")
        ln = int(idx.split(".")[0])
        if self.on_gutter_click:
            self.on_gutter_click(ln)
