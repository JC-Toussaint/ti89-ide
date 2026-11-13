#!/bin/sh
# Builds GCC4TI for Windows from Linux / WSL with MinGW-w64, into ./gcc4ti-win.
# The programs are 32-bit: GCC 4.1.2 assumes that a "long" can hold a pointer, which is
# true on 32-bit Windows but not on 64-bit Windows (cc1 crashes there). 32-bit programs
# run normally on 64-bit Windows.
# Prerequisites: scripts/build_gcc4ti.sh has been run (patched sources, Linux toolchain:
# its headers and libraries are reused, they do not depend on the host system),
# and the i686-w64-mingw32-gcc cross-compiler (Ubuntu package mingw-w64).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/gcc4ti-src/gcc4ti/trunk/tigcc-linux/gcc4ti-0.96b11"
LINUX="$ROOT/gcc4ti"
PREFIX="$ROOT/gcc4ti-win"
BUILD="$SRC/build-win"
HOST=${HOST:-i686-w64-mingw32}
BUILD_SYS=x86_64-pc-linux-gnu
# GCC 4.1.2 (2007) needs these options to build with a modern compiler
HOSTCC="$HOST-gcc -std=gnu89 -fcommon"
BUILDCC="gcc -std=gnu89 -fcommon"
FLAGS="-O2 -fcommon -fno-exceptions -fomit-frame-pointer -w"

[ -d "$SRC/download/gcc.ti" ] || { echo "Run scripts/build_gcc4ti.sh first"; exit 1; }
[ -x "$LINUX/bin/tigcc" ] || { echo "Run scripts/build_gcc4ti.sh first"; exit 1; }

# SKIP_BINUTILS=1 : keep the binutils already built (to retry only GCC and the tools)
if [ -z "$SKIP_BINUTILS" ]; then
rm -rf "$PREFIX" "$BUILD"
mkdir -p "$PREFIX/bin" "$BUILD/binutils" "$BUILD/gcc"

echo "=== binutils (as, ar, objcopy...) for Windows"
cd "$BUILD/binutils"
CC="$HOSTCC" CFLAGS="$FLAGS" CC_FOR_BUILD="$BUILDCC" CFLAGS_FOR_BUILD="$FLAGS" MAKEINFO=true \
  "$SRC/download/binutils.ti/configure" --build=$BUILD_SYS --host=$HOST --target=m68k-coff \
  --prefix="$PREFIX" --program-prefix=m68k-coff-tigcc- --disable-serial-configure \
  --disable-shared --enable-static --disable-multilib --disable-nls --disable-win32-registry
make -i MAKEINFO=true || true
make -i MAKEINFO=true install || true
fi

if [ -z "$SKIP_GCC" ]; then              # SKIP_GCC=1: keep cc1.exe already built
echo "=== GCC 4.1.2 (cc1, driver) for Windows"
rm -rf "$BUILD/gcc"
mkdir -p "$BUILD/gcc"
cd "$BUILD/gcc"
CC="$HOSTCC" CFLAGS="$FLAGS" CC_FOR_BUILD="$BUILDCC" CFLAGS_FOR_BUILD="$FLAGS" MAKEINFO=true \
  "$SRC/download/gcc.ti/configure" --build=$BUILD_SYS --host=$HOST --target=m68k-coff \
  --prefix="$PREFIX" --program-prefix=m68k-coff-tigcc- --with-gnu-as --disable-nls \
  --disable-multilib --disable-shared --enable-static --disable-threads \
  --disable-win32-registry --disable-checking --disable-werror --disable-pch \
  --disable-mudflap --disable-libssp
# libgcc cannot be built (it would need to run the Windows compiler): GCC4TI does not
# use it anyway, only cc1 and the driver are needed.
# GCC's Makefile wants the target binutils under their standard names (m68k-coff-as,
# -ld, -nm...); GCC4TI names them differently: temporary empty placeholder files.
DUMMIES="as ld nm ar ranlib strip objdump"
for t in $DUMMIES; do : > "$PREFIX/bin/m68k-coff-$t"; : > "$PREFIX/bin/m68k-coff-$t.exe"; done
# Two passes: in this Canadian-cross setup the generated gcc/Makefile does not know that
# Windows programs end in .exe, so the checksum tool reads "cc1-dummy" instead of
# "cc1-dummy.exe" and cc1 fails to link. Pass 1 generates gcc/Makefile; we fix exeext in
# it, drop the empty checksum, and pass 2 finishes cc1.exe.
make -i MAKEINFO=true all-gcc || true
sed -i 's/^exeext = $/exeext = .exe/' gcc/Makefile
rm -f gcc/cc1-checksum.c gcc/cc1-checksum.o
make -i MAKEINFO=true all-gcc || true
for t in $DUMMIES; do rm -f "$PREFIX/bin/m68k-coff-$t" "$PREFIX/bin/m68k-coff-$t.exe"; done
fi
cp "$BUILD/gcc/gcc/xgcc.exe" "$PREFIX/bin/m68k-coff-tigcc-gcc.exe"
cp "$BUILD/gcc/gcc/cc1.exe" "$PREFIX/bin/cc1.exe"

echo "=== a68k, ld-tigcc, tigcc front-end, tprbuilder, patcher for Windows"
build_tool() {        # build_tool <source dir> <produced file> <installed name> [compiler]
    rm -rf "$BUILD/$3"
    cp -r "$1" "$BUILD/$3"
    ( cd "$BUILD/$3" && make clean >/dev/null 2>&1 || true
      make -e CC="${4:-$HOSTCC}" CFLAGS="$FLAGS" )
    cp "$BUILD/$3/$2" "$PREFIX/bin/$3.exe"
}
build_tool "$SRC/sources/a68k" A68k.exe a68k
build_tool "$SRC/sources/ld-tigcc" ld-tigcc.exe ld-tigcc
build_tool "$SRC/sources/tigcc/src" tigcc.exe tigcc
build_tool "$SRC/sources/tprbuilder/src" tprbuilder.exe tprbuilder
# The patcher (called by tigcc) is built as a 64-bit program: Windows treats any 32-bit
# program whose name contains "patch" as an installer and refuses to start it without
# administrator rights ("installer detection"); 64-bit programs are not concerned.
build_tool "$SRC/sources/patcher/src" tigcc-patcher.exe tigcc-patcher "x86_64-w64-mingw32-gcc -std=gnu89 -fcommon"

echo "=== headers and libraries (same on every system)"
cp -r "$LINUX/include" "$LINUX/lib" "$PREFIX/"
# include/asm/OS.h is a symbolic link to os.h on Linux; Windows file names ignore case,
# so os.h already answers to OS.h there.
rm -f "$PREFIX/include/asm/OS.h"

# Remove what GCC4TI does not use (as on Linux)
rm -rf "$PREFIX/info" "$PREFIX/man" "$PREFIX/share" "$PREFIX/libexec" "$PREFIX/m68k-coff"
rm -f "$PREFIX"/bin/m68k-coff-tigcc-ld.exe "$PREFIX"/bin/m68k-coff-tigcc-ranlib.exe \
      "$PREFIX"/bin/m68k-coff-tigcc-readelf.exe "$PREFIX"/bin/m68k-coff-tigcc-strings.exe \
      "$PREFIX"/bin/m68k-coff-tigcc-addr2line.exe "$PREFIX"/bin/m68k-coff-tigcc-c++filt.exe \
      "$PREFIX"/bin/m68k-coff-tigcc-cpp.exe "$PREFIX"/bin/m68k-coff-tigcc-gcov.exe

echo "=== Windows toolchain installed in $PREFIX"
ls "$PREFIX/bin"
