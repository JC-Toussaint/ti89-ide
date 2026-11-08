"""Écriture de l'écran LCD en PNG (sans dépendance externe)."""
import struct
import zlib


def save_png(path, pixels, scale=3):
    h = len(pixels)
    w = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        line = bytearray([0])  # filtre PNG « None »
        for on in row:
            line += (b"\x1e\x23\x1e" if on else b"\xc4\xd4\xb4") * scale
        for _ in range(scale):
            raw += line
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w * scale, h * scale, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def save_ppm_png(path, ppm, scale=3):
    """Enregistre en PNG une image PPM (P6) produite par Session.levels_ppm."""
    header, _, rgb = ppm.partition(b"\n")
    _, w, h, _ = header.split()
    w, h = int(w), int(h)
    raw = bytearray()
    for y in range(h):
        line = bytearray([0])
        row = rgb[y * w * 3:(y + 1) * w * 3]
        for x in range(w):
            line += row[x * 3:x * 3 + 3] * scale
        for _ in range(scale):
            raw += line
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w * scale, h * scale, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
