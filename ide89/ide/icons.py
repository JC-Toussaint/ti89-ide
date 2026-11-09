"""
Icônes de la barre d'outils, dessinées au trait (style « outline » : traits de 2 px,
extrémités arrondies), sur une grille de 24 x 24 comme les jeux d'icônes Lucide/Tabler.

Tk ne lisse pas les traits : chaque icône est dessinée 8 fois plus grande avec Pillow,
puis réduite, ce qui donne des bords lisses.
"""
import math

from PIL import Image, ImageDraw

SS = 8                     # facteur de sur-échantillonnage
GRID = 24                  # grille de dessin (comme un viewBox SVG 0 0 24 24)
STROKE = 2.0               # épaisseur du trait, en unités de la grille


class Pen:
    """Dessine sur une grille 24x24 avec un trait arrondi."""

    def __init__(self, img, color, stroke=STROKE):
        self.d = ImageDraw.Draw(img)
        self.color = color
        self.w = stroke * SS

    @staticmethod
    def _p(x, y):
        return (x * SS, y * SS)

    def _dot(self, x, y):
        r = self.w / 2
        cx, cy = self._p(x, y)
        self.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=self.color)

    def line(self, *pts):
        """Ligne brisée avec jonctions et extrémités arrondies."""
        p = [self._p(x, y) for x, y in pts]
        self.d.line(p, fill=self.color, width=round(self.w), joint="curve")
        for x, y in pts:
            self._dot(x, y)

    def arc(self, cx, cy, r, start, end, steps=48):
        """Arc de cercle (angles en degrés, sens horaire depuis 3 h)."""
        pts = []
        for i in range(steps + 1):
            a = math.radians(start + (end - start) * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self.line(*pts)

    def circle(self, cx, cy, r):
        self.arc(cx, cy, r, 0, 360, 72)

    def rrect(self, x0, y0, x1, y1, r):
        """Rectangle aux coins arrondis (contour)."""
        self.arc(x1 - r, y0 + r, r, -90, 0, 12)
        self.arc(x1 - r, y1 - r, r, 0, 90, 12)
        self.arc(x0 + r, y1 - r, r, 90, 180, 12)
        self.arc(x0 + r, y0 + r, r, 180, 270, 12)
        self.line((x0 + r, y0), (x1 - r, y0))
        self.line((x1, y0 + r), (x1, y1 - r))
        self.line((x1 - r, y1), (x0 + r, y1))
        self.line((x0, y1 - r), (x0, y0 + r))

    def fill_rrect(self, x0, y0, x1, y1, r, color):
        self.d.rounded_rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS), radius=r * SS, fill=color)


# ---------------------------------------------------------------- les icônes
def _new(p):                       # document avec un « + » dans le coin
    p.line((11, 4), (6, 4))
    p.arc(6, 6, 2, 180, 270, 8)
    p.line((4, 6), (4, 18))
    p.arc(6, 18, 2, 90, 180, 8)
    p.line((6, 20), (18, 20))
    p.arc(18, 18, 2, 0, 90, 8)
    p.line((20, 18), (20, 13))
    p.line((18, 3), (18, 9))
    p.line((15, 6), (21, 6))


def _open(p):                      # dossier ouvert
    p.line((4, 19), (3, 18), (3, 6), (4, 5), (8, 5), (10, 7), (17, 7), (18, 8), (18, 10))
    p.line((4, 19), (7, 11.5), (8, 11), (20.5, 11), (21.5, 12), (19, 18.5), (18, 19), (4, 19))


def _save(p):                      # disquette
    p.line((6, 3), (16, 3), (21, 8), (21, 18))
    p.arc(18, 18, 3, 0, 90, 8)
    p.line((18, 21), (6, 21))
    p.arc(6, 18, 3, 90, 180, 8)
    p.line((3, 18), (3, 6))
    p.arc(6, 6, 3, 180, 270, 8)
    p.line((7, 21), (7, 14), (17, 14), (17, 21))
    p.line((7, 3), (7, 7), (14, 7))


def _build(p):                     # marteau
    p.line((13.5, 10.5), (5, 19))
    p.arc(4, 18, 1.4, 45, 225, 8)
    p.line((3, 17), (11.5, 8.5))
    p.line((9, 4), (12.5, 3.5), (16, 5), (21, 10), (18.5, 12.5), (15, 9), (12, 9), (10.5, 7), (9, 4))


def _run(p):                       # lecture dans un cercle (sur fond bleu, voir make_icon)
    p.circle(12, 12, 7.5)
    p.line((10.5, 9), (15, 12), (10.5, 15), (10.5, 9))


def _debug(p):                     # insecte
    p.line((9, 3), (10.5, 5.5))
    p.line((15, 3), (13.5, 5.5))
    p.arc(12, 9, 3.5, 180, 360, 16)
    p.rrect(7, 8.5, 17, 20.5, 5)
    p.line((12, 12), (12, 20.5))
    p.line((3, 13), (7, 13))
    p.line((17, 13), (21, 13))
    p.line((4, 19.5), (7.4, 17.5))
    p.line((20, 19.5), (16.6, 17.5))
    p.line((4, 7), (7.5, 9.3))
    p.line((20, 7), (16.5, 9.3))


def _stop(p):                      # carré arrondi
    p.rrect(5, 5, 19, 19, 2.5)


def _continue(p):                  # |▷
    p.line((5, 4), (5, 20))
    p.line((9, 4), (20, 12), (9, 20), (9, 4))


def _pause(p):                     # pause dans un cercle
    p.circle(12, 12, 9)
    p.line((10, 9), (10, 15))
    p.line((14, 9), (14, 15))


def _step_over(p):                 # flèche circulaire (enjamber)
    p.arc(12, 12, 8.5, -40, 245, 60)
    p.line((17, 4), (18.5, 6.5), (16, 8.5))


def _step_into(p):                 # flèche vers le bas
    p.line((12, 4), (12, 20))
    p.line((6, 14), (12, 20), (18, 14))


def _step_out(p):                  # flèche vers le haut
    p.line((12, 20), (12, 4))
    p.line((6, 10), (12, 4), (18, 10))


def _send(p):                      # téléphone : envoi vers la calculatrice
    p.rrect(7, 2.5, 17, 21.5, 2.5)
    p.line((11.5, 18), (12.5, 18))


ICONS = {
    "new": _new, "open": _open, "save": _save,
    "build": _build, "run": _run, "debug": _debug, "stop": _stop,
    "continue": _continue, "pause": _pause,
    "step_over": _step_over, "step_into": _step_into, "step_out": _step_out,
    "send": _send,
}


def make_icon(name, color, size=22, badge=None):
    """Image Pillow (RGBA) de l'icône. badge : couleur d'un carré arrondi de fond
    (bouton mis en avant, comme « Run »)."""
    big = Image.new("RGBA", (GRID * SS, GRID * SS), (0, 0, 0, 0))
    pen = Pen(big, color, stroke=STROKE)
    if badge:
        pen.fill_rrect(0, 0, GRID, GRID, 5, badge)
        pen.w = 1.8 * SS
    ICONS[name](pen)
    return big.resize((size, size), Image.LANCZOS)
