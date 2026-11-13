#!/bin/sh
# Builds the Linux package (dist-linux/ti89-ide-linux.tar.gz): the IDE and the emulator
# frozen with PyInstaller (Python, Tk and the libraries included), GCC4TI, the examples.
# Needs: the Linux toolchain (scripts/build_gcc4ti.sh), the C core (scripts/setup.sh),
# python3 with venv and tkinter. PyInstaller is installed in a temporary venv.
# The programs need a glibc at least as recent as the one of the build system.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/ti89-package-linux"
VENV="$WORK/venv"
BUILD="$WORK/build"
OUT="$ROOT/dist-linux"
NAME=ti89-ide-linux

[ -x "$ROOT/gcc4ti/bin/tigcc" ] || { echo "Run scripts/build_gcc4ti.sh first"; exit 1; }
[ -f "$ROOT/emu89/core/libti89core.so" ] || make -C "$ROOT/emu89/core"

echo "=== sources"
rm -rf "$BUILD"
mkdir -p "$BUILD"
cp -r "$ROOT/ide89" "$ROOT/emu89" "$BUILD/"
rm -rf "$BUILD/emu89/.venv" "$BUILD/emu89/musashi" "$BUILD/emu89/core/win"
find "$BUILD" -name "__pycache__" -prune -exec rm -rf {} +

echo "=== Python environment"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet pyinstaller pyelftools pillow

echo "=== PyInstaller"
cd "$BUILD"
"$VENV/bin/python" -m PyInstaller --noconfirm --log-level WARN \
  --name ti89-ide --paths ide89 --paths emu89 \
  --hidden-import PIL._tkinter_finder \
  --add-data emu89/core/libti89core.so:core \
  --add-data emu89/ti89emu/stubs/loadvar.bin:ti89emu/stubs \
  ide89/ide89.py

echo "=== package"
PKG="$BUILD/dist/ti89-ide"
mkdir -p "$PKG/gcc4ti"
cp -r "$ROOT/gcc4ti/bin" "$ROOT/gcc4ti/include" "$ROOT/gcc4ti/lib" "$PKG/gcc4ti/"
mkdir -p "$PKG/projets/exemples" "$PKG/ROM"
cp "$ROOT"/projets/exemples/*.c "$ROOT"/projets/exemples/*.s "$ROOT"/projets/exemples/*.asm \
   "$PKG/projets/exemples/"
cp "$ROOT/LICENSE" "$PKG/"
# GCC4TI is free software under the GNU GPL: its license and where to get the sources.
cp "$ROOT/gcc4ti-src/gcc4ti/trunk/tigcc-linux/COPYING" "$PKG/gcc4ti/COPYING"
cat > "$PKG/gcc4ti/SOURCES.txt" <<'TXT'
This folder contains a Linux build of GCC4TI 0.96 Beta 11 (GCC 4.1.2 and binutils
2.16.1 patched for the TI-68k calculators, ld-tigcc, A68k, the TIGCC library), which is
free software distributed under the GNU General Public License (see COPYING).

Corresponding source code:
  - GCC4TI, including the original GCC and binutils tarballs and the patches:
    https://github.com/debrouxl/gcc4ti
  - the script used to build it from those sources, unmodified (scripts/build_gcc4ti.sh):
    https://github.com/JC-Toussaint/ti89-ide
TXT
cat > "$PKG/ROM/PUT_YOUR_ROM_HERE.txt" <<'TXT'
Put the ROM image of your own TI-89 Titanium here, named ti89tv310.rom
(4 MB, AMS 3.10). It is copyrighted by Texas Instruments and is not included.
You can dump it from your calculator with TiLP.
TXT
cat > "$PKG/README.txt" <<'TXT'
TI-89 IDE for Linux
===================

1. Put your TI-89 Titanium ROM in the ROM folder (see ROM/PUT_YOUR_ROM_HERE.txt).
2. Start ./ti89-ide  (optionally with a file: ./ti89-ide program.c).
3. Open an example from projets/exemples, press F5 to run it, F6 to debug it.

Built on Ubuntu 24.04 (x86_64): needs glibc 2.38 or later (Ubuntu 24.04+, Debian 13+,
Fedora 39+...). Older systems: install from the sources instead.
Sending to a real calculator (USB) needs the TI link libraries (libticalcs2,
libticables2, libtifiles2, e.g. from the tilp2 package).
Source code, documentation: https://github.com/JC-Toussaint/ti89-ide
TXT

rm -rf "$OUT/$NAME" "$OUT/$NAME.tar.gz"
mkdir -p "$OUT"
cp -r "$PKG" "$OUT/$NAME"
cd "$OUT" && tar -czf "$NAME.tar.gz" "$NAME"
echo "=== $OUT/$NAME.tar.gz ($(du -h "$NAME.tar.gz" | cut -f1))"
