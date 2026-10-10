"""Procedural art kit for the circuit -- every texel generated here, nothing derived.

Textures (names are 8.3; all avoid decoded black except where transparency is meant):
  grass    tileable green turf              meadow   drier, yellower grass
  dirt     earth shoulder                   rock     grey-brown stone with strata
  asphalt  road: aggregate, edge lines, dashed centre line (u across, v along 10 m)
  kerb     red/white blocks along the band  armco    guardrail on posts (colorkey)
  pine     conifer billboard (colorkey)     oak      broadleaf billboard (colorkey)
  bush     low shrub billboard (colorkey)   sky      1024x256 panorama, tiles 4x256
"""
import numpy as np
from PIL import Image

RNG = np.random.default_rng(1998)


def tile_noise(size, cells, octaves=4, persistence=0.5, seed=0):
    """Tileable fBm value noise in [0, 1] on a size x size grid."""
    rng = np.random.default_rng(seed)
    out = np.zeros((size, size))
    amp, total, c = 1.0, 0.0, cells
    for _ in range(octaves):
        lattice = rng.random((c, c))
        ys = np.arange(size) * c / size
        y0 = np.floor(ys).astype(int); fy = ys - y0
        fy = fy * fy * (3 - 2 * fy)
        y1 = (y0 + 1) % c
        xs, x0, fx, x1 = ys, y0, fy, y1
        a = lattice[np.ix_(y0, x0)]; b = lattice[np.ix_(y0, x1)]
        cc = lattice[np.ix_(y1, x0)]; d = lattice[np.ix_(y1, x1)]
        FX, FY = np.meshgrid(fx, fy)
        out += amp * ((a * (1 - FX) + b * FX) * (1 - FY) + (cc * (1 - FX) + d * FX) * FY)
        total += amp; amp *= persistence; c *= 2
    return out / total


def colourise(n, low, high):
    low, high = np.array(low, float), np.array(high, float)
    return low + (high - low) * n[..., None]


def to_img(arr):
    arr = np.clip(arr, 10, 255).astype(np.uint8)       # never decoded black
    return Image.fromarray(arr, "RGB")


def speckle(size, density, seed):
    return (np.random.default_rng(seed).random((size, size)) < density).astype(float)


# ------------------------------------------------------------------ ground
def grass(size=128, seed=1, dry=False):
    n = tile_noise(size, 4, 5, 0.55, seed)
    fine = tile_noise(size, 32, 2, 0.5, seed + 7)
    if dry:
        img = colourise(n, (86, 108, 46), (136, 142, 66))    # dry olive, close to the grass
    else:
        img = colourise(n, (52, 98, 38), (98, 142, 56))
    img *= (0.85 + 0.3 * fine)[..., None]
    blades = speckle(size, 0.06, seed + 3)
    img += blades[..., None] * np.array([18, 22, 8]) * (1 if not dry else 1.2)
    return to_img(img)


def dirt(size=128, seed=11):
    n = tile_noise(size, 6, 5, 0.6, seed)
    img = colourise(n, (96, 72, 48), (146, 116, 80))
    pebbles = speckle(size, 0.03, seed + 1)
    img += pebbles[..., None] * np.array([40, 36, 30])
    return to_img(img)


def rock(size=128, seed=21):
    n = tile_noise(size, 4, 6, 0.6, seed)
    strata = 0.5 + 0.5 * np.sin(np.linspace(0, 6 * np.pi, size, endpoint=False)[:, None] + 3 * tile_noise(size, 3, 2, 0.5, seed + 2))
    v = 0.6 * n + 0.4 * strata
    img = colourise(v, (92, 86, 80), (168, 158, 146))
    cracks = (tile_noise(size, 16, 2, 0.5, seed + 5) > 0.78).astype(float)
    img *= (1 - 0.35 * cracks)[..., None]
    return to_img(img)


def asphalt(size=128, seed=31):
    n = tile_noise(size, 8, 4, 0.55, seed)
    img = colourise(n, (58, 60, 64), (84, 86, 90))
    agg = speckle(size, 0.12, seed + 1) * np.random.default_rng(seed).random((size, size))
    img += agg[..., None] * 30
    u = np.arange(size) / size
    edge = ((u > 0.035) & (u < 0.06)) | ((u > 0.94) & (u < 0.965))
    img[:, edge] = [228, 228, 222]
    v = np.arange(size) / size
    dash = (v % 0.5) < 0.28                            # two dashes per 10 m tile
    centre = (u > 0.49) & (u < 0.51)
    img[np.ix_(dash, centre)] = [232, 226, 150]
    return to_img(img)


