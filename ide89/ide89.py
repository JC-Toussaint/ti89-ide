#!/usr/bin/env python3
"""Lance l'IDE TI-89 : python ide89.py [fichier.c]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ide.app import IdeApp   # noqa: E402

IdeApp(sys.argv[1] if len(sys.argv) > 1 else None).run()
