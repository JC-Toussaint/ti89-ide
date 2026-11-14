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
        self.line = line
        self.msg = msg


# ------------------------------------------------------------------ lexer
_TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t]+)
  | (?P<comment>'.*)
  | (?P<num>&[Hh][0-9A-Fa-f]+|&[Bb][01]+|\d+\.\d*|\.\d+|\d+)
  | (?P<str>"[^"\n]*"?)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
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
UNTIL WAITFRAME WAITKEY WEND WHILE BUFFERED DIRECT SELECT IS TYPE
""".split())

TYPES = {"INTEGER": "short", "LONG": "long", "BOOLEAN": "short", "FIXED": "fixed"}

KEYS = {"LEFT": "RR_LEFT", "RIGHT": "RR_RIGHT", "UP": "RR_UP", "DOWN": "RR_DOWN",
        "ENTER": "RR_ENTER", "ESC": "RR_ESC", "F1": "RR_F1", "F2": "RR_F2", "F3": "RR_F3",
        "F4": "RR_F4", "F5": "RR_F5", "2ND": "RR_2ND", "SHIFT": "RR_SHIFT",
        "DIAMOND": "RR_DIAMOND", "ALPHA": "RR_ALPHA", "CLEAR": "RR_CLEAR",
        "APPS": "RR_APPS", "MODE": "RR_MODE", "HOME": "RR_HOME"}
COLORS = {"WHITE": 0, "BLACK": 1, "XOR": 2}

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


# Types: "short" (INTEGER, BOOLEAN), "long" (LONG), "fixed" (FIXED: 16.16 fixed point,
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
    return ty[4:] if is_rec(ty) else {"short": "INTEGER", "long": "LONG",
                                      "fixed": "FIXED"}.get(ty, ty)


class Var:
    """A variable, a parameter or a record field. dims: list of upper bounds (arrays)."""

    def __init__(self, name, ctype, dims=None, line=0, byref=False):
        self.name, self.ctype, self.dims, self.line = name, ctype, dims, line
        self.byref = byref          # record parameter: passed by address

    @property
    def ref(self):
        return f"(*bv_{self.name})" if self.byref else f"bv_{self.name}"


class Record:
    def __init__(self, name, line, display):
        self.name, self.line, self.display = name, line, display
        self.fields = {}            # name -> Var


class Proc:
    def __init__(self, name, params, ret, line):
        self.name, self.params, self.ret, self.line = name, params, ret, line


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
        self.lines = source.split("\n")
        self.globals = {}
        self.consts = {}
        self.procs = {}
        self.records = {}
        self.proc = None            # Proc being compiled (None: main program)
        self.locals = {}
        self.out = None             # current body (list of C lines)
        self.blocks = []
        self.label_n = 0
        self.end_used = False
        self.end_in_proc = False
        self.indent = 1

    # ---------------------------------------------------------- output
    def emit(self, line, text):
        self.out.append(f'#line {line} "{self.filename}"')
        self.out.append("  " * self.indent + text)

    def emit_raw(self, text):
        self.out.append("  " * self.indent + text)

    def new_label(self):
        self.label_n += 1
        return self.label_n

    # ---------------------------------------------------------- names
    def ctype(self, ty):
        """C type; a TYPE keeps the case of its name (bt_Enemy), shown so by the debugger."""
        if ty == "fixed":
            return "b89fixed"
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
        if up in KEYWORDS or up in TYPES or up in BUILTINS or up in COLORS or \
                up in ("TRUE", "FALSE", "KEYDOWN", "INT", "ROUND", "SQR", "SIN", "COS") or \
                up.startswith("KEY_"):
            raise CompileError(line, f"'{name}' is a reserved word")
        key = name.lower()
        if key in where or key in self.consts or (key in self.procs and where is not None):
            raise CompileError(line, f"'{name}' is already declared")

    # ---------------------------------------------------------- driver
    def compile(self):
        toklines = []
        for i, text in enumerate(self.lines, 1):
            t = tokenize_line(text, i)
            if t:
                toklines.append(t)
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
        return self.assemble(main, procs_code)

    def block_end(self, kind):
        return {"IF": "END IF", "FOR": "NEXT", "DO": "LOOP", "WHILE": "WEND",
                "SELECT": "END SELECT"}[kind]

    def prescan(self, toklines):
        """Reads the TYPEs (removed from the lines to compile), then registers the SUBs and
        FUNCTIONs, so they can be called before their definition."""
        rest, rec = [], None
        for toks in toklines:
            line = toks[0].line
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
                rec.fields[f.val.lower()] = Var(f.val.lower(), ty, dims, line)
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
        for toks in rest:
            if toks[0].is_("SUB", "FUNCTION") and len(toks) > 1:
                p = Parser(self, toks, 1)
                name_tok = p.expect_id()
                self.check_new_name(name_tok.val, name_tok.line, self.procs)
                params = p.params()
                ret = None
                if toks[0].is_("FUNCTION"):
                    p.expect_word("AS")
                    ret = p.type_name()
                    if is_rec(ret):
                        raise CompileError(toks[0].line, "a FUNCTION cannot return a TYPE in "
                                                         "this version (use a SUB parameter)")
                p.end()
                self.procs[name_tok.val.lower()] = Proc(name_tok.val, params, ret, toks[0].line)
        return rest

    def assemble(self, main, procs_code):
        lines = [f"/* Generated by Basic89 from {self.filename}: do not edit, edit the .b89 */",
                 '#include "b89rt.h"', ""]
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
        return f"{self.ctype(v.ctype)} bv_{v.name}" + "".join(f"[{d + 1}]" for d in v.dims or ())

    def proc_header(self, p):
        args = ", ".join(f"{self.ctype(t)} {'*' if is_rec(t) else ''}bv_{n.lower()}"
                         for n, t in p.params) or "void"
        return f"static {self.ctype(p.ret) if p.ret else 'void'} bs_{p.name.lower()}({args})"

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

        if self.blocks and self.blocks[-1][0] == "SELECT" and self.blocks[-1][4] == 0 \
                and word != "CASE" and not (word == "END" and len(toks) > 1 and toks[1].is_("SELECT")):
            raise CompileError(line, "expected CASE after SELECT CASE")

        if word in ("SUB", "FUNCTION"):
            if self.proc:
                raise CompileError(line, "SUB and FUNCTION cannot be nested")
            if self.blocks:
                raise CompileError(line, f"{word} inside a {self.blocks[-1][0]} block")
            self.proc = self.procs[toks[1].val.lower()]
            self.locals = {n.lower(): Var(n.lower(), t, byref=is_rec(t))
                           for n, t in self.proc.params}
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
            code = [f'#line {self.proc_line} "{self.filename}"', self.proc_header(self.proc), "{"]
            for v in self.locals.values():
                if v.name not in {n.lower() for n, _ in self.proc.params}:
                    code.append(f"  {self.decl(v)};")
            code += body
            self.out = code
            if self.proc.ret:
                self.emit(line, "return 0;")
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
            name = p.expect_id()
            self.check_new_name(name.val, line, self.consts)
            p.expect_op("=")
            self.consts[name.val.lower()] = p.const_value()
            p.end()
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
            e, sty = p.num_expr()
            p.end()
            n = self.new_label()
            self.emit(line, "{")
            self.indent += 1
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
                self.emit(line, "return;" if what == "SUB" else "return 0;")
            else:
                b = next((b for b in reversed(self.blocks) if b[0] == what), None)
                if b is None:
                    raise CompileError(line, f"EXIT {what} outside a {what} loop")
                b[2] = True
                self.emit(line, f"goto b89_x{b[3] if what != 'FOR' else b[5]};")
        elif word == "RETURN":
            if not self.proc or self.proc.ret is None:
                raise CompileError(line, "RETURN value is only allowed in a FUNCTION")
            e, ety = p.num_expr()
            p.end()
            self.emit(line, f"return {conv(e, ety, self.proc.ret)};")
        elif word == "PRINT":
            self.print_stmt(p, line)
        elif word == "CLS":
            p.end()
            self.emit(line, "clrscr();")
        elif word == "LOCATE":
            r, c = p.args(2)
            self.emit(line, f"b89_locate({r}, {c});")
        elif word == "PSET":
            a = p.args(2, 3)
            self.emit(line, f"b89_pset({a[0]}, {a[1]}, {a[2] if len(a) > 2 else 1});")
        elif word == "LINE":
            a = p.args(4, 5)
            self.emit(line, f"b89_line({', '.join(a[:4])}, {a[4] if len(a) > 4 else 1});")
        elif word == "BOX":
            a = p.args(4, 5, stop_word="FILL")
            fill = 1 if p.more() and p.expect_word("FILL") else 0
            p.end()
            self.emit(line, f"b89_box({', '.join(a[:4])}, {a[4] if len(a) > 4 else 1}, {fill});")
        elif word == "CIRCLE":
            a = p.args(3, 4)
            self.emit(line, f"b89_circle({', '.join(a[:3])}, {a[3] if len(a) > 3 else 1});")
        elif word == "SCREEN":
            mode = p.expect_word("BUFFERED", "DIRECT")
            p.end()
            self.emit(line, f"b89_screen({1 if mode == 'BUFFERED' else 0});")
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
            v = Var(name.val.lower(), ctype, dims, line)
            scope[v.name] = v
            if p.more() and p.peek().is_("="):
                if dims or is_rec(ctype):
                    raise CompileError(line, "an array or a TYPE variable cannot be "
                                             "initialized with =")
                p.next()
                e, ety = p.num_expr()
                self.emit(line, f"bv_{v.name} = {conv(e, ety, ctype)};")
            elif dims or is_rec(ctype):  # DIM sets to 0, also when the program runs again
                self.emit(line, f"memset(&bv_{v.name}, 0, sizeof bv_{v.name});")
            else:
                self.emit(line, f"bv_{v.name} = 0;")
            if not p.more():
                break
            p.expect_op(",")

    def for_stmt(self, p, line):
        var_tok = p.expect_id()
        ref, ty = p.lvalue(var_tok)
        if is_rec(ty):
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
            if t.kind == "str":
                p.next()
                fmt.append(c_string(t.val, line).replace("%", "%%"))
            else:
                e, ty = p.num_expr()
                if ty == "fixed":
                    fmt.append("%s")
                    args.append(f"b89_fstr({e})")
                else:
                    fmt.append("%ld")
                    args.append(f"(long)({e})")
        if newline:
            fmt.append("\\n")
        a = "".join(", " + x for x in args)
        self.emit(line, f'printf("{"".join(fmt)}"{a});')

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
        args = p.expr_list(")" if paren else None, typed=True)
        if paren:
            p.expect_op(")")
        p.end()
        self.emit(line, f"bs_{proc.name.lower()}({p.call_args(proc, args)});")

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
        if is_rec(ty) or is_rec(ety):
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

    def lvalue(self, name_tok):
        """A variable, an array element, a record field (a.b(2).c...): (C code, type)."""
        v = self.c.lookup(name_tok.val, self.line)
        code, ty, what = v.ref, v.ctype, name_tok.val
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
            if fld.dims:
                code += self.indices(fld.dims, what)
            elif self.more() and self.peek().is_("("):
                raise CompileError(self.line, f"'{what}' is not an array")
        return code, ty

    def call_args(self, proc, args):
        """Checks the arguments of a call; TYPE arguments are passed by address."""
        if len(args) != len(proc.params):
            raise CompileError(self.line, f"{proc.name} takes {len(proc.params)} argument(s), "
                                          f"{len(args)} given")
        out = []
        for (pname, pty), (code, ty) in zip(proc.params, args):
            if is_rec(pty) or is_rec(ty):
                if pty != ty:
                    raise CompileError(self.line, f"{proc.name}: '{pname}' must be "
                                                  f"{self.c.tname(pty)}, not {self.c.tname(ty)}")
                if not code.startswith(("bv_", "(*bv_")):
                    raise CompileError(self.line, f"{proc.name}: '{pname}' must be a variable")
                out.append(code[2:-1] if code.startswith("(*") and code.endswith(")")
                           and code.count("(") == 1 else f"&{code}")
            else:
                out.append(conv(code, ty, pty))
        return ", ".join(out)

    def num_expr(self):
        e, ty = self.expr()
        return e, self.num(ty)

    def num(self, ty):
        if is_rec(ty):
            raise CompileError(self.line, f"a {self.c.tname(ty)} variable cannot be used here "
                                          "(use one of its fields)")
        return ty

    def params(self):
        params = []
        if self.more() and self.peek().is_("("):
            self.next()
            while not self.peek().is_(")"):
                n = self.expect_id()
                self.expect_word("AS")
                params.append((n.val, self.type_name()))
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
        if ty == "fixed":
            raise CompileError(self.line, "an integer constant is expected here")
        return v

    def const_value(self):
        """(value, type) of a constant expression; a FIXED value is stored * 65536."""
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
            raise CompileError(self.line, "text is only allowed in PRINT in this version")
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
                a = self.expr_list(")", typed=True)
                self.expect_op(")")
            return f"bs_{key}({self.call_args(proc, a)})", proc.ret
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
