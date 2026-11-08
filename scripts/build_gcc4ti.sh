#!/bin/sh
# Downloads and builds GCC4TI (the TI-68k C / assembly toolchain) into ./gcc4ti.
# Takes about 10-20 minutes. Needs: git, gcc, make, patch, bzip2.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/gcc4ti-src"

if [ ! -d "$SRC/gcc4ti" ]; then
    mkdir -p "$SRC"
    git clone --depth 1 https://github.com/debrouxl/gcc4ti.git "$SRC/gcc4ti"
fi

cd "$SRC/gcc4ti/trunk/tigcc-linux/scripts"
./updatesrc
cd ../gcc4ti-0.96b11/scripts

# GCC 4.1.2 (2007) needs these options to build with a modern host GCC (13+)
export PREFIX_GCC4TI="$ROOT/gcc4ti"
export CC="gcc -std=gnu89 -fcommon"
export CFLAGS="-O2 -fcommon -fno-exceptions -fomit-frame-pointer -w"
export MAKEINFO=true
rm -rf "$PREFIX_GCC4TI" ../build ../download
./Install_All
echo "GCC4TI installed in $PREFIX_GCC4TI"
