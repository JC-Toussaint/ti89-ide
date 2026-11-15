"""Completion in the editor (Ctrl+Space): a list of the words that start like the word
being typed: keywords and functions of the language, names declared in the program."""
import re
import tkinter as tk

from .fonts import MONO

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\$?")


def basic_words(source):
    """Basic89: keywords, functions, constants, and the names of the program
    (variables, parameters, TYPE fields, CONSTs, SUBs, FUNCTIONs, TYPEs, IMAGEs, TILESETs)."""
    from basic89 import compiler as c
    words = set(c.KEYWORDS) | set(c.TYPES) | set(c.BUILTINS) | set(c.STR_FUNCS) | set(c.COLORS)
    words |= {"KEYDOWN", "TRUE", "FALSE", "INT", "ROUND", "SQR", "SIN", "COS", "WIDTH",
              "HEIGHT", "COLLIDE", "EXISTS", "ABS", "MIN", "MAX", "UBOUND", "LBOUND"}
    words |= {"KEY_" + k for k in c.KEYS}
    code = re.sub(r"'.*|\"[^\"\n]*\"?", "", source)          # without comments and texts
    names = set(re.findall(r"([A-Za-z_]\w*)\s*(?:\([^)\n]*\))?\s+AS\s", code, re.I))
    for consts in re.findall(r"\bCONST\b(.*)", code, re.I):
        names |= set(re.findall(r"([A-Za-z_]\w*)\s*=", consts))
    names |= set(re.findall(r"\b(?:SUB|FUNCTION|TYPE|IMAGE|TILESET)\s+([A-Za-z_]\w*\$?)", code, re.I))
    return words | {n for n in names if n.upper() not in c.KEYWORDS}


def generic_words(source, keywords=()):
    """C and assembly: the language's keywords and the words already in the file."""
    return set(keywords) | {w for w in _WORD.findall(source) if len(w) >= 3}


class Completer:
    def __init__(self, editor, provider):
        self.ed = editor
        self.t = editor.text
        self.provider = provider       # function -> set of words
        self.win = None
        self.items = []
        self.start = None
        self.t.bind("<Control-space>", self.open)
        self.t.bind("<Up>", lambda e: self._move(-1), add="+")
        self.t.bind("<Down>", lambda e: self._move(1), add="+")
        self.t.bind("<Escape>", lambda e: self.close() if self.active else None, add="+")
        self.t.bind("<FocusOut>", lambda e: self.t.after(150, self._focus_check), add="+")
        self.t.bind("<Button-1>", lambda e: self.close(), add="+")

    @property
    def active(self):
        return self.win is not None

    def _prefix(self):
        line = self.t.get("insert linestart", "insert")
        m = re.search(r"[A-Za-z_][A-Za-z0-9_]*\$?$", line)
        if not m:
            return "insert", ""
        return f"insert-{len(m.group())}c", m.group()

    def _candidates(self, pre):
        low = pre.lower()
        out = [w for w in self.provider() if w.lower().startswith(low) and w.lower() != low]
        return sorted(out, key=lambda w: (len(w) > len(pre) + 12, w.lower()))

    def open(self, event=None):
        self.start, pre = self._prefix()
        items = self._candidates(pre)
        if not items:
            self.close()
            self.t.bell()
            return "break"
        if len(items) == 1 and pre:
            self._insert(items[0])
            return "break"
        self._show(items)
        return "break"

    def _show(self, items):
        self.items = items
        if self.win is None:
            self.win = tk.Toplevel(self.t)
            self.win.overrideredirect(True)
            self.lb = tk.Listbox(self.win, font=(MONO, 10), bg="#252526", fg="#d4d4d4",
                                 selectbackground="#04395e", selectforeground="white",
                                 activestyle="none", relief="solid", bd=1, highlightthickness=0,
                                 exportselection=False)
            self.lb.pack(fill="both", expand=True)
            self.lb.bind("<Double-Button-1>", lambda e: self.accept())
            self.lb.bind("<ButtonRelease-1>", lambda e: self.t.focus_set())
        self.lb.delete(0, "end")
        for w in items[:200]:
            self.lb.insert("end", w)
        self.lb.configure(height=min(len(items), 10), width=max(12, max(len(w) for w in items[:200]) + 2))
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(0)
        self.lb.see(0)
        bbox = self.t.bbox("insert")
        if bbox:
            x = self.t.winfo_rootx() + bbox[0]
            y = self.t.winfo_rooty() + bbox[1] + bbox[3] + 2
            self.win.geometry(f"+{x}+{y}")
        self.win.lift()

    def refresh(self):
        """While the list is open, after each key: filter again (or close)."""
        if not self.active:
            return
        start, pre = self._prefix()
        items = self._candidates(pre) if pre else []
        if not items:
            self.close()
        else:
            self.start = start
            self._show(items)

    def _move(self, d):
        if not self.active:
            return None
        cur = self.lb.curselection()
        i = (cur[0] if cur else 0) + d
        i = max(0, min(i, self.lb.size() - 1))
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(i)
        self.lb.see(i)
        return "break"

    def accept(self):
        if not self.active:
            return None
        cur = self.lb.curselection()
        if cur:
            self._insert(self.lb.get(cur[0]))
        self.close()
        return "break"

    def _insert(self, word):
        start, pre = self._prefix()
        self.t.delete(start, "insert")
        self.t.insert("insert", word)
        self.t.see("insert")

    def _focus_check(self):
        if self.active and self.t.focus_get() is not self.lb:
            self.close()

    def close(self):
        if self.win is not None:
            self.win.destroy()
            self.win = None
        return None
