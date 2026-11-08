"""
Lecture des informations de débogage produites par `tigcc -g` (fichier .dbg).

Le .dbg est un objet COFF m68k contenant le programme lié (.text, adresse 0 = début du
code du programme) et les sections DWARF 2. Les noms de section COFF sont tronqués à
8 caractères (.debug_a = abbrev OU aranges, .debug_l = line OU loc) : on les identifie
par leur contenu. ld-tigcc a DÉJÀ appliqué les relocations (tout en laissant les entrées
dans le fichier) : il ne faut pas les appliquer une seconde fois.
"""
import io
import os
import struct
from dataclasses import dataclass, field

from elftools.dwarf.dwarfinfo import DWARFInfo, DebugSectionDescriptor, DwarfConfig

@dataclass
class LineEntry:
    addr: int      # décalage dans le programme (0 = premier octet du code)
    line: int
    file: str


@dataclass
class DebugInfo:
    path: str
    text_size: int
    lines: list = field(default_factory=list)            # LineEntry triées par adresse
    line_addrs: dict = field(default_factory=dict)       # ligne -> [adresses de début]
    functions: list = field(default_factory=list)        # (nom, début, fin)
    source: str = ""
    dwarf: object = None
    text: bytes = b""        # code du programme lié (avant relocation par AMS)
    symbols: dict = field(default_factory=dict)          # nom -> décalage dans le programme

    def line_for(self, off):
        """Ligne source contenant le décalage `off` (ou None)."""
        best = None
        for e in self.lines:
            if e.addr > off:
                break
            best = e
        if best is None or off >= self.text_size:
            return None
        if self.functions:
            # C : hors de toute fonction de l'utilisateur -> pas de ligne
            if not any(lo <= off < hi for _, lo, hi in self.functions):
                return None
        elif off < self.lines[0].addr:
            return None                          # assembleur : avant le code de l'utilisateur
        return best.line

    @property
    def is_asm(self):
        return not self.functions

    def function_for(self, off):
        if off is None:
            return None
        for name, lo, hi in self.functions:
            if lo <= off < hi:
                return name
        return None

    def breakable_line(self, line):
        """Ligne la plus proche (>= line) qui porte du code ; None si aucune."""
        cands = sorted(ln for ln in self.line_addrs if ln >= line)
        return cands[0] if cands else None

    def statement_addrs(self):
        """Toutes les adresses de début de ligne (pour le pas à pas)."""
        return sorted({a for addrs in self.line_addrs.values() for a in addrs})


def _parse_coff(data):
    magic, nsec, _ts, symptr, nsyms, opthdr, _flags = struct.unpack(">HHIIIHH", data[:20])
    if magic != 0x150:
        raise ValueError("not an m68k COFF object")
    sections = []
    off = 20 + opthdr
    for _ in range(nsec):
        name, _pa, _va, size, scnptr, relptr, _ln, nrel, _nln, _fl = struct.unpack(
            ">8sIIIIIIHHI", data[off:off + 40])
        sections.append({"name": name.rstrip(b"\0").decode(), "size": size,
                         "data": bytearray(data[scnptr:scnptr + size]) if scnptr else bytearray(size),
                         "relptr": relptr, "nrel": nrel})
        off += 40
    return sections


def _coff_symbols(data):
    """Symboles COFF de la section .text (n° 1) : nom -> valeur (décalage)."""
    _m, _n, _ts, symptr, nsyms, _o, _f = struct.unpack(">HHIIIHH", data[:20])
    strtab = symptr + nsyms * 18
    raw = {}
    i = 0
    while i < nsyms:
        e = data[symptr + i * 18: symptr + i * 18 + 18]
        if e[:4] == b"\0\0\0\0":
            so = struct.unpack(">I", e[4:8])[0]
            end = data.index(b"\0", strtab + so)
            name = data[strtab + so:end].decode("latin-1")
        else:
            name = e[:8].rstrip(b"\0").decode("latin-1")
        val, scn, _typ, _scl, naux = struct.unpack(">IhHBB", e[8:])
        if scn == 1 and name and " " not in name and not name.startswith(("L", ".")):
            raw[name] = val
        i += 1 + naux
    import re
    out = {}
    for name, val in raw.items():
        name = re.sub(r"\.\d+$", "", name)          # statique local : appels.3675 -> appels
        if name.endswith(".") or "." in name:
            continue
        out.setdefault(name, val)
    # Les noms C ont un « _ » de plus en assembleur (__main = _main en C) : la forme C prime
    for name, val in raw.items():
        if name.startswith("__") and "." not in name:
            out[name[1:]] = val
    return out


def _classify(sections):
    """Retrouve le vrai nom DWARF de chaque section COFF tronquée."""
    out = {}
    for s in sections:
        n, d = s["name"], bytes(s["data"])
        if n == ".text":
            out["text"] = d
        elif n == ".debug_a":
            # aranges : longueur(4) version(2)=2 offset_info(4) taille_adresse(1)=4
            if len(d) >= 12 and d[4:6] == b"\x00\x02" and d[10] == 4:
                out["aranges"] = d
            else:
                out["abbrev"] = d
        elif n == ".debug_l":
            if len(d) >= 6 and d[4:6] == b"\x00\x02" and "line" not in out:
                out["line"] = d
            else:
                out["loc"] = d
        elif n == ".debug_i":
            out["info"] = d
        elif n == ".debug_f":
            out["frame"] = d
        elif n == ".debug_s":
            out["str"] = d
        elif n == ".debug_p":
            out["pubnames"] = d
        elif n == ".debug_r":
            out["ranges"] = d
    return out


def _desc(d, name):
    if d is None:
        return None
    return DebugSectionDescriptor(stream=io.BytesIO(d), name=name, global_offset=0,
                                  size=len(d), address=0)


