"""Procedural art for the temple drag strip -- every texel generated here.

Names are 8.3. Opaque textures never decode to black (the engine keys it out);
colour-keyed ones use pure black only where they mean "nothing here".

  asphalt.tex  the strip: sandstone flagstones, 8 across the 20 m road
  kerb.tex     carved border blocks          dirt.tex    sand shoulder
  grass.tex    lush jungle ground            carve.tex   temple masonry with glyphs
  gold.tex     burnished gold (idols)        head.tex    a carved stone face
  palm.tex     palm tree billboard (keyed)   fern.tex    jungle undergrowth (keyed)
  broad.tex    broadleaf canopy tree (keyed)
"""
import math

import numpy as np
from PIL import Image, ImageDraw

import art
from art import colourise, speckle, tile_noise, to_img


def flagstones(size=128, seed=301):
    """Staggered sandstone flags with sunken grout: u across the road, v along 10 m."""
    n = tile_noise(size, 8, 4, 0.55, seed)
    img = colourise(n, (150, 126, 88), (204, 178, 128))
    cols, rows = 8, 4                                  # 2.5 m flags on a 20 m x 10 m tile
    cw, rh = size / cols, size / rows
    yy, xx = np.mgrid[0:size, 0:size]
    row = (yy / rh).astype(int)
    shift = (row % 2) * cw / 2
    col = ((xx + shift) / cw).astype(int)
    tint = np.random.default_rng(seed).uniform(0.86, 1.08, (rows + 1, cols + 2))
    img *= tint[row % (rows + 1), col % (cols + 2)][..., None]
    joint = ((yy % rh) < 1.6) | (((xx + shift) % cw) < 1.6)
    img = np.where(joint[..., None], np.array([98, 84, 62]), img)
    cracks = (tile_noise(size, 24, 2, 0.5, seed + 4) > 0.83).astype(float)
    img *= (1 - 0.25 * cracks)[..., None]
    img += speckle(size, 0.05, seed + 2)[..., None] * np.array([-18, -16, -12])
    return to_img(img)


def carved_kerb(size=64, seed=311):
    """Border blocks, alternating pale and dark stone, 8 per 10 m like the kerb they replace."""
    v = np.arange(size) / size
    dark = ((v * 8).astype(int) % 2) == 0
    n = tile_noise(size, 8, 3, 0.5, seed)
    pale = colourise(n, (176, 150, 108), (214, 190, 140))
    deep = colourise(n, (112, 92, 66), (146, 122, 88))
    img = np.where(dark[:, None, None], deep, pale)
    joint = (v * 8 % 1) < 0.06
    img[joint] = [84, 70, 52]
    return to_img(img)


def sand(size=128, seed=321):
    n = tile_noise(size, 6, 5, 0.6, seed)
    img = colourise(n, (168, 140, 96), (212, 186, 136))
    img += speckle(size, 0.05, seed + 1)[..., None] * np.array([-30, -28, -24])
    return to_img(img)


def jungle_grass(size=128, seed=331):
    n = tile_noise(size, 4, 5, 0.55, seed)
    fine = tile_noise(size, 32, 2, 0.5, seed + 7)
    img = colourise(n, (34, 74, 30), (70, 120, 44))
    img *= (0.82 + 0.34 * fine)[..., None]
    img += speckle(size, 0.07, seed + 3)[..., None] * np.array([10, 26, 6])
    return to_img(img)


GLYPHS = 7


