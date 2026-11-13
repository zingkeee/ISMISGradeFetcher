"""Generate the simple Grade Book PNG icons using only the Python standard library."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = (253, 251, 247)
INK = (26, 26, 26)
RED = (192, 48, 31)


def rectangle(pixels, size, x0, y0, x1, y1, color):
    left, top = int(x0 * size), int(y0 * size)
    right, bottom = int(x1 * size), int(y1 * size)
    for y in range(max(0, top), min(size, bottom)):
        row = pixels[y]
        for x in range(max(0, left), min(size, right)):
            row[x] = color


def chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)


def make_icon(size: int, target: Path) -> None:
    pixels = [[PAPER for _ in range(size)] for _ in range(size)]
    # Bold frame with a centered open-book glyph.
    rectangle(pixels, size, .18, .17, .82, .83, INK)
    rectangle(pixels, size, .24, .23, .49, .74, PAPER)
    rectangle(pixels, size, .51, .23, .76, .74, PAPER)
    rectangle(pixels, size, .485, .23, .515, .74, INK)
    rectangle(pixels, size, .29, .34, .45, .37, INK)
    rectangle(pixels, size, .29, .43, .45, .46, INK)
    rectangle(pixels, size, .55, .34, .71, .37, INK)
    rectangle(pixels, size, .55, .43, .71, .46, INK)
    rectangle(pixels, size, .29, .58, .71, .62, RED)

    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in pixels)
    ihdr = struct.pack(">2I5B", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    target.write_bytes(png)


if __name__ == "__main__":
    for dimensions in (192, 512):
        make_icon(dimensions, ROOT / f"icon-{dimensions}.png")
