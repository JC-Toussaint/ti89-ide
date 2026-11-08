"""Étape 1 : démarre AMS sans interface et enregistre l'écran LCD en PNG."""
import argparse
import collections
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ti89emu.hardware import TI89Titanium   # noqa: E402
from ti89emu.screenshot import save_png     # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--rom", default=os.path.join(os.path.dirname(__file__), "..", "ROM", "ti89tv310.rom"))
ap.add_argument("--seconds", type=float, default=5)
ap.add_argument("--out", default="boot.png")
ap.add_argument("--keys", default="", help="touches à presser après le démarrage, séparées par des virgules")
args = ap.parse_args()

calc = TI89Titanium(args.rom)
pcs = collections.Counter()
t0 = time.time()
for i in range(int(args.seconds * 256)):
    calc.tick()
    if i % 16 == 0:
        pcs[calc.core.pc & 0xFFFFF0] += 1
    if i % 256 == 0:
        print(f"t={i/256:5.1f}s  PC=${calc.core.pc:06X}  halted={calc.halted}  "
              f"irq={calc.core.irq_pending():02x}  flash w/e={calc.flash.writes}/{calc.flash.erases}")
for k in [k for k in args.keys.split(",") if k]:
    calc.key_down(k); calc.run_seconds(0.1); calc.key_up(k); calc.run_seconds(0.3)
dt = time.time() - t0
print(f"{args.seconds}s émulées en {dt:.2f}s réelles ({args.seconds/dt:.2f}x temps réel)")
print("PC les plus fréquents :", [f"${a:06X}:{n}" for a, n in pcs.most_common(5)])
print("Ports non émulés :", {f"${a:06X}/{k}": n for (a, k), n in sorted(calc.unknown_io.items())})
save_png(args.out, calc.lcd_pixels())
print("Écran enregistré dans", os.path.abspath(args.out))
