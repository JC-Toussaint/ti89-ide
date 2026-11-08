#!/usr/bin/env python3
"""Lance l'émulateur TI-89 Titanium : python emu89.py [--rom FICHIER] [--scale N]"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ti89emu.gui import EmulatorApp   # noqa: E402

ap = argparse.ArgumentParser(description="Émulateur TI-89 Titanium")
ap.add_argument("--rom", default=os.path.join(HERE, "..", "ROM", "ti89tv310.rom"))
ap.add_argument("--scale", type=int, default=4, help="agrandissement de l'écran LCD (défaut 4)")
args = ap.parse_args()
EmulatorApp(args.rom, scale=args.scale).run()
