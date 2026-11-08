"""
Lecture des variables C d'un programme en pause, à partir des informations DWARF 2.

Emplacements gérés (ce que produit GCC 4.1 en -O0 pour le 68000) :
  DW_OP_fbreg n   relatif à la base du cadre (DW_AT_frame_base, liste dans .debug_loc)
  DW_OP_addr a    adresse dans le programme (globales, static) -> base de chargement + a
  DW_OP_bregN n   registre N + n          DW_OP_regN   variable dans un registre
Types : entiers (int = 16 bits avec TIGCC), char, énumérations, pointeurs, tableaux,
structures/unions, typedef/const/volatile, flottants TI (BCD sur 10 octets).
"""
from dataclasses import dataclass, field

from .core import REG_D0, REG_A0

MAX_ARRAY = 200        # éléments affichés au plus
MAX_STRING = 64


def _sleb(data, i):
    result, shift = 0, 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            if b & 0x40:
                result -= 1 << shift
            return result, i


def _uleb(data, i):
    result, shift = 0, 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return result, i


def decode_ti_float(b):
    """Flottant TI-89 (SMAP BCD) : mot exposant (signe en bit 15, biais $4000)
    puis 16 chiffres BCD de mantisse ; valeur = d.ddd... x 10^(exp)."""
    if len(b) < 10:
        return None
    w = (b[0] << 8) | b[1]
    neg = bool(w & 0x8000)
    exp = (w & 0x7FFF) - 0x4000
    digits = "".join(f"{x >> 4}{x & 15}" for x in b[2:10])
    if not digits.isdigit():
        return "NaN/undefined"
    if int(digits) == 0:
        return 0.0
    val = int(digits) / 10 ** 15 * (10.0 ** exp)
    return -val if neg else val


@dataclass
class VarNode:
    name: str
    type_name: str
    value: str
    path: str                                   # identifiant stable (pour l'état déplié)
    children: object = None                     # fonction -> liste de VarNode, ou None
    error: bool = False


