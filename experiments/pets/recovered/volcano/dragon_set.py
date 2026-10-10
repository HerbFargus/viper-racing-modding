"""The crater set piece: a burninating dragon and three burning monks.

The DRAGON stands on the left (north-west) rim, turned side-on to the climb, and breathes
one expanding fireball -- white-hot at the jaws, billowing orange, then smoky red -- whose
leading mass sits on the jump's arc over the middle of the crater. Both are drawn only:
the car flies through the fire. Green scales, pale banded belly, purple bat wings, a
human-coloured muscle arm, beady black eyes under a long angry V of brow.

The MONKS are three hooded, cloaked monks with their heads on fire, each a two-panel
cutout (colorkey), placed as `obj obstacle cube` records on the level shelf of the right
(east) rim so a car can send them flying -- into the lava, with luck.

Geometry is built in a LOCAL frame (x = the arm's side, y = the way he faces, z = up) as
parts: (three points, three uvs, texture, face-normal hint). Every uv stays inside the unit
square (the game draws anything past 1.0 as a see-through patch): tube v runs ping-pong
along the length, so it repeats without ever leaving [0, 1].
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "circuit"))
sys.path.insert(0, str(HERE.parent / "lava"))
from art import colourise, tile_noise, to_img  # noqa: E402
import lava_art as la  # noqa: E402


# ------------------------------------------------------------------ textures
def gscale(size=256, seed=301):
    n = tile_noise(size, 16, 3, 0.5, seed)
    img = colourise(n, (38, 110, 40), (80, 160, 60))
    c = la.cracks(size, seed + 1, cells=14, width=0.07)
    img = img * (1 - 0.55 * c[..., None]) + np.array([20, 60, 24]) * 0.55 * c[..., None]
    return to_img(img)


def gbelly(size=256, seed=311):
    n = tile_noise(size, 6, 4, 0.5, seed)
    img = colourise(n, (170, 190, 90), (214, 226, 130))
    y = np.arange(size)[:, None] / size
    bands = (np.sin(y * 2 * np.pi * 8) > 0.7)[..., None]
    img = np.where(np.broadcast_to(bands, img.shape), img * 0.7, img)
    return to_img(img)


def wingtex(size=256, seed=321):
    n = tile_noise(size, 8, 4, 0.5, seed)
    img = colourise(n, (96, 40, 140), (150, 80, 196))
    x = np.arange(size)[None, :] / size
    veins = (np.abs(np.sin(x * np.pi * 6)) < 0.08)[..., None]
    img = np.where(np.broadcast_to(veins, img.shape), img * 0.6, img)
    return to_img(img)


def wingbone(size=64, seed=331):
    return to_img(colourise(tile_noise(size, 4, 2, 0.5, seed), (60, 24, 90), (90, 44, 120)))


def skin(size=128, seed=341):
    return to_img(colourise(tile_noise(size, 6, 3, 0.5, seed), (196, 140, 110), (232, 184, 150)))


def brow(size=64, seed=601):
    return to_img(colourise(tile_noise(size, 4, 2, 0.5, seed), (14, 12, 12), (34, 30, 30)))


def fang(size=64, seed=611):
    return to_img(colourise(tile_noise(size, 4, 2, 0.5, seed), (214, 206, 180), (246, 240, 222)))


def fire(lo, hi, smoke, seed):
    def make(size=128):
        n = tile_noise(size, 6, 4, 0.55, seed)
        img = colourise(n, lo, hi)
        if smoke:
            sm = np.clip((tile_noise(size, 4, 3, 0.5, seed + 1) - 0.58) * 4, 0, 1) * smoke
            img = img * (1 - sm[..., None]) + np.array([70, 34, 22]) * sm[..., None]
        return to_img(img)
    return make


def monk(variant=0, size=256):
    """A hooded, cloaked monk, arms thrown up, head ablaze. Keyed out round the figure."""
    rng = np.random.default_rng(400 + variant)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size // 2
    robe, shade_, rope = (112, 78, 46, 255), (84, 56, 32, 255), (196, 170, 110, 255)
    lean = [-8, 6, 0][variant % 3]
    d.polygon([(cx - 26 + lean, 120), (cx + 26 + lean, 120), (cx + 44, 250), (cx - 44, 250)], fill=robe)
    d.polygon([(cx - 6 + lean, 124), (cx + 6 + lean, 124), (cx + 10, 250), (cx - 10, 250)], fill=shade_)
    d.line([(cx - 32 + lean // 2, 170), (cx + 32 + lean // 2, 170)], fill=rope, width=5)
    d.line([(cx + 10, 172), (cx + 14, 206)], fill=rope, width=4)
    arms = [[(-24, 128, -50, 70), (24, 128, 50, 70)],
            [(-24, 128, -56, 82), (24, 128, 44, 64)],
            [(-24, 128, -58, 132), (24, 128, 48, 72)]][variant % 3]
    for x0, y0, x1, y1 in arms:
        d.line([(cx + x0 + lean, y0), (cx + x1 + lean, y1)], fill=robe, width=20)
        d.ellipse([cx + x1 + lean - 7, y1 - 9, cx + x1 + lean + 7, y1 + 3], fill=(214, 168, 128, 255))
    hx = cx + lean
    d.polygon([(hx - 24, 128), (hx - 22, 92), (hx - 8, 72), (hx + 8, 72), (hx + 22, 92), (hx + 24, 128)], fill=robe)
    d.ellipse([hx - 13, 88, hx + 13, 120], fill=(40, 26, 18, 255))
    d.ellipse([hx - 8, 98, hx - 2, 104], fill=(250, 220, 120, 255))
    d.ellipse([hx + 2, 98, hx + 8, 104], fill=(250, 220, 120, 255))
    d.ellipse([hx - 5, 108, hx + 5, 116], fill=(120, 40, 20, 255))
    for col, scale, wob in (((214, 50, 18, 255), 1.0, 1.0), ((250, 130, 20, 255), 0.72, 0.8), ((255, 226, 90, 255), 0.42, 0.6)):
        for j in range(7):
            u = (j - 3) / 3.0
            bx = hx + u * 20 * scale
            top = 76 - scale * (54 + 22 * math.cos(u * 1.4)) - rng.uniform(0, 14) * wob
            sway = rng.uniform(-10, 10) * wob
            d.polygon([(bx - 10 * scale, 90), (bx + sway * 0.5 - 6 * scale, 60 - 20 * scale), (bx + sway, top),
                       (bx + sway * 0.5 + 6 * scale, 60 - 20 * scale), (bx + 10 * scale, 90)], fill=col)
    for _ in range(8):
        sx, sy = hx + rng.uniform(-40, 40), rng.uniform(4, 40)
        d.ellipse([sx - 2, sy - 2, sx + 2, sy + 2], fill=(255, 200, 80, 255))
    a = np.array(img)
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    a[..., :3] = np.maximum(a[..., :3], 8)                    # no kept texel is black
    return Image.fromarray(a)


MONK_TEX = [f"monk{v}.tex" for v in range(3)]
TEXTURES = {"gscale.tex": (gscale, "opaque"), "gbelly.tex": (gbelly, "opaque"), "skin.tex": (skin, "opaque"),
            "wing.tex": (wingtex, "opaque"), "wingbone.tex": (wingbone, "opaque"), "brow.tex": (brow, "opaque"),
            "fang.tex": (fang, "opaque"),
            "fire1.tex": (fire((255, 206, 70), (255, 248, 200), 0, 501), "opaque"),
            "fire2.tex": (fire((236, 110, 18), (255, 200, 60), 0, 511), "opaque"),
            "fire3.tex": (fire((170, 36, 10), (246, 120, 24), 0.55, 521), "opaque")}
TEXTURES.update({t: ((lambda v=v: monk(v)), "colorkey") for v, t in enumerate(MONK_TEX)})
FIRE_TEX = ("fire1.tex", "fire2.tex", "fire3.tex")


# ------------------------------------------------------------------ geometry (local frame)
def pingpong(x):
    """A triangle wave in [0, 1]: repeats a texture along a tube without leaving the unit square."""
    x = x % 2.0
    return x if x <= 1.0 else 2.0 - x


def tube(spine, radii, tex, belly=None, seg=12):
    """Tapered tube, parallel-transported frames (no twist). belly: texture for the side
    facing forward/down, for spines in the y-z plane."""
    P = [np.array(p, float) for p in spine]
    n = len(P)
    T = []
    for i in range(n):
        t = P[min(i + 1, n - 1)] - P[max(i - 1, 0)]
        T.append(t / np.linalg.norm(t))
    a = np.array([1.0, 0, 0]) - T[0][0] * T[0]
    if np.linalg.norm(a) < 1e-3:
        a = np.array([0, 1.0, 0]) - T[0][1] * T[0]
    rings = []
    for i in range(n):
        a = a - np.dot(a, T[i]) * T[i]
        a /= np.linalg.norm(a)
        b = np.cross(T[i], a)
        rings.append([P[i] + radii[i] * (math.cos(2 * math.pi * k / seg) * a + math.sin(2 * math.pi * k / seg) * b)
                      for k in range(seg)])
    L = np.concatenate([[0], np.cumsum([np.linalg.norm(P[i + 1] - P[i]) for i in range(n - 1)])])
    V = [pingpong(l / (2 * np.mean(radii) + 1e-6)) for l in L]
    out = []
    for i in range(n - 1):
        mid = (P[i] + P[i + 1]) / 2
        tm = (T[i] + T[i + 1]) / 2
        front = np.array([0.0, tm[2], -tm[1]])
        front = front / (np.linalg.norm(front) + 1e-9)
        for k in range(seg):
            k2 = (k + 1) % seg
            q = [rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]]
            u0, u1 = k / seg, (k + 1) / seg
            uv = [(u0, V[i]), (u1, V[i]), (u1, V[i + 1]), (u0, V[i + 1])]
            off = np.mean(q, axis=0) - mid
            use = belly if belly and np.dot(off / (np.linalg.norm(off) + 1e-9), front) > 0.45 else tex
            for tri in ((0, 1, 2), (0, 2, 3)):
                out.append(([q[j] for j in tri], [uv[j] for j in tri], use, off))
    for end, sgn in ((0, -1), (n - 1, 1)):
        for k in range(seg):
            out.append(([P[end], rings[end][k], rings[end][(k + 1) % seg]], [(0.5, 0.5)] * 3, tex, sgn * T[end]))
    return out


def lumpy(c, r, tex, seed=0, rings=8, seg=12, amp=0.22):
    """A sphere, made billowy by amp (0 = smooth)."""
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0, 2 * math.pi, 4)
    c = np.array(c, float)

    def pt(i, j):
        th = math.pi * i / rings
        fi = 2 * math.pi * j / seg
        d = np.array([math.sin(th) * math.cos(fi), math.sin(th) * math.sin(fi), math.cos(th)])
        k = 1 + amp * (math.sin(3 * th + ph[0]) * math.cos(3 * fi + ph[1]) + 0.6 * math.sin(5 * fi + ph[2] + 2 * th))
        return c + r * k * d, d

    out = []
    for i in range(rings):
        for j in range(seg):
            q = [pt(i, j), pt(i, j + 1), pt(i + 1, j + 1), pt(i + 1, j)]
            uv = [(j / seg, i / rings), ((j + 1) / seg, i / rings), ((j + 1) / seg, (i + 1) / rings), (j / seg, (i + 1) / rings)]
            for tri in ((0, 1, 2), (0, 2, 3)):
                if i == 0 and tri == (0, 1, 2) or i == rings - 1 and tri == (0, 2, 3):
                    continue                                          # degenerate at the poles
                out.append(([q[t][0] for t in tri], [uv[t] for t in tri], tex, sum(q[t][1] for t in tri)))
    return out


def cone(base, tip, r, tex, seg=8):
    base, tip = np.array(base, float), np.array(tip, float)
    return tube([base, (base + tip) / 2, tip], [r, r * 0.5, 0.05], tex, seg=seg)


def bar(a, b, h, w, tex):
    """A straight box from a to b, h high and w wide: an eyebrow."""
    a, b = np.array(a, float), np.array(b, float)
    t = (b - a) / np.linalg.norm(b - a)
    side = np.cross(t, (0, 0, 1.0)); side /= np.linalg.norm(side)
    up = np.cross(side, t)
    c = {(i, j, k): (a if i == 0 else b) + up * h * j + side * w * k for i in (0, 1) for j in (-1, 1) for k in (-1, 1)}
    faces = [([(0, -1, -1), (0, 1, -1), (0, 1, 1), (0, -1, 1)], -t), ([(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)], t),
             ([(0, 1, -1), (1, 1, -1), (1, 1, 1), (0, 1, 1)], up), ([(0, -1, -1), (1, -1, -1), (1, -1, 1), (0, -1, 1)], -up),
             ([(0, -1, 1), (1, -1, 1), (1, 1, 1), (0, 1, 1)], side), ([(0, -1, -1), (1, -1, -1), (1, 1, -1), (0, 1, -1)], -side)]
    out = []
    for q, n in faces:
        P = [c[k] for k in q]
        for tri, uv in (((0, 1, 2), [(0, 0), (1, 0), (1, 1)]), ((0, 2, 3), [(0, 0), (1, 1), (0, 1)])):
            out.append(([P[i] for i in tri], uv, tex, n))
    return out


def wing(root, pts, tex):
    """A fan of triangles, drawn from both sides."""
    out = []
    root = np.array(root, float)
    pts = [np.array(p, float) for p in pts]
    for a, b in zip(pts, pts[1:]):
        n = np.cross(a - root, b - root)
        for s in (1, -1):
            out.append(([root, a, b], [(0.5, 0.0), (0.0, 1.0), (1.0, 1.0)], tex, s * n))
    return out


def yz(pts):
    return [(0.0, y, z) for y, z in pts]


def resample(spine, radii, k=3):
    """Catmull-Rom densify, so the S reads smooth."""
    P = [np.array(p, float) for p in spine]
    out, rr = [], []
    for i in range(len(P) - 1):
        p0, p1, p2, p3 = P[max(i - 1, 0)], P[i], P[i + 1], P[min(i + 2, len(P) - 1)]
        for s in range(k):
            t = s / k
            q = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
            out.append(tuple(q))
            rr.append(radii[i] + (radii[i + 1] - radii[i]) * t)
    out.append(tuple(P[-1])); rr.append(radii[-1])
    return out, rr


def back_spikes(spine, radii, every, h, lean=0.45, skip=()):
    out = []
    P = [np.array(p, float) for p in spine]
    for i in range(0, len(P), every):
        if i in skip:
            continue
        t = P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]
        t /= np.linalg.norm(t)
        back = np.array([0.0, -t[2], t[1]])
        base = P[i] + back * radii[i] * 0.8
        hh = h[i] if hasattr(h, "__len__") else h
        out += cone(base, base + back * hh - t * lean * hh, 0.32 * hh + 0.15, "gbelly.tex", seg=6)
    return out


BODY = [(0.5, 4.0), (1.8, 5.6), (2.4, 7.4), (1.7, 9.3), (-0.2, 10.8), (-1.2, 12.4), (-0.8, 13.9),
        (0.7, 15.0), (2.3, 15.5), (3.2, 15.6)]
BODY_R = [1.5, 1.75, 1.75, 1.5, 1.4, 1.5, 1.25, 1.05, 1.0, 1.0]
TAIL = [(-6.8, 2.6), (-5.2, 2.9), (-3.6, 3.3), (-2.0, 3.7), (-0.6, 4.0), (0.6, 4.1)]
TAIL_R = [0.12, 0.5, 0.85, 1.15, 1.4, 1.55]


def dragon():
    """The dragon without his fire, 21 local units tall at scale 1."""
    parts = []
    body, br = resample(yz(BODY), BODY_R)
    tail, tr = resample(yz(TAIL), TAIL_R)
    parts += tube(body, br, "gscale.tex", belly="gbelly.tex")
    parts += tube(tail, tr, "gscale.tex", belly="gbelly.tex")
    # head: long upper snout, dropped lower jaw, the throat glowing between them
    parts += tube([(0, 2.8, 15.7), (0, 4.0, 16.1), (0, 5.4, 16.0), (0, 6.8, 15.6)], [1.05, 1.0, 0.8, 0.5], "gscale.tex")
    parts += tube([(0, 3.2, 15.0), (0, 4.6, 14.4), (0, 6.2, 13.9)], [0.75, 0.55, 0.32], "gbelly.tex")
    parts += lumpy((0, 4.3, 15.1), 0.55, "fire1.tex", amp=0.0, rings=6, seg=8)
    for s in (1, -1):
        parts += tube([(s * 0.55, 3.6, 16.6), (s * 0.9, 2.3, 17.5), (s * 1.0, 1.1, 18.0), (s * 0.9, 0.5, 18.9)],
                      [0.32, 0.25, 0.17, 0.05], "gbelly.tex", seg=6)                  # swept-back horns
        parts += bar((s * 1.26, 4.14, 18.35), (s * 0.06, 4.66, 17.15), 0.14, 0.17, "brow.tex")   # the angry V
        parts += lumpy((s * 0.74, 4.66, 16.95), 0.3, "brow.tex", amp=0.0, rings=6, seg=8)   # beady black eyes
        parts += cone((s * 0.9, 3.4, 15.4), (s * 1.6, 2.2, 14.8), 0.3, "gbelly.tex", seg=5)   # cheek frills
        for j in range(3):                                                            # fangs
            parts += cone((s * 0.4, 5.2 + 0.6 * j, 15.3 - 0.1 * j), (s * 0.4, 5.2 + 0.6 * j, 14.8 - 0.1 * j),
                          0.1, "fang.tex", seg=4)
    parts += back_spikes(body, br, 2, [0.9] * 16 + [1.3] * 12, skip=(14, 16))
    parts += back_spikes(tail, tr, 2, [0.35, 0.45, 0.6, 0.7, 0.85, 0.95, 1.05, 1.1, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2])
    for k, (y, z) in enumerate(((2.9, 16.9), (2.2, 16.6), (1.5, 16.2))):
        parts += cone((0, y, z), (0, y - 0.9, z + 1.3 - 0.2 * k), 0.35, "gbelly.tex", seg=6)
    # THE ARM: shoulder, bicep, elbow back, forearm forward, fist
    parts += lumpy((1.8, -1.9, 12.9), 2.0, "skin.tex", amp=0.04, rings=10, seg=14)
    parts += tube(*resample([(2.1, -2.2, 12.7), (2.9, -4.2, 11.5), (3.2, -5.7, 9.4)], [2.0, 2.6, 1.5]), "skin.tex", seg=14)
    parts += tube(*resample([(3.2, -5.7, 9.4), (3.1, -5.1, 7.9), (2.8, -3.6, 6.8)], [1.5, 2.1, 1.25]), "skin.tex", seg=14)
    parts += lumpy((2.7, -2.6, 6.7), 1.65, "skin.tex", amp=0.04, rings=10, seg=14)
    for j in range(4):                                                                # knuckles
        parts += lumpy((2.7 + 0.15 * (j - 1.5), -1.3, 6.3 + 0.6 * (j - 1.5)), 0.5, "skin.tex", amp=0.0, rings=5, seg=6)
    # legs: stout thighs, digitigrade shins, splayed clawed feet
    for s in (1, -1):
        parts += tube([(s * 1.0, 0.6, 4.3), (s * 1.3, 1.6, 2.6), (s * 1.25, 0.6, 1.0), (s * 1.2, 0.9, 0.35)],
                      [1.0, 0.75, 0.42, 0.35], "gscale.tex", seg=10)
        for d in (-0.4, 0, 0.4):
            parts += tube([(s * 1.2 + d, 0.9, 0.35), (s * 1.2 + d * 1.8, 2.2, 0.18)], [0.2, 0.12], "gscale.tex", seg=6)
            parts += cone((s * 1.2 + d * 1.8, 2.2, 0.18), (s * 1.2 + d * 2.0, 2.7, 0.0), 0.12, "fang.tex", seg=4)
    # bat wings: finger spars and a scalloped membrane, one big, one small behind
    for xs, sc in ((-0.8, 1.0), (0.9, 0.62)):
        root = np.array((xs, -1.6, 13.6))
        fingers = [(xs * 1.1, -2.4, 17.2), (xs * 1.3, -5.0, 22.0), (xs * 1.4, -8.2, 19.8), (xs * 1.3, -8.8, 16.6),
                   (xs * 1.1, -6.2, 14.4)]
        tips = [root + sc * (np.array(f) - root) for f in fingers]
        edge = [tips[0], tips[1]]
        for a, b in zip(tips[1:], tips[2:]):
            edge += [root + 0.72 * ((a + b) / 2 - root), b]                           # scallop between fingers
        parts += wing(root, edge, "wing.tex")
        for f in tips[1:]:
            parts += tube([root, root + 0.55 * (f - root), f], [0.22, 0.14, 0.05], "wingbone.tex", seg=6)
    return parts


def fireball(end, radius):
    """One expanding blast from the jaws to `end` (local), `radius` across there."""
    parts = []
    m = np.array((0, 6.6, 14.8))
    e = np.array(end, float)
    axis = e - m
    L = np.linalg.norm(axis)
    side = np.cross(axis / L, (0, 0, 1.0))
    side = side / (np.linalg.norm(side) + 1e-9)
    upv = np.cross(side, axis / L)
    rng = np.random.default_rng(7)
    n = max(8, int(L / 1.6))
    for i in range(n + 1):
        t = i / n
        r = 0.35 + (radius - 0.35) * t ** 0.85
        c = m + axis * (t * 1.04) + (side * rng.uniform(-1, 1) + upv * rng.uniform(-1, 1)) * 0.25 * r * t
        tex = FIRE_TEX[0] if t < 0.3 else FIRE_TEX[1] if t < 0.7 else FIRE_TEX[2]
        parts += lumpy(c, r, tex, seed=10 + i, amp=0.18, rings=7, seg=11)
        if t > 0.45:                                                                  # billows off the leading mass
            for j in range(2):
                d = side * rng.uniform(-1, 1) + upv * rng.uniform(-0.6, 1) + axis / L * rng.uniform(0, 0.5)
                parts += lumpy(c + d / np.linalg.norm(d) * r * 0.8, r * rng.uniform(0.4, 0.6), FIRE_TEX[2],
                               seed=100 + 2 * i + j, amp=0.2, rings=6, seg=9)
    return parts


def place(parts, at, yaw_deg, scale=1.0):
    """Local -> source frame (x east, y north, z up). Returns (P, uv, tex, unit normal)."""
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    Rm = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    at = np.array(at, float)
    out = []
    for P, uv, tex, n in parts:
        Q = [at + Rm @ (np.asarray(p, float) * scale) for p in P]
        nn = Rm @ np.asarray(n, float)
        out.append((Q, uv, tex, nn / (np.linalg.norm(nn) + 1e-12)))
    return out


def yaw_facing(frm, to):
    """place() turns local +y to (-sin yaw, cos yaw): the yaw that faces frm toward to."""
    return math.degrees(math.atan2(-(to[0] - frm[0]), to[1] - frm[1]))


def smooth_greys(tris, sun, lo=0.62, hi=1.0):
    """Per-vertex baked light: face normals (turned to their hints) averaged over every
    triangle sharing a point, then lit by the sun."""
    acc = {}
    fn = []
    for P, _uv, _t, hint in tris:
        a, b, c = (np.asarray(p) for p in P)
        n = np.cross(b - a, c - a)
        nn = np.linalg.norm(n)
        n = hint if nn < 1e-12 else n / nn
        if np.dot(n, hint) < 0:
            n = -n
        fn.append(n)
        for p in P:
            k = tuple(np.round(p, 3))
            acc[k] = acc.get(k, 0) + n
    out = []
    for (P, _uv, _t, _h), n in zip(tris, fn):
        g = []
        for p in P:
            v = acc[tuple(np.round(p, 3))]
            v = v / (np.linalg.norm(v) + 1e-12)
            g.append(lo + (hi - lo) * max(0.0, float(v @ sun)))
        out.append(g)
    return out


def clamp_uv(uv):
    """Belt and braces: every uv inside the unit square."""
    return [(min(1.0, max(0.0, float(u))), min(1.0, max(0.0, float(v)))) for u, v in uv]


# ------------------------------------------------------------------ the monk obstacle mesh
def monk_mesh(tex_name, yaw_deg, to_game, w=2.4, h=3.4, foot=3.0):
    """Two crossed upright panels, each double-sided, centred on the mesh origin (the
    obstacle record places it), turned by yaw_deg to face the approach. Game frame."""
    from vrmod import mod
    verts, faces = [], []
    c0, s0 = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    for ang in (0.0, math.pi / 2):
        # a panel across local x, facing local +y, then yawed
        dx = np.array((math.cos(ang), math.sin(ang), 0.0))
        nrm = np.array((-math.sin(ang), math.cos(ang), 0.0))
        R2 = np.array([[c0, -s0, 0], [s0, c0, 0], [0, 0, 1]])
        dx, nrm = R2 @ dx, R2 @ nrm
        corners = [-dx * w / 2 - (0, 0, h / 2), dx * w / 2 - (0, 0, h / 2), dx * w / 2 + (0, 0, h / 2),
                   -dx * w / 2 + (0, 0, h / 2)]
        uvs = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
        for side in (1, -1):
            G = [np.array(to_game(tuple(p))) for p in corners]
            gn = np.array(to_game(tuple(nrm * side)))
            base = len(verts)
            for p, uv in zip(G, uvs):
                verts.append(mod.Vertex(float(p[0]), float(p[1]), float(p[2]), float(gn[0]), float(gn[1]), float(gn[2]),
                                        uv[0], uv[1]))
            for tri in ((0, 1, 2), (0, 2, 3)):
                a, b, c = (G[k] for k in tri)
                if np.dot(np.cross(b - a, c - a), gn) < 0:
                    tri = (tri[0], tri[2], tri[1])
                faces.append(tuple(base + k for k in tri))
    # the foot plate: a square at the feet, mapped to a keyed-out corner texel, so it is never
    # drawn -- but it widens the mesh's extents, and the engine sizes the collision box from those
    half = foot / 2
    corners = [(-half, -half, -h / 2), (half, -half, -h / 2), (half, half, -h / 2), (-half, half, -h / 2)]
    G = [np.array(to_game(c)) for c in corners]
    up = np.array(to_game((0.0, 0.0, 1.0)))
    base = len(verts)
    for p in G:
        verts.append(mod.Vertex(float(p[0]), float(p[1]), float(p[2]), float(up[0]), float(up[1]), float(up[2]),
                                0.02, 0.98))
    for tri in ((0, 1, 2), (0, 2, 3)):
        a, b, c = (G[k] for k in tri)
        if np.dot(np.cross(b - a, c - a), up) < 0:
            tri = (tri[0], tri[2], tri[1])
        faces.append(tuple(base + k for k in tri))
    return mod.Mesh(vertices=verts, faces=faces, materials=[mod.Material(
        name=tex_name, vertex_start=0, vertex_end=len(verts), face_start=0, face_end=len(faces))])


# ------------------------------------------------------------------ thatched cottages
def thatch(size=256, seed=221):
    n = tile_noise(size, 32, 3, 0.5, seed)
    img = colourise(n, (140, 110, 60), (196, 164, 96))
    y = np.arange(size)[:, None] / size
    img *= (0.85 + 0.15 * np.sin(y * 2 * np.pi * 24))[..., None]                 # rows of straw
    scorch = np.clip((tile_noise(size, 4, 3, 0.5, seed + 1) - 0.62) * 3, 0, 1)
    img = img * (1 - 0.5 * scorch[..., None]) + np.array([60, 40, 24]) * 0.5 * scorch[..., None]
    return to_img(img)


def plaster(size=128, seed=231):
    """Wattle and daub between dark timber: posts at both ends and the middle, a rail at the top."""
    n = tile_noise(size, 8, 3, 0.5, seed)
    img = colourise(n, (196, 186, 160), (226, 216, 190))
    x = np.arange(size)[None, :] / size
    y = np.arange(size)[:, None] / size
    beam = (np.abs(x - 0.5) < 0.035) | (x < 0.04) | (x > 0.96) | (y < 0.05) | (np.abs(y - 0.55) < 0.03)
    beam = np.broadcast_to(beam, img.shape[:2])
    img[beam] = img[beam] * 0 + np.array([92, 66, 42])
    return to_img(img)


TEXTURES.update({"thatch.tex": (thatch, "opaque"), "plaster.tex": (plaster, "opaque")})

COTTAGE_W, COTTAGE_D, COTTAGE_WALL = 8.0, 6.0, 3.2        # along y, across x (the door side is +x), wall height


def cottage(burning, sink=0.3, seed=0):
    """A timber-framed, thatch-roofed cottage, floor at z = 0, door and windows on +x.
    Walls run down to -sink so it sits into sloping ground. Burning: flames out of the
    thatch and glowing windows."""
    rng = np.random.default_rng(900 + seed)
    w, d, h = COTTAGE_D / 2, COTTAGE_W / 2, COTTAGE_WALL
    out = []

    def quad(P, uv, tex, n):
        P = [np.array(p, float) for p in P]
        out.append(([P[0], P[1], P[2]], [uv[0], uv[1], uv[2]], tex, np.array(n, float)))
        out.append(([P[0], P[2], P[3]], [uv[0], uv[2], uv[3]], tex, np.array(n, float)))

    z0 = -sink
    wall_uv = [(0, 1), (1, 1), (1, 0), (0, 0)]
    quad([(w, -d, z0), (w, d, z0), (w, d, h), (w, -d, h)], wall_uv, "plaster.tex", (1, 0, 0))
    quad([(-w, d, z0), (-w, -d, z0), (-w, -d, h), (-w, d, h)], wall_uv, "plaster.tex", (-1, 0, 0))
    quad([(w, d, z0), (-w, d, z0), (-w, d, h), (w, d, h)], wall_uv, "plaster.tex", (0, 1, 0))
    quad([(-w, -d, z0), (w, -d, z0), (w, -d, h), (-w, -d, h)], wall_uv, "plaster.tex", (0, -1, 0))
    ridge, eave, over = h + 3.4, h - 0.4, 0.7
    for s in (1, -1):                                                  # gables: plaster triangles up to the ridge
        out.append(([np.array((w * s, s * d, h)), np.array((-w * s, s * d, h)), np.array((0, s * d, ridge))],
                    [(0, 1), (1, 1), (0.5, 0.45)], "plaster.tex", np.array((0, s, 0.0))))
    for s in (1, -1):                                                  # the two thatch slopes, overhanging
        quad([(s * (w + over), -d - over, eave), (s * (w + over), d + over, eave), (0, d + over, ridge + 0.2),
              (0, -d - over, ridge + 0.2)], [(0, 1), (1, 1), (1, 0), (0, 0)], "thatch.tex", (s, 0, 1.2))
        quad([(s * (w + over), d + over, eave), (s * (w + over), -d - over, eave), (0, -d - over, ridge + 0.2),
              (0, d + over, ridge + 0.2)], [(0, 1), (1, 1), (1, 0), (0, 0)], "thatch.tex", (-s, 0, -1.2))  # underside
    e = 0.03                                                           # door and windows, just proud of the wall
    quad([(w + e, -0.6, 0.0), (w + e, 0.6, 0.0), (w + e, 0.6, 2.1), (w + e, -0.6, 2.1)],
         [(0.1, 0.9), (0.9, 0.9), (0.9, 0.1), (0.1, 0.1)], "brow.tex", (1, 0, 0))
    glass = "fire1.tex" if burning else "brow.tex"
    for yc in (-2.3, 2.3):
        quad([(w + e, yc - 0.55, 1.2), (w + e, yc + 0.55, 1.2), (w + e, yc + 0.55, 2.2), (w + e, yc - 0.55, 2.2)],
             [(0.1, 0.9), (0.9, 0.9), (0.9, 0.1), (0.1, 0.1)], glass, (1, 0, 0))
    if burning:                                                        # flames roaring up out of the thatch
        for k in range(7):
            yy = -d + 0.8 + k * (2 * d - 1.6) / 6 + rng.uniform(-0.3, 0.3)
            xx = rng.uniform(-1.8, 1.8)
            zb = ridge - abs(xx) * (ridge - eave) / (w + over) - 0.4
            tall = rng.uniform(4.0, 7.0)
            lean = rng.uniform(-0.6, 0.6)
            out += lumpy((xx, yy, zb + 0.6), 1.5, "fire2.tex", seed=300 + seed * 10 + k, amp=0.22, rings=5, seg=8)
            out += tube([(xx, yy, zb), (xx * 1.05, yy + lean * 0.5, zb + tall * 0.5), (xx * 1.1, yy + lean, zb + tall)],
                        [1.5, 1.0, 0.05], "fire2.tex", seg=8)
            out += tube([(xx, yy, zb + 0.3), (xx, yy + lean * 0.3, zb + tall * 0.4), (xx, yy + lean * 0.5, zb + tall * 0.65)],
                        [0.8, 0.5, 0.03], "fire1.tex", seg=6)
        for yc in (-2.3, 2.3):                                         # flames out of the windows
            out += tube([(w + 0.1, yc, 1.4), (w + 0.7, yc, 2.6), (w + 0.9, yc, 4.0)], [0.55, 0.45, 0.03], "fire2.tex", seg=6)
    return out


def flat_greys(tris, sun, lo=0.55, hi=1.0):
    """Per-face baked light, for flat-sided things like walls and roofs."""
    out = []
    for P, _uv, t, hint in tris:
        if t in FIRE_TEX:
            out.append([1.0] * 3)
            continue
        n = np.asarray(hint, float)
        n = n / (np.linalg.norm(n) + 1e-12)
        out.append([lo + (hi - lo) * max(0.0, float(n @ sun))] * 3)
    return out
