"""The RekordTrakt mark: a jog ring with a gap, a centre dot, on a dark rounded tile.

Drawn in code with analytic anti-aliasing, so every size is sharp and no image files or libraries are needed. The
same drawing gives the app icon (.ico), the tray icons (the ring in the status colour) and PNGs. The master vector is assets/icon/rekordtrakt.svg; keep the two in step (geometry is on a 96-unit grid).

  python -m rekordtrakt.shell.icons      writes assets/icon/ (ico and png sizes)
"""
import math
import struct
import zlib
from pathlib import Path

from rekordtrakt.shell.events import APP_DIR

TILE = (28, 31, 38)
DOT = (255, 255, 255)
TEAL = (93, 202, 165)
COLOURS = {                 # tray status -> ring colour
    "running": TEAL,
    "warning": (239, 159, 39),
    "starting": (55, 138, 221),
    "stopped": (136, 135, 128),     # also bypass
    "failed": (226, 75, 74),
}
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# Geometry on the 96-unit grid (matches the SVG master).
GRID, CORNER = 96.0, 22.0
RING_R, RING_W = 28.0, 12.0
GAP_FROM, GAP_TO = math.radians(223.0), math.radians(260.0)   # the jog marker gap, upper left (clockwise, y down)
DOT_R = 9.0
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
<rect width="96" height="96" rx="22" fill="#1c1f26"/>
<circle cx="48" cy="48" r="28" fill="none" stroke="#5dcaa5" stroke-width="12" stroke-dasharray="158 18" transform="rotate(-100 48 48)"/>
<circle cx="48" cy="48" r="9" fill="#ffffff"/>
</svg>
"""


def _cover(sd_px):
    """Pixel coverage from a signed distance in pixels (negative = inside)."""
    return max(0.0, min(1.0, 0.5 - sd_px))


def _gap_distance(x, y, d):
    """Signed distance (grid units) from the point to the gap's wedge: positive outside it."""
    a = math.atan2(y, x) % (2 * math.pi)
    if GAP_FROM <= a <= GAP_TO:
        return -min(a - GAP_FROM, GAP_TO - a) * d
    return min(abs((a - GAP_FROM + math.pi) % (2 * math.pi) - math.pi),
               abs((a - GAP_TO + math.pi) % (2 * math.pi) - math.pi)) * d


def render(size, ring=TEAL, tile=True, full_bleed=False):
    """RGBA bytes (top row first) of the mark at size x size pixels."""
    scale = size / GRID
    half, corner = GRID / 2, (0.0 if full_bleed else CORNER)
    out = bytearray()
    for py in range(size):
        for px in range(size):
            x = (px + 0.5) / scale - half
            y = (py + 0.5) / scale - half
            d = math.hypot(x, y)
            # rounded tile
            qx, qy = abs(x) - (half - corner), abs(y) - (half - corner)
            sd_tile = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - corner
            a_tile = _cover(sd_tile * scale) if tile else 0.0
            # ring, minus the gap wedge (square ends, like the SVG's dash)
            a_ring = _cover((abs(d - RING_R) - RING_W / 2) * scale)
            if a_ring:
                a_ring *= max(0.0, min(1.0, 0.5 + _gap_distance(x, y, d) * scale))
            a_dot = _cover((d - DOT_R) * scale)
            r = g = b = a = 0.0
            for colour, cov in ((TILE, a_tile), (ring, a_ring), (DOT, a_dot)):
                if cov:
                    r = colour[0] * cov + r * (1 - cov)
                    g = colour[1] * cov + g * (1 - cov)
                    b = colour[2] * cov + b * (1 - cov)
                    a = cov + a * (1 - cov)
            if a:
                r, g, b = r / a, g / a, b / a      # un-premultiply for straight-alpha formats
            out += bytes((int(r + 0.5), int(g + 0.5), int(b + 0.5), int(a * 255 + 0.5)))
    return bytes(out)


def png_bytes(size, rgba):
    rows = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def _bmp_entry(size, rgba):
    """ICO image as BMP (bottom-up BGRA plus an empty AND mask)."""
    pixels = bytearray()
    for y in range(size - 1, -1, -1):
        row = rgba[y * size * 4:(y + 1) * size * 4]
        for i in range(0, len(row), 4):
            pixels += bytes((row[i + 2], row[i + 1], row[i], row[i + 3]))
    mask = b"\x00" * (((size + 31) // 32) * 4 * size)
    header = struct.pack("<IiiHHIIiiII", 40, size, 2 * size, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + bytes(pixels) + mask


def ico_bytes(ring=TEAL, sizes=ICO_SIZES):
    """A multi-size .ico: BMP entries, PNG for 256 (as Windows expects)."""
    images = []
    for n in sizes:
        rgba = render(n, ring)
        images.append(png_bytes(n, rgba) if n >= 256 else _bmp_entry(n, rgba))
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    data = b""
    for n, img in zip(sizes, images):
        out += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(img), offset + len(data))
        data += img
    return out + data


def write_icons(folder=APP_DIR / "icons", sizes=(16, 20, 24, 32, 40, 48, 64)):
    """Tray icons, one .ico per status (the ring in the status colour); returns {status: path}.
    Cached: drawn again only when missing."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for status, rgb in COLOURS.items():
        path = folder / f"a-{status}.ico"          # "a-": design A; older icons are left alone
        if not path.exists():
            path.write_bytes(ico_bytes(rgb, sizes))
        paths[status] = path
    return paths


def favicon_data_uri():
    """The master SVG as a data: URI, for the window's icon."""
    from urllib.parse import quote
    return "data:image/svg+xml," + quote(SVG.replace("\n", ""))


def main():
    folder = Path(__file__).resolve().parents[2] / "assets" / "icon"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "rekordtrakt.svg").write_text(SVG, encoding="utf-8")
    (folder / "rekordtrakt.ico").write_bytes(ico_bytes())
    for n in (256, 512, 1024):
        (folder / f"rekordtrakt-{n}.png").write_bytes(png_bytes(n, render(n)))
    print(f"Wrote {folder}")


if __name__ == "__main__":
    main()