class VariableReader:
    def __init__(self, debugger):
        self.dbg = debugger
        self.info = debugger.info
        self.dw = self.info.dwarf
        self._cus = list(self.dw.iter_CUs())
        self._loclists = self.dw.location_lists()

    # ------------------------------------------------------------ mémoire
    @property
    def core(self):
        return self.dbg.core

    def read(self, addr, n):
        out = bytearray()
        ram, rom = self.core.ram, self.core.rom
        for k in range(n):
            a = (addr + k) & 0xFFFFFF
            if a < 0x40000 or 0x200000 <= a < 0x600000:
                out.append(ram[a & 0x3FFFF])
            elif 0x800000 <= a < 0xC00000:
                out.append(rom[a - 0x800000])
            else:
                return None
        return bytes(out)

    def _reg(self, n):
        return self.core.reg(REG_D0 + n) if n < 8 else self.core.reg(REG_A0 + n - 8)

    # ------------------------------------------------------------ emplacements
    def _cu_base(self, cu):
        lp = cu.get_top_DIE().attributes.get("DW_AT_low_pc")
        return lp.value if lp else 0

    def frame_base(self, func, cu, off):
        attr = func.attributes.get("DW_AT_frame_base")
        if attr is None:
            return None
        if attr.form in ("DW_FORM_data4", "DW_FORM_sec_offset"):
            base = self._cu_base(cu)
            for e in self._loclists.get_location_list_at_offset(attr.value):
                if not hasattr(e, "begin_offset"):
                    continue
                if base + e.begin_offset <= off < base + e.end_offset:
                    return self.eval_location(e.loc_expr, None)[0]
            return None
        return self.eval_location(attr.value, None)[0]

    def eval_location(self, expr, fb):
        """Retourne (adresse, None) ou (None, numéro de registre)."""
        data = bytes(expr)
        i, stack = 0, []
        while i < len(data):
            op = data[i]
            i += 1
            if op == 0x03:                                  # DW_OP_addr
                a = int.from_bytes(data[i:i + 4], "big")
                i += 4
                stack.append((self.dbg.base + a) & 0xFFFFFF)
            elif op == 0x91:                                # DW_OP_fbreg
                v, i = _sleb(data, i)
                if fb is None:
                    return None, None
                stack.append((fb + v) & 0xFFFFFFFF)
            elif 0x50 <= op <= 0x5F:                        # DW_OP_reg0..15
                return None, op - 0x50
            elif 0x70 <= op <= 0x7F:                        # DW_OP_breg0..15
                v, i = _sleb(data, i)
                stack.append((self._reg(op - 0x70) + v) & 0xFFFFFFFF)
            elif op == 0x23:                                # DW_OP_plus_uconst
                v, i = _uleb(data, i)
                stack.append((stack.pop() + v) & 0xFFFFFFFF)
            else:
                return None, None
        return (stack[-1] if stack else None), None

    # ------------------------------------------------------------ types
    @staticmethod
    def _type(die):
        return die.get_DIE_from_attribute("DW_AT_type") if "DW_AT_type" in die.attributes else None

    def _strip(self, t):
        while t is not None and t.tag in ("DW_TAG_typedef", "DW_TAG_const_type", "DW_TAG_volatile_type"):
            t = self._type(t)
        return t

    def type_name(self, t):
        if t is None:
            return "void"
        n = t.attributes.get("DW_AT_name")
        tag = t.tag
        if tag == "DW_TAG_pointer_type":
            return self.type_name(self._type(t)) + " *"
        if tag == "DW_TAG_const_type":
            return "const " + self.type_name(self._type(t))
        if tag == "DW_TAG_volatile_type":
            return "volatile " + self.type_name(self._type(t))
        if tag == "DW_TAG_array_type":
            return self.type_name(self._type(t)) + "".join(f"[{d}]" for d in self._dims(t))
        if n:
            name = n.value.decode("latin-1")
            prefix = {"DW_TAG_structure_type": "struct ", "DW_TAG_union_type": "union ",
                      "DW_TAG_enumeration_type": "enum "}.get(tag, "")
            return prefix + name
        return {"DW_TAG_structure_type": "struct {…}", "DW_TAG_union_type": "union {…}",
                "DW_TAG_enumeration_type": "enum {…}"}.get(tag, "?")

    def _dims(self, t):
        dims = []
        for ch in t.iter_children():
            if ch.tag == "DW_TAG_subrange_type":
                ub = ch.attributes.get("DW_AT_upper_bound")
                dims.append(ub.value + 1 if ub else 0)
        return dims or [0]

    def _size(self, t):
        t = self._strip(t)
        if t is None:
            return 1
        bs = t.attributes.get("DW_AT_byte_size")
        if bs:
            return bs.value
        if t.tag == "DW_TAG_array_type":
            n = 1
            for d in self._dims(t):
                n *= d
            return n * self._size(self._type(t))
        return 4

    # ------------------------------------------------------------ valeurs
    def _cstring(self, addr):
        b = self.read(addr, MAX_STRING)
        if b is None:
            return None
        s = b.split(b"\0")[0]
        txt = s.decode("latin-1")
        return '"' + txt + ('…' if len(s) == MAX_STRING else "") + '"'

    def node(self, name, t, addr, path, reg=None):
        tn = self.type_name(t)
        st = self._strip(t)
        if addr is None and reg is None:
            return VarNode(name, tn, "‹unknown location›", path, error=True)
        if reg is not None:
            raw = self._reg(reg).to_bytes(4, "big")
            size = self._size(st)
            data = raw[4 - size:] if size <= 4 else None
            where = f"register {'D' if reg < 8 else 'A'}{reg % 8}"
            addr = None
        else:
            data = None
            where = None
        try:
            return self._value(name, st, tn, addr, data, path, where)
        except Exception as e:                      # mémoire illisible, type exotique...
            return VarNode(name, tn, f"‹{e}›", path, error=True)

    def _value(self, name, st, tn, addr, data, path, where):
        def get(n):
            if data is not None:
                return data[:n]
            b = self.read(addr, n)
            if b is None:
                raise ValueError(f"address ${addr:06X} is not readable")
            return b

        if st is None:
            return VarNode(name, tn, "void", path)
        tag = st.tag
        if tag == "DW_TAG_base_type":
            size = st.attributes["DW_AT_byte_size"].value
            enc = st.attributes["DW_AT_encoding"].value
            b = get(size)
            if enc == 4:                                    # flottant TI (BCD)
                v = decode_ti_float(b)
                return VarNode(name, tn, f"{v:.14g}" if isinstance(v, float) else str(v), path)
            signed = enc in (5, 6, 0xD)
            v = int.from_bytes(b, "big", signed=signed)
            if enc in (6, 8) and size == 1:                 # char
                ch = chr(v & 0xFF)
                shown = f" '{ch}'" if 32 <= (v & 0xFF) < 127 else ""
                return VarNode(name, tn, f"{v}{shown}", path)
            if enc == 2:
                return VarNode(name, tn, "true" if v else "false", path)
            return VarNode(name, tn, str(v), path)
        if tag == "DW_TAG_enumeration_type":
            size = st.attributes["DW_AT_byte_size"].value
            v = int.from_bytes(get(size), "big", signed=True)
            for e in st.iter_children():
                if e.attributes["DW_AT_const_value"].value == v:
                    return VarNode(name, tn, f"{e.attributes['DW_AT_name'].value.decode()} ({v})", path)
            return VarNode(name, tn, str(v), path)
        if tag == "DW_TAG_pointer_type":
            p = int.from_bytes(get(4), "big")
            target = self._type(st)
            tt = self._strip(target)
            text = "NULL" if p == 0 else f"${p:06X}"
            children = None
            if p and tt is not None and tt.tag == "DW_TAG_base_type" and self._size(tt) == 1:
                s = self._cstring(p)
                if s:
                    text += f"  → {s}"
            elif p and tt is not None:
                children = lambda: [self.node("*" + name, target, p, path + "/*")]
            return VarNode(name, tn, text, path, children)
        if tag == "DW_TAG_array_type":
            elem = self._type(st)
            dims = self._dims(st)
            esize = self._size(elem)
            count = dims[0]
            # Tableau de char : affiché comme une chaîne
            et = self._strip(elem)
            if len(dims) > 1:
                # Tableau à plusieurs dimensions : sous-tableaux
                sub_count = 1
                for d in dims[1:]:
                    sub_count *= d
                esize = sub_count * self._size(elem)
            if et is not None and et.tag == "DW_TAG_base_type" and esize == 1 and len(dims) == 1:
                if addr is not None:
                    raw = get(count)
                    txt = '"' + raw.split(b"\0")[0].decode("latin-1") + '"'
                else:
                    txt = "…"
            else:
                txt = f"[{count}]"
            base = addr

            def kids():
                out = []
                for k in range(min(count, MAX_ARRAY)):
                    a = base + k * esize
                    if len(dims) > 1:
                        out.append(VarNode(f"[{k}]", "", f"[{dims[1]}]", f"{path}/{k}",
                                           lambda a=a, k=k: self._subarray(elem, dims[1:], a, f"{path}/{k}")))
                    else:
                        out.append(self.node(f"[{k}]", elem, a, f"{path}/{k}"))
                if count > MAX_ARRAY:
                    out.append(VarNode("…", "", f"{count - MAX_ARRAY} more elements", path + "/…"))
                return out
            if base is None:
                return VarNode(name, tn, txt, path)
            # Petit tableau d'éléments simples : résumé {a, b, c}
            if len(dims) == 1 and count <= 8 and et is not None and esize > 1 and \
                    et.tag in ("DW_TAG_base_type", "DW_TAG_enumeration_type", "DW_TAG_pointer_type"):
                vals = [self.node("", elem, base + k * esize, "").value for k in range(count)]
                txt = "{" + ", ".join(vals) + "}"
            return VarNode(name, tn, txt, path, kids)
        if tag in ("DW_TAG_structure_type", "DW_TAG_union_type"):
            members = [m for m in st.iter_children() if m.tag == "DW_TAG_member"]

            def kids():
                out = []
                for m in members:
                    mn = m.attributes.get("DW_AT_name")
                    mname = mn.value.decode("latin-1") if mn else "?"
                    off = 0
                    loc = m.attributes.get("DW_AT_data_member_location")
                    if loc is not None:
                        if isinstance(loc.value, int):
                            off = loc.value
                        elif loc.value and loc.value[0] == 0x23:     # DW_OP_plus_uconst n
                            off = _uleb(bytes(loc.value), 1)[0]
                    out.append(self.node(mname, self._type(m), addr + off, f"{path}.{mname}"))
                return out
            if addr is None:
                return VarNode(name, tn, "{…}", path)
            parts = []
            for k in kids()[:4]:
                parts.append(f"{k.name}={k.value}")
            summary = "{" + ", ".join(parts) + (", …" if len(members) > 4 else "") + "}"
            return VarNode(name, tn, summary, path, kids)
        return VarNode(name, tn, f"‹unsupported type {tag[7:]}›", path, error=True)

    def _subarray(self, elem, dims, addr, path):
        esize = self._size(elem)
        stride = esize
        for d in dims[1:]:
            stride *= d
        out = []
        for k in range(min(dims[0], MAX_ARRAY)):
            if len(dims) > 1:
                out.append(VarNode(f"[{k}]", "", f"[{dims[1]}]", f"{path}/{k}",
                                   lambda a=addr + k * stride, k=k: self._subarray(elem, dims[1:], a, f"{path}/{k}")))
            else:
                out.append(self.node(f"[{k}]", elem, addr + k * esize, f"{path}/{k}"))
        return out

    # ------------------------------------------------------------ portées
    def _function_die(self, off):
        for cu in self._cus:
            for die in cu.get_top_DIE().iter_children():
                if die.tag != "DW_TAG_subprogram" or "DW_AT_low_pc" not in die.attributes:
                    continue
                lo = die.attributes["DW_AT_low_pc"].value
                hi = die.attributes["DW_AT_high_pc"].value
                if lo <= off < hi:
                    return cu, die
        return None, None

    def locals(self):
        """(nom de fonction, [VarNode]) pour la fonction en cours, ou (None, [])."""
        off = self.dbg.offset()
        if off is None:
            return None, []
        cu, func = self._function_die(off)
        if func is None:
            return None, []
        fb = self.frame_base(func, cu, off)
        out = []

        def walk(scope, prefix):
            for d in scope.iter_children():
                if d.tag in ("DW_TAG_formal_parameter", "DW_TAG_variable") and "DW_AT_name" in d.attributes:
                    nm = d.attributes["DW_AT_name"].value.decode("latin-1")
                    loc = d.attributes.get("DW_AT_location")
                    addr = reg = None
                    if loc is not None and loc.form.startswith("DW_FORM_block"):
                        addr, reg = self.eval_location(loc.value, fb)
                    out.append(self.node(nm, self._type(d), addr, f"L/{prefix}{nm}", reg))
                elif d.tag == "DW_TAG_lexical_block":
                    lo = d.attributes.get("DW_AT_low_pc")
                    hi = d.attributes.get("DW_AT_high_pc")
                    if lo and hi and lo.value <= off < hi.value:
                        walk(d, prefix + "{}/")
        walk(func, "")
        fname = func.attributes["DW_AT_name"].value.decode("latin-1")
        return (fname[1:] if fname.startswith("__") else fname), out

    def globals(self):
        out = []
        for cu in self._cus:
            for d in cu.get_top_DIE().iter_children():
                if d.tag == "DW_TAG_variable" and "DW_AT_name" in d.attributes:
                    loc = d.attributes.get("DW_AT_location")
                    if loc is None or not loc.form.startswith("DW_FORM_block"):
                        continue
                    nm = d.attributes["DW_AT_name"].value.decode("latin-1")
                    addr, reg = self.eval_location(loc.value, None)
                    out.append(self.node(nm, self._type(d), addr, f"G/{nm}", reg))
        return out
