"""Compilation d'un fichier C avec GCC4TI et analyse des messages."""
import os
import re
import subprocess
from dataclasses import dataclass, field

# Racine du dépôt : .../ide89/ide/build.py -> trois niveaux au-dessus
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GCC4TI = os.environ.get("TIGCC", os.path.join(REPO_ROOT, "gcc4ti"))
_EXE = ".exe" if os.name == "nt" else ""


def tool(name):
    """Chemin complet d'un outil GCC4TI (tigcc, a68k...) : .exe sous Windows."""
    return os.path.join(GCC4TI, "bin", name + _EXE)

# GCC 4.1 : « fichier.c:12: error: message » (pas de colonne)
_MSG_RE = re.compile(r"^(?P<file>[^:\n]+?):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
                     r"(?:(?P<sev>error|warning|note|erreur|attention)\s*:\s*)?(?P<msg>.*)$",
                     re.IGNORECASE)
# A68k : « fichier.asm line 12 » puis la ligne source, puis « ^ message »
_A68K_RE = re.compile(r"^(?P<file>\S+\.asm) line (?P<line>\d+)$", re.IGNORECASE)
_CONTEXT_RE = re.compile(r"^[^:\n]+: (In function|At top level|In file included)")


@dataclass
class Message:
    severity: str          # "error", "warning", "note"
    line: int              # 0 si pas de ligne (erreur de l'éditeur de liens...)
    text: str
    file: str = ""


@dataclass
class BuildResult:
    ok: bool
    messages: list = field(default_factory=list)
    output: str = ""       # sortie brute de tigcc
    program: str = ""      # chemin du .89z
    debug: str = ""        # chemin du .dbg
    listing: str = ""      # listing A68k (.lst) pour le débogage d'un .asm
    size: int = 0


_SEV = {"error": "error", "erreur": "error", "warning": "warning",
        "attention": "warning", "note": "note", None: "error"}


def parse_messages(output, source_name):
    msgs = []
    lines = output.splitlines()
    pending_a68k = None
    for raw in lines:
        line = raw.rstrip()
        if pending_a68k is not None:
            st = line.strip()
            if st.startswith("^"):
                msgs.append(Message("error", pending_a68k[1], st.lstrip("^ ").strip(), pending_a68k[0]))
                pending_a68k = None
            continue
        a = _A68K_RE.match(line.strip())
        if a:
            pending_a68k = (a.group("file"), int(a.group("line")))
            continue
        if not line or _CONTEXT_RE.match(line) or line.endswith("Assembler messages:"):
            continue
        if re.match(r"^End of assembly - \d+ errors? (was|were) found", line):
            continue
        m = _MSG_RE.match(line)
        if m and m.group("file").strip().endswith((".c", ".h", ".s", ".asm")):
            sev = (m.group("sev") or "").lower() or None
            msgs.append(Message(_SEV[sev], int(m.group("line")),
                                m.group("msg").strip(), m.group("file").strip()))
        elif re.search(r"\berror\b|\berreur\b|unresolved|undefined reference|cannot|fatal",
                       line, re.I):
            msgs.append(Message("error", 0, line))
    return msgs


# GCC 4.1.2 compile en C89 par défaut ; on active le C99 (avec extensions GNU),
# le plus récent qu'il connaisse : for (int i...), stdint.h, bool, initialiseurs nommés...
C_STANDARD = "-std=gnu99"


def build(source_path, optimize="-O2", debug_build=False):
    """Compile source_path en .89z (+ .dbg) dans le même dossier."""
    src_dir = os.path.dirname(os.path.abspath(source_path))
    name = os.path.splitext(os.path.basename(source_path))[0]
    env = dict(os.environ)
    env["TIGCC"] = GCC4TI
    env["PATH"] = os.path.join(GCC4TI, "bin") + os.pathsep + env.get("PATH", "")
    out_base = os.path.join(src_dir, name)
    for ext in (".89z", ".dbg"):
        try:
            os.remove(out_base + ext)
        except FileNotFoundError:
            pass
    cmd = [tool("tigcc"), "-g", optimize, C_STANDARD, "-Wall"]
    if debug_build:
        # Variables globales non initialisées rangées dans le programme (et non dans un
        # bloc BSS créé au lancement) : le débogueur les trouve à leur adresse DWARF.
        cmd.append("-mno-bss")
    cmd += [os.path.basename(source_path), "-o", name]
    try:
        p = subprocess.run(cmd, cwd=src_dir, env=env, capture_output=True, text=True,
                           timeout=120)
        output = p.stdout + p.stderr
        rc = p.returncode
    except FileNotFoundError:
        return BuildResult(False, [Message("error", 0, f"tigcc not found in {GCC4TI}/bin")])
    except subprocess.TimeoutExpired:
        return BuildResult(False, [Message("error", 0, "build aborted (took more than 120 s)")])
    msgs = parse_messages(output, os.path.basename(source_path))
    program = out_base + ".89z"
    ok = rc == 0 and os.path.exists(program)
    if not ok and not any(m.severity == "error" for m in msgs):
        msgs.append(Message("error", 0, f"build failed (exit code {rc})"))
    shown = ["tigcc"] + cmd[1:]                 # chemin complet de tigcc inutile à l'affichage
    res = BuildResult(ok, msgs, f"$ {' '.join(shown)}\n{output}")
    if ok:
        res.program = program
        res.size = os.path.getsize(program)
        if os.path.exists(out_base + ".dbg"):
            res.debug = out_base + ".dbg"
        if source_path.lower().endswith(".asm"):
            res.listing = _a68k_listing(source_path, env)
    return res


def _a68k_listing(source_path, env):
    """Produit le listing A68k (adresse de chaque ligne) utilisé par le débogueur."""
    src_dir = os.path.dirname(os.path.abspath(source_path))
    lst = os.path.splitext(os.path.abspath(source_path))[0] + ".lst"
    tmp_obj = lst + ".o"
    try:
        subprocess.run([tool("a68k"), "-i" + os.path.join(GCC4TI, "include", "asm", ""), "-g", "-t", f"-l{lst}",
                        os.path.basename(source_path), tmp_obj],
                       cwd=src_dir, env=env, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        if os.path.exists(tmp_obj):
            os.remove(tmp_obj)
    return lst if os.path.exists(lst) else ""
