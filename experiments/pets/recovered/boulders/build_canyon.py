"""Boulder Canyon: an Indiana Jones run down a temple gorge, with 100,000 lb boulders.

Designed from the decoded obstacle physics (docs/reference/file-formats.md, "How an obstacle ball
rolls"; model in ../friction/boulder_sim.py). Heavy boulders skid down slopes almost frictionlessly and
barely slow on the flat. Physics runs from race load, and the green flag comes 4.8 s later
(RaceDeity::Reset), so every boulder is already rolling when the cars start.

  * The grid sits on a temple plateau at the head of a 24 m gorge, which drops 100 m at 12 degrees.
  * THE CHASER: a boulder on a chute behind the plateau (a gentle run-in, then a 40-degree drop),
    timed to cross the grid just after the back row pulls away, then chase the field down the gorge.
  * THREE AMBUSHES: chutes cut into the left mountainside at 10 degrees, meeting the road partway
    down the gorge. Each length is set so its boulder crosses just ahead of the leaders
    (car estimate: 5 m/s^2 up to 50 m/s -- to be tuned in game).
  * THE GRAVEYARD: at the bottom the road hairpins right; the boulders carry straight on into a pit
    past the outside of the turn.
  * The lap climbs back up behind a rock ridge to the plateau. Lap 2 on: the gorge is clear.

Source frame: x down the gorge, y to the left of a car climbing back (the return road is at +y),
z up. Every height change the cars must not drive over is a cliff: points at +-0.3 m either side,
plus a .sol box.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "friction"))
import build_boulderlab as L1  # noqa: E402  (B, bc, BP, art)
import boulder_sim  # noqa: E402

B, bc = L1.B, L1.bc
sys.path.insert(0, str(HERE.parent / "circuit"))
import make_boulder  # noqa: E402
import temple_art as TA  # noqa: E402
from art import colourise, tile_noise, to_img, speckle  # noqa: E402
from build_river import delaunay  # noqa: E402
from vrmod.trackgen import WATER  # noqa: E402
from vrmod import archive, camtab, ili, envelope, mod, obt as obt_mod, sky, sol, tex, track, trackbuild, trackgen, trackmap  # noqa: E402

NAME = sys.argv[1] if len(sys.argv) > 1 else "BoulderRun"
OUT = HERE / f"{NAME}.trk"
DATA = B.DATA
SLOT = "hastings"

# ---- layout -------------------------------------------------------------------------------------------
H = 100.0                                   # plateau height; the gorge bottom is 0
GORGE_DEG = 12.0
X_FOOT = H / math.tan(math.radians(GORGE_DEG))   # 470.5
SMOOTH = 24.0
HW = 12.0                                   # road half-width
Y_RET = 80.0                                # return road centre
X_TOP_C, X_BOT_C, TURN_R = -200.0, 520.0, 40.0   # turn centres (y = 40) and radius
X_BACK = X_TOP_C - TURN_R - HW - 4.0        # back wall of the plateau, just behind the top turn
START_X = -60.3                             # the start line; the grid sits behind it, 65 m clear of the turn
GRID_ROW, GRID_LAT = 9.0, 0.0               # SINGLE FILE on the chaser's line: every slot, the last included,
                                            # is in its path, whichever slot the game gives the player
X_OUTER = 580.0                             # outer wall beyond the hairpin
Y_OUTER = Y_RET + HW                        # 92
RIDGE_H = 25.0                              # the ridge between the down and return roads
CLIFF = 14.0                                # the mountain starts with a cliff this tall (above the road)
MT_DEG = 30.0                               # the mountainside above it
OUT_H = 20.0                                # the outer cliff beyond the return road
PIT = dict(x0=585.0, x1=700.0, y0=-25.0, y1=20.0, depth=0.0, ramp_deg=20.0)   # no hole: the quicksand IS the
                                                                                # surface, level with the ground
# the pit's floor is QUICKSAND: surface code 14, which the engine treats as water. A boulder that
# touches it loses its ground contact and gets water drag, -(500 + 10|v|) x pi r^2 x v, plus buoyancy:
# a 100,000 lb boulder at 70 mph stops within a couple of seconds and floats there. (Cars stick too;
# the pit is off the lap.)
QS = dict(x0=PIT["x0"] + 10.0, x1=PIT["x1"] - 4.0, y0=PIT["y0"] + 4.0, y1=PIT["y1"] - 4.0)

# the chaser's chute, behind the plateau on the straight's axis: big enough to tag both grid columns
CH_HW = HW                                   # the chute is the U, as wide as the road
CH_RUNIN_DEG, CH_RUNIN_LEN = 45.0, 0.0
CH_DROP_DEG, CH_DROP_LEN = 50.0, 80.0
CHASER_R = 6.5                               # 13 m across, down the middle
# the ambush chutes: where they meet the gorge, and their slope
AMB_X = (150.0, 280.0, 400.0)
AMB_DEG, AMB_HW = 10.0, 7.0
AMB_LEAD = 3.0                               # seconds ahead of the leaders (1.0, then 2.0, were late in game)

# ---- the run's cross-section: a U -- a flat floor with curved walls -- from the chaser's chute to the
# foot of the gorge. The walls stop at 70 degrees, not vertical: a near-vertical collision triangle is a
# wall at every height above it, and would stop an ambush boulder coming over the rim.
U_FLOOR = 5.0                                # flat floor half-width
U_DEG = 70.0                                 # the wall's slope at the rim
U_R = (HW - U_FLOOR) / math.sin(math.radians(U_DEG))
RIM_H = U_R * (1 - math.cos(math.radians(U_DEG)))    # about 4.9 m
X_U0 = X_TOP_C + 12.0                        # the start tunnel's mouth, just past where the top turn joins
X_U1 = X_FOOT + 4.0                          # the U flattens into the bottom chamber after this
X_T2_END = -5.0                              # the start tunnel opens onto the gorge here
ARCH_H = 13.0                                # tunnel roof apex above the rim (drawn only, no collision)

BOULDER_R, BOULDER_MASS = 4.0, 100000.0
GREEN = 7.9      # seconds of physics before the green: RaceDeity::Reset adds 4.8, but in game (2026-09-25)
                 # the chaser was ~3 s ahead of that, so the pre-race intro evidently runs the physics too
CAR_A, CAR_V = 5.0, 50.0                    # the car estimate the chutes are timed to
WALL_H, SEG = 10.0, 25.0
DX = 0.5
XS = np.arange(-400.0, 800.0 + DX / 2, DX)


def eased_profile(schedule, x_zero):
    """Heights along XS from a slope schedule [(x0, x1, deg)], eased with a moving average (which
    keeps each drop exact), integrated so that z(x_zero) = 0."""
    raw = np.zeros_like(XS)
    for a, b, deg in schedule:
        raw = np.where((XS >= a) & (XS < b), math.tan(math.radians(deg)), raw)
    k = int(SMOOTH / DX)
    sm = np.convolve(raw, np.ones(k) / k, mode="same")
    z = -np.cumsum(sm * DX)
    return z - np.interp(x_zero, XS, z)


ROAD = eased_profile([(0.0, X_FOOT, GORGE_DEG)], X_FOOT)


def rd(x):
    return float(np.interp(x, XS, ROAD))


def car_time(d):
    """The car estimate: seconds from race load until a car has covered d metres from the grid."""
    d1 = CAR_V ** 2 / (2 * CAR_A)
    return GREEN + (math.sqrt(2 * d / CAR_A) if d <= d1 else CAR_V / CAR_A + (d - d1) / CAR_V)


def boulder_time(slope_of_x, x_end):
    s = boulder_sim.run(BOULDER_MASS, BOULDER_R, slope_of_x, x_end)
    return s[-1][0], s[-1][2]


def chute_length_for(t_target, deg):
    c = math.cos(math.radians(deg))
    for L in np.arange(10.0, 800.0, 1.0):
        if boulder_time(lambda x: deg, L * c)[0] >= t_target:
            return float(L)
    raise SystemExit("no chute is long enough")


# the ambush chutes' lengths, from the timing
GRID_X = START_X - 12.0 - 3.5 * GRID_ROW     # the grid's middle
BACK_SLOT_X = START_X - 12.0 - 7 * GRID_ROW  # slot 8
AMB = []
for xc in AMB_X:
    t_lead = car_time(xc - GRID_X)
    L = chute_length_for(t_lead - AMB_LEAD, AMB_DEG)
    AMB.append(dict(x=xc, len=L, t=t_lead))

# the chaser's chute, as heights along x behind the plateau (x < X_BACK)
_c1, _c2 = math.cos(math.radians(CH_RUNIN_DEG)), math.cos(math.radians(CH_DROP_DEG))
CH_X_DROP = X_BACK - CH_DROP_LEN * _c2        # top of the 40-degree drop
CH_X_TOP = CH_X_DROP - CH_RUNIN_LEN * _c1     # top of the run-in (the boulder's start)
CH_X_END = CH_X_TOP - 16.0                   # the chute's back wall
X_CH_EXIT = X_BACK + SMOOTH / 2              # where the eased drop has finished, out on the plateau
TUNNELS_DEF = [(CH_X_END, X_BACK), (X_U0, X_T2_END)]   # the chaser's chute, and the start tunnel
CHASER = eased_profile([(CH_X_DROP, X_BACK, CH_DROP_DEG), (CH_X_TOP - 20.0, CH_X_DROP, CH_RUNIN_DEG)], X_CH_EXIT)


def chaser_z(x):
    return rd(X_CH_EXIT) + float(np.interp(max(x, CH_X_END), XS, CHASER))


def smooth01(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def u_mask(x):
    """How much of the U applies at x: all of it along the chaser's chute, none across the courtyard
    where the top turn joins, all of it again from the start tunnel to the foot of the gorge."""
    if x < X_CH_EXIT:
        return 1.0 - smooth01((x - (X_CH_EXIT - 12.0)) / 12.0)
    return smooth01((x - (X_U0 - 12.0)) / 12.0) * (1.0 - smooth01((x - X_U1) / 16.0))


def u_wall(y):
    d = min(abs(y), HW) - U_FLOOR
    return 0.0 if d <= 0 else U_R - math.sqrt(max(U_R * U_R - d * d, 0.0))


def u_height(x, y):
    """The U's rise above the floor at (x, y). At an ambush mouth the left wall becomes a straight
    35-degree ramp from the rim, blended in over 6 m either side, so a boulder coming off its chute
    rolls down into the U instead of dropping over a lip."""
    if abs(y) > HW:
        return 0.0
    h = u_wall(y)
    if y < -U_FLOOR:
        for a in AMB:
            w = 1.0 - smooth01((abs(x - a["x"]) - AMB_HW) / 6.0)
            if w > 0:
                ramp = RIM_H * (-U_FLOOR - y) / (HW - U_FLOOR)
                h += (ramp - h) * w
    return u_mask(x) * h


def ambush_floor(x, y, a):
    """A chute floor: rising at AMB_DEG away from the road edge, level across, except that it tilts
    with the road over the first 20 m so the mouth meets the road without a step."""
    d = -HW - y                                   # distance up the chute from the road edge
    w = max(0.0, 1.0 - d / 20.0)
    return rd(a["x"]) + (rd(x) - rd(a["x"])) * w + d * math.tan(math.radians(AMB_DEG)) + RIM_H


def mountain(x, y):
    base = rd(min(max(x, 0.0), X_FOOT)) if x < X_FOOT else 0.0
    return base + CLIFF + (-HW - y) * math.tan(math.radians(MT_DEG))


R_ISLAND = TURN_R - HW                       # the turns' inner edge: the ridge meets it exactly


def in_turn_island(x, y):
    return math.hypot(x - X_TOP_C, y - 40.0) < R_ISLAND or math.hypot(x - X_BOT_C, y - 40.0) < R_ISLAND


def pit_z(x, y):
    p = PIT
    if p["depth"] <= 0.0:
        return rd(x)
    run = p["depth"] / math.tan(math.radians(p["ramp_deg"]))
    t = min(1.0, max(0.0, (x - p["x0"]) / run))
    t = t * t * (3 - 2 * t)
    return rd(x) - p["depth"] * t


def region(x, y):
    """Which surface a point is on: road, chute, pit, ridge, mountain, outer, back."""
    p = PIT
    if QS["x0"] <= x <= QS["x1"] and QS["y0"] <= y <= QS["y1"]:
        return "quick"
    if p["x0"] <= x <= p["x1"] and p["y0"] <= y <= p["y1"]:
        return "pit"
    if CH_X_END <= x < X_CH_EXIT and abs(y) <= CH_HW:
        return "chaser"
    if x < X_BACK:
        return "back"
    if y < -HW:
        for k, a in enumerate(AMB):
            if abs(x - a["x"]) <= AMB_HW and -HW - y <= a["len"] + 12.0:
                return f"amb{k}"
        return "mountain"
    if y > Y_OUTER or x > p["x1"] or (x > X_OUTER and y > p["y1"]):
        return "outer"
    if (X_TOP_C <= x <= X_BOT_C and HW < y < Y_RET - HW) or in_turn_island(x, y):
        return "ridge"
    return "road"


def height(x, y):
    r = region(x, y)
    if r == "road":
        return rd(x) + u_height(x, y)
    if r in ("pit", "quick"):
        return pit_z(x, y)
    if r == "chaser":
        return chaser_z(x) + u_height(x, y)
    if r.startswith("amb"):
        return ambush_floor(x, y, AMB[int(r[3])])
    if r == "ridge":
        return rd(x) + RIDGE_H
    if r == "outer":
        return rd(min(x, X_FOOT)) + OUT_H
    if r == "back":
        # the mountain the chute is bored through: always well above the chute's roof, so the drawn
        # tunnel is buried rather than standing proud of the slope
        over = chaser_z(max(x, CH_X_END)) + RIM_H + ARCH_H + 6.0 - 0.3 * max(0.0, abs(y) - HW - 6.0)
        return max(H + OUT_H + (X_BACK - x) * 0.4, over)
    return mountain(x, y)


# ---- boundaries (the cliffs), as polylines --------------------------------------------------------------
def arc(cx, cy, r, a0, a1, step=4.0):
    n = max(2, int(abs(a1 - a0) * r / step))
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def boundaries():
    lines = []
    p = PIT
    # the road's left edge (mountain side), broken at the chute mouths, as far as the pit
    xs = [X_BACK] + sum([[a["x"] - AMB_HW, a["x"] + AMB_HW] for a in AMB], []) + [p["x0"]]
    for k in range(0, len(xs), 2):
        lines.append([(xs[k], -HW), (xs[k + 1], -HW)])
    for a in AMB:                                            # chute sides and back
        top = -HW - a["len"] - 12.0
        lines.append([(a["x"] - AMB_HW, -HW), (a["x"] - AMB_HW, top), (a["x"] + AMB_HW, top), (a["x"] + AMB_HW, -HW)])
    # the pit's sides and end (its mouth is a ramp), then the outer walls round to the back
    lines.append([(p["x0"], -HW), (p["x0"], p["y0"]), (p["x1"], p["y0"]), (p["x1"], p["y1"]), (X_OUTER, p["y1"]),
                  (X_OUTER, Y_OUTER), (X_BACK, Y_OUTER), (X_BACK, CH_HW)])
    if CH_HW < HW:
        lines.append([(X_BACK, -CH_HW), (X_BACK, -HW)])
    lines.append([(X_CH_EXIT, CH_HW), (CH_X_END, CH_HW), (CH_X_END, -CH_HW), (X_CH_EXIT, -CH_HW)])
    # the ridge, with the turn islands
    r_in = R_ISLAND
    ridge = [(X_TOP_C, HW)] + [(X_BOT_C, HW)] + arc(X_BOT_C, 40.0, r_in, -math.pi / 2, math.pi / 2)[1:-1] + \
            [(X_BOT_C, Y_RET - HW), (X_TOP_C, Y_RET - HW)] + arc(X_TOP_C, 40.0, r_in, math.pi / 2, 3 * math.pi / 2)[1:-1] + [(X_TOP_C, HW)]
    # the ridge's straight edges meet the island arcs: close the gaps
    lines.append(ridge)
    return lines


def densify(line, step):
    out = []
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / step)))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
    return out + [line[-1]]


# ---- art ------------------------------------------------------------------------------------------------
def sandstone(size=128, seed=701):
    n = tile_noise(size, 3, 5, 0.55, seed)
    strata = np.sin(np.linspace(0, 2 * np.pi * 4, size, endpoint=False))[:, None] * 0.12 + tile_noise(size, 16, 2, 0.5, seed + 1) * 0.1
    img = colourise(np.clip(n * 0.8 + strata + 0.1, 0, 1), (150, 104, 70), (196, 150, 104))
    img += speckle(size, 0.05, seed + 2)[..., None] * np.array([-14, -12, -10])
    return to_img(img)


def chute_stone(size=128, seed=711):
    n = tile_noise(size, 4, 4, 0.5, seed)
    img = colourise(n, (118, 100, 80), (150, 130, 104))
    g = np.zeros((size, size))
    g[:, :3] = g[:, -3:] = 1.0                            # worn grooves along the chute
    img *= (1 - 0.15 * g)[..., None]
    return to_img(img)


def quicksand(size=128, seed=721):
    n = tile_noise(size, 3, 4, 0.55, seed)
    swirl = tile_noise(size, 6, 3, 0.5, seed + 1)
    img = colourise(np.clip(0.6 * n + 0.4 * swirl, 0, 1), (122, 96, 58), (164, 134, 86))
    return to_img(img)


def cave_rock(size=128, seed=731):
    n = tile_noise(size, 3, 5, 0.55, seed)
    cracks = (tile_noise(size, 12, 2, 0.5, seed + 1) > 0.72).astype(float)
    img = colourise(n, (82, 68, 56), (140, 120, 98))
    img *= (1 - 0.25 * cracks)[..., None]
    return to_img(img)


def cave_vines(size=128, seed=741):
    """Cave rock with vines hanging down it (v runs down the strands), soft-edged so they don't shimmer."""
    img = np.array(cave_rock(size, seed)).astype(np.float32)
    rng = random.Random(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    for _ in range(6):
        x0, length = rng.uniform(0, size), rng.uniform(size * 0.45, size)
        amp, ph = rng.uniform(2, 6), rng.uniform(0, 6.3)
        cx = x0 + amp * np.sin(yy / size * 2 * np.pi + ph)
        dx = np.minimum(np.abs(xx - cx), size - np.abs(xx - cx))
        leaf = 0.5 + 0.5 * np.sin(yy * 0.9 + ph)                  # leaves bunch along the strand
        wmask = np.clip(1.0 - dx / (1.6 + 2.2 * leaf), 0, 1) * (yy < length)
        green = np.array([52, 96, 40]) + 40 * leaf[..., None] * np.array([0.6, 1.0, 0.4])
        img = img * (1 - wmask[..., None]) + green * wmask[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


TEXTURES = {"qsand.tex": quicksand, "flagst.tex": TA.flagstones, "sandst.tex": sandstone, "chute.tex": chute_stone,
            "boulder.tex": make_boulder.boulder_texture, "carve.tex": TA.carve,
            "caverock.tex": cave_rock, "cavevine.tex": cave_vines}


# ---- build ----------------------------------------------------------------------------------------------
def surface_edges():
    """Lines where the surface code changes but the height does not: points either side, no walls."""
    q = QS
    return [[(q["x0"], q["y0"]), (q["x1"], q["y0"]), (q["x1"], q["y1"]), (q["x0"], q["y1"]), (q["x0"], q["y0"])]]


def floor_points():
    lines = boundaries() + surface_edges()
    edge = []
    for ln in lines:
        d = densify(ln, 4.0)
        for (x0, y0), (x1, y1) in zip(d, d[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            nx, ny = -(y1 - y0) / L, (x1 - x0) / L
            for s in (-0.3, 0.3):
                edge.append((round(x0 + nx * s, 3), round(y0 + ny * s, 3)))
    near = np.array([(x, y) for x, y in edge])
    pts = set(edge)

    def far_from_edges(x, y):
        return np.min(np.hypot(near[:, 0] - x, near[:, 1] - y)) > 1.5

    # the U: rows that follow its curve, every 4 m along (2 m at the ambush mouths)
    rows = [0.0, 5.0, 7.5, 9.5, 10.8]
    xs_u = set(np.round(np.arange(CH_X_END + 1.0, X_U1 + 20.0, 6.0), 2))
    for xb in (0.0, X_FOOT, X_CH_EXIT - SMOOTH / 2, CH_X_DROP, X_U0 - 6.0):   # finer where the slope changes
        xs_u |= set(np.round(np.arange(xb - SMOOTH, xb + SMOOTH + 0.1, 3.0), 2))
    for a in AMB:
        xs_u |= set(np.round(np.arange(a["x"] - AMB_HW - 8.0, a["x"] + AMB_HW + 8.1, 2.0), 2))
    for x in sorted(xs_u):
        for y in rows + [-r for r in rows if r]:
            if np.min(np.hypot(near[:, 0] - x, near[:, 1] - y)) > 0.5:
                pts.add((float(x), float(y)))

    def in_u(x, y):
        return abs(y) < HW and CH_X_END <= x <= X_U1 + 20.0

    for i, x in enumerate(np.arange(CH_X_END - 30.0, 740.0, 8.0)):
        for j, y in enumerate(np.arange(-HW - max(a["len"] for a in AMB) - 40.0, Y_OUTER + 30.0, 8.0)):
            if in_u(x, y):
                continue
            r = region(x, y)
            fine = r in ("road", "pit", "quick", "chaser") or r.startswith("amb")
            if (fine or (i % 2 == 0 and j % 2 == 0)) and far_from_edges(x, y):
                pts.add((float(x), float(y)))
    # extra rows where the slope eases in and out, so the curve is smooth
    for xb in (0.0, X_FOOT, X_CH_EXIT - SMOOTH / 2, CH_X_DROP, PIT["x0"]):
        for x in np.arange(xb - SMOOTH, xb + SMOOTH + 0.1, 3.0):
            for y in np.arange(-HW + 2, HW - 1, 5.0):
                if not in_u(x, y) and far_from_edges(x, y):
                    pts.add((float(x), float(y)))
    return sorted(pts)


TUNNELS = TUNNELS_DEF


def in_tunnel(x):
    return any(a <= x <= b for a, b in TUNNELS)


def light(x, y):
    """Vertex grey: daylight outside; inside a tunnel it darkens away from the mouths, with a pool of
    torchlight every 24 m."""
    if abs(y) > HW + 0.5:
        return 0.95
    for a, b in TUNNELS:
        if a - 2 <= x <= b + 2:
            depth = min(x - a, b - x)
            base = max(0.28, 0.95 - max(depth, 0.0) / 18.0 * 0.67)
            pool = 0.5 * math.exp(-(((x - a) % 24.0 - 12.0) ** 2) / 18.0)
            return min(1.0, base + pool)
    return 0.95


def texture_for(P, names):
    if all(n == "quick" for n in names[1:]):
        return "qsand.tex"
    cx, cy = sum(p[0] for p in P) / 3, sum(p[1] for p in P) / 3
    if names[0] in ("road", "chaser") and abs(cy) < HW and u_mask(cx) > 0.3:
        if abs(cy) <= U_FLOOR + 0.5:
            return "flagst.tex"
        return "caverock.tex" if in_tunnel(cx) else "carve.tex"
    zs = [p[2] for p in P]
    if max(zs) - min(zs) > 3.0 and any(n != names[0] for n in names):
        # a cliff: carved stone where it rises from the U (cave rock inside a tunnel), else sandstone
        if any(abs(q[1]) <= HW + 0.5 and u_mask(q[0]) > 0.3 for q in P):
            return "caverock.tex" if in_tunnel(cx) else "carve.tex"
        return "sandst.tex"
    r = names[0]
    if r in ("road", "pit"):
        return "flagst.tex"
    if r == "chaser" or r.startswith("amb"):
        return "chute.tex"
    return "sandst.tex"


def build_floor(scene):
    pts = floor_points()
    tris = delaunay(pts)
    SB = L1.BP.ShadedBatch
    batches = {t: SB(scene, t.split(".")[0], t, True) for t in ("flagst.tex", "sandst.tex", "chute.tex", "carve.tex", "caverock.tex")}
    batches["qsand.tex"] = SB(scene, "qsand", "qsand.tex", True, code=WATER)
    for t in tris:
        P = [(pts[i][0], pts[i][1], height(pts[i][0], pts[i][1])) for i in t]
        cx, cy = sum(p[0] for p in P) / 3, sum(p[1] for p in P) / 3
        names = [region(cx, cy)] + [region(p[0], p[1]) for p in P]
        tx = texture_for(P, names)
        s = 16.0
        uv = [(p[0] / s, p[1] / s) if tx != "sandst.tex" else ((p[0] + p[1]) / 24.0, p[2] / 24.0) for p in P]
        if tx == "sandst.tex" and max(p[2] for p in P) - min(p[2] for p in P) < 3.0:
            uv = [(p[0] / 24.0, p[1] / 24.0) for p in P]
        if tx in ("carve.tex", "caverock.tex"):                  # the U walls: u along, v up the curve
            uv = [(p[0] / 8.0, (abs(p[1]) + (p[2] - rd(p[0]))) / 8.0) for p in P]
        batches[tx].tri3(P, uv, [light(p[0], p[1]) for p in P], (cx, cy, max(p[2] for p in P) + 10.0))
    for b in batches.values():
        b.flush()
    return len(tris), len(pts)


# ---- the cave: drawn roofs over the two tunnels, rock portals, stalactites (none of it collides) -------
def floor_z(x):
    return chaser_z(x) if x < X_CH_EXIT else rd(x)


def rough(x, phi):
    """Cave-wall roughness, metres outward: smooth bumps that fade to nothing at the rim."""
    r = 0.8 * math.sin(0.23 * x + 3.1 * phi) * math.cos(0.11 * x - 2.0 * phi + 1.0)         + 0.45 * math.sin(0.61 * x + 5.3 * phi + 2.0)
    # fades out over the last 4 m before each mouth, so the arch meets its portal ring exactly
    fade = max((min(1.0, max(0.0, (x - lo) / 4.0)) * min(1.0, max(0.0, (hi - x) / 4.0)) for lo, hi in TUNNELS), default=1.0)
    return r * math.sin(phi) ** 0.7 * fade


def arch_point(x, phi, off=0.0, bumpy=True):
    """A point on the roof: an elliptical arch from the left rim (phi 0) over to the right (phi pi)."""
    fz = floor_z(x)
    y, z = -HW * math.cos(phi), fz + RIM_H + ARCH_H * math.sin(phi)
    ny, nz = -math.cos(phi) / HW, math.sin(phi) / ARCH_H
    n = math.hypot(ny, nz)
    d = off + (rough(x, phi) if bumpy else 0.0)
    return (x, y + ny / n * d, z + nz / n * d)


def build_roof(scene):
    SB = L1.BP.ShadedBatch
    # distinct stems: both texture names start "cave", and two batches sharing a stem overwrite each
    # other's meshes in the scene (the missing roof the first build shipped with)
    inner = {"caverock.tex": SB(scene, "roofrock", "caverock.tex", False),
             "cavevine.tex": SB(scene, "roofvine", "cavevine.tex", False)}
    shell = SB(scene, "shell", "sandst.tex", False)
    K = 16
    for a, b in TUNNELS:
        xs = list(np.arange(a, b, 3.0)) + [b]
        for i, (xa, xb) in enumerate(zip(xs, xs[1:])):
            # keep every drawn object compact: the engine decides per OBJECT where it is visible, so one
            # mesh spread along the whole run (the first build's vine pieces from three mouths) goes
            # missing in places. A new object every 15 m, and at each tunnel's ends.
            if i % 5 == 0:
                for t_ in inner.values():
                    t_.flush()
            near_mouth = min(xa - a, b - xb) < 10.0
            for j in range(K):
                pa, pb = math.pi * j / K, math.pi * (j + 1) / K
                q = [arch_point(xa, pa), arch_point(xb, pa), arch_point(xb, pb), arch_point(xa, pb)]
                uv = [(xa / 8, pa * 12 / 8), (xb / 8, pa * 12 / 8), (xb / 8, pb * 12 / 8), (xa / 8, pb * 12 / 8)]
                g = [light(p[0], 0.0) for p in q]
                centre = (0.5 * (xa + xb), 0.0, floor_z(0.5 * (xa + xb)) + RIM_H)
                t = inner["cavevine.tex" if near_mouth else "caverock.tex"]
                t.tri3([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], [g[0], g[1], g[2]], centre)
                t.tri3([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], [g[0], g[2], g[3]], centre)
    for a, b in TUNNELS:
        xs = list(np.arange(a, b, 3.0)) + [b]
        # the cover: the heightfield can't overhang, so over a tunnel there is no terrain -- draw a lid
        # from the ground on one side to the ground on the other, bulging only where the roof needs it
        E = HW + 2.5
        for i, (xa, xb) in enumerate(zip(xs[::2], xs[2::2] + ([xs[-1]] if len(xs) % 2 == 0 else []))):
            if i % 3 == 0:
                shell.flush()
            rows = []
            for x in (xa, xb):
                zl, zr = height(x, -E), height(x, E)
                row = []
                for k in range(9):
                    t = k / 8.0
                    y = -E + 2 * E * t
                    phi = math.acos(max(-1.0, min(1.0, -y / HW))) if abs(y) <= HW else (0.0 if y < 0 else math.pi)
                    need = floor_z(x) + RIM_H + ARCH_H * math.sin(phi) + 3.5 if abs(y) <= HW else -1e9
                    row.append((x, y, max(zl + (zr - zl) * t, need)))
                rows.append(row)
            for k in range(8):
                q = [rows[0][k], rows[1][k], rows[1][k + 1], rows[0][k + 1]]
                uv = [(p_[0] / 24.0, p_[1] / 24.0) for p_ in q]
                up = (0.5 * (xa + xb), 0.0, max(p_[2] for p_ in q) + 20.0)
                shell.tri3([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], [0.85] * 3, up)
                shell.tri3([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], [0.85] * 3, up)
    for t_ in inner.values():                                # close the last tunnel's pieces first
        t_.flush()
    # portals: a ring of rock from each open mouth's arch out to a rough outline
    vine = inner["cavevine.tex"]
    for x, facing in ((X_BACK, 1.0), (X_U0, -1.0), (X_T2_END, 1.0)):
        fz = floor_z(x)
        cz = fz + RIM_H
        for j in range(K):
            pa, pb = math.pi * j / K, math.pi * (j + 1) / K
            ia, ib = arch_point(x, pa, 0.0, False), arch_point(x, pb, 0.0, False)
            oa = (x, -(HW + 12.0) * math.cos(pa), cz + (ARCH_H + 9.0 + 2.5 * math.sin(7 * pa)) * math.sin(pa))
            ob = (x, -(HW + 12.0) * math.cos(pb), cz + (ARCH_H + 9.0 + 2.5 * math.sin(7 * pb)) * math.sin(pb))
            q = [ia, oa, ob, ib]
            uv = [(p[1] / 8, -p[2] / 8) for p in q]
            front = (x + 10.0 * facing, 0.0, cz)
            vine.tri3([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], [0.9] * 3, front)
            vine.tri3([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], [0.9] * 3, front)
        vine.flush()                                         # each portal its own object
    # the chute's back end: close the arch so nothing shows through behind the chaser
    cap = inner["caverock.tex"]
    x = CH_X_END
    c = (x, 0.0, floor_z(x) + RIM_H)
    for j in range(K):
        pa, pb = math.pi * j / K, math.pi * (j + 1) / K
        a_, b_ = arch_point(x, pa, 0.0, False), arch_point(x, pb, 0.0, False)
        cap.tri3([c, a_, b_], [(0, 0), (1, 0), (1, 1)], [0.3] * 3, (x + 10.0, 0.0, c[2]))
    # stalactites, clear of the chaser's path
    rng = random.Random(1936)
    for t_ in inner.values():
        t_.flush()
    st = L1.BP.ShadedBatch(scene, "stal", "caverock.tex", False)
    count = 0
    for a, b in TUNNELS:
        xs_st = sorted(rng.uniform(a + 6.0, b - 6.0) for _ in range(int((b - a) / 4.0)))
        last = None
        for x in xs_st:
            if last is None or x - last > 30.0:
                st.flush()
                last = x
            phi = rng.uniform(0.28 * math.pi, 0.72 * math.pi)
            root = np.array(arch_point(x, phi, 0.4))
            y, fz = root[1], floor_z(x)
            clear = fz + (CHASER_R + math.sqrt(CHASER_R ** 2 - y * y) if abs(y) < CHASER_R else RIM_H) + 0.8
            L = min(rng.uniform(1.2, 4.0), root[2] - clear)
            if L < 0.8:
                continue
            rad = L * rng.uniform(0.22, 0.34)
            tip = root - np.array([0.0, 0.0, L])
            ring = [root + np.array([rad * math.cos(2 * math.pi * k / 6), rad * math.sin(2 * math.pi * k / 6), 0.0])
                    for k in range(6)]
            g = light(x, 0.0) * 0.85
            for k in range(6):
                p0, p1 = ring[k], ring[(k + 1) % 6]
                mid = (p0 + p1) / 2
                out = tuple(mid + (mid - np.array([root[0], root[1], mid[2]])) * 3)
                st.tri3([tuple(p0), tuple(p1), tuple(tip)], [(0, 0), (0.3, 0), (0.15, 0.6)], [g, g, g * 0.8], out)
            count += 1
    for t in list(inner.values()) + [shell, st]:
        t.flush()
    return count


U_CORRIDOR = 8.0     # track.ild field 5 inside the U. A reset lands field5/2 - 2.5 m LEFT of the line, so
                     # the road-width 24 put reset cars 9.5 m left, up the U's wall (seen in game); 8 puts
                     # them 1.5 m left, on the flat floor, and still counts the whole floor as track.


def fit_corridor(e):
    """Set track.ild's corridor per waypoint: U_CORRIDOR along the U, the road width elsewhere."""
    line = ili.parse_line(envelope.build(e.tag, e.version, e.payload))
    vals = []
    for r in line.records:
        x, y = -r[ili.FIELD_X], -r[ili.FIELD_Z]              # game frame -> source frame
        vals.append(U_CORRIDOR if abs(y) < 1.0 and u_mask(x) > 0.5 else 2 * HW)
    line.set_field(ili.FIELD_CORRIDOR, vals)
    e.payload = envelope.parse(ili.build(line)).payload
    print(f"corridor: {sum(v == U_CORRIDOR for v in vals)} of {len(vals)} waypoints at {U_CORRIDOR} m (the U), the rest {2 * HW}")


def wall_boxes(template):
    prims = []
    for ln in boundaries():
        d = densify(ln, SEG)
        for (x0, y0), (x1, y1) in zip(d, d[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            ux, uy = (x1 - x0) / L, (y1 - y0) / L
            nx, ny = -uy, ux
            zs = [height(x0 + (x1 - x0) * t + nx * s, y0 + (y1 - y0) * t + ny * s)
                  for t in np.linspace(0, 1, 10) for s in (-0.6, 0.6)]
            lo, hi = min(zs), max(zs)
            a = (x0 - ux * 0.5, y0 - uy * 0.5)
            b = (x1 + ux * 0.5, y1 + uy * 0.5)
            top = max(lo + WALL_H, hi + 2.0)
            prims.append(sol.box_from_segment(template, bc.game((a[0], a[1], lo - 2.0)), bc.game((b[0], b[1], lo - 2.0)),
                                              height=top - lo + 2.0, thickness=0.6))
    return prims


def centreline():
    pts = [(x, 0.0) for x in np.arange(START_X, X_BOT_C + 0.01, 10.0)]
    pts += arc(X_BOT_C, 40.0, TURN_R, -math.pi / 2, math.pi / 2, 10.0)[1:-1]
    pts += [(x, Y_RET) for x in np.arange(X_BOT_C - 0.3, X_TOP_C - 0.01, -10.0)]
    pts += arc(X_TOP_C, 40.0, TURN_R, math.pi / 2, 3 * math.pi / 2, 10.0)[1:-1]
    pts += [(x, 0.0) for x in np.arange(X_TOP_C + 9.7, START_X - 10.0 + 0.01, 10.0)]
    return [(float(x), float(y), height(x, y)) for x, y in pts]


def boulders():
    """(x, y) of each boulder: the chaser at the top of its run-in, the ambushes at the tops of theirs."""
    out = [(CH_X_TOP + 2.0, 0.0)]
    for a in AMB:
        out.append((a["x"], -HW - a["len"]))
    return out


def path_slope(x0, y0, dx, dy):
    """Slope (degrees, downhill positive) along a straight path from (x0, y0), as boulder_sim wants it."""
    def f(d):
        za, zb = height(x0 + dx * d, y0 + dy * d), height(x0 + dx * (d + 0.5), y0 + dy * (d + 0.5))
        return math.degrees(math.atan2(za - zb, 0.5))
    return f


def report():
    (bx, by), rs = boulders()[0], boulder_radii()
    for r_x, label in ((BACK_SLOT_X, "slot 8"),):
        s = boulder_sim.run(BOULDER_MASS, rs[0], path_slope(bx, by, 1.0, 0.0), r_x - bx - rs[0])
        print(f"chaser: reaches {label} (x {r_x:.0f}) at {s[-1][0]:.1f} s, {s[-1][2] * 2.237:.0f} mph; green at {GREEN} s")
    for k, a in enumerate(AMB):
        x, y = boulders()[k + 1]
        s = boulder_sim.run(BOULDER_MASS, rs[k + 1], path_slope(x, y, 0.0, 1.0), -HW - y)
        print(f"ambush {k + 1}: x {a['x']:.0f}, chute {a['len']:.0f} m, reaches the road at {s[-1][0]:.1f} s "
              f"({s[-1][2] * 2.237:.0f} mph); leaders there at {a['t']:.1f} s")


def boulder_radii():
    return [CHASER_R] + [BOULDER_R] * len(AMB)


def main():
    report()
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=HW)
    grid = []
    for k in range(8):
        (gx, gy, _), (tx, ty) = line.at(line.L - 12.0 - GRID_ROW * k)
        lat = GRID_LAT
        grid.append((gx - ty * lat, gy + tx * lat, height(gx - ty * lat, gy + tx * lat)))
    scene.grid = grid
    nt, npts = build_floor(scene)
    nst = build_roof(scene)
    names = [o.name for o in scene.driveables + scene.scenery]
    if len(names) != len(set(names)):
        raise SystemExit("two meshes share a name, so one overwrote the other: " + ", ".join(sorted({n for n in names if names.count(n) > 1})))
    print(f"cave: roofs over {len(TUNNELS)} tunnels, {nst} stalactites")
    trackgen.add_ground(scene, texture="sandst.tex", margin=600.0, drop=2.0)
    scene.colours["ground.mod"] = [bytes([150, 150, 150, 255])] * 4
    a = B.Batch(scene, "banc", "boulder.tex", False)       # a buried anchor, so boulder.tex ships
    a.tri([(0, 20, -5), (0.1, 20, -5), (0, 20.1, -5)], [(0.5, 0.5)] * 3, 1.0)
    a.flush()
    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables)
    print(f"points {npts}, floor triangles {nt}; collision {collide}; largest chunk {biggest}; "
          f"surfaces {len(drawn)}; lap {line.L:.0f} m")
    if biggest > B.MAX_VERTS or collide > 16500:
        raise SystemExit("over budget")
    trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                        textures={t: "asph.tex" for t in wanted}, closed=True, corridor=2 * HW)
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    fit_corridor(by["track.ild"])
    for name in sorted(wanted):
        arr = np.array(TEXTURES[name]().convert("RGB"))
        arr[..., :3] = np.maximum(arr[..., :3], 6)
        enc = envelope.parse(tex.encode_to_tex(Image.fromarray(arr).tobytes(), arr.shape[1], mode="opaque", wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = L1.BP.sunny_sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for cx, cy, cz, tx_, ty_ in ((-100.0, -40.0, H + 40.0, 0.0, 0.0), (120.0, 40.0, H + 10.0, 160.0, -40.0),
                                 (300.0, 40.0, 60.0, 330.0, -30.0), (470.0, 30.0, 40.0, 560.0, 0.0),
                                 (250.0, 110.0, 80.0, 250.0, 80.0)):
        gpos = bc.game((cx, cy, cz))
        gtgt = bc.game((tx_, ty_, height(tx_, ty_)))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    for mname, r, seed in (("boulder.mod", BOULDER_R, 11), ("chaser.mod", CHASER_R, 23)):
        menv = envelope.parse(mod.build(make_boulder.boulder_mesh(r, seed=seed)))
        ent.append(archive.ArchiveEntry(name=mname, tag=menv.tag, version=menv.version, payload=menv.payload))
    donor_sol = {e.name.lower(): e for e in archive.read(bc.DONOR)}["track.sol"]
    ds = sol.parse(envelope.build(donor_sol.tag, donor_sol.version, donor_sol.payload))
    prims = wall_boxes(sol.wall_template(ds))
    e = next(x for x in ent if x.name.lower() == "track.sol")
    ver = sol.parse(envelope.build(e.tag, e.version, e.payload)).version
    index, tail = sol.build_spatial_index(prims)
    env = envelope.parse(sol.build(sol.Sol(primitives=prims, index=index, tail=tail, version=ver)))
    e.tag, e.version, e.payload = env.tag, env.version, env.payload
    table = obt_mod.parse(envelope.build(by["track.obt"].tag, by["track.obt"].version, by["track.obt"].payload))
    recs = [r for r in table.records if r != obt_mod.TERMINATOR]
    for k, (x, y) in enumerate(boulders()):
        gx, _gh, gz = bc.game((x, y, 0.0))
        recs.append(f"obj obstacle ball {'chaser' if k == 0 else 'boulder'}.mod {gx:.6f},{gz:.6f}:0.0 {BOULDER_MASS:.6f}")
    table.records = recs + [obt_mod.TERMINATOR]
    by["track.obt"].payload = envelope.parse(obt_mod.build(table)).payload
    archive.write(ent, OUT)
    trackmap.install(OUT, OUT)
    out = DATA / f"{NAME}.tra"
    track.export_tra(OUT, out, layout="flat")
    print(f"{out.name}: {len(prims)} wall boxes, {len(boulders())} boulders; {out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
