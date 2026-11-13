"""Polices selon le système : DejaVu sous Linux, Consolas / Segoe UI sous Windows."""
import os

if os.name == "nt":
    SANS, MONO = "Segoe UI", "Consolas"
else:
    SANS, MONO = "DejaVu Sans", "DejaVu Sans Mono"
