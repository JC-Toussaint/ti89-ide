"""
Envoi fiable de touches à AMS.

Une touche tapée reste enfoncée au moins PRESS_TICKS et jusqu'à ce qu'AMS l'ait lue
MIN_SEEN fois sur le port clavier ; la suivante n'est envoyée que lorsque AMS attend
de nouveau une touche (CPU en veille via $600005). Ainsi aucune touche n'est perdue
quand AMS est occupé (interruptions masquées, initialisation d'une application...).
"""
from .hardware import KEYS

PRESS_TICKS = 8          # durée minimale d'appui (1/256 s)
MIN_SEEN = 6             # nombre de lectures du clavier par AMS avant de relâcher
PRESS_MAX_TICKS = 512    # sécurité
RELEASE_TICKS = 8        # pause minimale entre deux touches
RELEASE_MAX_TICKS = 256  # attente maximale
RELEASE_SEEN = 3         # lectures du clavier montrant la touche relâchée

# Caractère -> séquence de touches TI-89
CHAR_MAP = {
    "+": ["+"], "-": ["-"], "*": ["*"], "/": ["/"], "^": ["^"], "=": ["="],
    "(": ["("], ")": [")"], ",": [","], ".": ["."], "|": ["|"],
    "{": ["2nd", "("], "}": ["2nd", ")"], "[": ["2nd", ","], "]": ["2nd", "/"],
    "'": ["2nd", "="], '"': ["2nd", "1"], ":": ["2nd", "4"], ";": ["2nd", "9"],
    "\\": ["2nd", "2"], "<": ["2nd", "0"], ">": ["2nd", "."], "°": ["2nd", "|"],
    "_": ["diamond", "mode"], " ": ["alpha", "(-)"], "π": ["2nd", "^"],
}
_ALPHA = {"a": "=", "b": "(", "c": ")", "d": ",", "e": "/", "f": "|", "g": "7", "h": "8",
          "i": "9", "j": "*", "k": "ee", "l": "4", "m": "5", "n": "6", "o": "-", "p": "sto",
          "q": "1", "r": "2", "s": "3", "u": "+", "v": "0", "w": "."}
for _c in "0123456789":
    CHAR_MAP[_c] = [_c]
for _c, _k in _ALPHA.items():
    CHAR_MAP[_c] = ["alpha", _k]
    CHAR_MAP[_c.upper()] = ["shift", _k]
for _c in "xyzt":
    CHAR_MAP[_c] = [_c]
    CHAR_MAP[_c.upper()] = ["shift", _c]

# Touches spéciales du PC (keysym Tk) -> séquence de touches TI-89
KEYSYM_MAP = {
    "Return": ["enter"], "KP_Enter": ["enter"], "BackSpace": ["backspace"],
    "Delete": ["diamond", "backspace"], "Escape": ["esc"],
    "Up": ["up"], "Down": ["down"], "Left": ["left"], "Right": ["right"],
    "F1": ["f1"], "F2": ["f2"], "F3": ["f3"], "F4": ["f4"], "F5": ["f5"],
    "F6": ["2nd", "f1"], "F7": ["2nd", "f2"], "F8": ["2nd", "f3"],
    "F9": ["apps"], "F10": ["mode"], "F11": ["catalog"], "F12": ["on"],
    "Home": ["home"], "Tab": ["sto"], "End": ["clear"],
    "KP_Add": ["+"], "KP_Subtract": ["-"], "KP_Multiply": ["*"], "KP_Divide": ["/"],
    "KP_Decimal": ["."], "KP_Separator": ["."],
}
for _i in range(10):
    KEYSYM_MAP[f"KP_{_i}"] = [str(_i)]


def text_to_keys(text):
    keys = []
    for ch in text:
        if ch == "\n":
            keys.append("enter")
        elif ch in CHAR_MAP:
            keys.extend(CHAR_MAP[ch])
        else:
            raise ValueError(f"caractère non tapable sur la TI-89 : {ch!r}")
    return keys


class KeyFeeder:
    def __init__(self, calc, on_highlight=None):
        self.calc = calc
        self.queue = []
        self.state = None            # [touche, ticks appuyée, ticks relâchée, enfoncée?]
        self.on_highlight = on_highlight or (lambda k, on: None)

    def busy(self):
        return bool(self.queue or self.state)

    def clear(self):
        if self.state and self.state[3]:
            self.calc.key_up(self.state[0])
        self.queue.clear()
        self.state = None

    def type_keys(self, keys):
        for k in keys:
            if k not in KEYS and k != "on":
                raise ValueError(f"touche inconnue : {k}")
        self.queue.extend(keys)

    def type_text(self, text):
        self.type_keys(text_to_keys(text))

    def tick(self):
        """À appeler avant chaque tick d'émulation."""
        st = self.state
        if st is None:
            if not self.queue:
                return
            k = self.queue.pop(0)
            self.calc.key_down(k)
            self.on_highlight(k, True)
            self.state = [k, 0, RELEASE_TICKS, True]
            return
        if st[3]:
            st[1] += 1
            seen = self.calc.key_seen_count(st[0])
            if (st[1] >= PRESS_TICKS and seen >= MIN_SEEN) or st[1] >= PRESS_MAX_TICKS:
                self.calc.key_up(st[0])
                self.on_highlight(st[0], False)
                st[3] = False
        else:
            # Touche suivante quand le programme est revenu attendre une touche (AMS au
            # repos) ou qu'il a lu le clavier et vu la touche relâchée (jeu, boucle active)
            st[2] -= 1
            ready = self.calc.halted or self.calc.key_release_seen_count(st[0]) >= RELEASE_SEEN
            if (st[2] <= 0 and ready) or st[2] <= RELEASE_TICKS - RELEASE_MAX_TICKS:
                self.state = None
