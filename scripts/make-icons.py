#!/usr/bin/env python3
"""
Generate the PWA icon set from scratch, with nothing but the standard library.

Why not just ship PNGs? Because a binary blob in a repository is a thing nobody
can review. This script is the source: the icon is defined by the geometry
below, and anyone can read it, change a colour, and regenerate. It also keeps
the project's "no third-party dependencies" claim honest -- no Pillow, no
ImageMagick, no build step that only works on the machine that had them.

The PNG encoder is deliberately minimal: 8-bit RGBA, filter type 0, one IDAT.
That is a fully valid PNG, just not an optimally compressed one, and at these
dimensions the difference is a few hundred bytes.

Usage:
    python3 scripts/make-icons.py            # write theme/static/img/icon-*.png
    python3 scripts/make-icons.py --check    # verify they are up to date
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO_ROOT, "theme", "static", "img")

# Matches the tokens in theme/css/tokens.css and theme/static/img/favicon.svg.
BACKGROUND = (0x05, 0x07, 0x0A, 0xFF)
ACCENT = (0x7E, 0xF2, 0xA8, 0xFF)
FRAME = (0x3D, 0xDC, 0x84, 0x8C)   # the border, at ~55% alpha


# --------------------------------------------------------------------------- #
# PNG encoding
# --------------------------------------------------------------------------- #

def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rows: list[bytearray]) -> bytes:
    """Rows are RGBA bytearrays of length width*4."""
    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #

def _blend(dst: tuple[int, int, int, int], src: tuple[int, int, int, int], coverage: float) -> tuple[int, int, int, int]:
    """Source-over composite with an extra antialiasing coverage term."""
    alpha = (src[3] / 255.0) * max(0.0, min(1.0, coverage))
    if alpha <= 0:
        return dst
    return (
        round(src[0] * alpha + dst[0] * (1 - alpha)),
        round(src[1] * alpha + dst[1] * (1 - alpha)),
        round(src[2] * alpha + dst[2] * (1 - alpha)),
        max(dst[3], round(255 * alpha + dst[3] / 255.0 * (1 - alpha) * 255) if dst[3] < 255 else 255),
    )


def _distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def render_icon(size: int, *, padding: float = 0.0) -> list[bytearray]:
    """Draw the mark at ``size`` px.

    ``padding`` shrinks the artwork toward the centre, which is what a maskable
    icon needs: platforms crop maskable icons to a circle or squircle, and
    anything inside the outer 20% can be clipped away.
    """
    scale = size / 64.0
    inset = padding * size
    usable = size - 2 * inset

    def to_px(unit_x: float, unit_y: float) -> tuple[float, float]:
        return inset + unit_x / 64.0 * usable, inset + unit_y / 64.0 * usable

    # Geometry in the same 64x64 space the SVG uses.
    chevron = [((14, 24), (24, 32)), ((24, 32), (14, 40))]
    chevron_width = 5.0 / 64.0 * usable / 2
    bar = ((30 + 2.25, 39.25), (50 - 2.25, 39.25))
    bar_width = 4.5 / 64.0 * usable / 2

    frame_outer = inset + 3.5 / 64.0 * usable
    frame_inner = frame_outer + 2.0 / 64.0 * usable

    rows: list[bytearray] = []
    aa = max(0.75, scale * 0.9)  # antialiasing falloff in pixels

    for y in range(size):
        row = bytearray()
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            pixel = BACKGROUND

            if padding > 0 and (px < inset or px > size - inset or py < inset or py > size - inset):
                # Maskable padding stays background-coloured, never transparent.
                row.extend(pixel)
                continue

            # Border frame: inside the outer bound but outside the inner one.
            near_edge = min(px - frame_outer, py - frame_outer, size - inset - frame_outer - (px - inset), size - inset - frame_outer - (py - inset))
            inner_edge = min(px - frame_inner, py - frame_inner, size - inset - frame_inner - (px - inset), size - inset - frame_inner - (py - inset))
            if near_edge > -aa and inner_edge < aa:
                coverage = min(1.0, (near_edge + aa) / (2 * aa)) * min(1.0, (aa - inner_edge) / (2 * aa))
                pixel = _blend(pixel, FRAME, coverage)

            best = min(_distance_to_segment(px, py, *to_px(*a), *to_px(*b)) for a, b in chevron)
            if best < chevron_width + aa:
                pixel = _blend(pixel, ACCENT, (chevron_width + aa - best) / (2 * aa))

            bar_distance = _distance_to_segment(px, py, *to_px(*bar[0]), *to_px(*bar[1]))
            if bar_distance < bar_width + aa:
                pixel = _blend(pixel, ACCENT, (bar_width + aa - bar_distance) / (2 * aa))

            row.extend(pixel)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

TARGETS = [
    ("icon-192.png", 192, 0.0),
    ("icon-512.png", 512, 0.0),
    ("icon-maskable.png", 512, 0.14),
    ("og-default.png", 0, 0.0),  # handled separately below
]


def render_og_card(width: int = 1200, height: int = 630) -> bytes:
    """A plain Open Graph card: background, frame, and the mark centred."""
    mark_size = 220
    mark = render_icon(mark_size)
    rows: list[bytearray] = []
    offset_x = (width - mark_size) // 2
    offset_y = (height - mark_size) // 2

    for y in range(height):
        row = bytearray()
        for x in range(width):
            inside_mark = offset_x <= x < offset_x + mark_size and offset_y <= y < offset_y + mark_size
            if inside_mark:
                index = (x - offset_x) * 4
                source = mark[y - offset_y]
                row.extend(source[index:index + 4])
                continue
            # Thin accent rule near the bottom, otherwise flat background.
            if height - 90 <= y <= height - 86 and 80 <= x <= width - 80:
                row.extend(FRAME)
            else:
                row.extend(BACKGROUND)
        rows.append(row)
    return encode_png(width, height, rows)


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stale: list[str] = []

    for name, size, padding in TARGETS:
        path = os.path.join(OUTPUT_DIR, name)
        if name == "og-default.png":
            data = render_og_card()
        else:
            data = encode_png(size, size, render_icon(size, padding=padding))

        if check_only:
            existing = open(path, "rb").read() if os.path.exists(path) else b""
            if existing != data:
                stale.append(name)
            continue

        with open(path, "wb") as handle:
            handle.write(data)
        print(f"  {name:<22} {len(data):>7,} B")

    if check_only:
        if stale:
            print("out of date: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("icons are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
