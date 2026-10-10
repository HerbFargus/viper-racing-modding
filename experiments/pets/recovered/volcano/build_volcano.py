"""Volcano: climb the south flank, jump the summit crater, careen down the north side,
and loop home through the valley round its base.

THE JUMP IS THE CRATER. There is no ramp: the flank steepens toward the summit
(z = HR * ((RB - r) / (RB - RR)) ** P, P chosen so the slope at the rim is 15 degrees)
and the road runs straight up it to the rim, which is the lip. 60 m of crater later
the far rim falls away at the same angle -- a natural landing hill -- and the road
picks up again down the north flank.

THE CRATER is a lava lake (surface code 14: the car floats, as on water) 18 m below
the rim, with steep hot-rock walls. It is BREACHED to the north-east: a trench cut
from the lake's shore through the rim and down the flank, floor just above the
lava, so a car that falls in can float to the shore, drive out and down the ash
to the descent road. Falling in costs time; it does not trap you.

THE ROAD looks like dirt (dirtrd.tex: ruts, gravel, crumbling edges) but is coded
asphalt (0), so it grips like a road. Ash verges beside it.

ONE TRIANGULATION. Road points (stations x lateral offsets), a jittered terrain
lattice kept clear of the road, dense rings round the crater and the breach, and
the lava pools are triangulated together (Delaunay, in plan), so the road, the
flanks, the crater walls and the lava share edges exactly: no cracks, and no point
carries two surfaces. Each triangle is then classed by what it covers. Everything
is drivable -- the flanks are ash (dirt drag), so off the road you slow, you do
not fall through the world.

THE SET PIECE (dragon_set.py): a burninating dragon on the north-west rim breathes one
expanding fireball whose leading mass sits on the jump's arc -- drawn only, so the car
flies through it -- and three burning monks stand on the level shelf of the east rim as
`obj obstacle cube` records, there to be knocked into the lava.

Solo only. Baked grey light from a low western sun; the glow is in the textures.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "circuit"))
sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
import build_circuit as bc  # noqa: E402
import volcano_art as art  # noqa: E402
import dragon_set as ds  # noqa: E402
from build_river import delaunay  # noqa: E402
from vrmod import archive, camtab, envelope, mod, sky, sol, tex, trackbuild, trackgen, trackmap  # noqa: E402
from vrmod import ili  # noqa: E402
from vrmod import obt as obt_mod  # noqa: E402
from vrmod.trackgen import DIRT, GRASS, NO_COLLISION, ROAD, WATER  # noqa: E402

OUT = HERE / "volcano.trk"
SLOT = "nfield"
SEED = 1883                                         # Krakatoa
# the volcano (source frame: x east, y north, z up), centred a little off the origin
CX, CY = 0.0, 3.3
HR, RR = 170.0, 30.0                                # rim height, rim radius (60 m across)
RB, CONE_P = 480.0, 1.3                             # the cone: base radius, profile exponent (26 deg at the rim)
LIP = math.tan(math.radians(15.0))                  # the spurs meet the rim at 15 degrees: the jump's angle
SPUR_D = 900.0                                      # spur length from the rim to the plain
SPUR_Q = LIP * SPUR_D / HR                          # spur profile exponent (1.42)
SPURS = {"south": (-1, 14.0, 0.75), "north": (1, 92.0, 0.6)}   # direction along y, crest half-width, side slope
RB_PLAIN = SPUR_D + RR                              # where the land is flat again
RL, LZ = 17.0, HR - 18.0                            # lava lake radius and level
BREACH = math.radians(55.0)                         # the breach faces north-east
BW = 7.0                                            # breach trench half-width
# the road
HW, VW, CLEAR = 9.0, 3.5, 7.0                       # road half-width, ash verge, lattice clearance
STEP = 8.0
CTRL = [(0, -960), (0, -700), (0, -400), (0, -100), (0, 0), (0, 100), (0, 180), (48, 262), (72, 342),
        (28, 422), (-52, 500), (-40, 590), (28, 680), (56, 770), (4, 860), (-14, 950), (70, 1050),
        (300, 1080), (560, 980), (770, 770), (890, 480), (910, 160), (870, -160), (770, -470), (590, -730),
        (370, -910), (175, -1030), (45, -1068), (-18, -1030)]
POOLS = [(330.0, -330.0, 26.0, "lava"), (-350.0, -250.0, 28.0, "lava"),      # at the foot of the cone
         (520.0, 760.0, 34.0, "pond"), (1060.0, 0.0, 30.0, "pond")]         # in the jungle
MAGMA_R = 4.0                                        # the rolling boulders: 8 m across (the MESH sets the size)
# The obstacle record's last field is MASS, not radius (parse_obstacle 0x463870 stores it in
# the phob data and builds the inertias as size^2 x 10.75 x it). 4.0 made them beach balls;
# the horn ball's own record says 3000. Three horn balls:
MAGMA_MASS = 10000.0
# where they start (source frame): on the climb road below the rim, so they roll down
# it at the cars coming up; on the descent shoulder; and round the summit cone
MAGMA_AT = [(-3.0, -75.0), (4.0, -120.0), (-2.0, -170.0), (3.0, -235.0), (20.0, 120.0), (-25.0, 215.0),
            (-60.0, 45.0), (58.0, -40.0), (-45.0, -62.0), (66.0, 38.0)]
MAX_VERTS, SURFACE_BUDGET, COLLISION_BUDGET = 990, 600, 16500
# the set piece. The car flies north along x = CX from the south lip (y ~ -27) to the landing
# (y ~ +33), peaking ~4 m over the rim mid-crater: the fireball's leading mass sits there.
DRAGON_AT = (CX - 31.0, CY + 13.0)                  # the north-west rim, ahead-left on the climb
DRAGON_S = 1.4                                      # ~21 m tall
FIRE_AT = (CX, CY, HR + 4.0)
FIRE_R = 4.0
# The monks' ledge. The engine DROPS every obstacle from 4 m above the collision surface
# (parse_obstacle: y = TerrainGetHeight(x, z) - mesh min y + 4.0), and the east rim is only a
# crest 4-8 m wide falling away on both sides -- the first build lost all three monks into
# the crater before anyone reached them. So a level pad is carved into the rim: PAD_R across
# flat (dished PAD_DISH, so a bounce settles back to the middle), banked up where it
# overhangs the flank, well back from the crater edge.
PAD = (CX + 48.5, CY + 12.1)                        # 50 m from the crater centre, on the east crest
PAD_R, PAD_DISH, PAD_LEVEL = 14.0, 0.3, HR          # room for the monks and their burning cottage behind them
MONK_FORE = 4.0                                     # the monks stand this far toward the climb from the centre
COTTAGE_BACK = 6.0                                  # the cottage centre this far away from it
JUNGLE_COTTAGES, BURNING_EVERY = 7, 2               # every 2nd jungle cottage is alight
# The respawn detour (see add_respawn_line): track.ild leaves the road at the south lip,
# runs north along a level terrace on the west rim -- beside the lava's whole span,
# clear of the dragon's tail -- and rejoins the road on the north spur. Stations
# 117-125 (the crater crossing and the landing) are what it replaces.
# The detour's straight: x = CX - 50, from beyond the crater's south edge to beyond its
# north edge, so every point in the crater projects onto the middle of it (respawning
# facing north) rather than onto an end.
DETOUR = [(CX - 50.0, CY + y) for y in (-33.3, -30.2, -22.3, -14.4, -6.5, 1.4, 9.3, 17.2, 25.1, 33.0, 36.1)]
DETOUR_SKIP = range(117, 126)                      # road stations the detour stands in for
TERRACE = [(CX - 35.0, CY - 33.9)] + DETOUR       # level: back along the south leg (for step-backs) and all the straight
TERRACE_W, TERRACE_BANK = 7.0, 0.9                 # half-width; how steeply it meets the land
DETOUR_CORRIDOR = 5.0                              # field 5 on the detour: shift 0, off the path past 2.5 m
JPAD_R, JPAD_BANK = 11.0, 0.35                      # a burning jungle cottage's pad, and how steeply it meets the land
JPADS = []                                          # (x, y, level): filled by main() from a first build
FROZEN_SITES = []                                   # the cottage sites that first build chose
JUNGLE_MONKS = []                                   # (x, y, ground, look, yaw) round the jungle cottages
MONK_GAP = 4.5                                      # their collision boxes (3 m square) must not touch
MONK_H = 3.4                                        # the mesh is 3.4 m tall, centred on its origin
MONK_MASS = 200.0                                   # last field of the record: MASS (magma 10000 crushes, 4 floats)
DRAGON_STEMS = {"gscale.tex": "dgscl", "gbelly.tex": "dgbly", "skin.tex": "dgskn", "wing.tex": "dgwng",
                "wingbone.tex": "dgbon", "brow.tex": "dgbrw", "fang.tex": "dgfng",
                "fire1.tex": "dfira", "fire2.tex": "dfirb", "fire3.tex": "dfirc"}
art.ALL.update(ds.TEXTURES)

SUN = np.array([-0.55, -0.40, 0.73]) / np.linalg.norm([-0.55, -0.40, 0.73])


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ the path
def catmull(ctrl, step):
    """Closed Catmull-Rom through ctrl, resampled every `step` metres."""
    n = len(ctrl)
    dense = []
    for i in range(n):
        p0, p1, p2, p3 = (np.array(ctrl[(i + k) % n], float) for k in (-1, 0, 1, 2))
        for t in np.linspace(0, 1, 40, endpoint=False):
            dense.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                                + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    dense = np.array(dense)
    seg = np.linalg.norm(np.roll(dense, -1, axis=0) - dense, axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    L = cum[-1]
    s = np.arange(0, L, step)
    closed = np.vstack([dense, dense[:1]])
    return np.stack([np.interp(s, cum, closed[:, 0]), np.interp(s, cum, closed[:, 1])], axis=1), L


def base_h(x, y, volcanic_only=False):
    """The volcano without its crater: a steep cone, two lava spurs, gullies, the plain."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    r = np.hypot(x - CX, y - CY)
    th = np.arctan2(y - CY, x - CX)
    cone = HR * np.clip((RB - np.maximum(r, RR)) / (RB - RR), 0, 1) ** CONE_P
    gully = 4.0 * np.sin(11 * th + 0.011 * r) * smoothstep(RR + 40, RB * 0.8, r) * smoothstep(RB * 1.05, RB * 0.5, r)
    h = cone + gully
    for sign, crest, side in SPURS.values():
        d = sign * (y - CY) - RR                                 # distance down the spur from the rim
        prof = HR * np.clip(1 - np.maximum(d, 0) / SPUR_D, 0, 1) ** SPUR_Q
        spur = prof - side * np.clip(np.abs(x - CX) - crest, 0, None)
        h = np.maximum(h, np.where(d > -RR, spur, -1e9))
    plain = (5.0 * np.sin(x / 190.0 + 0.7) * np.cos(y / 230.0 - 0.4)
             + 3.0 * np.sin(x / 71.0) * np.sin(y / 93.0 + 1.1)) * smoothstep(RB * 0.9, RB * 1.4, r)
    if volcanic_only:
        return np.maximum(h, 0.0)
    return np.maximum(h, 0.0) + plain