def _glyph(d, x, y, s, kind, fill):
    """One carved sign in an s x s cell: spiral, eye, zigzag, sun, step, bird, ring."""
    c = (x + s / 2, y + s / 2)
    w = max(1, s // 10)
    if kind == 0:                                        # spiral
        pts = [(c[0] + math.cos(t) * t * s / 30, c[1] + math.sin(t) * t * s / 30)
               for t in np.linspace(0.5, 4.2 * math.pi, 40)]
        d.line(pts, fill=fill, width=w)
    elif kind == 1:                                      # eye
        d.ellipse([x + s * .12, y + s * .3, x + s * .88, y + s * .7], outline=fill, width=w)
        d.ellipse([c[0] - s * .1, c[1] - s * .1, c[0] + s * .1, c[1] + s * .1], fill=fill)
    elif kind == 2:                                      # zigzag
        pts = [(x + s * (0.1 + 0.8 * i / 6), y + s * (0.3 if i % 2 else 0.7)) for i in range(7)]
        d.line(pts, fill=fill, width=w)
    elif kind == 3:                                      # sun
        d.ellipse([c[0] - s * .18, c[1] - s * .18, c[0] + s * .18, c[1] + s * .18], outline=fill, width=w)
        for k in range(8):
            a = k * math.pi / 4
            d.line([(c[0] + math.cos(a) * s * .26, c[1] + math.sin(a) * s * .26),
                    (c[0] + math.cos(a) * s * .42, c[1] + math.sin(a) * s * .42)], fill=fill, width=w)
    elif kind == 4:                                      # stepped pyramid
        for k in range(4):
            d.rectangle([x + s * (0.15 + k * 0.09), y + s * (0.75 - k * 0.15),
                         x + s * (0.85 - k * 0.09), y + s * (0.75 - k * 0.15) + w], fill=fill)
    elif kind == 5:                                      # bird
        d.line([(x + s * .15, y + s * .45), (c[0], y + s * .6), (x + s * .85, y + s * .45)], fill=fill, width=w)
        d.line([(c[0], y + s * .6), (c[0], y + s * .8)], fill=fill, width=w)
    else:                                                # ring
        d.ellipse([x + s * .2, y + s * .2, x + s * .8, y + s * .8], outline=fill, width=w)
        d.ellipse([x + s * .38, y + s * .38, x + s * .62, y + s * .62], outline=fill, width=w)


def carve(size=128, seed=341):
    """Temple masonry: big sandstone blocks, each with a sunken glyph."""
    n = tile_noise(size, 8, 4, 0.6, seed)
    base = colourise(n, (140, 118, 84), (190, 164, 118))
    img = Image.fromarray(np.clip(base, 20, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    rows, cols = 2, 2
    ch, cw = size // rows, size // cols
    rng = np.random.default_rng(seed)
    for r in range(rows):
        for c in range(cols):
            x0 = c * cw + (cw // 2 if r % 2 else 0)
            for xo in (x0, x0 - size):
                d.rectangle([xo, r * ch, xo + cw - 1, r * ch + ch - 1], outline=(92, 76, 54), width=2)
                _glyph(d, xo + cw * 0.18, r * ch + ch * 0.18, int(cw * 0.64), int(rng.integers(GLYPHS)), (104, 84, 58))
    a = np.array(img).astype(float)
    a *= (0.9 + 0.2 * tile_noise(size, 4, 2, 0.5, seed + 2))[..., None]
    return to_img(a)


def gold(size=64, seed=351):
    n = tile_noise(size, 4, 4, 0.55, seed)
    y = np.linspace(0, 1, size)[:, None]
    band = 0.5 + 0.5 * np.sin(y * 7 * math.pi + n * 3)
    img = colourise(0.55 * n + 0.45 * band, (150, 102, 24), (252, 214, 96))
    img += (tile_noise(size, 16, 2, 0.5, seed + 3) > 0.8)[..., None] * np.array([30, 30, 20])
    return to_img(img)


def stone_head(size=128, seed=361):
    """A carved face filling the texture: brow, eyes, broad nose, set mouth.
    The top-left corner stays plain stone for the head's other sides."""
    n = tile_noise(size, 6, 4, 0.6, seed)
    base = colourise(n, (104, 100, 90), (156, 150, 136))
    img = Image.fromarray(np.clip(base, 20, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    dark, deep = (70, 66, 58), (48, 46, 40)
    s = size
    d.rectangle([s * .16, s * .26, s * .84, s * .31], fill=dark)                    # brow
    for ex in (.32, .68):
        d.ellipse([s * (ex - .11), s * .34, s * (ex + .11), s * .46], fill=dark)
        d.ellipse([s * (ex - .04), s * .37, s * (ex + .04), s * .43], fill=deep)
    d.polygon([(s * .5, s * .38), (s * .40, s * .64), (s * .60, s * .64)], fill=dark)   # nose
    d.rectangle([s * .30, s * .74, s * .70, s * .79], fill=deep)                    # mouth
    d.rectangle([s * .30, s * .80, s * .70, s * .82], fill=dark)
    for k in range(5):                                                              # headdress bands
        d.rectangle([s * .10, s * (.04 + k * .04), s * .90, s * (.05 + k * .04)], fill=dark)
    a = np.array(img).astype(float)
    return to_img(a)


PLAIN_UV = (0.95, 0.95)          # a corner of head.tex with no carving on it


def palm(size=128, seed=371):
    """A palm: a slim curving trunk and a crown of drooping fronds, keyed background."""
    img = Image.new("RGB", (size, size), (0, 0, 0))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(seed)
    top = (size * 0.52, size * 0.26)
    trunk = [(size * 0.5 + math.sin(t * 2.2) * size * 0.05, size * (1.0 - t * 0.74)) for t in np.linspace(0, 1, 16)]
    for (x0, y0), (x1, y1) in zip(trunk, trunk[1:]):
        d.line([(x0, y0), (x1, y1)], fill=(104, 80, 54), width=max(2, size // 28))
    for i in range(12):
        a = -math.pi + i * math.pi / 11 + rng.normal(0, 0.12)
        L = size * rng.uniform(0.38, 0.50)
        pts = []
        for t in np.linspace(0, 1, 12):
            x = top[0] + math.cos(a) * L * t
            y = top[1] + math.sin(a) * L * t * 0.6 + (t ** 2) * L * 0.45
            pts.append((x, y))
        for k, (x, y) in enumerate(pts[1:], 1):
            w = size * 0.085 * (1 - k / 14)
            g = int(90 + 50 * rng.random())
            d.line([pts[k - 1], (x, y)], fill=(34, g, 32), width=max(2, int(w)))
            d.line([(x, y), (x + rng.normal(0, 3), y + w * 1.6)], fill=(30, g - 20, 30), width=1)
    a = np.array(img)
    solid = a.sum(axis=2) > 0
    a[solid] = np.maximum(a[solid], 14)
    return Image.fromarray(a, "RGB")


def fern(size=64, seed=381):
    img = Image.new("RGB", (size, size), (0, 0, 0))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(seed)
    for i in range(11):
        a = -math.pi * (0.1 + 0.8 * i / 10) + rng.normal(0, 0.1)
        L = size * rng.uniform(0.35, 0.5)
        x0, y0 = size / 2, size * 0.98
        pts = [(x0 + math.cos(a) * L * t, y0 + math.sin(a) * L * t + (t ** 2) * L * 0.35) for t in np.linspace(0, 1, 8)]
        g = int(80 + 60 * rng.random())
        d.line(pts, fill=(38, g, 30), width=3)
    a = np.array(img)
    solid = a.sum(axis=2) > 0
    a[solid] = np.maximum(a[solid], 14)
    return Image.fromarray(a, "RGB")


def broad(size=128, seed=391):
    """A broadleaf jungle tree: the circuit's oak, darker and denser."""
    a = np.array(art.oak(size, seed)).astype(float)
    solid = a.sum(axis=2) > 0
    a[solid] *= np.array([0.7, 0.92, 0.72])
    out = np.clip(a, 0, 255).astype(np.uint8)
    out[solid] = np.maximum(out[solid], 14)
    return Image.fromarray(out, "RGB")


def jungle_sky(width=1024, height=256, seed=401):
    """Hazy, humid sky over a green hill line."""
    y = np.linspace(0, 1, height)[:, None]
    top, hor = np.array([88, 132, 176]), np.array([214, 222, 206])
    base = np.broadcast_to(top + (hor - top) * (y ** 1.3)[..., None], (height, width, 3)).copy()
    c = tile_noise(width, 8, 5, 0.55, seed)[:height]
    band = np.exp(-((y - 0.5) / 0.3) ** 2)
    cover = np.clip((c - 0.48) * 2.6, 0, 1) * band
    base = base * (1 - cover[..., None]) + np.array([236, 238, 232]) * cover[..., None]
    x = np.arange(width) / width * 2 * np.pi
    ridge = 0.05 * np.sin(x * 3 + 0.4) + 0.04 * np.sin(x * 7 + 1.3) + 0.025 * np.sin(x * 13 + 0.2)
    below = y > (1.0 - 0.10 - ridge)[None, :]
    base[below] = base[below] * 0.35 + np.array([60, 96, 62]) * 0.65
    return to_img(base)


ALL = {
    "asphalt.tex": (flagstones, "opaque"), "kerb.tex": (carved_kerb, "opaque"),
    "dirt.tex": (sand, "opaque"), "grass.tex": (jungle_grass, "opaque"),
    "carve.tex": (carve, "opaque"), "gold.tex": (gold, "opaque"), "head.tex": (stone_head, "opaque"),
    "palm.tex": (palm, "colorkey"), "fern.tex": (fern, "colorkey"), "broad.tex": (broad, "colorkey"),
}


if __name__ == "__main__":
    from pathlib import Path
    tiles = [(k, f()) for k, (f, _m) in ALL.items()] + [("sky", jungle_sky())]
    sheet = Image.new("RGB", (6 * 150 + 20, 2 * 160 + 40 + 280), (24, 26, 22))
    d = ImageDraw.Draw(sheet)
    for i, (k, im) in enumerate(tiles[:-1]):
        x, y = 10 + (i % 6) * 150, 10 + (i // 6) * 160
        show = im.resize((128, 128), Image.NEAREST)
        if ALL[k][1] == "colorkey":
            a = np.array(show); key = a.sum(axis=2) == 0
            chk = ((np.indices(key.shape).sum(0) // 8) % 2)[..., None] * 40 + 60
            a[key] = np.broadcast_to(chk, a.shape)[key]
            show = Image.fromarray(a)
        sheet.paste(show, (x, y)); d.text((x, y + 132), k, fill=(220, 220, 200))
    sheet.paste(tiles[-1][1].resize((900, 225)), (10, 340))
    out = Path(__file__).resolve().parent / "temple_art.png"
    sheet.save(out); print(out)
