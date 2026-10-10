"""Volcano crater art -- every texel generated here, nothing derived.

  ash.tex    the road: dark volcanic asphalt, orange edge lines, dashed centre line
             (u across the 24 m road, v along 12 m)
  basalt.tex black-grey rock, cracked; tiles on the world grid
  hot.tex    basalt near the lava: its cracks glow orange (the glow lives in the
             texture because tinted vertex colours are unverified)
  lava.tex   molten orange-yellow with dark crust plates
  ramp.tex   steel deck with yellow/charcoal hazard chevrons (u across, v along 7 m)
  paint.tex  distance stripes: left half white, right half flame orange
  nums.tex   distance boards 50..300, a 4 x 8 atlas of 64 x 32 cells
  sky        1024 x 256 strip: smoke-dark crimson above, fire glow at the horizon,
             the crater rim in silhouette

No texel decodes to black (that is a hole in this engine): to_img floors at 10.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "circuit"))
from art import colourise, speckle, tile_noise, to_img  # noqa: E402

FONT = r"C:\Windows\Fonts\bahnschrift.ttf"
MARKS = list(range(50, 301, 10))            # 26 boards
CELL_W, CELL_H, COLS = 64, 32, 4


def _font(size, style="Bold Condensed"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(style)
    except Exception:
        pass
    return f


def cracks(size, seed, cells=6, width=0.06):
    """Tileable crack network: thin bands where a warped noise crosses 0.5."""
    n = tile_noise(size, cells, 4, 0.5, seed)
    w = tile_noise(size, cells * 2, 3, 0.5, seed + 9)
    v = np.abs((n + 0.25 * (w - 0.5)) - 0.5)
    return np.clip(1 - v / width, 0, 1)


def basalt(size=256, seed=41):
    n = tile_noise(size, 8, 5, 0.6, seed)
    img = colourise(n, (34, 30, 30), (74, 66, 62))
    img *= (1 - 0.55 * cracks(size, seed + 1)[..., None])
    img += speckle(size, 0.02, seed + 2)[..., None] * np.array([26, 22, 20])
    return to_img(img)


def hot(size=256, seed=41):
    img = np.array(basalt(size, seed)).astype(float)
    c = cracks(size, seed + 1)[..., None]
    glow = colourise(tile_noise(size, 4, 3, 0.5, seed + 5), (220, 70, 10), (255, 170, 40))
    img = img * (1 - c) + glow * c
    img += np.array([30, 6, 0]) * tile_noise(size, 4, 2, 0.5, seed + 6)[..., None]      # warm cast
    return to_img(img)


def lava(size=256, seed=77):
    n = tile_noise(size, 5, 5, 0.55, seed)
    img = colourise(n, (230, 70, 8), (255, 206, 60))
    crust = np.clip((tile_noise(size, 7, 4, 0.5, seed + 3) - 0.55) * 6, 0, 1)
    crust *= 1 - cracks(size, seed + 4, cells=7, width=0.08)            # plates split by glowing seams
    img = img * (1 - crust[..., None]) + np.array([58, 26, 20]) * crust[..., None]
    return to_img(img)


def ash(size=256, seed=23):
    n = tile_noise(size, 16, 4, 0.5, seed)
    img = colourise(n, (44, 40, 40), (66, 60, 58))
    img += speckle(size, 0.05, seed + 1)[..., None] * np.array([22, 20, 18])
    x = np.arange(size)[None, :] / size
    y = np.arange(size)[:, None] / size
    edge = (np.abs(x - 0.03) < 0.012) | (np.abs(x - 0.97) < 0.012)
    centre = (np.abs(x - 0.5) < 0.008) & ((y % 0.5) < 0.28)
    img[np.broadcast_to(edge, img.shape[:2])] = [236, 120, 30]
    img[np.broadcast_to(centre, img.shape[:2])] = [210, 206, 196]
    return to_img(img)


def ramp(size=256, seed=5):
    n = tile_noise(size, 32, 2, 0.5, seed)
    img = colourise(n, (120, 120, 116), (150, 150, 146))
    x = np.arange(size)[None, :] / size
    y = np.arange(size)[:, None] / size
    tread = ((np.arange(size)[:, None] + np.arange(size)[None, :]) % 16 < 2) | \
            ((np.arange(size)[:, None] - np.arange(size)[None, :]) % 16 < 2)
    img[tread] *= 0.8
    band = (x < 0.14) | (x > 0.86)                                    # chevron bands down both edges
    chev = ((np.abs(x - 0.5) * 0.9 + y) % 0.25) < 0.125
    img = np.where((band & chev)[..., None], np.array([240, 196, 20]), img)
    img = np.where((band & ~chev)[..., None], np.array([36, 34, 32]), img)
    return to_img(img)


def paint(size=64):
    img = np.zeros((size, size, 3))
    img[:, : size // 2] = [238, 234, 222]
    img[:, size // 2:] = [246, 120, 24]
    return to_img(img)


def cell_of(mark):
    """(u0, v0, u1, v1) of a distance board in nums.tex, v measured from the top."""
    k = MARKS.index(mark)
    c, r = k % COLS, k // COLS
    return (c * CELL_W / 256, r * CELL_H / 256, (c + 1) * CELL_W / 256, (r + 1) * CELL_H / 256)


def nums(size=256):
    im = Image.new("RGB", (size * 4, size * 4), (40, 34, 32))
    d = ImageDraw.Draw(im)
    f_big, s = _font(96), 4
    for m in MARKS:
        u0, v0, u1, v1 = cell_of(m)
        x0, y0, x1, y1 = u0 * size * s, v0 * size * s, u1 * size * s, v1 * size * s
        big = m % 50 == 0
        d.rectangle([x0 + 3, y0 + 3, x1 - 4, y1 - 4], fill=(246, 120, 24) if big else (52, 44, 40),
                    outline=(238, 234, 222), width=5)
        d.text(((x0 + x1) / 2, (y0 + y1) / 2 + 2), str(m), font=f_big,
               fill=(34, 26, 22) if big else (238, 234, 222), anchor="mm")
    return to_img(np.array(im.resize((size, size), Image.LANCZOS)).astype(float))


def crater_sky(width=1024, height=256, seed=13, volcanoes=((300, 150, 0.30), (760, 100, 0.20))):
    """Row 0 is the zenith side, the last row the horizon. Wraps left to right:
    every feature repeats on a period that divides the width."""
    y = np.linspace(0, 1, height)[:, None]
    top, low = np.array([40, 16, 16]), np.array([196, 74, 26])
    img = top + (low - top) * (y ** 1.8)[..., None]
    img = np.broadcast_to(img, (height, width, 3)).copy()
    big = tile_noise(width, 8, 5, 0.55, seed)[:height]
    smoke = np.clip((big - 0.45) * 2.2, 0, 1) * (1 - 0.6 * y)
    img = img * (1 - 0.55 * smoke[..., None]) + np.array([30, 24, 24]) * 0.55 * smoke[..., None]
    # the crater rim: a ragged ridge built from harmonics of the width, so it wraps
    x = np.arange(width)
    rng = np.random.default_rng(seed + 1)
    ridge = np.full(width, 0.83)
    for k in range(1, 40):
        ridge += 0.045 / k ** 0.9 * np.sin(2 * np.pi * k * x / width + rng.uniform(0, 2 * np.pi)) * (1 if k > 2 else 0.4)
    # distant volcanoes: cones standing above the rim. The strip repeats four times
    # round the horizon, so two per strip read as eight around the crater.
    VOLCANOES = list(volcanoes)                                # (centre px, half-width px, height)
    for cx, hw, ht in VOLCANOES:
        base = ridge[cx] + 0.02
        peak = base - ht
        mouth = hw * 0.12
        d = np.abs(x - cx)
        cone = np.where(d < mouth, peak, peak + (d - mouth) / (hw - mouth) * (base - peak))
        cone += 0.012 * np.sin(x / 7.0 + cx) * (d < hw)
        ridge = np.where(d < hw, np.minimum(ridge, cone), ridge)
    rim = y > ridge[None, :]
    rock = colourise(tile_noise(width, 32, 3, 0.5, seed + 2)[:height], (22, 16, 16), (40, 28, 26))
    # fire glow behind the rim: strongest just above it, fading up the sky
    above = np.clip(ridge[None, :] - y, 0, None)
    img += np.array([120, 40, 6]) * np.exp(-above / 0.06)[..., None] * (~rim)[..., None]
    rng = np.random.default_rng(seed + 7)
    for cx, hw, ht in VOLCANOES:
        peak = ridge[cx]
        # the ash column: a widening dark plume leaning downwind, textured by noise
        up = np.clip(peak - y, 0, None)
        lean = cx + 0.9 * up * height
        spread = hw * 0.10 + up * height * 0.55
        plume = np.exp(-((x[None, :] - lean) / spread) ** 2) * (y < peak) * np.clip(up / 0.05, 0, 1)
        plume *= 0.55 + 0.45 * tile_noise(width, 16, 4, 0.5, seed + cx)[:height]
        img = img * (1 - 0.8 * plume[..., None]) + np.array([46, 36, 34]) * 0.8 * plume[..., None]
        # the underside of the plume lit by the eruption
        img += np.array([150, 50, 10]) * (plume * np.exp(-up / 0.05))[..., None]
    img = np.where(rim[..., None], rock, img)
    for cx, hw, ht in VOLCANOES:
        peak = ridge[cx]
        py = int(peak * height)
        # the glowing mouth
        for dx in range(-int(hw * 0.14), int(hw * 0.14) + 1):
            for dy in range(0, 4):
                if 0 <= py + dy < height:
                    img[py + dy, cx + dx] = [255, 200 - 30 * dy, 60 - 12 * dy]
        # lava streaks down the flanks
        for side in (-1, 1):
            for k in range(3):
                x0 = cx + side * rng.uniform(0.02, 0.12) * hw
                for t in np.linspace(0, 1, 90):
                    xx = int(x0 + side * t * hw * rng.uniform(0.35, 0.6) + 2 * np.sin(t * 9 + k))
                    yy = int((peak + t * (ridge[min(max(xx, 0), width - 1)] - peak) * 0.9) * height) + 2
                    if 0 <= yy < height and 0 <= xx < width and t < 0.3 + 0.2 * k:
                        img[yy, xx] = [255, 120 + int(60 * (1 - t)), 20]
        # the fountain: sparks thrown up and falling back, hottest at the vent
        for _ in range(int(900 * hw / 150)):
            vx = rng.normal(0, 0.35); vy = rng.uniform(0.5, 1.0)
            t = rng.uniform(0, 1.6)
            sx = cx + vx * t * hw * 0.35
            sy = peak * height - (vy * t - 0.5 * t * t) * ht * height * 0.9
            if 0 <= int(sy) < height and sy < peak * height + 2:
                heat = np.clip(1 - t / 1.6, 0, 1)
                img[int(sy), int(sx) % width] = [255, 90 + int(150 * heat), 20 + int(60 * heat)]
    # embers drifting up
    ember = speckle(width, 0.0015, seed + 4)[:height].astype(bool) & (y < ridge[None, :])
    img[ember] = [255, 170, 60]
    return Image.fromarray(np.clip(img, 12, 255).astype(np.uint8), "RGB")


ALL = {"ash.tex": (ash, "opaque"), "basalt.tex": (basalt, "opaque"), "hot.tex": (hot, "opaque"),
       "lava.tex": (lava, "opaque"), "ramp.tex": (ramp, "opaque"), "paint.tex": (paint, "opaque"),
       "nums.tex": (nums, "opaque")}


if __name__ == "__main__":
    out = Path(__file__).resolve().parent
    sheet = Image.new("RGB", (7 * 140 + 10, 150 + 270), (20, 16, 16))
    for i, (name, (fn, _)) in enumerate(ALL.items()):
        sheet.paste(fn().resize((128, 128), Image.NEAREST), (10 + i * 140, 10))
    sheet.paste(crater_sky().resize((980, 245)), (10, 160))
    sheet.save(out / "lava_art.png")
    print(out / "lava_art.png")