def barren(x, y):
    """On the volcano (bare ash and rock) rather than in the jungle, with a ragged edge."""
    v = base_h(x, y, volcanic_only=True)
    edge = 3.0 + 2.5 * np.sin(np.asarray(x) / 37.0) * np.cos(np.asarray(y) / 41.0)
    return (v > edge) | (np.hypot(np.asarray(x) - CX, np.asarray(y) - CY) < RB)


def full_h(x, y):
    """Terrain with the crater, its breach and the lava pools cut in."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    h = base_h(x, y)
    r = np.hypot(x - CX, y - CY)
    wall = LZ + (HR - LZ) * np.clip((r - RL) / (RR - RL), 0, 1) ** 0.6
    h = np.where(r < RR, wall, h)
    d = np.array([math.cos(BREACH), math.sin(BREACH)])
    along = (x - CX) * d[0] + (y - CY) * d[1]
    perp = np.abs(-(x - CX) * d[1] + (y - CY) * d[0])
    floor = LZ + 0.4 - 0.012 * np.clip(along - RL, 0, None)
    trench = floor + np.clip(perp - BW * 0.55, 0, None) * 1.1
    h = np.where(along > RL - 3, np.minimum(h, trench), h)
    for px, py, pr, _kind in POOLS:
        level = pool_level(px, py)
        rp = np.hypot(x - px, y - py)
        bank = level + np.clip(rp - pr, 0, None) * 0.35
        h = np.where(rp < pr + 40, np.minimum(h, bank), h)
    dt = terrace_dist(x, y)                                        # the respawn terrace
    h = np.where(r > RR + 1, np.where(dt < TERRACE_W, HR,
                                      np.maximum(h, HR - TERRACE_BANK * (dt - TERRACE_W))), h)
    rp = np.hypot(x - PAD[0], y - PAD[1])                         # the monks' ledge
    top = PAD_LEVEL - PAD_DISH * (1 - np.clip(rp / PAD_R, 0, 1) ** 2)
    bank = PAD_LEVEL - 0.9 * np.clip(rp - PAD_R, 0, None)
    h = np.where(rp < PAD_R, top, np.where(r > RR + 1, np.maximum(h, bank), h))
    return h


def pad_apply(x, y, h, road_d):
    """Cut the jungle pads into heights h (already eased onto the road): level and dished
    inside, banked back to the land outside, untouched within the road's verge."""
    x, y, h = np.asarray(x, float), np.asarray(y, float), np.asarray(h, float)
    for px, py, level in JPADS:
        rp = np.hypot(x - px, y - py)
        top = level - PAD_DISH * (1 - np.clip(rp / JPAD_R, 0, 1) ** 2)
        lim = JPAD_BANK * np.clip(rp - JPAD_R, 0, None)
        banked = level + np.clip(h - level, -lim, lim)
        h = np.where(np.asarray(road_d) > HW + VW + 2, np.where(rp < JPAD_R, top, banked), h)
    return h


