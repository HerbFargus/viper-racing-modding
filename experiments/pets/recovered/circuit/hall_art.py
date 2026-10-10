"""Art for the temple hall -- floor tiles, torches, vault stone and a painted interior sky.

  tile.tex   a 2x2 atlas of 5 m floor slabs: plain, cracked, glyph, worn. Each floor
             tile picks one quadrant, so the floor varies on a single material.
  torch.tex  a wall torch: iron bracket and flame (colour-keyed)
  vault.tex  dark rough stone for everything below and beyond the floor
  sky        1024x256: the far walls of a vast hall -- colonnade and arches lit by
             torches at the bottom, rising into a dark ribbed vault
"""
import math

import numpy as np
from PIL import Image, ImageDraw

import temple_art as ta
from art import colourise, speckle, tile_noise, to_img


def floor_tiles(size=128, seed=601):
    q = size // 2
    n = tile_noise(size, 8, 4, 0.55, seed)
    img = colourise(n, (128, 106, 76), (176, 150, 108))
    pil = Image.fromarray(np.clip(img, 20, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(pil)
    rng = np.random.default_rng(seed)
    for k, (x0, y0) in enumerate(((0, 0), (q, 0), (0, q), (q, q))):
        # bevelled slab: dark grout ring, a lighter lip inside it
        d.rectangle([x0, y0, x0 + q - 1, y0 + q - 1], outline=(70, 58, 42), width=2)
        d.rectangle([x0 + 2, y0 + 2, x0 + q - 3, y0 + q - 3], outline=(186, 162, 120), width=1)
        if k == 1:                                          # cracked
            pts = [(x0 + q * 0.2, y0 + q * 0.3)]
            for _ in range(6):
                px, py = pts[-1]
                pts.append((px + rng.uniform(4, 9), py + rng.uniform(-4, 6)))
            d.line(pts, fill=(84, 70, 50), width=1)
        elif k == 2:                                        # glyph
            ta._glyph(d, x0 + q * 0.2, y0 + q * 0.2, int(q * 0.6), int(rng.integers(ta.GLYPHS)), (102, 84, 60))
        elif k == 3:                                        # worn
            yy, xx = np.mgrid[0:q, 0:q]
            pass
    a = np.array(pil).astype(float)
    wear = tile_noise(size, 6, 3, 0.5, seed + 5)
    a[q:, q:] *= (0.85 + 0.25 * wear[q:, q:])[..., None]
    a += speckle(size, 0.04, seed + 2)[..., None] * np.array([-16, -14, -10])
    return to_img(a)


def trap_tile(inset=9):
    """The plain slab from the floor atlas, with a pressure plate set into it: a hairline
    seam inset from the grout, lit on one edge and shadowed on the other. Low contrast
    on purpose -- a tell for anyone looking, not a warning sign."""
    a = np.array(floor_tiles())[:64, :64].astype(float)          # atlas quadrant 0, the plain slab
    q = 64
    seam = np.array([118, 98, 70], float)
    lit = np.array([176, 152, 112], float)
    i0, i1 = inset, q - 1 - inset
    a[i0, i0:i1 + 1] = seam; a[i0:i1 + 1, i0] = seam              # shadowed top/left
    a[i1, i0:i1 + 1] = lit; a[i0:i1 + 1, i1] = lit                # lit bottom/right
    a[i0 + 1, i0 + 1:i1] = a[i0 + 1, i0 + 1:i1] * 0.94           # a whisker of depth
    return to_img(a)


def atlas_uv(k):
    """UV rect (u0, v0, u1, v1) of atlas quadrant k, inset half a texel against bleeding."""
    e = 0.5 / 128
    u0, v0 = (k % 2) * 0.5, (k // 2) * 0.5
    return u0 + e, v0 + e, u0 + 0.5 - e, v0 + 0.5 - e


def torch(size=64, seed=611):
    img = Image.new("RGB", (size, size), (0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size / 2
    d.rectangle([cx - 2, size * 0.45, cx + 2, size * 0.98], fill=(60, 48, 40))             # shaft
    d.polygon([(cx - 7, size * 0.40), (cx + 7, size * 0.40), (cx + 4, size * 0.52), (cx - 4, size * 0.52)],
              fill=(78, 64, 50))                                                           # cup
    rng = np.random.default_rng(seed)
    for r, col in ((13, (200, 70, 20)), (10, (236, 128, 30)), (7, (252, 196, 70)), (4, (255, 240, 170))):
        pts = []
        for i in range(14):
            a = 2 * math.pi * i / 14
            rr = r * (1 + 0.25 * rng.random())
            pts.append((cx + math.sin(a) * rr * 0.7, size * 0.30 - math.cos(a) * rr * (1.6 if math.cos(a) > 0 else 0.6)))
        d.polygon(pts, fill=col)
    a = np.array(img)
    solid = a.sum(axis=2) > 0
    a[solid] = np.maximum(a[solid], 14)
    return Image.fromarray(a, "RGB")


def vault(size=64, seed=621):
    n = tile_noise(size, 4, 5, 0.6, seed)
    return to_img(colourise(n, (34, 28, 22), (62, 52, 40)))


def temple_sky(width=1024, height=256, seed=631):
    """The far walls of the hall, seen from the floor. Row 0 is the top of the vault,
    the last row the horizon. Wraps left to right exactly: every feature repeats on
    a period that divides the width."""
    y = np.linspace(0, 1, height)[:, None]
    x = np.arange(width)[None, :]
    stone = tile_noise(width, 16, 4, 0.55, seed)[:height]
    # vault: near-black brown at the top, warming toward the wall head
    top, low = np.array([30, 24, 20]), np.array([96, 76, 54])
    img = top + (low - top) * np.clip((y - 0.05) / 0.6, 0, 1)[..., None] ** 1.4
    img = np.broadcast_to(img, (height, width, 3)).copy()
    img *= (0.85 + 0.3 * stone)[..., None]
    # vault ribs: bright-ish arcs converging upward, period 128 px
    ph = (x % 128) / 128.0
    rib = np.abs(ph - 0.5 - (0.5 - y) * 0.0) < 0.012 + 0.0 * y
    arcs = np.abs(((x % 128) - 64) / 64.0) ** 2 * 0.35 + 0.08
    rib_arc = (np.abs(y - arcs) < 0.012) & (y < 0.45)
    img[np.broadcast_to(rib_arc, (height, width))] = [88, 70, 50]
    # the wall: a colonnade from the horizon up to a cornice at ~55% height
    wall = y > 0.55
    colp = (x % 64)
    column = (colp < 12) & wall
    arch_c = 32 + 6
    niche = wall & ~column & ((((colp - arch_c) / 22.0) ** 2 + ((y - 0.72) / 0.12) ** 2) < 1) & (y > 0.60)
    wall_col = colourise(stone, (72, 58, 42), (108, 88, 64))
    img = np.where(np.broadcast_to(wall, (height, width))[..., None], wall_col, img)
    img = np.where(np.broadcast_to(column, (height, width))[..., None], wall_col * 1.2, img)
    img = np.where(np.broadcast_to(niche, (height, width))[..., None], np.array([44, 34, 26]), img)
    cornice = (np.abs(y - 0.56) < 0.012) | (np.abs(y - 0.60) < 0.006)
    img[np.broadcast_to(cornice, (height, width))] = [128, 104, 74]
    # torch glow on every other column, warm and falling off
    for cx in range(6, width, 128):
        for dx in (0, width, -width):
            gy, gx = 0.66, cx + dx
            r2 = ((x - gx) / 28.0) ** 2 + ((y - gy) / 0.10) ** 2
            glow = np.exp(-r2)[..., None]
            img = img * (1 + 0.45 * glow) + glow * np.array([34, 16, 2])
    # floor line: the hall floor meeting the wall, dim
    img[np.broadcast_to(y > 0.97, (height, width))] *= 0.7
    return to_img(img)


ALL = {"tile.tex": (floor_tiles, "opaque"), "trap.tex": (trap_tile, "opaque"), "torch.tex": (torch, "colorkey"), "vault.tex": (vault, "opaque"),
       "carve.tex": (ta.carve, "opaque"), "gold.tex": (ta.gold, "opaque"), "head.tex": (ta.stone_head, "opaque")}


if __name__ == "__main__":
    from pathlib import Path
    sheet = Image.new("RGB", (4 * 150 + 20, 170 + 20 + 280), (24, 22, 20))
    dd = ImageDraw.Draw(sheet)
    for i, (k, (f, mode)) in enumerate(ALL.items()):
        if i >= 4:
            break
        im = f().resize((128, 128), Image.NEAREST)
        if mode == "colorkey":
            a = np.array(im); key = a.sum(axis=2) == 0
            chk = ((np.indices(key.shape).sum(0) // 8) % 2)[..., None] * 40 + 60
            a[key] = np.broadcast_to(chk, a.shape)[key]
            im = Image.fromarray(a)
        sheet.paste(im, (10 + i * 150, 10)); dd.text((10 + i * 150, 142), k, fill=(220, 210, 190))
    sheet.paste(temple_sky().resize((600, 150)), (10, 180))
    out = Path(__file__).resolve().parent / "hall_art.png"
    sheet.save(out); print(out)
