#!/bin/sh
# Starts the TI-89 IDE:  ./run-ide.sh [file.c|file.s|file.asm]
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/emu89/.venv/bin/python" "$ROOT/ide89/ide89.py" "$@"
