"""Désassemble une zone de la ROM : python disasm.py ADRESSE_HEX [NB_INSTRUCTIONS]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ti89emu.core import Core
c = Core()
c.load_rom(open(os.path.join(os.path.dirname(__file__), "..", "ROM", "ti89tv310.rom"), "rb").read())
pc = int(sys.argv[1], 16); n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
for _ in range(n):
    size, txt = c.disassemble(pc)
    print(f"${pc:06X}  {txt}")
    pc += size
