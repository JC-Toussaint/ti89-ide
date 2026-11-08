"""
« Variables » d'un programme en assembleur : données étiquetées et constantes, lues dans
le source (A68k ou GNU as) puis en mémoire.

  A68k   : ball:  dc.b %00111100,...     buf: ds.w 10      MAX_X equ 160-8
  GNU as : msg:   .asciz "Hello"         tab: .word 1,2    .set LIMIT, 100
Les lignes de données qui suivent sans étiquette prolongent la donnée précédente
(par exemple les 8 lignes « dc.b » d'un sprite).
"""
import re
from dataclasses import dataclass, field

from .variables import VarNode

MAX_ELEMS = 256


@dataclass
class AsmData:
    name: str
    size: int                    # 1, 2 ou 4 octets par élément
    count: int                   # nombre d'éléments
    is_string: bool = False
    line: int = 0


@dataclass
class AsmConst:
    name: str
    expr: str
    line: int = 0


@dataclass
class AsmSymbols:
    data: list = field(default_factory=list)
    consts: list = field(default_factory=list)


# Directives de données : nom -> (taille d'un élément, réservation ?, chaîne ?)
_A68K_DIRS = {"dc.b": (1, False), "dc": (2, False), "dc.w": (2, False), "dc.l": (4, False),
              "ds.b": (1, True), "ds": (2, True), "ds.w": (2, True), "ds.l": (4, True)}
_GAS_DIRS = {".byte": (1, False), ".word": (2, False), ".short": (2, False), ".long": (4, False),
             ".int": (4, False), ".ascii": (1, False), ".asciz": (1, False), ".string": (1, False),
             ".space": (1, True), ".skip": (1, True)}


