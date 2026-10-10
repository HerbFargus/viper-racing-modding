"""Cats vs Dogs: the generated track, built from the layout mockup (cats-vs-dogs-track.html).

THE LAP is the mockup's 37 control points through a centripetal Catmull-Rom (the same curve
three.js drew), 14 m of road. A fence down x = 0 splits dog country (west: grass, red kerbs)
from cat country (east: paving, purple kerbs); the lap crosses it at the start gate and
through a giant cat flap.

THE GROUND is one solid height field (the Coliseum's pattern): Delaunay over road stations
and a jittered lattice, z from height(). Two jumps live in the road's own profile:
  frisbee   a 3 m kicker, 38 m gap, a 1.6 m landing ramp
  rooftop   the road climbs onto a 7 m roof plateau, then drops off its edge onto a 3.5 m
            landing ramp
Every lip has a 35-degree back slope -- a sheer face there is a near-vertical collision
triangle, and those act as walls for cars flying over them (the Coliseum, confirmed in game).
The roof's SIDES are steep on purpose: they act as rails keeping cars on the roof.

PROPS are low-poly flat-colour meshes from the track's own palette cvdtrk.tex (so the pets'
texture ships with the track, drawn). Its own NAME matters: the game caches textures by name,
and the cars' palettes order their colours differently.

THE BONE POND is real water: a flat surface 0.4 m down in the lawn, surface code 14 -- the
engine floats a car on it, as on Ridge Valley's lake -- inside a sandy bank. Its texture,
pondwat.tex, is generated like everything else here (no game art ships with the track). Solid ones get .sol spheres (hydrants, trees, the
yarn ball, the scratching post, tennis balls) or boxes (fence, doghouses, buildings, stalls,
box tunnel walls) -- boxes patched to closed ends (+0x68 = 0).

THE PETS are 36 `obj obstacle ball` records, 4x size, 50 lb, placed where the mockup has them.

    python build_catsdogs.py              build out/CatsDogs.trk
    python build_catsdogs.py --install    ...and install as "Cats vs Dogs" in the hastings slot
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import kit  # noqa: E402  (puts vrmod on sys.path)
from kit import terrain, tracks  # noqa: E402
from kit.art import colourise, tile_noise, to_img, water  # noqa: E402
from kit.shapes import Builder, Palette, tennis_ball, yarn_ball  # noqa: E402
from kit.terrain import Batch, CatmullRom, Line, delaunay, game, smootherstep  # noqa: E402
from kit.terrain import mockup_to_source as src  # noqa: E402
import cvd_models as M  # noqa: E402
from vrmod import archive, ili, trackbuild, trackgen  # noqa: E402

PAL = Palette("cvdtrk.tex")            # this track's own palette NAME (the cars carry acpal/dhpal)
INSTALL = kit.INSTALL
NAME = "Cats vs Dogs"
SLOT = "hastings"                       # "Ridge Valley": 12 letters, exactly the name's width
OUT = HERE / "out" / "CatsDogs.trk"
SEED = 2026
HW = 7.0                                # road half-width
VERGE = 2.0
PET_MASS = 50
TAN35 = math.tan(math.radians(35))
ROOF_SIDE = math.tan(math.radians(78))  # the roof's sides: steep, so they act as rails
WORLD = (-370.0, 370.0, -330.0, 330.0)  # source x0, x1, y0, y1
SUN = np.array([-0.4, 0.3, 0.86]) / np.linalg.norm([-0.4, 0.3, 0.86])

# ---------------------------------------------------------------- the lap (mockup frame)
CTRL = [
    (60, -120), (0, -120), (-60, -120), (-105, -122), (-135, -122), (-150, -122),
    (-188, -122), (-215, -120), (-255, -105), (-283, -65), (-292, -10), (-280, 40),
    (-250, 70), (-225, 95), (-200, 100), (-175, 125), (-150, 135),
    (-120, 155), (-60, 158), (-20, 158), (20, 158),
    (70, 158), (140, 158), (185, 148), (215, 120), (230, 85),
    (235, 50), (235, 15), (232, -20), (222, -55), (212, -80), (200, -100),
    (180, -130), (160, -165), (125, -175), (100, -150), (80, -125),
]
CURVE = CatmullRom(CTRL)                # the same curve the mockup page drew
at_m = CURVE.at
CTRL_S, LAP = CURVE.ctrl_s, CURVE.length
ST_S, ST_XY, ST_T, ST_L = CURVE.stations(1.0)      # 1 m stations, source frame


# ---------------------------------------------------------------- the road's profile
S_FRIS = CTRL_S[5]                     # frisbee lip
S_FRIS_LAND = CTRL_S[6]                # its landing lip, 38 m on
FRIS_H, FRIS_FACE, LAND_H, LAND_RUN = 3.0, 30.0, 1.6, 25.0
S_ROOF0, S_ROOF1 = CTRL_S[25], CTRL_S[27]     # the climb onto the roof
S_ROOF_LIP = CTRL_S[29]
ROOF_H, ROOF_GAP, ROOF_LAND_H, ROOF_LAND_RUN = 7.0, 16.0, 3.5, 30.0
GAPS = [(S_FRIS, S_FRIS_LAND), (S_ROOF_LIP, S_ROOF_LIP + ROOF_GAP)]


def profile(s):
    """Road height at arc length s, and whether it is roof (steep sides)."""
    s %= LAP
    # frisbee kicker
    if S_FRIS - FRIS_FACE <= s <= S_FRIS:
        return FRIS_H * ((s - (S_FRIS - FRIS_FACE)) / FRIS_FACE) ** 1.6, False
    if S_FRIS < s < S_FRIS_LAND:
        back = FRIS_H - (s - S_FRIS) * TAN35
        front = LAND_H - (S_FRIS_LAND - s) * TAN35
        return max(0.0, back, front), False
    if S_FRIS_LAND <= s <= S_FRIS_LAND + LAND_RUN:
        return LAND_H * (1 - smootherstep((s - S_FRIS_LAND) / LAND_RUN)), False
    # the roof
    if S_ROOF0 <= s < S_ROOF1:
        return ROOF_H * smootherstep((s - S_ROOF0) / (S_ROOF1 - S_ROOF0)), True
    if S_ROOF1 <= s <= S_ROOF_LIP:
        return ROOF_H, True
    land = S_ROOF_LIP + ROOF_GAP
    if S_ROOF_LIP < s < land:
        back = ROOF_H - (s - S_ROOF_LIP) * TAN35
        front = ROOF_LAND_H - (land - s) * TAN35
        return max(0.0, back, front), back > 0.0
    if land <= s <= land + ROOF_LAND_RUN:
        return ROOF_LAND_H * (1 - smootherstep((s - land) / ROOF_LAND_RUN)), False
    return 0.0, False


def in_gap(s):
    s %= LAP
    return any(a < s < b for a, b in GAPS)


ST_Z = np.array([profile(s)[0] for s in ST_S])
ST_ROOF = np.array([profile(s)[1] for s in ST_S])


POND_C = (-170.0, -20.0)                # source frame
POND_DEPTH, POND_BANK, POND_SAND = 0.4, 2.0, 5.0


def pond_sd(x, y):
    """Signed distance to the bone: a 60 x 12 m bar with two 9 m knuckles at each end."""
    px, py = np.asarray(x, float) - POND_C[0], np.asarray(y, float) - POND_C[1]
    qx, qy = np.abs(px) - 30.0, np.abs(py) - 6.0
    bar = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)
    d = bar
    for kx in (-30.0, 30.0):
        for ky in (-7.0, 7.0):
            d = np.minimum(d, np.hypot(px - kx, py - ky) - 9.0)
    return d


def pond_z(x, y):
    """The water 0.4 m down inside the bone, a bank up to the lawn over 2 m, else None."""
    d = pond_sd(x, y)
    bank = -POND_DEPTH * (1 - np.clip(d / POND_BANK, 0, 1))
    return np.where(d <= 0, -POND_DEPTH, np.where(d < POND_BANK, bank, np.inf))


def pond_points():
    """The bone's outline (water's edge), the bank's top and the sand's edge, plus its inside."""
    pts = []
    for off in (0.0, POND_BANK, POND_SAND):
        for k in range(64):
            a = 2 * math.pi * k / 64
            for kx in (-30.0, 30.0):
                for ky in (-7.0, 7.0):
                    x, y = POND_C[0] + kx + (9 + off) * math.cos(a), POND_C[1] + ky + (9 + off) * math.sin(a)
                    if abs(float(pond_sd(x, y)) - off) < 0.05:
                        pts.append((x, y))
        for t in np.arange(-30, 30.01, 2.0):
            for sy in (-1, 1):
                x, y = POND_C[0] + t, POND_C[1] + sy * (6 + off)
                if abs(float(pond_sd(x, y)) - off) < 0.05:
                    pts.append((x, y))
    for gx in np.arange(-40, 40.01, 6.0):
        for gy in np.arange(-16, 16.01, 6.0):
            x, y = POND_C[0] + gx, POND_C[1] + gy
            if float(pond_sd(x, y)) < -2.0:
                pts.append((x, y))
    return pts


def locate_many(P):
    """(s, lat, station index) for an (n, 2) array of source points."""
    P = np.asarray(P, float)
    idx = np.empty(len(P), int)
    for a in range(0, len(P), 2000):
        d = ((P[a:a + 2000, None, :] - ST_XY[None, :, :]) ** 2).sum(-1)
        idx[a:a + 2000] = d.argmin(1)
    rel = P - ST_XY[idx]
    along = (rel * ST_T[idx]).sum(1)
    lat = (rel * ST_L[idx]).sum(1)
    return (ST_S[idx] + along) % LAP, lat, idx


def heights(P):
    s, lat, idx = locate_many(P)
    z = np.array([profile(v)[0] for v in s])
    roof = np.array([profile(v)[1] for v in s])
    edge = np.where(roof, HW + 3.0, HW + VERGE)
    slope = np.where(roof, ROOF_SIDE, TAN35)
    out = np.maximum(0.0, z - np.maximum(0.0, np.abs(lat) - edge) * slope)
    P = np.asarray(P, float)
    out = np.minimum(out, pond_z(P[:, 0], P[:, 1]))
    return out, s, lat


def height(x, y):
    return float(heights([(x, y)])[0][0])


# ---------------------------------------------------------------- textures
def _uv(size):
    return np.arange(size)[None, :] / size, np.arange(size)[:, None] / size


def road_tex(kerb, size=256, seed=11):
    """u across the road, v along it every 20 m: asphalt, a white edge line, and kerbs that
    alternate kerb colour and white every 5 m."""
    u, v = _uv(size)
    img = colourise(tile_noise(size, 16, 3, 0.5, seed), (56, 58, 62), (80, 82, 88)).astype(np.float32)
    kb = (u < 0.06) | (u > 0.94)
    alt = ((v * 4) % 1.0) < 0.5
    col = np.where(np.broadcast_to(alt, img.shape[:2])[..., None], np.array(kerb, np.float32),
                   np.array([238, 236, 230], np.float32))
    img = np.where(np.broadcast_to(kb, img.shape[:2])[..., None], col, img)
    line = (np.abs(u - 0.085) < 0.008) | (np.abs(u - 0.915) < 0.008)
    img[np.broadcast_to(line, img.shape[:2])] = [228, 228, 222]
    return to_img(img)


def grass_tex(size=256, seed=21):
    """Tiled every 32 m: soft low-contrast lawn with faint mowing stripes."""
    u, v = _uv(size)
    img = colourise(tile_noise(size, 8, 4, 0.5, seed), (92, 150, 70), (116, 170, 84)).astype(np.float32)
    stripe = 0.96 + 0.06 * np.sin(np.pi * 4 * u)
    return to_img(img * np.broadcast_to(stripe, img.shape[:2])[..., None])


def paving_tex(size=256, seed=31):
    """Tiled every 32 m: lavender-grey paving with soft 8 m slab seams."""
    u, v = _uv(size)
    img = colourise(tile_noise(size, 8, 4, 0.5, seed), (150, 142, 164), (170, 162, 182)).astype(np.float32)
    du = np.minimum((u * 4) % 1.0, 1 - (u * 4) % 1.0)
    dv = np.minimum((v * 4) % 1.0, 1 - (v * 4) % 1.0)
    seam = np.exp(-(np.minimum(du, dv) / 0.03) ** 2)
    return to_img(img * (1 - 0.12 * seam)[..., None])


def side_tex(size=128, seed=41):
    """Steep faces -- building walls and ramp backs: warm brick courses."""
    u, v = _uv(size)
    img = colourise(tile_noise(size, 8, 3, 0.5, seed), (140, 82, 66), (164, 100, 80)).astype(np.float32)
    row = (v * 8) % 1.0
    off = (np.floor(v * 8) % 2) * 0.5
    col = ((u * 4 + off) % 1.0)
    mortar = (row < 0.08) | (col < 0.04)
    img[np.broadcast_to(mortar, img.shape[:2])] = [196, 186, 170]
    return to_img(img)


def check_tex(size=64):
    a = np.zeros((size, size, 3), np.uint8)
    for j in range(size):
        for i in range(size):
            a[j, i] = 245 if ((i // 8) + (j // 8)) % 2 else 20
    return Image.fromarray(a)


def day_sky(w=1024, h=512, seed=7):
    y = np.linspace(0, 1, h)[:, None, None]
    top, horizon = np.array([70, 130, 210], np.float32), np.array([190, 215, 240], np.float32)
    img = top * (1 - y) + horizon * y
    img = np.broadcast_to(img, (h, w, 3)).copy()
    n = tile_noise(w, 16, 5, 0.55, seed)[:h, :w]
    cloud = np.clip((n - 0.55) * 3.0, 0, 1) * (1 - np.linspace(0, 1, h)[:, None] ** 3)
    img = img * (1 - cloud[..., None]) + np.array([250, 250, 252], np.float32) * cloud[..., None]
    return Image.fromarray(np.clip(img, 8, 255).astype(np.uint8))


def sand_tex(size=128, seed=61):
    return to_img(colourise(tile_noise(size, 8, 4, 0.5, seed), (206, 190, 150), (226, 212, 176)))


TEXTURES = {"pondwat.tex": water, "sand.tex": sand_tex, "roaddog.tex": lambda: road_tex((210, 52, 40)), "roadcat.tex": lambda: road_tex((122, 79, 192)),
            "grass.tex": grass_tex, "paving.tex": paving_tex, "side.tex": side_tex, "chequer.tex": check_tex}


# ---------------------------------------------------------------- the ground
def floor_points(rng):
    pts = []
    s = 0.0
    while s < LAP:
        z, roof = profile(s)
        busy = z > 0.0 or in_gap(s) or any(abs(s - a) < 6 or abs(s - b) < 6 for a, b in GAPS)
        step = 1.0 if busy else 4.0
        k = int(s) % len(ST_S)
        p, l = ST_XY[k] + ST_T[k] * (s - ST_S[k]), ST_L[k]
        lats = [-HW - VERGE - 2, -HW - VERGE, -HW, -HW / 2, 0.0, HW / 2, HW, HW + VERGE, HW + VERGE + 2]
        if z > 0.05:
            edge = HW + (3.0 if roof else VERGE)
            slope = ROOF_SIDE if roof else TAN35
            for d in (edge, edge + z / slope * 0.5, edge + z / slope, edge + z / slope + 1.5):
                lats += [d, -d]
        for lat in sorted(set(round(v, 3) for v in lats)):
            pts.append((float(p[0] + l[0] * lat), float(p[1] + l[1] * lat)))
        s += step
    road = np.array(pts)
    x0, x1, y0, y1 = WORLD
    for gx in np.arange(x0, x1 + 1, 34.0):
        for gy in np.arange(y0, y1 + 1, 34.0):
            onrim = gx in (x0, x1) or gy in (y0, y1)
            px = gx if onrim else gx + rng.uniform(-5, 5)
            py = gy if onrim else gy + rng.uniform(-5, 5)
            if not onrim and np.hypot(road[:, 0] - px, road[:, 1] - py).min() < 7:
                continue
            if float(pond_sd(px, py)) < POND_SAND + 4:
                continue
            pts.append((float(px), float(py)))
    # the fence line: keep the ground flat and split cleanly along x = 0
    for gy in np.arange(y0, y1 + 1, 10.0):
        if np.hypot(road[:, 0], road[:, 1] - gy).min() > 6:
            pts.append((0.0, float(gy)))
    pts += pond_points()
    uniq = {}
    for p in pts:
        uniq.setdefault((round(p[0], 2), round(p[1], 2)), p)
    return list(uniq.values())


def build_floor(scene, rng):
    pts = floor_points(rng)
    tris = delaunay(pts)
    Z, S, LATS = heights(pts)
    batches = {k: Batch(scene, k[:5], t, True) for k, t in (
        ("roaddog", "roaddog.tex"), ("roadcat", "roadcat.tex"), ("grass", "grass.tex"),
        ("paving", "paving.tex"), ("sidew", "side.tex"), ("sand", "sand.tex"))}
    batches["water"] = Batch(scene, "water", "pondwat.tex", True, code=trackgen.WATER)
    counts = {k: 0 for k in batches}
    for t in tris:
        P = [(pts[i][0], pts[i][1], float(Z[i])) for i in t]
        cx, cy = sum(p[0] for p in P) / 3, sum(p[1] for p in P) / 3
        cz, cs, clat = heights([(cx, cy)])
        cs, clat = float(cs[0]), float(clat[0])
        a, b, c = (np.array(p) for p in P)
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        steep = abs(n[2]) / ln < math.cos(math.radians(40))
        psd = float(pond_sd(cx, cy))
        if psd < 0 and all(p[2] <= -POND_DEPTH + 1e-6 for p in P):
            batches["water"].tri(P, [(p[0] / 16.0, p[1] / 16.0) for p in P], 0.95)
            counts["water"] += 1
            continue
        if psd < POND_SAND:
            batches["sand"].tri(P, [(p[0] / 16.0, p[1] / 16.0) for p in P], 0.92)
            counts["sand"] += 1
            continue
        if abs(clat) <= HW and not in_gap(cs) and not steep:
            kind = "roaddog" if cx < 0 else "roadcat"
            uv = []
            for i in t:
                sp = float(S[i])
                if abs(sp - cs) > LAP / 2:
                    sp += LAP if sp < cs else -LAP
                uv.append((min(0.98, max(0.02, (float(LATS[i]) + HW) / (2 * HW))), sp / 20.0))
        elif steep:
            kind = "sidew"
            uv = [((p[0] + p[1]) / 8.0, -p[2] / 4.0) for p in P]
        else:
            kind = "grass" if cx < 0 else "paving"
            uv = [(p[0] / 32.0, p[1] / 32.0) for p in P]
        batches[kind].tri(P, uv, 0.92 if kind != "sidew" else 0.8)
        counts[kind] += 1
    for bt in batches.values():
        bt.flush()
    return counts


# ---------------------------------------------------------------- props
class Props:
    """Low-poly props from cvd_models.Builder (mockup frame), drawn with the palette, plus
    their collision: spheres onto the scene, boxes kept for after assembly."""

    def __init__(self, scene):
        self.scene = scene
        self.batch = Batch(scene, "prop", PAL.name, False)
        self.boxes = []                   # (a, b, height, thickness), source frame, base z in a/b
        self.tris = 0

    def add(self, builder: Builder, ground=None):
        for a, b, c, col in builder.tris:
            P = [src(*p) for p in (a, b, c)]
            if ground is not None:
                P = [(p[0], p[1], p[2] + ground) for p in P]
            A, Bv, C = (np.array(p) for p in P)
            n = np.cross(Bv - A, C - A)
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            n = n / ln
            cen = (A + Bv + C) / 3
            uv = [PAL.uv(col)] * 3
            grey = 0.62 + 0.38 * max(0.0, float(n @ SUN))
            self.batch.tri(P, uv, grey, up=tuple(cen + n))
            self.tris += 1

    def sphere(self, mx, my, mz, r):
        self.scene.spheres.append((src(mx, my, mz), r))

    def box(self, m_a, m_b, base, h, thick):
        a, b = src(m_a[0], base, m_a[1]), src(m_b[0], base, m_b[1])
        self.boxes.append((a, b, h, thick))

    def footprint(self, mx, mz, w, d, ry, base, h):
        """A w x d box centred at (mx, mz), turned ry about up (three.js sense)."""
        ax, az = math.sin(ry), math.cos(ry)        # local +z after the turn
        self.box((mx - ax * d / 2, mz - az * d / 2), (mx + ax * d / 2, mz + az * d / 2), base, h, w)

    def flush(self):
        self.batch.flush()


def ry_of(t):
    return math.atan2(t[0], t[1])                 # JS: Math.atan2(tg.x, tg.z)


def build_props(scene, rng):
    pr = Props(scene)
    W = Builder()

    # --- the border fence, with openings at the two crossings
    for z in range(-330, 330, 4):
        if abs(z + 120) < 12 or abs(z - 158) < 12:
            continue
        W.box([0, 2.5, z], [.6, 5, 3.6], "#b98a57" if (z // 4) % 2 else "#a57946")
        W.pyr([0, 5, z], [.6, 1, 3.6], "#a57946")
    for z0, z1 in ((-330, -132), (-108, 146), (170, 330)):
        pr.box((0, z0), (0, z1), 0.0, 5.0, 0.6)
    # start gate arch: dog face red, cat face purple
    for k in (1, -1):
        W.box([0, 6, -120 + k * (HW + 2)], [2.4, 12, 2.4], "#3b4652")
        pr.box((0, -120 + k * (HW + 2) - 1.2), (0, -120 + k * (HW + 2) + 1.2), 0.0, 12.0, 2.4)
    W.box([-.7, 12.5, -120], [1.4, 3, 2 * HW + 7], "#d23c2a")
    W.box([.7, 12.5, -120], [1.4, 3, 2 * HW + 7], "#7a4fc0")
    # the cat flap: a frame and the flap swung up
    for k in (1, -1):
        W.box([0, 6, 158 + k * (HW + 1.5)], [2, 12, 2], "#e6e1d8")
        pr.box((0, 158 + k * (HW + 1.5) - 1), (0, 158 + k * (HW + 1.5) + 1), 0.0, 12.0, 2.0)
    W.box([0, 12.5, 158], [2, 2, 2 * HW + 5], "#e6e1d8")
    W.box([3.5, 10.5, 158], [.4, 8, 2 * HW], "#9b7ad6", r=(0, 0, -.9))
    # the start line marks and a gate sign are in add_start_line

    # --- dog country
    (lx, lz), _t, _l = at_m(5, 0, -16)                       # the giant frisbee at the lip
    W.cyl([lx, 0, lz], .5, 9, "#777777", n=6)
    W.cyl([lx, 9, lz], 9, 1.2, "#e8452c", n=14, rad2=7.5, c2="#ff7a5c", rot=(.5, 0, .2))
    for i, (sg, f, o) in enumerate(((8, .5, -24), (9, .2, -24), (9, .6, -24), (10, .3, -24), (10, .8, -24),
                                    (9, .4, 26), (10, .5, 24))):
        (x, z), t, _l = at_m(sg, f, o)
        ry = ry_of(t)
        col = ["#c0392b", "#2e86c1", "#d68910", "#229954"][i % 4]
        W.box([x, 3, z], [9, 6, 9], col, r=(0, ry, 0))
        W.box([x, 8, z], [10, 4, 10], "#5d4037", top=(.05, 1), r=(0, ry, 0))
        W.box([x, 2, z], [3.5, 4, 9.2], "#2b2b2b", r=(0, ry, 0))
        pr.footprint(x, z, 9, 9, ry, 0.0, 6.0)
    for sg, f, o in ((12, .6, -4), (13, .2, 4), (13, .8, -4), (14, .4, 4), (15, .1, -4), (15, .7, 4), (16, .3, -4)):
        (x, z), _t, _l = at_m(sg, f, o)                      # hydrants in the road
        W.cyl([x, 0, z], 1.1, 3.2, "#d7261e", n=8)
        W.cyl([x, 3.2, z], 1.3, 1, "#b81f18", n=8, rad2=.6)
        for k in (1, -1):
            W.box([x + k * 1.3, 2.2, z], [.8, .6, .6], "#b81f18")
        pr.sphere(x, 1.2, z, 1.3)
        pr.sphere(x, 2.8, z, 1.2)
    W.cyl([-95, 0, 65], 11, 5, "#c3c9d1", n=16, rad2=14, c2="#8b5a2b")    # the dog bowl
    for k in range(8):
        a = k * math.pi / 4
        pr.footprint(-95 + 11.5 * math.sin(a), 65 + 11.5 * math.cos(a), 9.5, 1.5, a + math.pi / 2, 0.0, 5.0)
    # trees
    road = ST_XY
    n_tree = 0
    while n_tree < 70:
        x, z = -30 - rng.random() * 320, -310 + rng.random() * 620
        sx, sy = src(x, 0, z)[:2]
        if np.hypot(road[:, 0] - sx, road[:, 1] - sy).min() < 16 or math.hypot(x + 170, z - 20) < 42 \
                or math.hypot(x + 95, z - 65) < 20:
            continue
        h = 10 + rng.random() * 8
        W.cyl([x, 0, z], .8, h * .35, "#6d4c33", n=5)
        W.cyl([x, h * .3, z], 4 + rng.random() * 2, h * .75, "#3e8e41" if n_tree % 3 else "#2f7a3a", n=6, rad2=.2)
        pr.sphere(x, 1.0, z, 1.0)
        n_tree += 1
    for k in range(8):                                        # tennis balls, solid
        x, z = -130 - rng.random() * 90, -40 + rng.random() * 40
        bt = tennis_ball(2.6)
        W.tris += [(tuple(p[0] + x for p in [a]) + (a[1] + 2.6, a[2] + z), (b[0] + x, b[1] + 2.6, b[2] + z),
                    (c[0] + x, c[1] + 2.6, c[2] + z), col) for a, b, c, col in bt.tris]
        pr.sphere(x, 2.6, z, 2.6)

    # --- cat country
    f = .02
    while f < 1:                                              # the cardboard box tunnel
        (x, z), t, l = at_m(21, f)
        ry = ry_of(t)
        for k in (1, -1):
            sx_, sz_ = x + l[0] * k * (HW + 3.5), z + l[1] * k * (HW + 3.5)
            W.box([sx_, 4, sz_], [6, 8, 7], "#c49a6c" if k > 0 else "#b5895b", r=(0, ry, 0))
            pr.footprint(sx_, sz_, 6, 7, ry, 0.0, 8.0)
        if round(f * 10) % 2 == 0:
            W.box([x, 8.4, z], [2 * HW + 13, .8, 7], "#d2a877", r=(0, ry, 0))
        f += .1
    for i, (sg, fr) in enumerate(((23, .2), (23, .5), (23, .8), (24, .2), (24, .55))):
        (x, z), t, _l = at_m(sg, fr, -16)                      # fish stalls
        ry = ry_of(t)
        W.box([x, 1.6, z], [8, 3.2, 4], "#e6e1d8", r=(0, ry, 0))
        W.box([x, 5.5, z], [9, .6, 5], "#2a9d8f" if i % 2 else "#e76f51", r=(0, ry, 0))
        W.box([x, 3.4, z], [6, .6, 1.6], "#9fc3d4", r=(0, ry, .3))
        for k in (1, -1):
            W.box([x + math.cos(ry) * k * 4, 2.8, z - math.sin(ry) * k * 4], [.3, 5.6, .3], "#777777")
        pr.footprint(x, z, 8, 4, ry, 0.0, 3.2)
    # rooftop furniture: chimneys and vents along the roof's edges
    for sg in (26, 27, 28):
        for fr in (.3, .8):
            (x, z), t, l = at_m(sg, fr)
            sx, sy = src(x, 0, z)[:2]
            gz = height(sx, sy)
            if gz < 6.5:
                continue
            for k in (1, -1):
                px, pz = x + l[0] * k * (HW + 2.2), z + l[1] * k * (HW + 2.2)
                W.box([px, gz + 1.0, pz], [1.4, 2.0, 1.4], "#7d6e8f")
    # skyline and city blocks (solid)
    for i in range(26):
        x, z, h = 270 + rng.random() * 80, -300 + i * 24, 10 + rng.random() * 28
        w = 18 + rng.random() * 10
        W.box([x, h / 2, z], [w, h, 18], ["#6f6483", "#8a7f99", "#5b5470", "#7b6a7f"][i % 4])
        for row in range(int(h // 4)):                         # window bands
            W.box([x - w / 2 - .05, 2.5 + row * 4, z], [.1, 1.2, 14], "#e8d9a8" if (row + i) % 3 else "#3c5866")
        pr.footprint(x, z, w, 18, 0.0, 0.0, h)
    for i in range(14):
        x, z = 40 + rng.random() * 90, -300 + rng.random() * 100
        W.box([x, 8, z], [16, 16, 16], "#7b6a7f")
        pr.footprint(x, z, 16, 16, 0.0, 0.0, 16.0)
    cx, cz = 138, -142                                         # the scratching-post tower
    W.cyl([cx, 0, cz], 9, 1.5, "#c9b79c", n=10)
    W.cyl([cx, 1.5, cz], 5, 40, "#d9c49b", n=10)
    for y in range(4, 40, 5):
        W.cyl([cx, y, cz], 5.3, 1.3, "#a8865a", n=10)
    W.box([cx, 20, cz], [18, 1.2, 14], "#8e6fc4")
    W.box([cx, 41.5, cz], [16, 3, 16], "#8e6fc4")
    W.box([cx + 7, 32, cz], [.3, 9, .3], "#eeeeee")
    W.box([cx + 7, 27, cz], [1.6, 1.6, 1.6], "#e8452c")
    for y in (5.0, 11.0):
        pr.sphere(cx, y, cz, 5.5)
    pr.sphere(cx, 0.0, cz, 9.0)                                # the base disc: a low dome you bounce off
    yb = yarn_ball(20.0)                                  # the giant yarn ball, and its needles
    W.tris += [((a[0] + 125, a[1] + 19, a[2] + 20), (b[0] + 125, b[1] + 19, b[2] + 20),
                (c[0] + 125, c[1] + 19, c[2] + 20), col) for a, b, c, col in yb.tris]
    for k in (1, -1):
        W.cyl([125 + k * 6, 8, 20], .8, 50, "#c7c7c7", n=6, rot=(k * .3, 0, k * .5))
    pr.sphere(125, 19, 20, 20.0)
    for i in range(18):                                        # loose cardboard boxes in the infield
        x, z = 60 + rng.random() * 140, -60 + rng.random() * 160
        sx, sy = src(x, 0, z)[:2]
        if np.hypot(road[:, 0] - sx, road[:, 1] - sy).min() < 14 or math.hypot(x - 125, z - 20) < 26:
            continue
        s_ = 3 + rng.random() * 2
        ry = rng.random() * 3
        W.box([x, s_ / 2, z], [s_, s_, s_], "#c49a6c", r=(0, ry, 0))
        W.box([x, s_ + .05, z], [s_ * 1.02, .1, s_ * .3], "#a57946", r=(0, ry, 0))
        pr.footprint(x, z, s_, s_, ry, 0.0, s_)

    pr.add(W)
    pr.flush()
    return pr


def add_start_line(scene, s0):
    b = Batch(scene, "startln", "chequer.tex", False)
    k = int(s0) % len(ST_S)
    p, t, l = ST_XY[k], ST_T[k], ST_L[k]
    q = [(p[0] + l[0] * lat + t[0] * d, p[1] + l[1] * lat + t[1] * d, 0.05)
         for lat, d in ((-HW, -1.5), (-HW, 1.5), (HW, 1.5), (HW, -1.5))]
    uv = [(0.02, 0.02), (0.98, 0.02), (0.98, 0.98), (0.02, 0.98)]
    b.tri(q[:3], uv[:3], 1.0)
    b.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 1.0)
    b.flush()


# ---------------------------------------------------------------- pets
def pet_records():
    placed = []

    def put(_sec, pid, seg, frac, off, face=None):
        (x, z), t, _l = at_m(seg, frac, off)
        placed.append((pid, x, z, t, face))
    put(0, "corgi", 2, .5, -5); put(0, "corgi", 2, .7, 5)
    put(1, "lab", 7, .35, -5); put(1, "lab", 7, .6, 5); put(1, "corgi", 7, .85, 4)
    put(2, "dachs", 8, .5, -5); put(2, "dachs", 9, .3, -4); put(2, "corgi", 9, .8, 4); put(2, "lab", 10, .5, -5)
    put(3, "corgi", 12, .5, 3); put(3, "dachs", 13, .6, -3); put(3, "lab", 15, .4, 4)
    for i, (f, o) in enumerate(((.7, 0), (.77, -2.6), (.77, 2.6), (.84, -5.2), (.84, 0), (.84, 5.2))):
        put(4, "dachs" if i % 2 else "corgi", 17, f, o, "back")
    put(5, "tabby", 20, .6, -4); put(5, "blkcat", 20, .75, 4)
    put(6, "loaf", 21, .3, 0); put(6, "blkcat", 21, .6, -4); put(6, "tabby", 21, .85, 4); put(6, "loaf", 22, .5, -3)
    put(7, "tabby", 23, .4, -5); put(7, "blkcat", 23, .8, -5); put(7, "loaf", 24, .5, 5)
    put(8, "blkcat", 27, .3, -5); put(8, "tabby", 27, .5, 5); put(8, "loaf", 27, .75, -4)
    put(8, "blkcat", 28, .2, 5); put(8, "tabby", 28, .5, 0)
    put(9, "loaf", 32, .5, 5); put(9, "tabby", 33, .2, 5); put(9, "blkcat", 33, .7, 5); put(9, "tabby", 34, .4, 5)
    rng = random.Random(7)
    recs = []
    for pid, x, z, t, face in placed:
        sx, sy, _ = src(x, 0, z)
        gt = game((t[0], -t[1], 0.0))
        heading = math.degrees(math.atan2(gt[0], gt[2]))
        rot = (heading + 180) if face == "back" else rng.uniform(0, 360)
        recs.append((pid, rot % 360, (sx, sy)))
    return recs


# ---------------------------------------------------------------- menu picture
def menu_picture():
    w, h = 180, 120
    im = Image.new("RGB", (w, h), (116, 170, 84))
    d = ImageDraw.Draw(im)
    x0, x1, y0, y1 = WORLD

    def px(x, y):
        return ((x - x0) / (x1 - x0) * w, (1 - (y - y0) / (y1 - y0)) * h)
    d.rectangle([w / 2, 0, w, h], fill=(164, 156, 178))
    pts = [px(*p) for p in ST_XY[::4]]
    d.line(pts + [pts[0]], fill=(60, 62, 68), width=5)
    d.line([px(0, y0), px(0, y1)], fill=(165, 121, 70), width=2)
    d.text((8, 6), "DOGS", fill=(200, 50, 40))
    d.text((w - 40, 6), "CATS", fill=(110, 70, 180))
    return im


# ---------------------------------------------------------------- build
def main():
    rng = random.Random(SEED)
    s0 = CTRL_S[1] + 40.0                                    # the start line, 40 m past the gate (westward)
    step = LAP / int(LAP // 8)
    centre = []
    s = s0
    for k in range(int(LAP // 8)):
        kk = int(s % LAP) % len(ST_S)
        p = ST_XY[kk] + ST_T[kk] * ((s % LAP) - ST_S[kk])
        centre.append((float(p[0]), float(p[1]), float(profile(s)[0])))
        s += step
    scene = trackgen.TrackScene(centreline=centre)
    line = Line(centre)
    trackgen.add_checkpoints(scene, 4, half_width=HW + 3.0)
    grid = []
    for k in range(8):
        (gx, gy, gz), (tx, ty) = line.at(line.L - 16.0 - 10.0 * (k // 2))
        lat = 3.5 if k % 2 else -3.5
        grid.append((gx - ty * lat, gy + tx * lat, 0.0))
    scene.grid = grid
    x0, x1, y0, y1 = WORLD
    corners = [(x0 + 2, y0 + 2), (x1 - 2, y0 + 2), (x1 - 2, y1 - 2), (x0 + 2, y1 - 2)]
    scene.walls = []
    for a, b in zip(corners, corners[1:] + corners[:1]):          # the world's edge: 6 m walls
        n = int(math.hypot(b[0] - a[0], b[1] - a[1]) // 60) + 1
        for k in range(n):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            q = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
            scene.walls.append([(p[0], p[1], 0.0), (q[0], q[1], 0.0), (q[0], q[1], 6.0), (p[0], p[1], 6.0)])

    counts = build_floor(scene, rng)
    add_start_line(scene, s0)
    pr = build_props(scene, rng)
    for n in M.PETS:
        M.pet(n).mesh(PAL)                                         # every pet colour into the palette

    names = [o.name for o in scene.driveables + scene.scenery]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate mesh names")
    drawn = [nm for nm in names if nm in scene.meshes]
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables)
    print(f"lap {LAP:.0f} m; floor {counts}; props {pr.tris} tris; largest chunk {biggest} verts; "
          f"collision triangles {collide}; surfaces {len(drawn)}; spheres {len(scene.spheres)}, "
          f"boxes {len(pr.boxes)}; textures {sorted(wanted)}")
    if biggest > terrain.MAX_VERTS or collide > 16500 or len(drawn) > 500:
        raise SystemExit("over budget")

    OUT.parent.mkdir(exist_ok=True)
    corridor = ili.corridor_for(2 * HW)
    res = trackbuild.assemble(scene, donor=kit.DONOR_TRACK, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True, corridor=corridor)
    print(f"assembled: {res.summary()}")
    ent = archive.read(OUT)
    by = tracks.by_name(ent)
    for name in sorted(wanted):
        if name == PAL.name:
            tracks.set_member(by[name], PAL.tex_bytes(wrap=0))
        else:
            tracks.set_member(by[name], tracks.image_tex(TEXTURES[name]()))
    tracks.set_sky(ent, day_sky())
    spots = []
    for k in range(8):                                           # trackside cameras round the lap
        i = int(k * LAP / 8)
        p, l, z0 = ST_XY[i], ST_L[i], float(ST_Z[i])
        spots.append(((p[0] + l[0] * 30, p[1] + l[1] * 30, z0 + 12.0), (p[0], p[1], z0 + 1.0)))
    tracks.cameras(ent, spots)
    n_solids = tracks.add_boxes(ent, pr.boxes)
    pets = pet_records()
    for pid, _rot, (sx, sy) in pets:
        hz = height(sx, sy)
        if hz not in (0.0, ROOF_H):
            print(f"   note: {pid} at ({sx:.0f}, {sy:.0f}) stands on a slope ({hz:.2f} m)")
    n_obj = tracks.add_obstacles(ent, {f"{n}.mod": M.pet(n).mesh(PAL) for n in M.PETS},
                                 [(f"{pid}.mod", sx, sy, rot, PET_MASS, "ball") for pid, rot, (sx, sy) in pets])
    tra = tracks.finish(ent, OUT, NAME, menu=menu_picture())
    menu_picture().resize((540, 360), Image.NEAREST).save(HERE / "out" / "catsdogs-menu.png")
    print(f"{OUT.name}: {n_solids} solids ({len(pr.boxes)} boxes), {len(pets)} pets, {n_obj} placed objects, "
          f"{OUT.stat().st_size:,} bytes -> {tra.name}")
    if "--install" in sys.argv:
        print(tracks.install(tra, SLOT))


if __name__ == "__main__":
    main()