def kerb(size=64):
    v = np.arange(size) / size
    red = ((v * 8).astype(int) % 2) == 0              # 8 blocks per 10 m
    img = np.where(red[:, None, None], np.array([196, 34, 30]), np.array([236, 236, 232]))
    img = np.broadcast_to(img, (size, size, 3)).astype(float).copy()
    img *= (0.9 + 0.1 * tile_noise(size, 8, 2, 0.5, 41))[..., None]
    return to_img(img)


def stone(size=128, seed=91):
    """Coursed masonry: staggered blocks with mortar joints, for the bridge."""
    n = tile_noise(size, 8, 4, 0.6, seed)
    img = colourise(n, (108, 104, 98), (168, 162, 152))
    rows, cols = 6, 4
    rh, cw = size / rows, size / cols
    yy, xx = np.mgrid[0:size, 0:size]
    row = (yy / rh).astype(int)
    shift = (row % 2) * cw / 2
    joint = (((yy % rh) < 2.0) | (((xx + shift) % cw) < 2.0))
    img = np.where(joint[..., None], np.array([74, 72, 68]), img)
    shade = 0.9 + 0.2 * tile_noise(size, rows, 1, 0.5, seed + 3)
    return to_img(img * shade[..., None])


def water(size=128, seed=95):
    """Still water: deep blue-green with soft ripples and a few highlights."""
    n = tile_noise(size, 5, 4, 0.55, seed)
    ripple = 0.5 + 0.5 * np.sin(tile_noise(size, 3, 2, 0.5, seed + 1) * 9.0
                                + np.linspace(0, 8 * np.pi, size, endpoint=False)[:, None])
    v = 0.65 * n + 0.35 * ripple
    img = colourise(v, (26, 58, 92), (74, 126, 148))
    glint = (tile_noise(size, 24, 2, 0.5, seed + 7) > 0.80).astype(float)
    img += glint[..., None] * np.array([40, 48, 40])
    return to_img(img)


# ------------------------------------------------------------------ props (colorkey)
KEY = np.array([0, 0, 0])


def armco(size=64):
    """Guardrail: a W-profile rail across the upper half, posts below, air (keyed) elsewhere."""
    img = np.zeros((size, size, 3))
    y = np.arange(size)[:, None]; x = np.arange(size)[None, :]
    rail = (y >= size * 0.18) & (y < size * 0.52)
    shade = 150 + 60 * np.cos((y - size * 0.18) / (size * 0.34) * 2 * np.pi)
    img[np.broadcast_to(rail, (size, size))] = 0
    metal = np.broadcast_to(shade, (size, size))[..., None] * np.array([0.92, 0.95, 1.0])
    img = np.where(np.broadcast_to(rail, (size, size))[..., None], metal, img)
    posts = ((x % 32) >= 12) & ((x % 32) < 20) & (y >= size * 0.18)
    img = np.where(np.broadcast_to(posts, (size, size))[..., None], np.array([118, 118, 112]), img)
    out = np.clip(img, 0, 255).astype(np.uint8)
    solid = (out.sum(axis=2) > 0)
    out[solid] = np.maximum(out[solid], 20)            # solid parts never read as key
    return Image.fromarray(out, "RGB")


def pine(size=128, seed=51):
    """A conifer: stacked jagged tiers on a trunk, keyed background."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size, 3))
    yy, xx = np.mgrid[0:size, 0:size]
    cx = size / 2
    trunk = (abs(xx - cx) < size * 0.035) & (yy > size * 0.82)
    img[trunk] = [92, 62, 40]
    n = tile_noise(size, 16, 3, 0.5, seed)
    for tier in range(5):
        top = size * (0.04 + tier * 0.15); bot = top + size * 0.34
        half = (yy - top) / (bot - top) * size * (0.18 + 0.05 * tier)
        jag = half * (0.85 + 0.3 * n)
        inside = (yy >= top) & (yy < bot) & (abs(xx - cx) < jag)
        light = 0.75 + 0.35 * n + 0.15 * (cx - xx) / size
        col = np.stack([28 * light, 78 * light, 40 * light], -1)
        img[inside] = col[inside]
    out = np.clip(img, 0, 255).astype(np.uint8)
    solid = out.sum(axis=2) > 0
    out[solid] = np.maximum(out[solid], 14)
    return Image.fromarray(out, "RGB")


def oak(size=128, seed=61):
    """A broadleaf tree: lumpy round canopy of blobs over a trunk."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size, 3))
    yy, xx = np.mgrid[0:size, 0:size]
    cx = size / 2
    trunk = (abs(xx - cx) < size * 0.05 + (yy - size) * -0.01) & (yy > size * 0.55)
    img[trunk] = [96, 70, 48]
    n = tile_noise(size, 16, 3, 0.5, seed)
    canopy = np.zeros((size, size), bool)
    for _ in range(14):
        bx = cx + rng.normal(0, size * 0.12); by = size * 0.40 + rng.normal(0, size * 0.07)
        r = size * rng.uniform(0.11, 0.17)
        canopy |= (xx - bx) ** 2 + (yy - by) ** 2 < r * r
    light = 0.7 + 0.4 * n + 0.25 * (size * 0.5 - yy) / size
    col = np.stack([56 * light, 104 * light, 38 * light], -1)
    img[canopy] = col[canopy]
    out = np.clip(img, 0, 255).astype(np.uint8)
    solid = out.sum(axis=2) > 0
    out[solid] = np.maximum(out[solid], 14)
    return Image.fromarray(out, "RGB")


