#!/bin/sh
# Builds the Windows package (dist-windows/ti89-ide-windows.zip) from WSL.
# Needs: the Windows toolchain (scripts/build_gcc4ti_windows.sh), the Windows DLL of the
# C core (make -C emu89/core windows), and a 64-bit Python 3 for Windows (the "py" launcher).
# PyInstaller and the Python libraries are installed in a temporary Windows venv.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WTEMP="$(cmd.exe /c "echo %TEMP%" 2>/dev/null | tr -d '\r')"
WBUILD="$WTEMP\\ti89-package"
BUILD="$(wslpath -u "$WBUILD")"
VENV="$WTEMP\\ti89-package-venv"
OUT="$ROOT/dist-windows"
NAME=ti89-ide-windows

[ -f "$ROOT/gcc4ti-win/bin/tigcc.exe" ] || { echo "Run scripts/build_gcc4ti_windows.sh first"; exit 1; }
[ -f "$ROOT/emu89/core/ti89core.dll" ] || make -C "$ROOT/emu89/core" windows

echo "=== sources"
rm -rf "$BUILD"
mkdir -p "$BUILD"
cp -r "$ROOT/ide89" "$ROOT/emu89" "$BUILD/"
rm -rf "$BUILD/emu89/.venv" "$BUILD/emu89/musashi" "$BUILD/emu89/core/win"
find "$BUILD" -name "__pycache__" -prune -exec rm -rf {} +

echo "=== Python environment (Windows)"
cd /mnt/c
[ -f "$(wslpath -u "$VENV")/Scripts/python.exe" ] || cmd.exe /c "py -3 -m venv $VENV"
cmd.exe /c "$VENV\\Scripts\\python.exe -m pip install --quiet pyinstaller pyelftools pillow"

echo "=== PyInstaller"
cmd.exe /c "cd /d $WBUILD && $VENV\\Scripts\\python.exe -m PyInstaller --noconfirm --windowed \
  --name ti89-ide --paths ide89 --paths emu89 \
  --add-data emu89\\core\\ti89core.dll;core \
  --add-data emu89\\ti89emu\\stubs\\loadvar.bin;ti89emu\\stubs \
  ide89\\ide89.py" | tr -d '\r' | tail -3

echo "=== package"
PKG="$BUILD/dist/ti89-ide"
cp -r "$ROOT/gcc4ti-win" "$PKG/gcc4ti"
mkdir -p "$PKG/projets/exemples" "$PKG/ROM"
cp "$ROOT"/projets/exemples/*.c "$ROOT"/projets/exemples/*.s "$ROOT"/projets/exemples/*.asm \
   "$PKG/projets/exemples/"
cp "$ROOT/LICENSE" "$PKG/"
cat > "$PKG/ROM/PUT_YOUR_ROM_HERE.txt" <<'TXT'
Put the ROM image of your own TI-89 Titanium here, named ti89tv310.rom
(4 MB, AMS 3.10). It is copyrighted by Texas Instruments and is not included.
You can dump it from your calculator with TiLP.
TXT
cat > "$PKG/README.txt" <<'TXT'
TI-89 IDE for Windows
=====================

1. Put your TI-89 Titanium ROM in the ROM folder (see ROM\PUT_YOUR_ROM_HERE.txt).
2. Start ti89-ide.exe.
3. Open an example from projets\exemples, press F5 to run it, F6 to debug it.

Sending to a real calculator (USB) needs TiLP for Windows and its USB driver.
Source code, documentation: https://github.com/JC-Toussaint/ti89-ide
TXT

rm -rf "$OUT/$NAME" "$OUT/$NAME.zip"
mkdir -p "$OUT"
cp -r "$PKG" "$OUT/$NAME"
cd "$OUT" && zip -qr "$NAME.zip" "$NAME"
echo "=== $OUT/$NAME.zip ($(du -h "$NAME.zip" | cut -f1))"
