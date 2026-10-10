"""Jungle and magma art -- every texel generated here.

  jungle.tex  the jungle floor: dark leaf litter, moss, a few fallen fronds (world-tiled)
  pond.tex    still jungle water, deep green-teal with a sheen (world-tiled)
  palm.tex    a palm (colorkey): curved ringed trunk, drooping fronds
  jtree.tex   a canopy tree (colorkey): tall buttressed trunk, clumped crowns, hanging vines
  fern.tex    undergrowth (colorkey): a fan of fern fronds
  magma.tex   the rolling boulders: purple-grey stone split by glowing lava cracks
              (after Rayman's lava rocks), sphere-mapped
Billboards are 256 x 256; alpha < 128 is keyed out, and no kept texel is black.
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "circuit"))
sys.path.insert(0, str(HERE.parent / "lava"))
from art import colourise, speckle, tile_noise, to_img  # noqa: E402
import lava_art as la  # noqa: E402


def jungle(size=256, seed=101):
    n = tile_noise(size, 8, 5, 0.6, seed)
    img = colourise(n, (34, 44, 22), (72, 84, 38))
    moss = np.clip((tile_noise(size, 4, 3, 0.5, seed + 1) - 0.5) * 3, 0, 1)
    img = img * (1 - 0.4 * moss[..., None]) + np.array([54, 96, 34]) * 0.4 * moss[..., None]
    img += speckle(size, 0.04, seed + 2)[..., None] * np.array([46, 30, 12])       # dead leaves
    img -= speckle(size, 0.05, seed + 3)[..., None] * np.array([14, 16, 8])
    return to_img(img)


def pond(size=256, seed=111):
    n = tile_noise(size, 6, 4, 0.5, seed)
    img = colourise(n, (22, 58, 54), (44, 92, 84))
    sheen = np.clip((tile_noise(size, 12, 3, 0.5, seed + 1) - 0.62) * 5, 0, 1)
    img += sheen[..., None] * np.array([60, 70, 60])
    return to_img(img)


def _keyed(img_rgba):
    a = np.array(img_rgba).astype(np.uint8)
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    rgb = a[..., :3]
    rgb[(a[..., 3] > 0) & (rgb.max(axis=2) < 16)] = 16
    return Image.fromarray(a, "RGBA")


def _frond(d, base, angle, length, width, colour, droop, rng, S):
    """A frond as a spine with leaflets either side."""
    pts = []
    for k in range(24):
        t = k / 23
        a = angle + droop * t * t
        pts.append((base[0] + math.cos(a) * length * t, base[1] - math.sin(a) * length * t))
    for k in range(1, 24):
        x, y = pts[k]
        px, py = pts[k - 1]
        nx, ny = -(y - py), (x - px)
        nl = math.hypot(nx, ny) or 1
        w = width * math.sin(math.pi * k / 23) * S
        c = tuple(int(v * rng.uniform(0.85, 1.1)) for v in colour) + (255,)
        d.line([(x, y), (x + nx / nl * w, y + ny / nl * w + w * 0.4)], fill=c, width=3 * S)
        d.line([(x, y), (x - nx / nl * w, y - ny / nl * w + w * 0.4)], fill=c, width=3 * S)
    d.line(pts, fill=(70, 88, 40, 255), width=3 * S)


def palm(size=256, seed=121):
    S = 4
    rng = np.random.default_rng(seed)
    im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    W = size * S
    top = (W * 0.56, W * 0.22)
    trunk = []
    for k in range(40):
        t = k / 39
        trunk.append((W * 0.46 + (top[0] - W * 0.46) * t ** 1.6, W * 0.99 + (top[1] - W * 0.99) * t))
    for k in range(39):
        w = (0.045 - 0.018 * k / 39) * W
        shade = 110 - 30 * (k % 3 == 0)
        d.line([trunk[k], trunk[k + 1]], fill=(shade, 86, 58, 255), width=int(w))
    for i in range(11):
        ang = 2 * math.pi * i / 11 + rng.uniform(-0.15, 0.15)
        up = math.sin(ang) * 0.6 + 0.35
        _frond(d, top, math.atan2(up, math.cos(ang)), W * rng.uniform(0.36, 0.46), 9, (58, 118, 40), -0.9, rng, S)
    for i in range(3):
        d.ellipse([top[0] - 14 * S + i * 9 * S, top[1] + 4 * S, top[0] - 4 * S + i * 9 * S, top[1] + 14 * S],
                  fill=(92, 70, 34, 255))
    return _keyed(im.resize((size, size), Image.LANCZOS))


def jtree(size=256, seed=131):
    S = 4
    rng = np.random.default_rng(seed)
    W = size * S
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # buttressed trunk
    d.polygon([(W * 0.44, W * 0.99), (W * 0.47, W * 0.35), (W * 0.53, W * 0.35), (W * 0.56, W * 0.99)], fill=(96, 82, 62, 255))
    d.polygon([(W * 0.36, W * 0.99), (W * 0.46, W * 0.80), (W * 0.47, W * 0.99)], fill=(84, 72, 54, 255))
    d.polygon([(W * 0.64, W * 0.99), (W * 0.54, W * 0.80), (W * 0.53, W * 0.99)], fill=(84, 72, 54, 255))
    for bx, by in ((0.36, 0.42), (0.64, 0.40), (0.5, 0.3)):
        d.line([(W * 0.5, W * 0.45), (W * bx, W * by)], fill=(90, 76, 58, 255), width=int(W * 0.02))
    # clumped crowns
    for i in range(34):
        cx = W * (0.5 + rng.normal(0, 0.17)); cy = W * (0.26 + rng.normal(0, 0.09))
        r = W * rng.uniform(0.06, 0.12)
        g = rng.uniform(0.75, 1.15)
        d.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], fill=(int(40 * g), int(92 * g), int(34 * g), 255))
    # highlights and vines
    for i in range(40):
        cx = W * (0.5 + rng.normal(0, 0.16)); cy = W * (0.2 + rng.normal(0, 0.07)); r = W * 0.025
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(84, 140, 52, 255))
    for i in range(7):
        x = W * rng.uniform(0.3, 0.7)
        d.line([(x, W * 0.3), (x + rng.uniform(-10, 10) * S, W * rng.uniform(0.5, 0.75))], fill=(52, 96, 36, 255), width=S * 2)
    return _keyed(im.resize((size, size), Image.LANCZOS))


def fern(size=256, seed=141):
    S = 4
    rng = np.random.default_rng(seed)
    W = size * S
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    base = (W * 0.5, W * 0.98)
    for i in range(13):
        ang = math.radians(20 + 140 * i / 12 + rng.uniform(-6, 6))
        _frond(d, base, ang, W * rng.uniform(0.5, 0.72), 16, (46, 112, 38), -0.5 * math.cos(ang), rng, S)
    return _keyed(im.resize((size, size), Image.LANCZOS))


def magma(size=256, seed=151):
    """Sphere-mapped (u around, v pole to pole): purple-grey stone, glowing crack network."""
    n = tile_noise(size, 6, 5, 0.6, seed)
    img = colourise(n, (64, 52, 70), (118, 100, 122))
    img *= (0.85 + 0.3 * tile_noise(size, 24, 2, 0.5, seed + 1))[..., None]
    c = la.cracks(size, seed + 2, cells=4, width=0.05)
    core = la.cracks(size, seed + 2, cells=4, width=0.02)
    glow = np.array([255, 110, 20]) * c[..., None] + np.array([255, 220, 90]) * core[..., None]
    img = img * (1 - c[..., None]) + np.clip(glow, 0, 255)
    rim = np.clip(la.cracks(size, seed + 2, cells=4, width=0.10) - c, 0, 1)      # warm halo round each crack
    img += np.array([90, 26, 0]) * rim[..., None]
    return to_img(img)


ALL = {"jungle.tex": (jungle, "opaque"), "pond.tex": (pond, "opaque"), "palm.tex": (palm, "colorkey"),
       "jtree.tex": (jtree, "colorkey"), "fern.tex": (fern, "colorkey"), "magma.tex": (magma, "opaque")}


if __name__ == "__main__":
    sheet = Image.new("RGB", (6 * 140 + 10, 150), (40, 60, 80))
    for i, (name, (fn, _)) in enumerate(ALL.items()):
        im = fn().resize((128, 128), Image.LANCZOS)
        sheet.paste(im, (10 + i * 140, 10), im if im.mode == "RGBA" else None)
    sheet.save(HERE / "jungle_art.png")
    print(HERE / "jungle_art.png")