def terrace_dist(x, y):
    """Distance from (x, y) to the respawn terrace's centre line, vectorised."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    best = np.full(np.broadcast(x, y).shape, np.inf)
    for (ax, ay), (bx, by) in zip(TERRACE, TERRACE[1:]):
        dx, dy = bx - ax, by - ay
        t = np.clip(((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy), 0, 1)
        best = np.minimum(best, np.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


def pool_level(px, py):
    return float(base_h(np.array(px), np.array(py))) - 1.8


def in_pool(x, y):
    """The kind of pool at (x, y) -- "lava" or "pond" -- or None."""
    for px, py, pr, kind in POOLS:
        if math.hypot(x - px, y - py) < pr:
            return kind
    return None


# ------------------------------------------------------------------ geometry
def build(verbose=True):
    rng = random.Random(SEED)
    path, L = catmull(CTRL, STEP)
    n = len(path)
    tang = np.roll(path, -1, axis=0) - np.roll(path, 1, axis=0)
    tang /= np.linalg.norm(tang, axis=1)[:, None]
    norm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)          # left of travel
    rpath = np.hypot(path[:, 0] - CX, path[:, 1] - CY)
    gap = rpath < RR                                             # over the crater: no road
    # road height: the flank, smoothed along the road (never across the gap)
    z0 = base_h(path[:, 0], path[:, 1])
    zc = z0.copy()
    for i in range(n):
        if gap[i]:
            continue
        idx = [(i + k) % n for k in range(-4, 5) if not gap[(i + k) % n]]
        near_crater = rpath[i] < RR + 40
        zc[i] = z0[i] if near_crater else z0[idx].mean()
    # the lips: put a station exactly on each rim so the road ends on the crest
    road_pts, road_uv, road_st = [], [], []
    lats = [-(HW + VW), -HW, 0.0, HW, HW + VW]
    stations = [i for i in range(n) if not gap[i]]
    extra = []
    for i in range(n):
        j = (i + 1) % n
        if gap[i] != gap[j]:                                     # crossing a rim between i and j
            a, b = path[i], path[j]
            ra, rb_ = rpath[i], rpath[j]
            t = (RR - ra) / (rb_ - ra)
            p = a + t * (b - a)
            extra.append((i if not gap[i] else j, p))
    s_of = np.arange(n) * STEP
    for i in stations:
        for lat in lats:
            q = path[i] + norm[i] * lat
            road_pts.append((q[0], q[1], zc[i] - (0.15 if abs(lat) > HW else 0.0)))
            road_uv.append(((lat + HW) / (2 * HW), s_of[i] / 16.0))
            road_st.append((i, lat))
    for i, p in extra:                                           # rim stations
        for lat in lats:
            q = p + norm[i] * lat
            road_pts.append((q[0], q[1], HR - (0.15 if abs(lat) > HW else 0.0)))
            road_uv.append(((lat + HW) / (2 * HW), s_of[i] / 16.0))
            road_st.append((i, lat))
    road_pts = np.array(road_pts)
    nroad = len(road_pts)
    # ---- terrain points
    xs, ys = path[:, 0], path[:, 1]
    x0, x1, y0, y1 = xs.min() - 260, xs.max() + 260, ys.min() - 260, ys.max() + 260
    road_xy = path[stations]
    road_z = zc[stations]
    cand = []
    LAT = 26.0
    for gx in np.arange(x0, x1 + 1, LAT):
        for gy in np.arange(y0, y1 + 1, LAT):
            r = math.hypot(gx - CX, gy - CY)
            if r > RB_PLAIN and (int(round(gx / LAT)) + int(round(gy / LAT))) % 3:
                continue                                          # sparser on the plain
            cand.append((gx + rng.uniform(-4, 4), gy + rng.uniform(-4, 4)))
    n_lattice = len(cand)
    # crater and breach detail
    for rad, k in ((RL - 6, 10), (RL, 36), (RL + 3, 36), (RL + 7, 40), (RR - 4, 44), (RR - 1, 48), (RR + 5, 48), (RR + 14, 48)):
        for m in range(k):
            a = 2 * math.pi * (m + 0.5 * (rad % 2)) / k
            cand.append((CX + rad * math.cos(a), CY + rad * math.sin(a)))
    cand.append((CX, CY))
    for rad, k in ((3.0, 8), (6.5, 14), (10.0, 20), (PAD_R - 0.5, 26), (PAD_R + 1.5, 28), (PAD_R + 5, 30),
                   (PAD_R + 10, 32)):
        for m in range(k):
            a = 2 * math.pi * (m + 0.5 * (k % 2)) / k
            cand.append((PAD[0] + rad * math.cos(a), PAD[1] + rad * math.sin(a)))
    cand.append(PAD)
    for (ax, ay), (bx, by) in zip(TERRACE, TERRACE[1:]):              # the respawn terrace
        seg = math.hypot(bx - ax, by - ay)
        nx_, ny_ = -(by - ay) / seg, (bx - ax) / seg
        for k in range(max(1, round(seg / 7.0))):
            t = k / max(1, round(seg / 7.0))
            cx_, cy_ = ax + t * (bx - ax), ay + t * (by - ay)
            for off in (0.0, TERRACE_W - 0.5, -(TERRACE_W - 0.5), TERRACE_W + 3.0, -(TERRACE_W + 3.0)):
                cand.append((cx_ + nx_ * off, cy_ + ny_ * off))
    for off in (0.0, TERRACE_W - 0.5, -(TERRACE_W - 0.5)):
        cand.append((TERRACE[-1][0] + off, TERRACE[-1][1]))
    for px, py, _level in JPADS:
        for rad, k in ((JPAD_R * 0.5, 6), (JPAD_R - 0.5, 12), (JPAD_R + 3, 14)):
            for m in range(k):
                a = 2 * math.pi * (m + 0.5 * (k % 2)) / k
                cand.append((px + rad * math.cos(a), py + rad * math.sin(a)))
        cand.append((px, py))
    d = np.array([math.cos(BREACH), math.sin(BREACH)]); pn = np.array([-d[1], d[0]])
    for along in np.arange(RL + 2, 120, 5.0):
        for off in (0.0, -BW * 0.55, BW * 0.55, -BW * 1.1, BW * 1.1, -BW * 2.0, BW * 2.0):
            q = np.array([CX, CY]) + d * along + pn * off
            cand.append((q[0], q[1]))
    for px, py, pr, _kind in POOLS:
        for rad, k in ((pr * 0.5, 10), (pr, 28), (pr + 5, 30), (pr + 16, 30)):
            for m in range(k):
                a = 2 * math.pi * m / k
                cand.append((px + rad * math.cos(a), py + rad * math.sin(a)))
        cand.append((px, py))
    cand = np.array(cand)
    near_t = terrace_dist(cand[:, 0], cand[:, 1])                  # the terrace's own points replace it too
    lattice = np.arange(len(cand)) < n_lattice
    cand = cand[~(lattice & (near_t < TERRACE_W + 6.0))]
    for px, py, _level in JPADS:                                   # the pad's rings replace the lattice there
        r_ = np.hypot(cand[:, 0] - px, cand[:, 1] - py)
        ring = np.isclose(r_, 0) | np.isclose(r_, JPAD_R * 0.5) | np.isclose(r_, JPAD_R - 0.5) | np.isclose(r_, JPAD_R + 3)
        cand = cand[(r_ > JPAD_R + 6) | ring]
    # keep clear of the road -- except inside the crater, whose wall meets the lips
    dmin = np.full(len(cand), np.inf)
    for k in range(0, len(road_xy), 200):
        blk = road_xy[k:k + 200]
        dd = np.hypot(cand[:, None, 0] - blk[None, :, 0], cand[:, None, 1] - blk[None, :, 1]).min(axis=1)
        dmin = np.minimum(dmin, dd)
    rc = np.hypot(cand[:, 0] - CX, cand[:, 1] - CY)
    keep = (dmin > HW + VW + CLEAR) | (rc < RR - 0.5)
    cand = cand[keep]
    # heights: the terrain, eased onto the road's height near it (cut and fill)
    th = full_h(cand[:, 0], cand[:, 1])
    near_idx = np.zeros(len(cand), int); near_d = np.full(len(cand), np.inf)
    for k in range(0, len(road_xy), 200):
        blk = road_xy[k:k + 200]
        dd = np.hypot(cand[:, None, 0] - blk[None, :, 0], cand[:, None, 1] - blk[None, :, 1])
        j = dd.argmin(axis=1); m = dd[np.arange(len(cand)), j]
        better = m < near_d
        near_d[better] = m[better]; near_idx[better] = j[better] + k
    rc = np.hypot(cand[:, 0] - CX, cand[:, 1] - CY)
    blend = smoothstep(HW + VW, HW + VW + 45, near_d)
    road_here = road_z[near_idx] - 0.15
    eased = road_here + (th - road_here) * blend
    on_pad = np.hypot(cand[:, 0] - PAD[0], cand[:, 1] - PAD[1]) < PAD_R + 12     # the monks' ledge keeps its shape
    on_pad |= terrace_dist(cand[:, 0], cand[:, 1]) < TERRACE_W + 4.0         # and so does the respawn terrace
    th = np.where((rc < RR + 1) | on_pad, th, eased)
    th = pad_apply(cand[:, 0], cand[:, 1], th, near_d)
    terr = np.column_stack([cand, th])
    pts = np.vstack([road_pts, terr])
    if verbose:
        print(f"lap {L:.0f} m; {n} stations ({gap.sum()} over the crater); spur exponent {SPUR_Q:.2f}; "
              f"{nroad} road points + {len(terr)} terrain points")
    tris = delaunay([tuple(p[:2]) for p in pts])
    return dict(path=path, L=L, zc=zc, gap=gap, norm=norm, pts=pts, nroad=nroad, road_uv=road_uv,
                road_st=road_st, tris=tris, stations=stations, road_xy=road_xy, road_z=road_z)


# ------------------------------------------------------------------ meshes
class Batch:
    """Triangles for one texture and surface, chunked under MAX_VERTS."""

    def __init__(self, scene, stem, texture, code, solid=True):
        self.scene, self.stem, self.texture, self.code, self.solid = scene, stem, texture, code, solid
        self.v, self.f, self.c, self.n = [], [], [], 0

    def tri(self, P, uv, grey, face=None):
        g = [bc.game(tuple(p)) for p in P]
        a, b, c = (np.array(q) for q in g)
        cr = np.cross(b - a, c - a)
        want = np.array([0.0, 1.0, 0.0]) if face is None else np.array(bc.game(face)) - (a + b + c) / 3
        order = [0, 1, 2] if np.dot(cr, want) >= 0 else [0, 2, 1]
        if len(self.v) + 3 > MAX_VERTS:
            self.flush()
        base = len(self.v)
        for k in order:
            self.v.append(mod.Vertex(*g[k], 0.0, 1.0, 0.0, *uv[k]))
            gv = int(max(40, min(255, grey[k] * 255)))
            self.c.append(bytes([gv, gv, gv, 0xFF]))
        self.f.append((base, base + 1, base + 2))

    def flush(self):
        if not self.f:
            return
        name = f"{self.stem}{self.n}.mod"
        self.scene.meshes[name] = mod.Mesh(vertices=self.v, faces=self.f, materials=[mod.Material(
            name=self.texture, vertex_start=0, vertex_end=len(self.v), face_start=0, face_end=len(self.f))])
        self.scene.colours[name] = self.c
        if self.solid:
            self.scene.driveables.append(trackgen.SceneObject(name, self.code))
        else:
            self.scene.scenery.append(trackgen.SceneObject(name, GRASS, NO_COLLISION))
        self.v, self.f, self.c, self.n = [], [], [], self.n + 1


def shade(P):
    a, b, c = P
    nrm = np.cross(b - a, c - a)
    nrm /= (np.linalg.norm(nrm) + 1e-12)
    if nrm[2] < 0:
        nrm = -nrm
    return 0.36 + 0.6 * max(0.0, float(nrm @ SUN)), nrm


def build_meshes(scene, g):
    pts, nroad = g["pts"], g["nroad"]
    B = {k: Batch(scene, k, t, c) for k, t, c in (("road", "dirtrd.tex", ROAD), ("verge", "ash.tex", DIRT),
                                                   ("ash", "ash.tex", DIRT), ("rock", "basalt.tex", DIRT),
                                                   ("hot", "hot.tex", DIRT), ("lava", "lava.tex", WATER),
                                                   ("jverge", "jungle.tex", DIRT), ("jungle", "jungle.tex", GRASS),
                                                   ("pond", "pond.tex", WATER))}
    counts = {k: 0 for k in B}
    L16 = g["L"] / 16.0
    for t in g["tris"]:
        P = pts[list(t)]
        cx, cy = P[:, 0].mean(), P[:, 1].mean()
        rc = math.hypot(cx - CX, cy - CY)
        all_road = all(i < nroad for i in t)
        light, nrm = shade(P)
        if all_road:
            lat = max(abs(g["road_st"][i][1]) for i in t)
            cls = "road" if all(abs(g["road_st"][i][1]) <= HW for i in t) else "verge"
            if cls == "verge" and not barren(cx, cy):
                cls = "jverge"
        elif rc < RL + 0.5 and np.ptp(P[:, 2]) < 0.05 and abs(P[:, 2].mean() - LZ) < 0.05:
            cls = "lava"
        elif in_pool(cx, cy) and np.ptp(P[:, 2]) < 0.05:
            cls = "lava" if in_pool(cx, cy) == "lava" else "pond"
        elif rc < RR + 2 or (rc < 125 and abs(-(cx - CX) * math.sin(BREACH) + (cy - CY) * math.cos(BREACH)) < BW * 1.2
                             and (cx - CX) * math.cos(BREACH) + (cy - CY) * math.sin(BREACH) > 0):
            cls = "hot"
        else:
            cls = "rock" if nrm[2] < math.cos(math.radians(21)) else "ash"
            if rc < RR + 45 and cls == "rock":
                cls = "hot"                                   # the summit is still hot
            elif not barren(cx, cy):
                cls = "jungle"
        if cls == "road":
            uv = [g["road_uv"][i] for i in t]
            vs = [q[1] for q in uv]
            if max(vs) - min(vs) > L16 / 2:                      # the lap's seam: keep v continuous
                uv = [(u, v + L16 if v < L16 / 2 else v) for u, v in uv]
            grey = [min(1.0, light + 0.05)] * 3
        elif cls in ("lava", "pond"):
            uv = [(p[0] / 18.0, p[1] / 18.0) for p in P]
            grey = [1.0 if cls == "lava" else 0.8] * 3
        else:
            sc = 22.0 if cls in ("ash", "verge", "jungle", "jverge") else 14.0
            uv = [(p[0] / sc + p[2] / (2 * sc), p[1] / sc + p[2] / (2 * sc)) for p in P]
            glow = 0.25 * math.exp(-max(rc - RR, 0) / 25.0) if cls == "hot" else 0.0
            grey = [min(1.0, light + glow)] * 3
        B[cls].tri(P, uv, grey)
        counts[cls] += 1
    for b in B.values():
        b.flush()
    return counts


def icosphere(radius):
    t = (1 + 5 ** 0.5) / 2
    V = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
         (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
         (8, 6, 7), (9, 8, 1)]
    V = [np.array(v, float) / np.linalg.norm(v) * radius for v in V]
    return V, F


def add_boulders(scene, g, count=70):
    rng = random.Random(SEED + 1)
    rocks = Batch(scene, "boulder", "basalt.tex", GRASS, solid=False)
    placed = 0
    road_xy = g["road_xy"]
    while placed < count:
        r = rng.uniform(RR + 25, RB + 450)
        a = rng.uniform(0, 2 * math.pi)
        x, y = CX + r * math.cos(a), CY + r * math.sin(a)
        if np.hypot(road_xy[:, 0] - x, road_xy[:, 1] - y).min() < HW + VW + 22 or in_pool(x, y):
            continue
        if not barren(x, y):
            continue
        if abs(-(x - CX) * math.sin(BREACH) + (y - CY) * math.cos(BREACH)) < BW * 3 and r < 160:
            continue
        if math.hypot(x - PAD[0], y - PAD[1]) < PAD_R + 14:       # keep the monks' ledge clear
            continue
        if float(terrace_dist(x, y)) < TERRACE_W + 10:             # and the respawn terrace
            continue
        rad = rng.uniform(1.4, 4.2)
        h = float(full_h(np.array(x), np.array(y)))
        c = np.array([x, y, h - 0.35 * rad])
        V, F = icosphere(rad)
        squash = np.array([1.0 + rng.uniform(-0.2, 0.3), 1.0 + rng.uniform(-0.2, 0.3), 0.75])
        W = [c + v * squash for v in V]
        for f in F:
            P = np.array([W[k] for k in f])
            light, _ = shade(P)
            out = tuple(P.mean(axis=0) + (P.mean(axis=0) - c) * 3)
            rocks.tri(P, [(p[0] / 4, p[1] / 4 + p[2] / 4) for p in P], [light] * 3, face=out)
        scene.spheres.append(((x, y, h - 0.35 * rad), rad * 0.95))
        placed += 1
    rocks.flush()


def ground_at(x, y, g):
    """Terrain height as built: the surface, eased onto the road near it."""
    xy = g["road_xy"]
    d = np.hypot(xy[:, 0] - x, xy[:, 1] - y)
    j = int(d.argmin())
    h = float(full_h(np.array(x), np.array(y)))
    road = g["road_z"][j] - 0.15
    eased = road + (h - road) * float(smoothstep(HW + VW, HW + VW + 45, d[j]))
    return float(pad_apply(x, y, eased, d[j])), float(d[j])


TREES = {"palm.tex": (9.0, 13.0, 0.5), "jtree.tex": (16.0, 20.0, 1.1), "fern.tex": (5.0, 4.0, 0.0)}


def billboard(batch, x, y, z, w, h, yaw, grey):
    """Two crossed upright quads, each drawn from both sides."""
    for a in (yaw, yaw + math.pi / 2):
        c, s_ = math.cos(a), math.sin(a)
        p0 = (x - c * w / 2, y - s_ * w / 2, z - 0.3); p1 = (x + c * w / 2, y + s_ * w / 2, z - 0.3)
        p2 = (p1[0], p1[1], z + h); p3 = (p0[0], p0[1], z + h)
        uv0, uv1, uv2, uv3 = (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)
        for side in (1, -1):
            f = (x - s_ * 20 * side, y + c * 20 * side, z + h / 2)
            batch.tri([p0, p1, p2], [uv0, uv1, uv2], [grey] * 3, face=f)
            batch.tri([p0, p2, p3], [uv0, uv2, uv3], [grey] * 3, face=f)


def add_trees(scene, g):
    """Jungle along the valley road, thinning into the forest behind it. Trunks near
    the road are solid (a sphere each); the rest, and all the ferns, are drawn only."""
    rng = random.Random(SEED + 2)
    batches = {t: Batch(scene, t.split(".")[0], t, GRASS, solid=False) for t in TREES}
    path, norm = g["path"], g["norm"]
    placed = 0
    spots = []
    for i in g["stations"]:
        for side in (1, -1):
            if rng.random() < 0.8:
                lat = side * rng.uniform(HW + VW + 5, HW + VW + 30)
                q = path[i] + norm[i] * lat + np.array([rng.uniform(-3, 3), rng.uniform(-3, 3)])
                spots.append((q[0], q[1], True))
    xs, ys = path[:, 0], path[:, 1]
    for _ in range(900):
        spots.append((rng.uniform(xs.min() - 250, xs.max() + 250), rng.uniform(ys.min() - 250, ys.max() + 250), False))
    for x, y, by_road in spots:
        if barren(x, y) or in_pool(x, y):
            continue
        z, d = ground_at(x, y, g)
        if d < HW + VW + 4:
            continue
        if any(math.hypot(x - cx_, y - cy_) < 11 for cx_, cy_, *_ in COTTAGES):   # clear round the cottages
            continue
        if any(math.hypot(x - px_, y - py_) < JPAD_R + 3 for px_, py_, _l in JPADS):   # and off the monks' pads
            continue
        kind = rng.choices(list(TREES), weights=(4, 3, 3))[0]
        w, h, trunk = TREES[kind]
        k = rng.uniform(0.75, 1.3)
        billboard(batches[kind], x, y, z, w * k, h * k, rng.uniform(0, math.pi), 0.82 if kind != "fern.tex" else 0.75)
        if trunk and d < HW + VW + 18:                          # only the front row is solid
            scene.spheres.append(((x, y, z + trunk * k * 0.6), trunk * k))
        placed += 1
    for bt_ in batches.values():
        bt_.flush()
    return placed


def lumpy_sphere(radius, subdiv, rng, rough=0.06):
    V, F = icosphere(1.0)
    V = [v / np.linalg.norm(v) for v in V]
    for _ in range(subdiv):
        mid = {}
        nf = []
        for a, b_, c in F:
            ids = []
            for p, q in ((a, b_), (b_, c), (c, a)):
                key = (min(p, q), max(p, q))
                if key not in mid:
                    m = V[p] + V[q]
                    V.append(m / np.linalg.norm(m))
                    mid[key] = len(V) - 1
                ids.append(mid[key])
            ab, bc_, ca = ids
            nf += [(a, ab, ca), (b_, bc_, ab), (c, ca, bc_), (ab, bc_, ca)]
        F = nf
    scale = [radius * (1 + rng.uniform(-rough, rough)) for _ in V]
    return [v * s for v, s in zip(V, scale)], F


def magma_mesh():
    """The rolling boulder: a lumpy sphere at its own origin, sphere-mapped magma.tex,
    in the game frame (the obstacle record places and spins it)."""
    rng = random.Random(SEED + 3)
    V, F = lumpy_sphere(MAGMA_R, 2, rng)
    verts, faces = [], []
    for f in F:
        P = [V[k] for k in f]
        uv = []
        for p in P:
            n = p / np.linalg.norm(p)
            uv.append([(math.atan2(n[2], n[0]) / (2 * math.pi)) % 1.0, math.acos(max(-1, min(1, n[1]))) / math.pi])
        us = [q[0] for q in uv]
        if max(us) - min(us) > 0.5:                              # the wrap seam
            for q in uv:
                if q[0] < 0.5:
                    q[0] += 1.0
        a, b_, c = (np.array(q) for q in P)
        order = [0, 1, 2] if np.dot(np.cross(b_ - a, c - a), (a + b_ + c) / 3) > 0 else [0, 2, 1]
        base = len(verts)
        for k in order:
            p = P[k]; n = p / np.linalg.norm(p)
            verts.append(mod.Vertex(float(p[0]), float(p[1]), float(p[2]), float(n[0]), float(n[1]), float(n[2]),
                                    float(uv[k][0]), float(uv[k][1])))
        faces.append((base, base + 1, base + 2))
    return mod.Mesh(vertices=verts, faces=faces, materials=[mod.Material(
        name="magma.tex", vertex_start=0, vertex_end=len(verts), face_start=0, face_end=len(faces))])


def add_embers(scene):
    """Small glowing magma rocks strewn round the rim: drawn, and they make sure magma.tex
    ships and loads with the track for the rolling boulders to use."""
    rng = random.Random(SEED + 4)
    emb = Batch(scene, "ember", "magma.tex", GRASS, solid=False)
    for _ in range(16):
        a = rng.uniform(0, 2 * math.pi); r = rng.uniform(RR + 6, RR + 40)
        if abs(math.cos(a)) < 0.35:                               # keep off the road spurs (north and south)
            continue
        x, y = CX + r * math.cos(a), CY + r * math.sin(a)
        rad = rng.uniform(0.7, 1.6)
        c = np.array([x, y, float(full_h(np.array(x), np.array(y))) + 0.2 * rad])
        V, F = lumpy_sphere(rad, 1, rng, 0.12)
        for f in F:
            P = np.array([c + V[k] for k in f])
            emb.tri(P, [(0.5 + (p[0] - c[0]) / (4 * rad), 0.5 + (p[2] - c[2]) / (4 * rad)) for p in P], [1.0] * 3,
                    face=tuple(P.mean(axis=0) + (P.mean(axis=0) - c) * 3))
    emb.flush()


def add_dragon(scene):
    """The dragon and his fireball: drawn-only scenery, chunked like everything else.
    Scales and skin carry baked smooth light from the sun; the fire is full bright."""
    bx, by = DRAGON_AT
    bz = float(full_h(np.array(bx), np.array(by))) - 0.3
    yaw = ds.yaw_facing((bx, by), FIRE_AT)
    dist = math.hypot(FIRE_AT[0] - bx, FIRE_AT[1] - by)
    end = (0.0, dist / DRAGON_S, (FIRE_AT[2] - bz) / DRAGON_S)
    body = ds.place(ds.dragon(), (bx, by, bz), yaw, DRAGON_S)
    fire = ds.place(ds.fireball(end, FIRE_R / DRAGON_S), (bx, by, bz), yaw, DRAGON_S)
    greys = ds.smooth_greys(body, SUN) + [[1.0] * 3 for _ in fire]
    batches = {}
    for (P, uv, t, n), grey in zip(body + fire, greys):
        if t in ds.FIRE_TEX:
            grey = [1.0] * 3
        if t not in batches:
            batches[t] = Batch(scene, DRAGON_STEMS[t], t, GRASS, solid=False)
        c = np.mean(P, axis=0)
        batches[t].tri(P, ds.clamp_uv(uv), grey, face=tuple(c + n * 3))
    for b in batches.values():
        b.flush()
    return len(body), len(fire)


def monk_spots():
    """(x, y, ground, look, yaw) for each monk: a line across the ledge, square to the view
    from the climb, all facing it."""
    view = np.array([PAD[0] - CX, PAD[1] - (CY - 65.0)])
    view /= np.linalg.norm(view)
    across = np.array([view[1], -view[0]])
    for look, k in enumerate((-1, 0, 1)):
        x = PAD[0] - view[0] * MONK_FORE + across[0] * k * MONK_GAP
        y = PAD[1] - view[1] * MONK_FORE + across[1] * k * MONK_GAP
        yield x, y, float(full_h(np.array(x), np.array(y))), look, ds.yaw_facing((x, y), (CX, CY - 65.0))
    yield from JUNGLE_MONKS


def jungle_pad_layout(sites):
    """For each burning jungle cottage: its pad centre (6 m roadward of it) and three monks
    4 m further roadward, spread 4.5 m apart, facing the road."""
    pads, monks = [], []
    for k, (x, y, yaw, burning) in enumerate(sites[1:]):
        if not burning:
            continue
        u = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])   # the door: toward the road
        across = np.array([-u[1], u[0]])
        pc = np.array([x, y]) + u * COTTAGE_BACK
        pads.append(pc)
        for j, off in enumerate((-1, 0, 1)):
            m = pc + u * MONK_FORE + across * off * MONK_GAP
            monks.append((float(m[0]), float(m[1]), (k + j) % 3, ds.yaw_facing(m, m + u * 10)))
    return pads, monks


def add_monk_anchors(scene):
    """The track only ships textures its drawn meshes use, and the monks' textures live on
    their obstacle meshes alone -- so each gets one tiny triangle buried under a monk
    (the embers do the same job for magma.tex). One per texture: the rim's three."""
    for x, y, z, look, _yaw in list(monk_spots())[:3]:
        b = Batch(scene, f"mnka{look}", ds.MONK_TEX[look], GRASS, solid=False)
        b.tri([(x, y, z - 2.0), (x + 0.1, y, z - 2.0), (x, y + 0.1, z - 2.0)], [(0.5, 0.9), (0.6, 0.9), (0.5, 0.8)],
              [1.0] * 3)
        b.flush()


