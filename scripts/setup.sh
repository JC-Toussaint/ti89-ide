#!/bin/sh
# Prepares the emulator and the IDE: Python environment, Musashi, C core.
# Needs: python3 (with tkinter), gcc, make, git.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
git -C "$ROOT" submodule update --init
python3 -m venv "$ROOT/emu89/.venv"
"$ROOT/emu89/.venv/bin/pip" install --quiet pyelftools
make -C "$ROOT/emu89/core"
echo "Done. Next: build GCC4TI (scripts/build_gcc4ti.sh), put your ROM in ROM/, run ./run-ide.sh"