def bush(size=64, seed=71):
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size, 3))
    yy, xx = np.mgrid[0:size, 0:size]
    n = tile_noise(size, 8, 3, 0.5, seed)
    body = np.zeros((size, size), bool)
    for _ in range(9):
        bx = size / 2 + rng.normal(0, size * 0.16); by = size * 0.62 + rng.normal(0, size * 0.06)
        r = size * rng.uniform(0.14, 0.24)
        body |= (xx - bx) ** 2 + (yy - by) ** 2 < r * r
    body &= yy < size * 0.97
    light = 0.7 + 0.45 * n
    col = np.stack([70 * light, 108 * light, 44 * light], -1)
    img[body] = col[body]
    out = np.clip(img, 0, 255).astype(np.uint8)
    solid = out.sum(axis=2) > 0
    out[solid] = np.maximum(out[solid], 14)
    return Image.fromarray(out, "RGB")


# ------------------------------------------------------------------ sky
def sky(width=1024, height=256, seed=81):
    """One seamless 90-degree strip: gradient, soft clouds, a distant ridge line at the horizon."""
    y = np.linspace(0, 1, height)[:, None]                 # 0 top, 1 horizon
    top, hor = np.array([62, 112, 186]), np.array([196, 218, 236])
    base = top + (hor - top) * (y ** 1.6)[..., None]
    base = np.broadcast_to(base, (height, width, 3)).copy()
    # clouds: tileable horizontally only -> build on a square and stretch
    c = tile_noise(width, 10, 5, 0.55, seed)[:height] # full-width noise: wraps left-right exactly
    band = np.exp(-((y - 0.45) / 0.28) ** 2)               # clouds mid-sky, thin near the horizon
    cover = np.clip((c - 0.52) * 3.2, 0, 1) * band
    base = base * (1 - cover[..., None]) + np.array([246, 246, 250]) * cover[..., None]
    # distant ridge: a periodic profile, hazy blue-green
    x = np.arange(width) / width * 2 * np.pi
    ridge = (0.06 * np.sin(x * 2 + 0.3) + 0.035 * np.sin(x * 5 + 1.1) + 0.02 * np.sin(x * 11 + 2.0))
    ridge_y = 1.0 - 0.08 - ridge
    below = y > ridge_y[None, :]
    base[below] = base[below] * 0.45 + np.array([96, 124, 132]) * 0.55
    return to_img(base)


ALL = {
    "grass.tex": (grass, "opaque"), "meadow.tex": (lambda: grass(seed=5, dry=True), "opaque"),
    "dirt.tex": (dirt, "opaque"), "rock.tex": (rock, "opaque"), "asphalt.tex": (asphalt, "opaque"),
    "kerb.tex": (kerb, "opaque"), "armco.tex": (armco, "colorkey"), "pine.tex": (pine, "colorkey"),
    "oak.tex": (oak, "colorkey"), "bush.tex": (bush, "colorkey"),
    "stone.tex": (stone, "opaque"), "water.tex": (water, "opaque"),
}


if __name__ == "__main__":
    from PIL import ImageDraw
    imgs = {k: f()[0] if False else f() for k, (f, _m) in ALL.items()}
    sheet = Image.new("RGB", (5 * 150 + 20, 2 * 170 + 20 + 290), (21, 24, 28))
    d = ImageDraw.Draw(sheet)
    for i, (k, im) in enumerate(imgs.items()):
        x, y = 10 + (i % 5) * 150, 10 + (i // 5) * 170
        show = im.resize((128, 128), Image.NEAREST)
        if ALL[k][1] == "colorkey":                         # show keyed pixels as a checker
            a = np.array(show); key = a.sum(axis=2) == 0
            chk = ((np.indices(key.shape).sum(0) // 8) % 2) * 60 + 150
            a[key] = np.stack([chk] * 3, -1)[key]
            show = Image.fromarray(a)
        sheet.paste(show, (x, y))
        d.text((x, y + 132), f"{k}  ({ALL[k][1]})", fill=(220, 224, 228))
    s = sky()
    sheet.paste(s.resize((750, 188)), (10, 360))
    d.text((10, 552), "sky: one 1024x256 strip, tiled 4x around the horizon", fill=(220, 224, 228))
    sheet.save("art_sheet.png")
    print("ok")