def cottage_sites(g):
    """(x, y, yaw, burning) for every cottage: the pad's, then the jungle's, door to the road."""
    view = np.array([PAD[0] - CX, PAD[1] - (CY - 65.0)])
    view /= np.linalg.norm(view)
    sites = [(PAD[0] + view[0] * COTTAGE_BACK, PAD[1] + view[1] * COTTAGE_BACK,
              math.degrees(math.atan2(-view[1], -view[0])), True)]         # door toward the monks and the climb
    rng = random.Random(SEED + 7)
    path, norm, xy = g["path"], g["norm"], g["road_xy"]
    stations = list(g["stations"])
    tries = 0
    while len(sites) < 1 + JUNGLE_COTTAGES and tries < 4000:
        tries += 1
        i = rng.choice(stations)
        side = rng.choice((1, -1))
        q = path[i] + norm[i] * side * rng.uniform(HW + VW + 22, HW + VW + 40)
        x, y = float(q[0]), float(q[1])
        if barren(x, y) or in_pool(x, y) or any(math.hypot(x - a, y - b) < 90 for a, b, *_ in sites):
            continue
        d = np.hypot(xy[:, 0] - x, xy[:, 1] - y)
        if d.min() < HW + VW + 20:
            continue
        corners = [ground_at(x + dx, y + dy, g)[0] for dx in (-6, 6) for dy in (-6, 6)]
        if max(corners) - min(corners) > 1.6:                            # too steep to sit a house on
            continue
        j = int(d.argmin())
        yaw = math.degrees(math.atan2(xy[j, 1] - y, xy[j, 0] - x)) + rng.uniform(-20, 20)
        sites.append((x, y, yaw, (len(sites) - 1) % BURNING_EVERY == 0))
    return sites