def _split_operands(text):
    """Découpe « 1,"ab,c",3 » en opérandes en respectant les chaînes."""
    out, cur, quote = [], "", None
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _strip_comment(line, gas):
    """Retire le commentaire (« ; » en A68k, « | » en GNU as) hors des chaînes."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ("|" if gas else ";"):
            return line[:i]
    return line


def parse(source, lang):
    """Analyse le source. lang : « a68k » ou « gas »."""
    gas = lang == "gas"
    dirs = _GAS_DIRS if gas else _A68K_DIRS
    res = AsmSymbols()
    current = None                               # donnée en cours (lignes de suite)
    pending = None                               # étiquette seule sur sa ligne
    for ln, raw in enumerate(source.splitlines(), start=1):
        if not gas and raw.startswith("*"):
            continue
        line = _strip_comment(raw, gas).rstrip()
        if not line.strip():
            continue
        label = None
        rest = line
        if gas:
            m = re.match(r"^\s*([A-Za-z_.$][\w.$]*):(.*)$", line)
            if m:
                label, rest = m.group(1), m.group(2)
            m = re.match(r"^\s*\.(?:set|equ)\s+([A-Za-z_][\w.]*)\s*,\s*(.+)$", rest)
            if m:
                res.consts.append(AsmConst(m.group(1), m.group(2).strip(), ln))
                continue
        else:
            m = re.match(r"^([A-Za-z_.\\@][\w.\\@]*):?(.*)$", line)     # étiquette en colonne 1
            if m:
                label, rest = m.group(1), m.group(2)
            m = re.match(r"^\s*(equ|set|=)\s+(.+)$", rest, re.I)
            if label and m:
                res.consts.append(AsmConst(label, m.group(2).strip(), ln))
                current = None
                continue
        if label and not rest.strip():
            pending = label                      # « message: » seul : la donnée suit
            current = None
            continue
        if not label and pending:
            label, pending = pending, None
        else:
            pending = None
        m = re.match(r"^\s*([.\w]+)\s*(.*)$", rest)
        directive = m.group(1).lower() if m else ""
        operands = m.group(2) if m else ""
        if directive in dirs:
            size, reserve = dirs[directive]
            ops = _split_operands(operands)
            if reserve:
                try:
                    count = int(_eval(ops[0], {})) if ops else 0
                except ValueError:
                    count = 0
                is_str = False
            else:
                count = 0
                is_str = False
                for op in ops:
                    if op[:1] in "\"'":
                        count += len(op.strip("\"'"))
                        is_str = True
                    else:
                        count += 1
                if directive in (".asciz", ".string"):
                    count += 1
            if label and not label.startswith("\\"):
                current = AsmData(label, size, count, is_str, ln)
                res.data.append(current)
            elif current is not None and current.size == size and not label:
                current.count += count                  # suite de la donnée précédente
                current.is_string = current.is_string or is_str
        elif directive in ("even", ".even", "align", ".align", "cnop"):
            continue
        else:
            current = None
    return res


_NUM_RE = re.compile(r"\$([0-9a-fA-F]+)|0[xX]([0-9a-fA-F]+)|%([01]+)|0[bB]([01]+)|(\d+)")


def _eval(expr, consts, depth=0):
    """Évalue une expression de constante (nombres $hex, %bin, + - * / ( ), noms)."""
    if depth > 20:
        raise ValueError("expression trop imbriquée")

    def num(m):
        if m.group(1): return str(int(m.group(1), 16))
        if m.group(2): return str(int(m.group(2), 16))
        if m.group(3): return str(int(m.group(3), 2))
        if m.group(4): return str(int(m.group(4), 2))
        return m.group(5)

    def name(m):
        n = m.group(0)
        if n not in consts:
            raise ValueError(f"inconnu : {n}")
        return str(_eval(consts[n], consts, depth + 1))

    e = _NUM_RE.sub(num, expr)
    e = re.sub(r"[A-Za-z_][\w.]*", name, e)
    if not re.fullmatch(r"[\d\s+\-*/()<>&|^~]+", e):
        raise ValueError(f"expression non gérée : {expr}")
    return int(eval(e.replace("/", "//"), {"__builtins__": {}}, {}))


class AsmVariableReader:
    """Construit les VarNode de l'onglet Variables pour un programme assembleur."""

    def __init__(self, debugger, source, lang):
        self.dbg = debugger
        self.syms = parse(source, lang)

    def _read(self, addr, n):
        return self.dbg.session.peek(addr, n)

    def _elem(self, b, size):
        v = int.from_bytes(bytes(b), "big")
        if size == 1:                    # binaire : utile pour les sprites et les drapeaux
            return f"{v}  (${v:02X})  %{v:08b}"
        return f"{v}  (${v:0{size * 2}X})"

    def data_nodes(self):
        d = self.dbg
        out = []
        for item in self.syms.data:
            off = d.info.symbols.get(item.name)
            tname = {1: "byte", 2: "word", 4: "long"}[item.size]
            tname += f"[{item.count}]" if item.count != 1 else ""
            path = f"D/{item.name}"
            if off is None or d.base is None:
                out.append(VarNode(item.name, tname, "‹address unknown›", path, error=True))
                continue
            addr = (d.base + off) & 0xFFFFFF
            n = min(item.count, MAX_ELEMS)
            raw = self._read(addr, n * item.size)
            if None in raw:
                out.append(VarNode(item.name, tname, f"${addr:06X} ‹not readable›", path, error=True))
                continue
            if item.is_string and item.size == 1:
                txt = bytes(raw).split(b"\0")[0].decode("latin-1")
                value = f'"{txt}"   @ ${addr:06X}'
            elif item.count == 1:
                value = self._elem(raw, item.size) + f"   @ ${addr:06X}"
            else:
                shown = [str(int.from_bytes(bytes(raw[k * item.size:(k + 1) * item.size]), "big"))
                         for k in range(min(n, 8))]
                value = "{" + ", ".join(shown) + (", …" if n > 8 else "") + f"}}   @ ${addr:06X}"

            def kids(raw=raw, item=item, n=n, path=path, addr=addr):
                return [VarNode(f"[{k}]", {1: "byte", 2: "word", 4: "long"}[item.size],
                                self._elem(raw[k * item.size:(k + 1) * item.size], item.size),
                                f"{path}/{k}")
                        for k in range(n)]
            out.append(VarNode(item.name, tname, value, path, kids if item.count > 1 else None))
        return out

    def const_nodes(self):
        table = {c.name: c.expr for c in self.syms.consts}
        out = []
        for c in self.syms.consts:
            try:
                v = _eval(c.expr, table)
                value = f"{v}  (${v & 0xFFFFFFFF:X})"
                err = False
            except (ValueError, SyntaxError, ZeroDivisionError):
                value, err = c.expr, False
            out.append(VarNode(c.name, "equ", value, f"C/{c.name}", error=err))
        return out