def load(dbg_path, source_path=None):
    with open(dbg_path, "rb") as f:
        data = f.read()
    secs = _classify(_parse_coff(data))
    cfg = DwarfConfig(little_endian=False, machine_arch="m68k", default_address_size=4)
    dw = DWARFInfo(
        config=cfg,
        debug_info_sec=_desc(secs.get("info"), ".debug_info"),
        debug_aranges_sec=_desc(secs.get("aranges"), ".debug_aranges"),
        debug_abbrev_sec=_desc(secs.get("abbrev"), ".debug_abbrev"),
        debug_frame_sec=_desc(secs.get("frame"), ".debug_frame"),
        eh_frame_sec=None,
        debug_str_sec=_desc(secs.get("str"), ".debug_str"),
        debug_loc_sec=_desc(secs.get("loc"), ".debug_loc"),
        debug_ranges_sec=_desc(secs.get("ranges"), ".debug_ranges"),
        debug_line_sec=_desc(secs.get("line"), ".debug_line"),
        debug_pubtypes_sec=None,
        debug_pubnames_sec=_desc(secs.get("pubnames"), ".debug_pubnames"),
        debug_addr_sec=None, debug_str_offsets_sec=None, debug_line_str_sec=None,
        debug_loclists_sec=None, debug_rnglists_sec=None, debug_sup_sec=None,
        gnu_debugaltlink_sec=None, debug_types_sec=None)
    info = DebugInfo(dbg_path, len(secs.get("text", b"")), dwarf=dw, text=secs.get("text", b""))
    try:
        info.symbols = _coff_symbols(data)
    except (struct.error, ValueError):
        pass
    src_base = os.path.basename(source_path) if source_path else None
    for cu in dw.iter_CUs():
        top = cu.get_top_DIE()
        cu_name = top.attributes.get("DW_AT_name")
        cu_name = cu_name.value.decode("latin-1") if cu_name else ""
        lp = dw.line_program_for_CU(cu)
        if lp is not None:
            files = [fe.name.decode("latin-1") for fe in lp["file_entry"]]
            for ent in lp.get_entries():
                st = ent.state
                if st is None or st.end_sequence:
                    continue
                fname = files[st.file - 1] if 0 < st.file <= len(files) else cu_name
                if src_base and os.path.basename(fname) != src_base:
                    continue
                info.lines.append(LineEntry(st.address, st.line, fname))
        for die in top.iter_children():
            if die.tag == "DW_TAG_subprogram" and "DW_AT_low_pc" in die.attributes:
                lo = die.attributes["DW_AT_low_pc"].value
                hi = die.attributes["DW_AT_high_pc"].value
                if die.attributes["DW_AT_high_pc"].form not in ("DW_FORM_addr",):
                    hi = lo + hi
                nm = die.attributes.get("DW_AT_name")
                info.functions.append((nm.value.decode("latin-1") if nm else "?", lo, hi))
    info.lines.sort(key=lambda e: (e.addr, e.line))
    for e in info.lines:
        info.line_addrs.setdefault(e.line, [])
        if e.addr not in info.line_addrs[e.line]:
            info.line_addrs[e.line].append(e.addr)
    info.functions.sort(key=lambda f: f[1])
    return info


def from_a68k_listing(lst_path, source_path, program_path):
    """Informations de débogage d'un programme A68k en mode _nostub, à partir du listing.

    En _nostub, le code du fichier commence à l'adresse 0 du programme : les adresses du
    listing sont directement des décalages dans le programme. Les lignes du listing sont
    numérotées en comptant aussi les fichiers inclus et les expansions de macros (« + ») :
    on les aligne sur les lignes du fichier source par leur texte."""
    import re
    with open(source_path, encoding="latin-1") as f:
        src = [l.rstrip("\r\n") for l in f]
    entries = []                    # (adresse ou None, a_du_code, expansion?, texte)
    rx = re.compile(r"^([0-9A-Fa-f]{6})?\t([0-9A-Fa-f ]*)\t*\s*(\d+)(\+?) ?(.*)$")
    with open(lst_path, encoding="latin-1") as f:
        for raw in f:
            m = rx.match(raw.rstrip("\r\n"))
            if not m:
                continue
            addr = int(m.group(1), 16) if m.group(1) else None
            has_code = bool(m.group(2).strip())
            entries.append((addr, has_code, m.group(4) == "+", m.group(5)))
    with open(program_path, "rb") as f:
        d = f.read()
    code = d[0x58:-2]               # après le mot de longueur de la variable
    info = DebugInfo(lst_path, len(code), text=code)
    j = 0
    for ln, text in enumerate(src, start=1):
        if not text.strip() or text.lstrip().startswith((";", "*")):
            continue
        k = j
        while k < len(entries) and (entries[k][2] or entries[k][3].rstrip() != text.rstrip()):
            k += 1
        if k >= len(entries):
            continue
        j = k + 1
        addr, has_code, _, _ = entries[k]
        if not has_code:
            # Appel de macro : le code est dans les lignes d'expansion qui suivent
            n = k + 1
            while n < len(entries) and entries[n][2] and not entries[n][1]:
                n += 1
            if n < len(entries) and entries[n][2] and entries[n][1]:
                addr, has_code = entries[n][0], True
        lm = re.match(r"^([A-Za-z_][\w.]*):?(?:\s|$)", text)
        if lm and addr is not None and lm.group(1).lower() not in ("include", "xdef", "xref"):
            info.symbols[lm.group(1)] = addr
        if has_code and addr is not None and addr < len(code):
            info.lines.append(LineEntry(addr, ln, source_path))
    info.lines.sort(key=lambda e: (e.addr, e.line))
    for e in info.lines:
        info.line_addrs.setdefault(e.line, []).append(e.addr)
    return info