def add_cottages(scene, g):
    """Each cottage sits level on its highest corner, its walls run down into the slope, and
    two solid spheres down its length stop the cars."""
    bat = {}
    sites = FROZEN_SITES or cottage_sites(g)
    for k, (x, y, yaw, burning) in enumerate(sites):
        c, s_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        foot = [(x + c * a - s_ * b, y + s_ * a + c * b) for a in (-ds.COTTAGE_D / 2, ds.COTTAGE_D / 2)
                for b in (-ds.COTTAGE_W / 2, ds.COTTAGE_W / 2)]
        gz = [ground_at(fx, fy, g)[0] for fx, fy in foot]
        floor = max(gz)
        tris = ds.place(ds.cottage(burning, sink=floor - min(gz) + 0.3, seed=k), (x, y, floor), yaw)
        for (P, uv, t, n), grey in zip(tris, ds.flat_greys(tris, SUN)):
            if t not in bat:
                bat[t] = Batch(scene, "ct" + t.split(".")[0][:5], t, GRASS, solid=False)
            bat[t].tri(P, ds.clamp_uv(uv), grey, face=tuple(np.mean(P, axis=0) + n * 3))
        for b in (-2.0, 2.0):                                            # along the ridge line
            scene.spheres.append(((x - s_ * b, y + c * b, floor + 1.2), 3.0))
    for b in bat.values():
        b.flush()
    COTTAGES[:] = sites
    return len(sites)


