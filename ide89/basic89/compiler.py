"""
Basic89 -> C translator (prototype).

A structured BASIC in the spirit of QuickBASIC, compiled to C for GCC4TI. Every generated
statement is preceded by a `#line N "program.b89"` directive, so GCC's error messages and
the DWARF debug information refer to the lines of the BASIC program: the IDE's debugger
(breakpoints, stepping, variables) works on the .b89 source.

    python -m basic89 program.b89          ->  program.b89.c
"""
import os
import re

RUNTIME_DIR = os.path.dirname(os.path.abspath(__file__))     # b89rt.h


class CompileError(Exception):
    def __init__(self, line, msg):
        super().__init__(msg)
        self.line = int(line)
        self.file = getattr(line, "file", None)     # set for the lines of an INCLUDEd file
        self.msg = msg


class Loc(int):
    """A line number that also knows its file (main program or INCLUDEd file): it goes
    through the compiler like the line number it is, and the #line directives and the
    error messages name the right file."""

    def __new__(cls, n, file):
        o = int.__new__(cls, n)
        o.file = file
        return o


# ------------------------------------------------------------------ lexer
_TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t]+)
  | (?P<comment>'.*)
  | (?P<num>&[Hh][0-9A-Fa-f]+|&[Bb][01]+|\d+\.\d*|\.\d+|\d+)
  | (?P<str>"[^"\n]*"?)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*\$?)
  | (?P<op>\+=|-=|\*=|<>|<=|>=|[-+*/\\=<>(),;:.])
""", re.X)


class Tok:
    __slots__ = ("kind", "val", "line")

    def __init__(self, kind, val, line):
        self.kind, self.val, self.line = kind, val, line

    def is_(self, *words):
        return self.kind in ("id", "op") and self.val.upper() in words

    def __repr__(self):
        return f"{self.kind}:{self.val}"


def tokenize_line(text, line):
    toks, pos = [], 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise CompileError(line, f"unexpected character {text[pos]!r}")
        pos = m.end()
        kind = m.lastgroup
        val = m.group()
        if kind in ("ws", "comment"):
            continue
        if kind == "id" and val.upper() == "REM":
            break
        if kind == "str":
            if not val.endswith('"') or len(val) < 2:
                raise CompileError(line, "missing closing quote")
            val = val[1:-1]
        toks.append(Tok(kind, val, line))
    return toks


KEYWORDS = set("""
AND AS BOX CALL CASE CIRCLE CLS CONST DELAY DIM DO ELSE ELSEIF END EXIT FILL FLIP FOR
FUNCTION IF LINE LOCATE LOOP MOD NEXT NOT OR PRINT PSET RETURN SCREEN STEP SUB THEN TO
UNTIL WAITFRAME WAITKEY WEND WHILE BUFFERED DIRECT SELECT IS TYPE INPUT INCLUDE COLOR GRAY4
BYVAL BYREF
IMAGE SPRITE TILESET MAP MAPROW SOUND PLAY BEEP SAVE LOAD KILL
""".split())

TYPES = {"INTEGER": "short", "LONG": "long", "BOOLEAN": "bool", "FIXED": "fixed",
         "STRING": "str"}
STR_FUNCS = {"LEFT$", "RIGHT$", "MID$", "STR$", "CHR$", "UCASE$", "LCASE$", "LEN", "ASC",
             "INSTR", "VAL"}
TMP_SIZE = 256              # temporary string buffers b89_tN

KEYS = {"LEFT": "RR_LEFT", "RIGHT": "RR_RIGHT", "UP": "RR_UP", "DOWN": "RR_DOWN",
        "ENTER": "RR_ENTER", "ESC": "RR_ESC", "F1": "RR_F1", "F2": "RR_F2", "F3": "RR_F3",
        "F4": "RR_F4", "F5": "RR_F5", "2ND": "RR_2ND", "SHIFT": "RR_SHIFT",
        "DIAMOND": "RR_DIAMOND", "ALPHA": "RR_ALPHA", "CLEAR": "RR_CLEAR",
        "APPS": "RR_APPS", "MODE": "RR_MODE", "HOME": "RR_HOME"}
COLORS = {"WHITE": 0, "LIGHTGRAY": 1, "DARKGRAY": 2, "BLACK": 3, "XOR": 4}

# built-in functions: name -> (number of arguments, C template, type)
BUILTINS = {
    "RND": (1, "b89_rnd({0})", "short"),
    "ABS": (1, "b89_abs({0})", "long"),
    "MIN": (2, "b89_min({0}, {1})", "long"),
    "MAX": (2, "b89_max({0}, {1})", "long"),
    "ISIN": (1, "b89_isin({0})", "short"),
    "ICOS": (1, "b89_icos({0})", "short"),
    "GETKEY": (0, "b89_getkey()", "short"),
    "TICKS": (0, "((long)b89_ticks)", "long"),
    "PI": (0, "205887L", "fixed"),
}


# Types: "short" (INTEGER), "bool" (BOOLEAN, a short), "long" (LONG), "fixed" (FIXED: 16.16 fixed point,
# a long holding value * 65536), "rec:<name>" (a TYPE ... END TYPE)
def is_rec(ty):
    return ty.startswith("rec:")


def conv(code, frm, to):
    """C code converting a number from type frm to type to."""
    if frm == to or is_rec(frm) or is_rec(to):
        return code
    if to == "fixed":
        return f"((long)({code}) << 16)"
    if frm == "fixed":
        return f"(({code}) >> 16)"          # rounded down
    return code


def fixed_literal(text, line):
    raw = round(float(text) * 65536)
    if raw >= 1 << 31:
        raise CompileError(line, f"{text} is too large for a FIXED (at most 32767.99998)")
    return f"{raw}L"


def basic_type(ty):
    return ty[4:] if is_rec(ty) else {"short": "INTEGER", "long": "LONG", "bool": "BOOLEAN",
                                      "fixed": "FIXED", "str": "STRING"}.get(ty, ty)


class Var:
    """A variable, a parameter or a record field. dims: list of upper bounds (arrays)."""

    def __init__(self, name, ctype, dims=None, line=0, byref=False, cap=255):
        self.name, self.ctype, self.dims, self.line = name, ctype, dims, line
        self.byref = byref          # record parameter: passed by address
        self.cap = cap              # STRING: maximum length
        self.readonly = False       # STRING parameter
        self.sizes = None           # array parameter: C names of its sizes (b89_d1_x...)
        self.strsize = None         # array parameter of STRINGs: C name of the element size

    def size_exprs(self):
        """Sizes of the dimensions of an array, as C expressions."""
        return self.sizes if self.sizes else [str(d + 1) for d in self.dims]

    def str_size(self):
        return self.strsize if self.strsize else str(self.cap + 1)

    @property
    def ref(self):
        return f"(*bv_{self.name})" if self.byref else f"bv_{self.name}"


# IMAGE pixels: transparent, white, light gray, dark gray, black (also 0 1 2 3)
PIXELS = {".": None, " ": None, "w": 0, "W": 0, "0": 0, ":": 1, "1": 1, "+": 2, "2": 2,
          "#": 3, "X": 3, "x": 3, "3": 3}


class Image:
    def __init__(self, name, line, display):
        self.name, self.line, self.display = name, line, display
        self.rows = []              # strings

    def c_data(self):
        """Tables for b89_sprite: for each column of 32 pixels, mask (0 = opaque),
        light plane, dark plane, black and white."""
        w, h = len(self.rows[0]), len(self.rows)
        out = []
        for s in range((w + 31) // 32):
            tables = [[], [], [], []]
            for row in self.rows:
                mask, light, dark = 0xFFFFFFFF, 0, 0
                for k in range(32):
                    x = s * 32 + k
                    c = PIXELS[row[x]] if x < w else None
                    if c is None:
                        continue
                    bit = 1 << (31 - k)
                    mask &= ~bit
                    if c & 1:
                        light |= bit
                    if c & 2:
                        dark |= bit
                tables[0].append(mask)
                tables[1].append(light)
                tables[2].append(dark)
                tables[3].append(light | dark)
            for t in tables:
                out += t
        return w, h, (w + 31) // 32, out


class Record:
    def __init__(self, name, line, display):
        self.name, self.line, self.display = name, line, display
        self.fields = {}            # name -> Var


class Param:
    """A parameter of a SUB/FUNCTION. mode: "val" (a copy), "ro" (STRING without
    keyword: read only, not copied), "copy" (BYVAL STRING: a local copy), "ref" (BYREF,
    and TYPE without keyword). rank > 0: an array, always by reference."""

    def __init__(self, name, ty, mode, rank=0):
        self.name, self.ty, self.mode, self.rank = name, ty, mode, rank
        self.key = name.lower()


class Proc:
    def __init__(self, name, params, ret, line):
        self.name, self.params, self.ret, self.line = name, params, ret, line
        self.cname = name.lower().replace("$", "_S")      # twice$ -> bs_twice_S


def c_string(s, line):
    out = []
    for ch in s:
        try:
            b = ch.encode("latin-1")[0]
        except UnicodeEncodeError:
            raise CompileError(line, f"character {ch!r} cannot be displayed on the TI-89")
        if ch in '"\\':
            out.append("\\" + ch)
        elif 32 <= b < 127:
            out.append(ch)
        else:
            out.append(f"\\{b:03o}")
    return "".join(out)


# ------------------------------------------------------------------ parser / generator
class Compiler:
    def __init__(self, source, filename):
        self.filename = os.path.basename(filename)
        self.base_dir = os.path.dirname(os.path.abspath(filename))
        self.lines = source.split("\n")
        self.globals = {}
        self.consts = {}
        self.procs = {}
        self.records = {}
        self.images = {}
        self.tilesets = {}          # name -> (display name, [Image])
        self.proc = None            # Proc being compiled (None: main program)
        self.locals = {}
        self.out = None             # current body (list of C lines)
        self.blocks = []
        self.label_n = 0
        self.end_used = False
        self.end_in_proc = False
        self.uses_gray = False
        self.indent = 1
        self.tmp_n = 0              # temporary string buffers used by the current statement
        self.tmp_max = 0            # ... by the current SUB/FUNCTION (or the main program)
        self.main_tmp_max = 0

    # ---------------------------------------------------------- output
    def emit(self, line, text):
        self.out.append(f'#line {int(line)} "{getattr(line, "file", self.filename)}"')
        self.out.append("  " * self.indent + text)

    def emit_raw(self, text):
        self.out.append("  " * self.indent + text)

    def new_label(self):
        self.label_n += 1
        return self.label_n

    # ---------------------------------------------------------- names
    def ctype(self, ty):
        """C type; a TYPE keeps the case of its name (bt_Enemy), shown so by the debugger."""
        if ty == "str":
            return "const char *"
        if ty == "fixed":
            return "b89fixed"
        if ty == "bool":
            return "b89bool"            # a short, shown TRUE / FALSE by the debugger
        return f"bt_{self.records[ty[4:]].display}" if is_rec(ty) else ty

    def tname(self, ty):
        """Type name as written in the program (INTEGER, LONG, or the TYPE's name)."""
        return self.records[ty[4:]].display if is_rec(ty) else basic_type(ty)

    def lookup(self, name, line):
        key = name.lower()
        if self.proc and key in self.locals:
            return self.locals[key]
        if key in self.globals:
            return self.globals[key]
        raise CompileError(line, f"variable '{name}' is not declared (use DIM {name} AS INTEGER)")

    def check_new_name(self, name, line, where):
        up = name.upper()
        if name.endswith("$"):
            raise CompileError(line, f"'{name}': $ is only used by the string functions "
                                     "(LEFT$...); declare text with DIM name AS STRING")
        if up in KEYWORDS or up in TYPES or up in BUILTINS or up in COLORS or up in STR_FUNCS or \
                up in ("TRUE", "FALSE", "KEYDOWN", "INT", "ROUND", "SQR", "SIN", "COS",
                       "WIDTH", "HEIGHT", "COLLIDE", "EXISTS", "UBOUND", "LBOUND") or \
                up.startswith("KEY_"):
            raise CompileError(line, f"'{name}' is a reserved word")
        key = name.lower()
        if key in where or key in self.consts or (key in self.procs and where is not None):
            raise CompileError(line, f"'{name}' is already declared")

    # ---------------------------------------------------------- driver
    def read_lines(self, rel, lines, toklines, seen):
        """Tokenizes a file; INCLUDE "other.b89" inserts that file's lines in its place
        (only once per file: a library included twice is read once)."""
        for i, text in enumerate(lines, 1):
            loc = Loc(i, rel)
            t = tokenize_line(text, loc)
            if not t:
                continue
            if t[0].is_("INCLUDE"):
                if len(t) != 2 or t[1].kind != "str":
                    raise CompileError(loc, 'expected INCLUDE "file.b89"')
                target = os.path.normpath(os.path.join(os.path.dirname(rel), t[1].val))
                if target.replace("\\", "/").startswith("../") or os.path.isabs(t[1].val):
                    target = t[1].val
                full = os.path.join(self.base_dir, target)
                key = os.path.normcase(os.path.abspath(full))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    with open(full, encoding="utf-8") as f:
                        sub = f.read().split("\n")
                except FileNotFoundError:
                    raise CompileError(loc, f"file not found: {t[1].val} (the path is relative "
                                            "to the file that includes it)")
                except (OSError, UnicodeDecodeError) as e:
                    raise CompileError(loc, f"cannot read {t[1].val} ({e.__class__.__name__})")
                self.read_lines(target.replace("\\", "/"), sub, toklines, seen)
                continue
            toklines.append(t)

    def compile(self):
        toklines = []
        main_key = os.path.normcase(os.path.join(self.base_dir, self.filename))
        self.read_lines(self.filename, self.lines, toklines, {main_key})
        toklines = self.prescan(toklines)
        main = []
        self.out = main
        procs_code = []
        for toks in toklines:
            self.statement_line(toks, procs_code)
        if self.proc:
            raise CompileError(self.proc.line, f"SUB/FUNCTION {self.proc.name} has no END")
        if self.blocks:
            kind, line = self.blocks[-1][0], self.blocks[-1][1]
            raise CompileError(line, f"{kind} without its end ({self.block_end(kind)})")
        self.main_tmp_max = self.tmp_max          # every SUB is closed: main program's count
        return self.assemble(main, procs_code)

    def block_end(self, kind):
        return {"IF": "END IF", "FOR": "NEXT", "DO": "LOOP", "WHILE": "WEND",
                "SELECT": "END SELECT"}[kind]

    def prescan(self, toklines):
        """Reads the TYPEs (removed from the lines to compile), then registers the SUBs and
        FUNCTIONs, so they can be called before their definition."""
        rest, rec, img = [], None, None
        for toks in toklines:
            line = toks[0].line
            if img is not None:
                if toks[0].is_("END") and len(toks) > 1 and toks[1].is_("IMAGE"):
                    Parser(self, toks, 2).end()
                    if not img.rows:
                        raise CompileError(img.line, f"IMAGE {img.display} has no rows")
                    img = None
                    continue
                if len(toks) != 1 or toks[0].kind != "str":
                    raise CompileError(line, 'an IMAGE row is written between quotes, e.g. "..##.."')
                row = toks[0].val
                bad = next((c for c in row if c not in PIXELS), None)
                if bad is not None:
                    raise CompileError(line, f"'{bad}' is not a pixel: . (transparent) w (white) "
                                             ": (light gray) + (dark gray) # (black), or 0 1 2 3")
                if img.rows and len(row) != len(img.rows[0]):
                    raise CompileError(line, f"all the rows of an IMAGE must have the same "
                                             f"width ({len(img.rows[0])} here)")
                if not 1 <= len(row) <= 160:
                    raise CompileError(line, "an IMAGE is 1 to 160 pixels wide")
                img.rows.append(row)
                if len(img.rows) > 100:
                    raise CompileError(line, "an IMAGE is at most 100 rows high")
                continue
            if toks[0].is_("TILESET"):
                p = Parser(self, toks, 1)
                name = p.expect_id()
                self.check_new_name(name.val, line, self.tilesets)
                p.expect_op("=")
                imgs = [p.image()]
                while p.more():
                    p.expect_op(",")
                    imgs.append(p.image())
                size = (len(imgs[0].rows[0]), len(imgs[0].rows))
                for im in imgs:
                    if (len(im.rows[0]), len(im.rows)) != size:
                        raise CompileError(line, f"the images of a TILESET must have the same "
                                                 f"size: {im.display} is not {size[0]}x{size[1]}")
                if len(imgs) > 36:
                    raise CompileError(line, "a TILESET has at most 36 images (0-9, a-z)")
                self.tilesets[name.val.lower()] = (name.val, imgs)
                continue
            if toks[0].is_("IMAGE"):
                if len(toks) != 2 or toks[1].kind != "id":
                    raise CompileError(line, "expected IMAGE name")
                name = toks[1].val
                self.check_new_name(name, line, self.images)
                img = Image(name.lower(), line, name)
                self.images[img.name] = img
                continue
            if rec is not None:
                if toks[0].is_("END") and len(toks) > 1 and toks[1].is_("TYPE"):
                    Parser(self, toks, 2).end()
                    if not rec.fields:
                        raise CompileError(rec.line, f"TYPE {rec.display} has no field")
                    rec = None
                    continue
                p = Parser(self, toks, 0)
                f = p.expect_id()
                self.check_new_name(f.val, line, rec.fields)
                dims = p.dims()
                p.expect_word("AS")
                ty = p.type_name()
                if ty == f"rec:{rec.name}":
                    raise CompileError(line, f"a TYPE cannot contain itself")
                p.end()
                rec.fields[f.val.lower()] = Var(f.val.lower(), ty, dims, line, cap=p.cap)
                continue
            if toks[0].is_("TYPE"):
                if len(toks) != 2 or toks[1].kind != "id":
                    raise CompileError(line, "expected TYPE name")
                name = toks[1].val
                self.check_new_name(name, line, self.records)
                rec = Record(name.lower(), line, name)
                self.records[rec.name] = rec
                continue
            rest.append(toks)
        if rec is not None:
            raise CompileError(rec.line, f"TYPE {rec.display} without END TYPE")
        if img is not None:
            raise CompileError(img.line, f"IMAGE {img.display} without END IMAGE")
        for toks in rest:
            if toks[0].is_("SUB", "FUNCTION") and len(toks) > 1:
                p = Parser(self, toks, 1)
                name_tok = p.expect_id()
                self.check_new_name(name_tok.val.rstrip("$"), name_tok.line, self.procs)
                params = p.params()
                ret = None
                if toks[0].is_("FUNCTION"):
                    p.expect_word("AS")
                    ret = p.type_name()
                    if name_tok.val.endswith("$") and ret != "str":
                        raise CompileError(toks[0].line, f"{name_tok.val}: a name ending with $ "
                                                         "is for a FUNCTION ... AS STRING")
                    if is_rec(ret):
                        raise CompileError(toks[0].line, "a FUNCTION cannot return a TYPE in "
                                                         "this version (use a SUB parameter)")
                p.end()
                if toks[0].is_("SUB") and name_tok.val.endswith("$"):
                    raise CompileError(toks[0].line, "a SUB name cannot end with $")
                self.procs[name_tok.val.lower()] = Proc(name_tok.val, params, ret, toks[0].line)
        return rest

    def assemble(self, main, procs_code):
        lines = [f"/* Generated by Basic89 from {self.filename}: do not edit, edit the .b89 */"]
        if self.uses_gray:
            lines.append("#define B89_GRAY")
        lines += ['#include "b89rt.h"', ""]
        for im in self.images.values():
            w, h, slabs, data = im.c_data()
            vals = ", ".join(f"0x{v:08X}" for v in data)
            lines.append(f"static const unsigned long b89i_{im.name}_d[] = {{{vals}}};")
            b8 = "0"
            if w <= 8:                         # bytes for the fast 8-pixel tiles of MAP
                vals8 = ", ".join(str(v >> 24) for v in data)
                lines.append(f"static const unsigned char b89i_{im.name}_b[] = {{{vals8}}};")
                b8 = f"b89i_{im.name}_b"
            lines.append(f"static const b89img b89i_{im.name} = {{{w}, {h}, {slabs}, "
                         f"b89i_{im.name}_d, {b8}}};")
        for key, (_, imgs) in self.tilesets.items():
            refs = ", ".join(f"&b89i_{im.name}" for im in imgs)
            lines.append(f"static const b89img *const b89ts_{key}[] = {{{refs}}};")
        for r in self.records.values():
            lines.append("typedef struct {")
            for f in r.fields.values():
                lines.append(f"  {self.decl(f)};")
            lines.append(f"}} bt_{r.display};")
        for p in self.procs.values():
            lines.append(self.proc_header(p) + ";")
        for v in self.globals.values():
            lines.append(f"static {self.decl(v)};")
        if self.end_in_proc:
            lines.append("static JMP_BUF b89_jmp;       /* END in a SUB/FUNCTION jumps back to _main */")
        for k in range(self.main_tmp_max):
            lines.append(f"static char b89_t{k}[{TMP_SIZE}];")
        lines.append("")
        lines += procs_code
        lines += ["void _main(void)", "{", "  b89_init();"]
        if self.end_in_proc:
            lines.append("  if (!setjmp(b89_jmp)) {")
        lines += main
        lines.append("#line RESET")
        if self.end_in_proc:
            lines.append("  }")
        if self.end_used:
            lines.append("b89_end:")
        lines += ["  b89_exit();", "}", ""]
        cname = self.filename + ".c"
        final = []
        for ln in lines:
            if ln == "#line RESET":
                ln = f'#line {len(final) + 2} "{cname}"'
            final.append(ln)
        return "\n".join(final)

    def decl(self, v):
        dims = "".join(f"[{d + 1}]" for d in v.dims or ())
        if v.ctype == "str":
            return f"char bv_{v.name}{dims}[{v.cap + 1}]"
        return f"{self.ctype(v.ctype)} bv_{v.name}{dims}"

    def param_c(self, pa):
        n, ty = pa.key, pa.ty
        if pa.rank:
            # pointer to an array whose sizes are passed before it (C99 variable-length array)
            dims = [f"b89_d{k}_{n}" for k in range(1, pa.rank + 1)]
            out = [f"short {d}" for d in dims]
            if ty == "str":
                out.append(f"short b89_s_{n}")
                dims.append(f"b89_s_{n}")
                elem = "char"
            else:
                elem = self.ctype(ty)
            return ", ".join(out + [f"{elem} (*bv_{n})" + "".join(f"[{d}]" for d in dims)])
        if pa.mode == "ref":
            if ty == "str":
                return f"short b89_s_{n}, char (*bv_{n})[b89_s_{n}]"
            return f"{self.ctype(ty)} *bv_{n}"
        if pa.mode == "copy":
            return f"const char *b89_in_{n}"
        c = self.ctype(ty)
        return f"{c}{'' if c.endswith('*') else ' '}bv_{n}"

    def proc_header(self, p):
        args = ", ".join(self.param_c(pa) for pa in p.params) or "void"
        ret = self.ctype(p.ret) if p.ret else "void"
        return f"static {ret}{'' if ret.endswith('*') else ' '}bs_{p.cname}({args})"

    # ---------------------------------------------------------- statements
    def statement_line(self, toks, procs_code):
        # statements separated by ':' ; a one-line IF takes the rest of the line
        i = 0
        while i < len(toks):
            if toks[i].is_("IF"):
                then = next((k for k in range(i, len(toks)) if toks[k].is_("THEN")), None)
                if then is not None and then + 1 < len(toks) and not toks[then + 1].is_(":"):
                    self.single_line_if(toks[i:], procs_code)
                    return
            j = i
            while j < len(toks) and not toks[j].is_(":"):
                j += 1
            if j > i:
                self.statement(toks[i:j], procs_code)
            i = j + 1

    def single_line_if(self, toks, procs_code):
        p = Parser(self, toks, 1)
        cond = p.condition()
        p.expect_word("THEN")
        rest = toks[p.i:]
        else_at = next((k for k, t in enumerate(rest) if t.is_("ELSE")), None)
        self.emit(toks[0].line, f"if ({cond}) {{")
        self.indent += 1
        self.statement_line(rest if else_at is None else rest[:else_at], procs_code)
        self.indent -= 1
        if else_at is not None:
            self.emit_raw("} else {")
            self.indent += 1
            self.statement_line(rest[else_at + 1:], procs_code)
            self.indent -= 1
        self.emit_raw("}")

    def statement(self, toks, procs_code):
        t0 = toks[0]
        line = t0.line
        word = t0.val.upper() if t0.kind == "id" else None
        p = Parser(self, toks, 1)
        self.tmp_n = 0

        if self.blocks and self.blocks[-1][0] == "SELECT" and self.blocks[-1][4] == 0 \
                and word != "CASE" and not (word == "END" and len(toks) > 1 and toks[1].is_("SELECT")):
            raise CompileError(line, "expected CASE after SELECT CASE")

        if word in ("SUB", "FUNCTION"):
            if self.proc:
                raise CompileError(line, "SUB and FUNCTION cannot be nested")
            if self.blocks:
                raise CompileError(line, f"{word} inside a {self.blocks[-1][0]} block")
            self.proc = self.procs[toks[1].val.lower()]
            self.locals = {}
            self.prologue = []
            for pa in self.proc.params:
                v = Var(pa.key, pa.ty, byref=pa.rank > 0 or pa.mode == "ref")
                if pa.rank:
                    v.dims = [None] * pa.rank
                    v.sizes = [f"b89_d{k}_{pa.key}" for k in range(1, pa.rank + 1)]
                    v.strsize = f"b89_s_{pa.key}" if pa.ty == "str" else None
                elif pa.mode == "ro":
                    v.readonly = True
                elif pa.mode == "copy":     # BYVAL STRING: a local copy that can be changed
                    self.prologue.append(f"  char bv_{pa.key}[256]; "
                                         f"b89_sset(bv_{pa.key}, 256, b89_in_{pa.key});")
                self.locals[pa.key] = v
            self.main_tmp_max, self.tmp_max = self.tmp_max, 0
            self.saved_out, self.out = self.out, []
            self.proc_line = line
            self.indent = 1
            return
        if word == "END" and len(toks) > 1 and toks[1].is_("SUB", "FUNCTION"):
            kind = toks[1].val.upper()
            if not self.proc or (kind == "SUB") != (self.proc.ret is None):
                raise CompileError(line, f"END {kind} without {kind}")
            if self.blocks:
                b = self.blocks[-1]
                raise CompileError(b[1], f"{b[0]} without its end ({self.block_end(b[0])})")
            body = self.out
            pf = getattr(self.proc_line, "file", self.filename)
            code = [f'#line {int(self.proc_line)} "{pf}"', self.proc_header(self.proc), "{"]
            for v in self.locals.values():
                if v.name not in {pa.key for pa in self.proc.params}:
                    code.append(f"  {self.decl(v)};")
            code += self.prologue
            for k in range(self.tmp_max):
                code.append(f"  char b89_t{k}[{TMP_SIZE}];")
            if self.proc.ret == "str":
                code.append(f"  static char b89_r[{TMP_SIZE}];     /* the returned STRING */")
            self.tmp_max = self.main_tmp_max
            code += body
            self.out = code
            if self.proc.ret:
                self.emit(line, 'return "";' if self.proc.ret == "str" else "return 0;")
            self.out.append("}")
            self.out.append("#line RESET")
            procs_code += self.out
            self.out = self.saved_out
            self.proc = None
            self.locals = {}
            return

        if word == "DIM":
            self.dim(p, line)
        elif word == "CONST":
            while True:                       # CONST A = 1, B = 2
                name = p.expect_id()
                self.check_new_name(name.val, line, self.consts)
                p.expect_op("=")
                self.consts[name.val.lower()] = p.const_value()
                if not p.more():
                    break
                p.expect_op(",")
        elif word == "IF":
            cond = p.condition()
            p.expect_word("THEN")
            p.end()
            self.emit(line, f"if ({cond}) {{")
            self.blocks.append(["IF", line, False])
            self.indent += 1
        elif word == "ELSEIF":
            b = self.need_block("IF", line, "ELSEIF")
            if b[2]:
                raise CompileError(line, "ELSEIF after ELSE")
            cond = p.condition()
            p.expect_word("THEN")
            p.end()
            self.indent -= 1
            self.emit(line, f"}} else if ({cond}) {{")
            self.indent += 1
        elif word == "ELSE":
            b = self.need_block("IF", line, "ELSE")
            if b[2]:
                raise CompileError(line, "two ELSE in the same IF")
            b[2] = True
            p.end()
            self.indent -= 1
            self.emit_raw("} else {")
            self.indent += 1
        elif word == "SELECT":
            p.expect_word("CASE")
            e, sty = p.expr()
            if sty != "str":
                p.num(sty)
            p.end()
            n = self.new_label()
            self.emit(line, "{")
            self.indent += 1
            if sty == "str":
                self.emit(line, f"char b89_s{n}[{TMP_SIZE}]; b89_sset(b89_s{n}, {TMP_SIZE}, {e});")
            else:
                self.emit(line, f"long b89_s{n} __attribute__((unused)) = {e};")
            # [kind, line, CASE ELSE seen, temp number, number of CASEs]
            self.blocks.append(["SELECT", line, False, n, 0, sty])
        elif word == "CASE":
            b = self.need_block("SELECT", line, "CASE")
            if b[2]:
                raise CompileError(line, "CASE after CASE ELSE")
            if p.more() and p.peek().is_("ELSE"):
                p.next()
                p.end()
                b[2] = True
                if b[4] == 0:                 # only CASE ELSE: always executed
                    self.emit(line, "{")
                    self.indent += 1
                else:
                    self.indent -= 1
                    self.emit(line, "} else {")
                    self.indent += 1
                b[4] += 1
                return
            cond = p.case_tests(f"b89_s{b[3]}", b[5])
            if b[4] == 0:
                self.emit(line, f"if ({cond}) {{")
                self.indent += 1
            else:
                self.indent -= 1
                self.emit(line, f"}} else if ({cond}) {{")
                self.indent += 1
            b[4] += 1
        elif word == "END" and len(toks) > 1 and toks[1].is_("SELECT"):
            b = self.need_block("SELECT", line, "END SELECT")
            p.next()
            p.end()
            self.blocks.pop()
            if b[4]:
                self.indent -= 1
                self.emit_raw("}")
            self.indent -= 1
            self.emit_raw("}")
        elif word == "END" and len(toks) > 1 and toks[1].is_("IF"):
            self.need_block("IF", line, "END IF")
            self.blocks.pop()
            self.indent -= 1
            self.emit_raw("}")
        elif word == "END":
            p.end()
            if self.proc:
                # from a SUB/FUNCTION: back to _main (setjmp below), which cleans up
                self.end_in_proc = True
                self.emit(line, "longjmp(b89_jmp, 1);")
            else:
                self.end_used = True
                self.emit(line, "goto b89_end;")
        elif word == "FOR":
            self.for_stmt(p, line)
        elif word == "NEXT":
            b = self.need_block("FOR", line, "NEXT")
            if p.more():
                v = p.expect_id()
                if v.val.lower() != b[3]:
                    raise CompileError(line, f"NEXT {v.val} does not match FOR {b[3]}")
            p.end()
            self.blocks.pop()
            self.emit(line, f"{b[6]} += {b[4]};")
            self.indent -= 1
            self.emit_raw("}")
            self.close_label(b)
            self.indent -= 1
            self.emit_raw("}")
        elif word == "DO":
            n = self.new_label()
            if p.more():
                kw = p.expect_word("WHILE", "UNTIL")
                cond = p.condition()
                c = cond if kw == "WHILE" else f"!({cond})"
                self.emit(line, f"while ({c}) {{")
            else:
                self.emit(line, "for (;;) {")
            p.end()
            self.blocks.append(["DO", line, False, n])
            self.indent += 1
        elif word == "LOOP":
            b = self.need_block("DO", line, "LOOP")
            if p.more():
                kw = p.expect_word("WHILE", "UNTIL")
                cond = p.condition()
                p.end()
                b[2] = True
                self.emit(line, f"if (!({cond})) goto b89_x{b[3]};" if kw == "WHILE"
                          else f"if ({cond}) goto b89_x{b[3]};")
            self.blocks.pop()
            self.indent -= 1
            self.emit_raw("}")
            self.close_label(b)
        elif word == "WHILE":
            cond = p.condition()
            p.end()
            self.emit(line, f"while ({cond}) {{")
            self.blocks.append(["WHILE", line, False, self.new_label()])
            self.indent += 1
        elif word == "WEND":
            b = self.need_block("WHILE", line, "WEND")
            p.end()
            self.blocks.pop()
            self.indent -= 1
            self.emit_raw("}")
            self.close_label(b)
        elif word == "EXIT":
            what = p.expect_word("FOR", "DO", "WHILE", "SUB", "FUNCTION")
            p.end()
            if what in ("SUB", "FUNCTION"):
                if not self.proc or (what == "SUB") != (self.proc.ret is None):
                    raise CompileError(line, f"EXIT {what} outside a {what}")
                self.emit(line, "return;" if what == "SUB" else
                          'return "";' if self.proc.ret == "str" else "return 0;")
            else:
                b = next((b for b in reversed(self.blocks) if b[0] == what), None)
                if b is None:
                    raise CompileError(line, f"EXIT {what} outside a {what} loop")
                b[2] = True
                self.emit(line, f"goto b89_x{b[3] if what != 'FOR' else b[5]};")
        elif word == "RETURN":
            if not self.proc or self.proc.ret is None:
                raise CompileError(line, "RETURN value is only allowed in a FUNCTION")
            e, ety = p.expr()
            p.end()
            p.same_kind(self.proc.ret, ety, "RETURN")
            if ety == "str":
                self.emit(line, f"return b89_sset(b89_r, sizeof b89_r, {e});")
            else:
                self.emit(line, f"return {conv(e, ety, self.proc.ret)};")
        elif word == "PRINT":
            self.print_stmt(p, line)
        elif word == "INPUT":
            if p.more() and p.peek().kind == "str":
                prompt = c_string(p.next().val, line).replace("%", "%%")
                p.expect_op(";") if p.peek().is_(";") else p.expect_op(",")
                self.emit(line, f'b89_puts("{prompt.replace("%%", "%")}");')
            name = p.expect_id()
            target, ty = p.lvalue(name)
            p.end()
            if ty == "str":
                p.writable(name)
                self.emit(line, f"b89_input({target}, sizeof({target}));")
            else:
                p.num(ty)
                fn = "b89_input_fixed()" if ty == "fixed" else "b89_input_long()"
                self.emit(line, f"{target} = {conv(fn, 'fixed' if ty == 'fixed' else 'long', ty)};")
        elif word == "CLS":
            p.end()
            self.emit(line, "b89_cls();")
        elif word == "LOCATE":
            r, c = p.args(2)
            self.emit(line, f"b89_locate({r}, {c});")
        elif word == "PSET":
            a = p.args(2, 3)
            self.emit(line, f"b89_pset({a[0]}, {a[1]}, {a[2] if len(a) > 2 else -1});")
        elif word == "LINE":
            a = p.args(4, 5)
            self.emit(line, f"b89_line({', '.join(a[:4])}, {a[4] if len(a) > 4 else -1});")
        elif word == "BOX":
            a = p.args(4, 5, stop_word="FILL")
            fill = 1 if p.more() and p.expect_word("FILL") else 0
            p.end()
            self.emit(line, f"b89_box({', '.join(a[:4])}, {a[4] if len(a) > 4 else -1}, {fill});")
        elif word == "CIRCLE":
            a = p.args(3, 4, stop_word="FILL")
            fill = 1 if p.more() and p.expect_word("FILL") else 0
            p.end()
            self.emit(line, f"b89_circle({', '.join(a[:3])}, {a[3] if len(a) > 3 else -1}, {fill});")
        elif word == "SCREEN":
            mode = p.expect_word("BUFFERED", "DIRECT", "GRAY4")
            gray = mode == "GRAY4"
            self.uses_gray = self.uses_gray or gray
            buffered = mode == "BUFFERED" or (gray and p.more() and p.expect_word("BUFFERED"))
            p.end()
            self.emit(line, f"b89_screen({int(gray)}, {int(bool(buffered))});")
        elif word == "SPRITE":
            if len(toks) < 6:
                raise CompileError(line, "expected SPRITE image, x, y [, XOR]")
            im = p.image()
            p.expect_op(",")
            x = conv(*p.num_expr(), "long")
            p.expect_op(",")
            y = conv(*p.num_expr(), "long")
            a = [x, y]
            xor = 0
            if p.more():
                p.expect_op(",")
                p.expect_word("XOR")
                xor = 1
            p.end()
            self.emit(line, f"b89_sprite(&b89i_{im.name}, {a[0]}, {a[1]}, {xor});")
        elif word in ("MAP", "MAPROW"):
            g = p.expect_id()
            v = self.lookup(g.val, line)
            if not v.dims or len(v.dims) != 2 or v.ctype != "short":
                raise CompileError(line, f"{word}: '{g.val}' must be a 2-dimension INTEGER array "
                                         f"(DIM {g.val}(rows, columns) AS INTEGER)")
            grid = f"&{v.ref}[0][0]"
            rows, cols = v.size_exprs()
            p.expect_op(",")
            if word == "MAP":
                ts = p.expect_id()
                if ts.val.lower() not in self.tilesets:
                    raise CompileError(line, f"'{ts.val}' is not a TILESET")
                n = len(self.tilesets[ts.val.lower()][1])
                p.expect_op(",")
                sx, sy = p.args(2)
                opaque = all(PIXELS[ch] is not None for im in self.tilesets[ts.val.lower()][1]
                             for row in im.rows for ch in row)
                self.emit(line, f"b89_map({grid}, {rows}, {cols}, b89ts_{ts.val.lower()}, {n}, "
                                f"{sx}, {sy}, {int(opaque)});")
            else:
                r = conv(*p.num_expr(), "long")
                p.expect_op(",")
                e, ty = p.expr()
                p.end()
                p.same_kind("str", ty, "MAPROW")
                self.emit(line, f"b89_maprow({grid}, {rows}, {cols}, {r}, {e});")
        elif word in ("SAVE", "LOAD", "KILL"):
            name = p.save_name(word)
            if word == "KILL":
                p.end()
                self.emit(line, f"b89_kill({name});")
                return
            refs = []
            while p.more():
                p.expect_op(",")
                v = p.expect_id()
                ref, ty = p.lvalue(v, whole=True)
                lv = self.locals.get(v.val.lower()) if self.proc else None
                if lv is not None and lv.readonly:
                    raise CompileError(line, f"{word}: '{v.val}' is a STRING parameter (copy it "
                                             "to a local STRING variable)")
                refs.append(ref)
            if not refs:
                raise CompileError(line, f'expected {word} "name", variable, variable...')
            ptrs = ", ".join(f"&({r})" for r in refs)
            sizes = ", ".join(f"sizeof({r})" for r in refs)
            const = "const " if word == "SAVE" else ""
            self.emit(line, f"{{ {const}void *b89_p[] = {{{ptrs}}}; short b89_z[] = {{{sizes}}}; "
                            f"b89_{word.lower()}({name}, b89_p, b89_z, {len(refs)}); }}")
        elif word == "SOUND":
            f, ms = p.args(2)
            self.emit(line, f"b89_tone({f}, {ms});")
        elif word == "BEEP":
            p.end()
            self.emit(line, "b89_tone(880, 80);")
        elif word == "PLAY":
            e, ty = p.expr()
            p.end()
            p.same_kind("str", ty, "PLAY")
            self.emit(line, f"b89_play({e});")
        elif word == "COLOR":
            (c,) = p.args(1)
            self.emit(line, f"b89_color = {c};")
        elif word == "FLIP":
            p.end()
            self.emit(line, "b89_flip();")
        elif word == "WAITFRAME":
            (fps,) = p.args(1)
            self.emit(line, f"b89_waitframe({fps});")
        elif word == "WAITKEY":
            p.end()
            self.emit(line, "b89_getkey();")
        elif word == "DELAY":
            (ms,) = p.args(1)
            self.emit(line, f"b89_delay({ms});")
        elif word == "CALL":
            name = p.expect_id()
            self.call_stmt(name, p, line)
        elif t0.kind == "id" and word not in KEYWORDS:
            if t0.val.lower() in self.procs and not (p.more() and p.peek().is_("=", "+=", "-=", "*=")):
                self.call_stmt(t0, p, line)
            else:
                self.assignment(t0, p, line)
        else:
            raise CompileError(line, f"unexpected '{t0.val}'")

    def need_block(self, kind, line, what):
        if not self.blocks or self.blocks[-1][0] != kind:
            if self.blocks:
                b = self.blocks[-1]
                raise CompileError(line, f"{what} found, but the {b[0]} of line {b[1]} "
                                         f"is not closed ({self.block_end(b[0])})")
            raise CompileError(line, f"{what} without {kind}")
        return self.blocks[-1]

    def close_label(self, b):
        if b[2]:
            n = b[5] if b[0] == "FOR" else b[3]
            self.emit_raw(f"b89_x{n}: ;")

    def dim(self, p, line):
        scope = self.locals if self.proc else self.globals
        while True:
            name = p.expect_id()
            self.check_new_name(name.val, line, scope)
            dims = p.dims()
            p.expect_word("AS")
            ctype = p.type_name()
            v = Var(name.val.lower(), ctype, dims, line, cap=p.cap)
            scope[v.name] = v
            if p.more() and p.peek().is_("="):
                if dims or is_rec(ctype):
                    raise CompileError(line, "an array or a TYPE variable cannot be "
                                             "initialized with =")
                p.next()
                e, ety = p.expr()
                p.same_kind(ctype, ety, "DIM")
                if ctype == "str":
                    self.emit(line, f"b89_sset(bv_{v.name}, sizeof bv_{v.name}, {e});")
                else:
                    self.emit(line, f"bv_{v.name} = {conv(e, ety, ctype)};")
            elif dims or is_rec(ctype):  # DIM sets to 0, also when the program runs again
                self.emit(line, f"memset(&bv_{v.name}, 0, sizeof bv_{v.name});")
            elif ctype == "str":
                self.emit(line, f"bv_{v.name}[0] = 0;")
            else:
                self.emit(line, f"bv_{v.name} = 0;")
            if not p.more():
                break
            p.expect_op(",")

    def for_stmt(self, p, line):
        var_tok = p.expect_id()
        ref, ty = p.lvalue(var_tok)
        if is_rec(ty) or ty == "str":
            raise CompileError(line, "the FOR counter must be a number")
        p.expect_op("=")
        start, t1 = p.num_expr()
        start = conv(start, t1, ty)
        p.expect_word("TO")
        end, t2 = p.num_expr()
        end = conv(end, t2, ty)
        step = conv("1", "short", ty)
        if p.more():
            p.expect_word("STEP")
            step, t3 = p.num_expr()
            step = conv(step, t3, ty)
        p.end()
        n = self.new_label()
        self.emit(line, "{")
        self.indent += 1
        neg = re.fullmatch(r"\(?-\s*\d+\)?", step.replace(" ", "")) is not None
        lit = re.fullmatch(r"\(?-?\s*\d+\)?", step.replace(" ", "")) is not None
        if lit:
            st = step
            test = f"{ref} >= b89_to{n}" if neg else f"{ref} <= b89_to{n}"
            self.emit(line, f"long b89_to{n} = {end};")
        else:
            st = f"b89_st{n}"
            self.emit(line, f"long b89_to{n} = {end}; long b89_st{n} = {step};")
            test = f"(b89_st{n} >= 0 ? {ref} <= b89_to{n} : {ref} >= b89_to{n})"
        self.emit(line, f"for ({ref} = {start}; {test}; ) {{")
        self.indent += 1
        # [kind, line, exit label used, counter name, step, exit label number, counter C code]
        self.blocks.append(["FOR", line, False, var_tok.val.lower(), st, n, ref])

    def print_stmt(self, p, line):
        fmt, args, newline = [], [], True
        while p.more():
            t = p.peek()
            if t.is_(";"):
                p.next()
                newline = False
                continue
            if t.is_(","):
                p.next()
                fmt.append(" ")
                newline = False
                continue
            newline = True
            nxt = p.toks[p.i + 1] if p.i + 1 < len(p.toks) else None
            if t.kind == "str" and (nxt is None or nxt.is_(";", ",")):
                p.next()                     # plain text: written into the format
                fmt.append(c_string(t.val, line).replace("%", "%%"))
            else:
                e, ty = p.expr()
                if ty == "str":
                    fmt.append("%s")
                    args.append(e)
                    continue
                p.num(ty)
                if ty == "fixed":
                    fmt.append("%s")
                    args.append(f"b89_fstr({e})")
                else:
                    fmt.append("%ld")
                    args.append(f"(long)({e})")
        if newline:
            fmt.append("\\n")
        a = "".join(", " + x for x in args)
        if args:
            self.emit(line, f'sprintf(b89_pbuf, "{"".join(fmt)}"{a}); b89_puts(b89_pbuf);')
        else:
            self.emit(line, f'b89_puts("{"".join(fmt).replace("%%", "%")}");')

    def call_stmt(self, name_tok, p, line):
        proc = self.procs.get(name_tok.val.lower())
        if proc is None:
            raise CompileError(line, f"unknown SUB '{name_tok.val}'")
        if proc.ret is not None:
            raise CompileError(line, f"{proc.name} is a FUNCTION: use its value, "
                                     f"e.g. x = {proc.name}(...)")
        paren = p.more() and p.peek().is_("(")
        if paren:
            p.next()
        args = p.call_arguments(proc, ")" if paren else None)
        if paren:
            p.expect_op(")")
        p.end()
        self.emit(line, f"bs_{proc.cname}({p.call_args(proc, args)});")

    def assignment(self, name_tok, p, line):
        if name_tok.val.lower() in self.consts:
            raise CompileError(line, f"'{name_tok.val}' is a CONST, it cannot be changed")
        target, ty = p.lvalue(name_tok)
        if not p.more():
            raise CompileError(line, f"'{name_tok.val}' alone is not a statement "
                                     "(expected = value, or a SUB name)")
        op = p.next()
        if not op.is_("=", "+=", "-=", "*="):
            raise CompileError(line, f"expected = after {name_tok.val}")
        e, ety = p.expr()
        p.end()
        if ty == "str" or ety == "str":
            p.same_kind(ty, ety, "=")
            p.writable(name_tok)
            if op.val not in ("=", "+="):
                raise CompileError(line, f"{op.val} cannot be used with a STRING (= or +=)")
            fn = "b89_sset" if op.val == "=" else "b89_sappend"
            self.emit(line, f"{fn}({target}, sizeof({target}), {e});")
        elif is_rec(ty) or is_rec(ety):
            if op.val != "=" or ty != ety:
                raise CompileError(line, f"cannot assign {self.tname(ety)} to {self.tname(ty)}")
            self.emit(line, f"{target} = {e};")
        elif op.val == "=":
            self.emit(line, f"{target} = {conv(e, ety, ty)};")
        elif "fixed" in (ty, ety):
            # x += 0.5, f *= 2... : computed with the FIXED rules, then stored
            r, rty = p.arith(target, ty, op.val[0], e, ety)
            self.emit(line, f"{target} = {conv(r, rty, ty)};")
        else:
            self.emit(line, f"{target} {op.val} {e};")


class Parser:
    """Expression and argument parser for one statement."""

    def __init__(self, comp, toks, start):
        self.c, self.toks, self.i = comp, toks, start
        self.cap = 255
        self.line = toks[0].line

    def more(self):
        return self.i < len(self.toks)

    def peek(self):
        return self.toks[self.i]

    def next(self):
        if not self.more():
            raise CompileError(self.line, "incomplete statement")
        t = self.toks[self.i]
        self.i += 1
        return t

    def end(self):
        if self.more():
            raise CompileError(self.line, f"unexpected '{self.peek().val}'")

    def expect_op(self, op):
        t = self.next()
        if not t.is_(op):
            raise CompileError(self.line, f"expected '{op}' instead of '{t.val}'")
        return t

    def expect_word(self, *words):
        t = self.next()
        if not t.is_(*words):
            raise CompileError(self.line, f"expected {' or '.join(words)} instead of '{t.val}'")
        return t.val.upper()

    def expect_id(self):
        t = self.next()
        if t.kind != "id":
            raise CompileError(self.line, f"expected a name instead of '{t.val}'")
        return t

    def type_name(self):
        t = self.next()
        ty = TYPES.get(t.val.upper())
        self.cap = 255
        if ty == "str" and self.more() and self.peek().is_("*"):
            self.next()
            e, cty = self.add()               # not a whole expression: "= value" may follow
            try:
                self.cap = int(eval(e.replace("L", "").replace("/", "//"), {"__builtins__": {}}))
            except Exception:
                raise CompileError(self.line, "STRING * n: n must be a constant")
            if not 1 <= self.cap <= 255:
                raise CompileError(self.line, "STRING * n: n must be between 1 and 255")
        if ty:
            return ty
        if t.kind == "id" and t.val.lower() in self.c.records:
            return f"rec:{t.val.lower()}"
        raise CompileError(self.line, f"unknown type '{t.val}' (INTEGER, LONG, BOOLEAN "
                                      "or the name of a TYPE)")

    def dims(self):
        """(10) or (20, 12) after a name in DIM or TYPE: the upper bounds, or None."""
        if not (self.more() and self.peek().is_("(")):
            return None
        self.next()
        dims = []
        while True:
            d = self.const_expr()
            if not 0 <= d <= 8000:
                raise CompileError(self.line, "array bounds must be between 0 and 8000")
            dims.append(d)
            if self.peek().is_(")"):
                break
            self.expect_op(",")
        self.next()
        n = 1
        for d in dims:
            n *= d + 1
        if n > 16000:
            raise CompileError(self.line, f"array too large ({n} elements)")
        return dims

    def indices(self, dims, what):
        if not (self.more() and self.peek().is_("(")):
            raise CompileError(self.line, f"'{what}' is an array: give an index, e.g. "
                                          f"{what}({', '.join('ijk'[:len(dims)] if len(dims) <= 3 else ['i'] * len(dims))})")
        self.next()
        idx = self.expr_list(")")
        self.expect_op(")")
        if len(idx) != len(dims):
            raise CompileError(self.line, f"'{what}' has {len(dims)} dimension(s), "
                                          f"{len(idx)} index(es) given")
        return "".join(f"[{i}]" for i in idx)

    def lvalue(self, name_tok, whole=False):
        """A variable, an array element, a record field (a.b(2).c...): (C code, type).
        whole: a whole array may be given without index (SAVE, LOAD)."""
        v = self.c.lookup(name_tok.val, self.line)
        code, ty, what = v.ref, v.ctype, name_tok.val
        self.whole = None
        if v.dims and whole and not (self.more() and self.peek().is_("(")):
            self.whole = (v.size_exprs(), v.str_size() if ty == "str" else None)
            return code, ty
        if v.dims:
            code += self.indices(v.dims, what)
        elif self.more() and self.peek().is_("("):
            raise CompileError(self.line, f"'{what}' is not an array")
        while self.more() and self.peek().is_("."):
            self.next()
            if not is_rec(ty):
                raise CompileError(self.line, f"'{what}' is not a TYPE variable: it has no fields")
            rec = self.c.records[ty[4:]]
            f = self.expect_id()
            fld = rec.fields.get(f.val.lower())
            if fld is None:
                raise CompileError(self.line, f"TYPE {rec.display} has no field '{f.val}'")
            what = f"{what}.{f.val}"
            code, ty = f"{code}.bv_{fld.name}", fld.ctype
            if fld.dims and whole and not (self.more() and self.peek().is_("(")):
                self.whole = (fld.size_exprs(), fld.str_size() if ty == "str" else None)
                return code, ty
            if fld.dims:
                code += self.indices(fld.dims, what)
            elif self.more() and self.peek().is_("("):
                raise CompileError(self.line, f"'{what}' is not an array")
        return code, ty

    def call_arguments(self, proc, closer):
        """Parses the arguments of a call: an expression, or a variable for a BYREF
        parameter, or a whole array for an array parameter.
        Returns [(code, type, whole array info or None, is a variable)]."""
        args = []
        if not self.more() or (closer and self.peek().is_(closer)):
            return args
        while True:
            pa = proc.params[len(args)] if len(args) < len(proc.params) else None
            if pa is not None and (pa.rank or pa.mode == "ref"):
                t = self.next()
                if t.kind != "id":
                    raise CompileError(self.line, f"{proc.name}: '{pa.name}' is BYREF or an array: "
                                                  "give a variable")
                if pa.ty == "str" and not pa.rank:
                    self.writable(t)
                code, ty = self.lvalue(t, whole=bool(pa.rank))
                if self.more() and not self.peek().is_(",") and not (closer and self.peek().is_(closer)):
                    raise CompileError(self.line, f"{proc.name}: '{pa.name}' is BYREF: give a "
                                                  "variable, not a calculation")
                args.append((code, ty, self.whole, True))
            else:
                e, ty = self.expr()
                args.append((e, ty, None, False))
            if self.more() and self.peek().is_(","):
                self.next()
                continue
            return args

    def call_args(self, proc, args):
        """Checks the arguments of a call and makes the C argument list."""
        if len(args) != len(proc.params):
            raise CompileError(self.line, f"{proc.name} takes {len(proc.params)} argument(s), "
                                          f"{len(args)} given")
        out = []
        for pa, (code, ty, whole, is_var) in zip(proc.params, args):
            want = self.c.tname(pa.ty) + ("()" if pa.rank else "")
            if pa.rank:                               # array: sizes, then its address
                if whole is None or len(whole[0]) != pa.rank or ty != pa.ty:
                    raise CompileError(self.line, f"{proc.name}: '{pa.name}' must be an array "
                                                  f"{self.c.tname(pa.ty)} with {pa.rank} "
                                                  "dimension(s), given without index")
                sizes, strsize = whole
                out += sizes + ([strsize] if pa.ty == "str" else []) + [self.address(code)]
            elif pa.mode == "ref":                    # BYREF: the address of the variable
                if ty != pa.ty:
                    raise CompileError(self.line, f"{proc.name}: '{pa.name}' is BYREF "
                                                  f"{self.c.tname(pa.ty)}: give a variable of "
                                                  f"that type, not {self.c.tname(ty)}")
                if whole is not None:
                    raise CompileError(self.line, f"{proc.name}: '{pa.name}' is not an array "
                                                  "parameter: give an element")
                if pa.ty == "str":
                    out.append(f"sizeof({code})")
                out.append(self.address(code))
            elif pa.ty == "str" or ty == "str" or is_rec(pa.ty) or is_rec(ty):
                if pa.ty != ty:
                    raise CompileError(self.line, f"{proc.name}: '{pa.name}' must be "
                                                  f"{want}, not {self.c.tname(ty)}")
                out.append(code)                      # STRING (pointer), or a TYPE copied
            else:
                out.append(conv(code, ty, pa.ty))
        return ", ".join(out)

    @staticmethod
    def address(code):
        """&code; a BYREF parameter (*bv_x) is already the address bv_x."""
        if code.startswith("(*") and code.endswith(")") and code.count("(") == 1:
            return code[2:-1]
        return f"&{code}"

    def num_expr(self):
        e, ty = self.expr()
        return e, self.num(ty)

    def same_kind(self, to, frm, what):
        """Text and numbers do not mix: STRING only with STRING."""
        if (to == "str") != (frm == "str"):
            if what in ("=", "DIM"):
                msg = f"cannot assign {self.c.tname(frm)} to {self.c.tname(to)}"
            else:
                msg = f"{what}: a {self.c.tname(to)} is expected, not {self.c.tname(frm)}"
            raise CompileError(self.line, msg + " (STR$() and VAL() convert)")

    def writable(self, name_tok):
        v = self.c.locals.get(name_tok.val.lower()) if self.c.proc else None
        if v is not None and v.readonly:
            raise CompileError(self.line, f"'{name_tok.val}' is a STRING parameter: it cannot "
                                          f"be changed (BYVAL {name_tok.val} AS STRING gives a copy "
                                          f"that can be changed, BYREF changes the caller's text)")

    def tmp(self):
        """A temporary string buffer for the current statement."""
        n = self.c.tmp_n
        self.c.tmp_n += 1
        self.c.tmp_max = max(self.c.tmp_max, self.c.tmp_n)
        if self.c.tmp_n > 24:
            raise CompileError(self.line, "string expression too complex: split it")
        return f"b89_t{n}"

    def num(self, ty):
        if ty == "str":
            raise CompileError(self.line, "a STRING cannot be used here (VAL() converts text "
                                          "to a number)")
        if is_rec(ty):
            raise CompileError(self.line, f"a {self.c.tname(ty)} variable cannot be used here "
                                          "(use one of its fields)")
        return ty

    def params(self):
        """( [BYVAL | BYREF] name [(,...)] AS type, ... )"""
        params = []
        if self.more() and self.peek().is_("("):
            self.next()
            while not self.peek().is_(")"):
                how = self.next().val.upper() if self.peek().is_("BYVAL", "BYREF") else None
                n = self.expect_id()
                rank = 0
                if self.more() and self.peek().is_("("):     # a() or a(,): an array
                    self.next()
                    rank = 1
                    while self.peek().is_(","):
                        self.next()
                        rank += 1
                    self.expect_op(")")
                self.expect_word("AS")
                ty = self.type_name()
                if rank:
                    if how == "BYVAL":
                        raise CompileError(self.line, f"'{n.val}()': arrays are always passed "
                                                      "by reference (no BYVAL)")
                    mode = "ref"
                elif how == "BYREF":
                    mode = "ref"
                elif how == "BYVAL":
                    mode = "copy" if ty == "str" else "val"
                else:
                    mode = "ro" if ty == "str" else "ref" if is_rec(ty) else "val"
                if any(pa.key == n.val.lower() for pa in params):
                    raise CompileError(self.line, f"two parameters named '{n.val}'")
                params.append(Param(n.val, ty, mode, rank))
                if not self.peek().is_(")"):
                    self.expect_op(",")
            self.next()
        return params

    def args(self, nmin, nmax=None, stop_word=None):
        a = self.expr_list(None, stop_word)
        if not (nmin <= len(a) <= (nmax or nmin)):
            want = f"{nmin}" if not nmax else f"{nmin} to {nmax}"
            raise CompileError(self.line, f"{self.toks[0].val.upper()} takes {want} values, "
                                          f"{len(a)} given")
        if stop_word is None:
            self.end()
        return a

    def expr_list(self, closer, stop_word=None, typed=False):
        out = []
        if not self.more() or (closer and self.peek().is_(closer)) or \
                (stop_word and self.peek().is_(stop_word)):
            return out
        while True:
            e, ty = self.expr() if typed else self.num_expr()
            out.append((e, ty) if typed else conv(e, ty, "long"))
            if self.more() and self.peek().is_(","):
                self.next()
                continue
            return out

    def const_expr(self):
        """A constant integer (array bounds)."""
        v, ty = self.const_value()
        if ty not in ("short", "long"):
            raise CompileError(self.line, "an integer constant is expected here")
        return v

    def const_value(self):
        """(value, type) of a constant expression; a FIXED value is stored * 65536."""
        if self.more() and self.peek().kind == "str" and (
                self.i + 1 == len(self.toks) or self.toks[self.i + 1].is_(",")):
            return f'"{c_string(self.next().val, self.line)}"', "str"
        e, ty = self.num_expr()
        try:
            return int(eval(e.replace("L", "").replace("/", "//"), {"__builtins__": {}})), ty
        except Exception:
            raise CompileError(self.line, "a constant value is expected here")

    def case_tests(self, var, vty="long"):
        """CASE 1, 3 TO 5, IS > 10  ->  C condition on the SELECT value."""
        tests = []
        while True:
            if self.more() and self.peek().is_("IS"):
                self.next()
                ops = {"=": "==", "<>": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">="}
                op = self.next()
                if op.val not in ops:
                    raise CompileError(self.line, f"expected a comparison after IS instead of '{op.val}'")
                e, ety = self.add()
                tests.append(self.arith(var, vty, op.val, e, ety)[0])
            else:
                a, aty = self.add()
                if self.more() and self.peek().is_("TO"):
                    self.next()
                    b, bty = self.add()
                    tests.append(f"({self.arith(var, vty, '>=', a, aty)[0]} && "
                                 f"{self.arith(var, vty, '<=', b, bty)[0]})")
                else:
                    tests.append(self.arith(var, vty, "=", a, aty)[0])
            if not self.more():
                break
            self.expect_op(",")
        return " || ".join(tests)

    # precedence: OR < AND < NOT < comparisons < + - < * / \ MOD < unary minus
    def condition(self):
        e, _ = self.num_expr()
        return e

    def expr(self):
        a, ta = self.and_expr()
        while self.more() and self.peek().is_("OR"):
            self.next()
            b, tb = self.and_expr()
            self.num(ta), self.num(tb)
            a, ta = f"({a} || {b})", "short"
        return a, ta

    def and_expr(self):
        a, ta = self.not_expr()
        while self.more() and self.peek().is_("AND"):
            self.next()
            b, tb = self.not_expr()
            self.num(ta), self.num(tb)
            a, ta = f"({a} && {b})", "short"
        return a, ta

    def not_expr(self):
        if self.more() and self.peek().is_("NOT"):
            self.next()
            a, ta = self.not_expr()
            self.num(ta)
            return f"(!{a})", "short"
        return self.compare()

    def compare(self):
        a, ta = self.add()
        ops = {"=": "==", "<>": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">="}
        if self.more() and self.peek().kind == "op" and self.peek().val in ops:
            op = self.next().val
            b, tb = self.add()
            return self.arith(a, ta, op, b, tb)
        return a, ta

    def arith(self, a, ta, op, b, tb):
        """a op b with the type rules: INTEGER < LONG < FIXED (FIXED if one side is)."""
        cmp0 = {"=": "==", "<>": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">="}
        if ta == "str" and tb == "str":
            if op == "+":
                return f"b89_cat({self.tmp()}, {a}, {b})", "str"
            if op in cmp0:
                return f"(strcmp({a}, {b}) {cmp0[op]} 0)", "short"
            raise CompileError(self.line, f"'{op}' cannot be used with STRINGs (+ joins them)")
        if "str" in (ta, tb):
            raise CompileError(self.line, "text and numbers cannot be mixed "
                                          "(STR$() and VAL() convert)")
        self.num(ta), self.num(tb)
        cmp = {"=": "==", "<>": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">="}
        if "fixed" in (ta, tb):
            fa, fb = conv(a, ta, "fixed"), conv(b, tb, "fixed")
            if op in cmp:
                return f"({fa} {cmp[op]} {fb})", "short"
            if op in "+-":
                return f"({fa} {op} {fb})", "fixed"
            if op == "*":
                if ta != "fixed":                 # integer * FIXED: no shift needed
                    return f"({fb} * (long)({a}))", "fixed"
                if tb != "fixed":
                    return f"({fa} * (long)({b}))", "fixed"
                return f"b89_fmul({fa}, {fb})", "fixed"
            if op == "/":
                if tb != "fixed":                 # FIXED / integer
                    return f"({fa} / (long)({b}))", "fixed"
                return f"b89_fdiv({fa}, {fb})", "fixed"
            if op == "\\":
                return f"(b89_fdiv({fa}, {fb}) >> 16)", "long"
            raise CompileError(self.line, "MOD works on integers only (use INT() first)")
        if op in cmp:
            return f"({a} {cmp[op]} {b})", "short"
        cop = {"\\": "/", "MOD": "%"}.get(op, op)
        return f"({a} {cop} {b})", "long" if "long" in (ta, tb) else "short"

    def add(self):
        a, ta = self.mul()
        while self.more() and self.peek().is_("+", "-"):
            op = self.next().val
            b, tb = self.mul()
            a, ta = self.arith(a, ta, op, b, tb)
        return a, ta

    def mul(self):
        a, ta = self.unary()
        while self.more() and self.peek().is_("*", "/", "\\", "MOD"):
            op = self.next().val.upper()
            b, tb = self.unary()
            a, ta = self.arith(a, ta, op, b, tb)
        return a, ta

    def unary(self):
        if self.more() and self.peek().is_("-"):
            self.next()
            a, ta = self.unary()
            return f"(-{a})", self.num(ta)
        if self.more() and self.peek().is_("+"):
            self.next()
            return self.unary()
        return self.primary()

    def save_name(self, what):
        """Name of the calculator variable of SAVE / LOAD / KILL / EXISTS (a STRING)."""
        if self.more() and self.peek().kind == "str":
            n = self.peek().val
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,7}", n):
                raise CompileError(self.line, f'{what}: "{n}" is not a calculator variable name '
                                              "(1 to 8 letters or digits, starting with a letter)")
        e, ty = self.expr()
        self.same_kind("str", ty, what)
        return e

    def image(self):
        t = self.expect_id()
        im = self.c.images.get(t.val.lower())
        if im is None:
            raise CompileError(self.line, f"'{t.val}' is not an IMAGE")
        return im

    def image_function(self, up):
        self.expect_op("(")
        if up in ("WIDTH", "HEIGHT"):
            im = self.image()
            self.expect_op(")")
            return str(len(im.rows[0]) if up == "WIDTH" else len(im.rows)), "short"
        a = self.image()                       # COLLIDE(img1, x1, y1, img2, x2, y2)
        self.expect_op(",")
        ax = conv(*self.num_expr(), "long")
        self.expect_op(",")
        ay = conv(*self.num_expr(), "long")
        self.expect_op(",")
        b = self.image()
        self.expect_op(",")
        bx = conv(*self.num_expr(), "long")
        self.expect_op(",")
        by = conv(*self.num_expr(), "long")
        self.expect_op(")")
        return f"b89_collide(&b89i_{a.name}, {ax}, {ay}, &b89i_{b.name}, {bx}, {by})", "short"

    def string_function(self, up):
        self.expect_op("(")
        args = self.expr_list(")", typed=True)
        self.expect_op(")")
        kinds = {"LEFT$": "sn", "RIGHT$": "sn", "MID$": "sn", "STR$": "n", "CHR$": "n",
                 "UCASE$": "s", "LCASE$": "s", "LEN": "s", "ASC": "s", "INSTR": "ss",
                 "VAL": "s"}[up]
        if up == "MID$" and len(args) == 3:
            kinds = "snn"
        if len(args) != len(kinds):
            want = "2 or 3" if up == "MID$" else str(len(kinds))
            raise CompileError(self.line, f"{up} takes {want} argument(s), {len(args)} given")
        a = []
        for k, (code, ty) in zip(kinds, args):
            if k == "s":
                if ty != "str":
                    raise CompileError(self.line, f"{up}: a STRING is expected, not {self.c.tname(ty)}")
                a.append(code)
            else:
                self.num(ty)
                a.append(code if up == "STR$" else conv(code, ty, "long"))
        if up == "STR$":
            ty = args[0][1]
            if ty == "fixed":
                return f"b89_sset({self.tmp()}, {TMP_SIZE}, b89_fstr({a[0]}))", "str"
            return f"b89_str({self.tmp()}, {a[0]})", "str"
        if up == "LEN":
            return f"((short)strlen({a[0]}))", "short"
        if up == "ASC":
            return f"((short)(unsigned char)({a[0]})[0])", "short"
        if up == "INSTR":
            return f"b89_instr({a[0]}, {a[1]})", "long"
        if up == "VAL":
            return f"b89_fval({a[0]})", "fixed"
        if up == "MID$":
            return f"b89_mid({self.tmp()}, {a[0]}, {a[1]}, {a[2] if len(a) > 2 else '-1'})", "str"
        fn = {"LEFT$": "b89_left", "RIGHT$": "b89_right", "CHR$": "b89_chr",
              "UCASE$": "b89_ucase", "LCASE$": "b89_lcase"}[up]
        return f"{fn}({self.tmp()}, {', '.join(a)})", "str"

    def typed_builtin(self, up):
        """Functions whose result follows the type of their arguments (FIXED or integer)."""
        self.expect_op("(")
        args = self.expr_list(")", typed=True)
        self.expect_op(")")
        n = 2 if up in ("MIN", "MAX") else 1
        if len(args) != n:
            raise CompileError(self.line, f"{up} takes {n} argument(s), {len(args)} given")
        for _, ty in args:
            self.num(ty)
        (a, ta) = args[0]
        if up == "ABS":
            return f"b89_abs({a})", "fixed" if ta == "fixed" else "long"
        if up in ("MIN", "MAX"):
            (b, tb) = args[1]
            ty = "fixed" if "fixed" in (ta, tb) else "long"
            return f"b89_{up.lower()}({conv(a, ta, ty)}, {conv(b, tb, ty)})", ty
        if up == "INT":                         # rounded down
            return (f"(({a}) >> 16)", "long") if ta == "fixed" else (a, ta)
        if up == "ROUND":                       # to the nearest integer
            return (f"((({a}) + 32768L) >> 16)", "long") if ta == "fixed" else (a, ta)
        fn = {"SQR": "b89_fsqrt", "SIN": "b89_fsin", "COS": "b89_fcos"}[up]
        return f"{fn}({conv(a, ta, 'fixed')})", "fixed"

    def primary(self):
        t = self.next()
        if t.kind == "num" and "." in t.val:
            return fixed_literal(t.val, self.line), "fixed"
        if t.kind == "num":
            v = t.val
            n = int(v[2:], 16) if v[:2].upper() == "&H" else \
                int(v[2:], 2) if v[:2].upper() == "&B" else int(v)
            return (f"{n}L", "long") if n > 32767 else (str(n), "short")
        if t.kind == "str":
            return f'"{c_string(t.val, self.line)}"', "str"
        if t.is_("("):
            e, ty = self.expr()
            self.expect_op(")")
            return f"({e})", ty
        if t.kind != "id":
            raise CompileError(self.line, f"unexpected '{t.val}'")
        up = t.val.upper()
        if up in ("TRUE", "FALSE"):
            return ("1" if up == "TRUE" else "0"), "short"
        if up in COLORS:
            return str(COLORS[up]), "short"
        if up.startswith("KEY_"):
            raise CompileError(self.line, f"{t.val} can only be used in KEYDOWN({t.val})")
        if up == "KEYDOWN":
            self.expect_op("(")
            k = self.expect_id()
            key = KEYS.get(k.val.upper()[4:]) if k.val.upper().startswith("KEY_") else None
            if not key:
                raise CompileError(self.line, f"unknown key '{k.val}' (KEY_LEFT, KEY_UP, "
                                              "KEY_ENTER, KEY_ESC, KEY_F1...)")
            self.expect_op(")")
            return f"(_keytest({key}) != 0)", "short"
        if up in STR_FUNCS:
            return self.string_function(up)
        if up in ("WIDTH", "HEIGHT", "COLLIDE"):
            return self.image_function(up)
        if up in ("UBOUND", "LBOUND"):
            self.expect_op("(")
            t = self.expect_id()
            code, ty = self.lvalue(t, whole=True)
            if self.whole is None:
                raise CompileError(self.line, f"{up}: '{t.val}' is not an array (give it without index)")
            sizes = self.whole[0]
            d = 1
            if self.more() and self.peek().is_(","):
                self.next()
                d = self.const_expr()
            self.expect_op(")")
            if not 1 <= d <= len(sizes):
                raise CompileError(self.line, f"{up}: '{t.val}' has {len(sizes)} dimension(s)")
            if up == "LBOUND":
                return "0", "short"
            sz = sizes[d - 1]
            return (str(int(sz) - 1) if sz.isdigit() else f"({sz} - 1)"), "short"
        if up == "EXISTS":
            self.expect_op("(")
            n = self.save_name("EXISTS")
            self.expect_op(")")
            return f"b89_exists({n})", "short"
        if t.val.endswith("$") and t.val.lower() not in self.c.procs:
            raise CompileError(self.line, f"unknown function '{t.val}'")
        if up in ("ABS", "MIN", "MAX", "INT", "ROUND", "SQR", "SIN", "COS"):
            return self.typed_builtin(up)
        if up in BUILTINS:
            n, tmpl, ty = BUILTINS[up]
            a = []
            if n or (self.more() and self.peek().is_("(")):
                self.expect_op("(")
                a = self.expr_list(")")
                self.expect_op(")")
            if len(a) != n:
                raise CompileError(self.line, f"{up} takes {n} argument(s), {len(a)} given")
            return tmpl.format(*a), ty
        key = t.val.lower()
        if key in self.c.consts:
            v, cty = self.c.consts[key]
            if cty == "str":
                return v, "str"
            if cty == "fixed":
                return f"({v}L)", "fixed"
            return (f"{v}L", "long") if abs(v) > 32767 else (f"({v})" if v < 0 else str(v), "short")
        if key in self.c.procs and not (self.c.proc and key in self.c.locals):
            proc = self.c.procs[key]
            if proc.ret is None:
                raise CompileError(self.line, f"{proc.name} is a SUB: it has no value")
            a = []
            if self.more() and self.peek().is_("("):
                self.next()
                a = self.call_arguments(proc, ")")
                self.expect_op(")")
            call = f"bs_{proc.cname}({self.call_args(proc, a)})"
            if proc.ret == "str":
                # copied at once: a second call in the same expression reuses the
                # function's result buffer
                return f"b89_sset({self.tmp()}, {TMP_SIZE}, {call})", "str"
            return call, proc.ret
        return self.lvalue(t)


def compile_source(source, filename):
    """Returns the C code; raises CompileError(line, message)."""
    return Compiler(source, filename).compile()


def compile_file(path):
    """Writes path + '.c' (program.b89 -> program.b89.c) and returns its path."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    code = compile_source(src, path)
    out = path + ".c"
    with open(out, "w", encoding="latin-1", newline="\n") as f:
        f.write(code)
    return out