COTTAGES = []


# ------------------------------------------------------------------ build
def main(verbose=True):
    if not FROZEN_SITES:
        g0 = build(False)
        FROZEN_SITES[:] = cottage_sites(g0)
        pads, monks = jungle_pad_layout(FROZEN_SITES)
        JPADS[:] = [(float(pc[0]), float(pc[1]), ground_at(pc[0], pc[1], g0)[0]) for pc in pads]
        JUNGLE_MONKS[:] = [(x, y, 0.0, look, yaw) for x, y, look, yaw in monks]
    g = build(verbose)
    JUNGLE_MONKS[:] = [(x, y, ground_at(x, y, g)[0], look, yaw) for x, y, _z, look, yaw in JUNGLE_MONKS]
    path, L, zc, gap = g["path"], g["L"], g["zc"], g["gap"]
    centre = []
    for i in range(len(path)):                                   # every station
        centre.append((float(path[i, 0]), float(path[i, 1]), float(HR if gap[i] else zc[i])))
    scene = trackgen.TrackScene(centreline=centre)
    line = bc.Line(centre)
    trackgen.add_checkpoints(scene, 4, half_width=HW + 1.0)
    grid = []
    for k in range(8):
        (gx, gy, _gz), (tx, ty) = line.at(line.L - 14.0 - 10.0 * (k // 2))
        lat = 4.0 if k % 2 else -4.0
        q = (gx - ty * lat, gy + tx * lat)
        grid.append((q[0], q[1], float(base_h(np.array(q[0]), np.array(q[1])))))
    scene.grid = grid
    counts = build_meshes(scene, g)
    add_boulders(scene, g)
    cottages = add_cottages(scene, g)
    trees = add_trees(scene, g)
    add_embers(scene)
    dragon_tris = add_dragon(scene)
    add_monk_anchors(scene)
    trackgen.add_ground(scene, texture="jungle.tex", margin=900.0, drop=10.0)   # under every dip of the plain
    scene.colours["ground.mod"] = [bytes([70, 70, 70, 255])] * 4
    scene.walls = []

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    if verbose:
        print(f"triangles by class {counts}; trees {trees}; solids {len(scene.spheres)}; "
              f"dragon {dragon_tris[0]} + fire {dragon_tris[1]} triangles; cottages {cottages} "
              f"({sum(1 for *_, b in COTTAGES if b)} burning); monks {len(list(monk_spots()))}")
        print(f"surfaces {surfaces} (budget {SURFACE_BUDGET}); largest chunk {biggest} verts; collision triangles "
              f"{collide} (budget {COLLISION_BUDGET}); textures {sorted(wanted)}")
    if surfaces > SURFACE_BUDGET or biggest > MAX_VERTS or collide > COLLISION_BUDGET:
        raise SystemExit("over budget")
    return scene, g, line, wanted


def respawn_line(g) -> tuple["ili.Line", list[bool]]:
    """track.ild with the crater crossing swapped for the west-rim detour.

    Same generator, corridor and flags trackbuild.assemble uses, so everything but the
    detour matches the line it replaces. Returns the line and, per record, whether it
    belongs to the detour (those carry DETOUR_CORRIDOR in field 5)."""
    path, zc = g["path"], g["zc"]
    pts, on_detour = [], []
    for i in range(len(path)):
        if i in DETOUR_SKIP:
            if i == DETOUR_SKIP[0]:
                pts += [(x, y, HR) for x, y in DETOUR]
                on_detour += [True] * len(DETOUR)
            continue
        pts.append((float(path[i, 0]), float(path[i, 1]), float(zc[i])))
        on_detour.append(False)
    gpts = [bc.game(q) for q in pts]
    line = ili.generate([(q[0], q[2]) for q in gpts], kind=ili.KIND_ILD, sectors=True,
                        closed=True, corridor=HW + VW + 8.0)
    first = on_detour.index(True)
    # the leg out from the lip belongs to the record before the detour: it carries the
    # detour's corridor too, so a stepped-back reset lands ON it (on the terrace), not 7.75 m aside
    f5 = [DETOUR_CORRIDOR if d or i == first - 1 else r[ili.FIELD_CORRIDOR]
          for i, (r, d) in enumerate(zip(line.records, on_detour))]
    line.set_field(ili.FIELD_CORRIDOR, f5)
    # Only the terrace may claim a point in the crater. IdealLine::get_nearest_pair lets a
    # segment claim p when dot(t_start, p - start) > 0 and dot(t_end, p - end) < 0, and takes
    # the nearest by closer endpoint -- so the legs to and from the terrace (whose ends are
    # nearer the lava than the terrace is) must fail that test. Their tangents do it: up the
    # road at the lips, east where the detour meets the terrace, west where it leaves it.
    # Short tangents, so the Hermite curve barely bends; the test only reads their direction.
    first = on_detour.index(True)
    last = len(on_detour) - 1 - on_detour[::-1].index(True)
    north, east, west = bc.game((0, 1, 0)), bc.game((1, 0, 0)), bc.game((-1, 0, 0))
    k = 0.5
    tx = [r[ili.FIELD_DIR_X] for r in line.records]
    tz = [r[ili.FIELD_DIR_Z] for r in line.records]
    for i, d in ((first - 1, north), (first, east), (last, west), (last + 1, north)):
        tx[i], tz[i] = d[0] * k, d[2] * k
    line.set_field(ili.FIELD_DIR_X, tx)
    line.set_field(ili.FIELD_DIR_Z, tz)
    if not ili.origin_is_claimed(line):
        raise SystemExit("respawn line: nothing claims the world origin (the race would crash)")
    return line, on_detour


def write(scene, g, line, wanted):
    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True, corridor=HW + VW + 8.0)
    print(f"assembled: {res.summary()}")
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        fn, mode = art.ALL[name]
        im = fn()
        if mode == "opaque" and int((np.array(im).sum(axis=2) == 0).sum()):
            raise SystemExit(f"{name} has black texels")
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), im.width, mode=mode, wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = art.sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for pos, tgt in (((-40.0, -380.0, 60.0), (0.0, -120.0, 70.0)),        # the climb
                     ((-70.0, -20.0, HR + 25.0), (0.0, 20.0, HR - 5.0)),  # beside the summit, across the crater
                     ((60.0, 150.0, 80.0), (0.0, 40.0, HR)),              # the landing, looking back up
                     ((260.0, 420.0, 40.0), (100.0, 420.0, 20.0)),        # the descent bends
                     ((980.0, 250.0, 25.0), (840.0, 200.0, 5.0)),         # the valley
                     ((200.0, -1050.0, 20.0), (20.0, -960.0, 3.0))):      # the hairpin onto the climb
        gpos, gtgt = bc.game(pos), bc.game(tgt)
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    menv = envelope.parse(mod.build(magma_mesh()))
    ent.append(archive.ArchiveEntry(name="magma.mod", tag=menv.tag, version=menv.version, payload=menv.payload))
    table = obt_mod.parse(envelope.build(by["track.obt"].tag, by["track.obt"].version, by["track.obt"].payload))
    records = [r for r in table.records if r != obt_mod.TERMINATOR]
    for x, y in MAGMA_AT:
        gx, gh, gz = bc.game((x, y, float(base_h(np.array(x), np.array(y))) + MAGMA_R + 0.4))
        # x, z : YAW (degrees) MASS. The engine finds the height itself (a ray down the collision
        # mesh) and drops the obstacle from 4 m above it; the third number only turns it.
        records.append(f"obj obstacle ball magma.mod {gx:.6f},{gz:.6f}:0.000000 {MAGMA_MASS:.6f}")
    for i, (x, y, z, look, yaw) in enumerate(monk_spots()):
        menv = envelope.parse(mod.build(ds.monk_mesh(ds.MONK_TEX[look], yaw, bc.game)))
        ent.append(archive.ArchiveEntry(name=f"monk{i}.mod", tag=menv.tag, version=menv.version, payload=menv.payload))
        gx, gh, gz = bc.game((x, y, z))
        records.append(f"obj obstacle cube monk{i}.mod {gx:.6f},{gz:.6f}:0.000000 {MONK_MASS:.6f}")
    table.records = records + [obt_mod.TERMINATOR]
    tenv = envelope.parse(obt_mod.build(table))
    by["track.obt"].payload = tenv.payload
    archive.write(ent, OUT)
    trackmap.install(OUT, OUT)            # the minimap is drawn from the straight line...
    ent = archive.read(OUT)               # ...then track.ild takes the respawn detour
    rline, _flags = respawn_line(g)
    env = envelope.parse(ili.build(rline))
    ild = next(e for e in ent if e.name.lower() == "track.ild")
    ild.tag, ild.version, ild.payload = env.tag, env.version, env.payload
    archive.write(ent, OUT)
    by = {e.name.lower(): e for e in archive.read(OUT)}
    for name in sorted(wanted) + list(sky.TILES):
        tex.parse(envelope.build(by[name].tag, by[name].version, by[name].payload))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    print(f"textures decode; {len(so.primitives)} solids (boulders); {len(cams)} cameras; "
          f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    write(*main())
