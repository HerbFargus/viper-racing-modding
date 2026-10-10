"""Coliseum: a Bemidji-sized banked oval under a stadium dome open to the night sky, with a
gap jump in the infield and a drop of giant coloured balls.

THE OVAL is measured off stock Bemidji (measure_bemidji.py) without its S-bends: 28 m of
road, two 180-degree turns at 215 m radius banked 16.7 degrees (easing in over 140 m), and
433 m straights. The banking pivots on the inside edge, so the infield is flat and the
outside of the turns rises 8.4 m. Beyond a 4 m verge at the road's outer edge, RAKED STANDS
rise to 20 m at the dome wall, painted as neon seat sections -- a drivable slope (about 18
degrees on the straights), so nothing gets stuck behind the road. Everything
is concrete-grade grip, so you can cut into the infield at speed.

THE RAMPS are a gap jump in the middle of the infield: two curved ramps, 52 m long, 28 m wide
and 14 m tall at the lip, lips facing each other across a 115 m gap along the long axis. The
profile is H * f^1.6, so the slope starts at zero -- no sudden angle to clip the tyres -- and
steepens to about 23 degrees at the lip; behind the lip the ramp slopes back down to the
floor over 20 m (a sheer drop there acted as a wall). Each is the other's landing ramp: launch off one at
about 100 mph (on the approach) and you come down softly on the far one's downslope, from
either direction; the crest is rounded so a car landing on it isn't jolted.

THE DOME is an ellipsoid over a 25 m wall: 1,000 x 570 m at the base, rising toward an 80 m
crown -- but OPEN from 62% of the way in, onto a starry night sky. The roof is a steel-ribbed
stadium roof with floodlight rings, drawn on both faces so it still shows from above. Its COLLISION is a
separate shell of .sol boxes (which the AI ignores and which don't count toward the 512
physics objects): the base wall runs up to where the roof leans in, then the roof steps
inward in flat treads and upright risers, always a little inside the drawn roof so nothing
pokes through it.

THE BALLS are 60 of the 16 m beach balls (mass 40), dropped the engine's 4 m at the start.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ballroom"))
sys.path.insert(0, str(HERE.parent / "circuit"))
import build_ballroom as B  # noqa: E402  (Batch, beach balls, bc, vrmod)
from build_river import delaunay  # noqa: E402
from art import colourise, tile_noise, to_img  # noqa: E402

bc = B.bc
from vrmod import archive, camtab, envelope, mod, obt as obt_mod, sky, sol, tex, track, trackbuild, trackgen, trackmap  # noqa: E402
from vrmod.trackgen import ROAD  # noqa: E402

DATA = B.DATA
NAME = "Coliseum"
OUT = HERE / f"{NAME}.trk"
SLOT = "bemidji"
SEED = 1976                                         # the Montreal Olympic Stadium's roof, at last

# ---- the oval (source frame: x east, y north, z up; anticlockwise) -------------------
SL, R, HW = 216.5, 215.0, 14.0                      # half-straight, turn radius, road half-width
SHIFT = 3.7                                         # no waypoint at x = 0 (the world origin rule)
BANK = math.radians(16.7)
EASE = 70.0                                         # banking eases in over +-70 m of the turn entry
START_X = -SL + 80.0                                # start line, on the bottom straight
CORRIDOR = 30.0                                     # Bemidji's track.ild corridor

# ---- ramps --------------------------------------------------------------------------
RAMP_LEN, RAMP_H, RAMP_HALF_W, RAMP_GAP = 52.0, 14.0, 14.0, 115.0   # gap: sized for ~100 mph approaches (size_ramps3.py)
RAMP_BACK = 20.0                                    # the lip's back slope: 14 m down over 20 m, 35 deg
RAMP_CREST = 2.5                                    # the crest is rounded over +-2.5 m of the lip

# ---- the stands ------------------------------------------------------------------------
STAND_VERGE = 4.0                                   # a flat verge beside the road before they rise
STAND_TOP = 20.0                                    # their height at the wall (the wall is 25 m)...
STAND_MAX = math.radians(25.0)                      # ...unless that's steeper than this: in the four
                                                    # corners the wall comes within 12 m of the road
SEAT_TILE_U, SEAT_TILE_V = 36.0, 9.6                # one seats.tex tile: 3 sections by 4 rows of 2.4 m
RAMP_POW = 1.6                                      # profile H * f^p: flat at the foot, ~23 deg at the lip

# ---- the dome ------------------------------------------------------------------------
DA, DB = 500.0, 285.0                               # base ellipse semi-axes
WALL, TOP = 25.0, 80.0                              # wall height, crown height
OPEN = 0.62                                         # the roof is open inside this (normalised) radius
RINGS = [1.0, 0.995, 0.985, 0.97, 0.95, 0.92, 0.88, 0.83, 0.77, 0.7, OPEN]
LIGHT_RINGS = {5, 8}                                # these bands carry the floodlights
LIP = 3.0                                           # the opening's rim stands this tall
SEGS = 72
SHELL = [0.995, 0.97, 0.9, 0.8, 0.7, OPEN]          # collision terraces (see shell_prims); none over the opening
CLEAR = 1.0                                         # every solid stays this far under the DRAWN roof

# ---- balls ---------------------------------------------------------------------------
B.BALL_R, B.BALL_MASS = 8.0, 40.0
N_BALLS, BALL_GAP = 60, 18.5
MAX_VERTS = B.MAX_VERTS


def smoothstep(a, b, x):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def smootherstep(a, b, x):
    """C2-continuous: the banking's rate of change eases in and out too, not only the bank."""
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0, 1)
    return t * t * t * (t * (6 * t - 15) + 10)


def roof_z(rho):
    return WALL + (TOP - WALL) * math.sqrt(max(0.0, 1.0 - rho * rho))


def drawn_z(rho):
    """The DRAWN roof's height over normalised radius rho: straight panels between RINGS, so it
    sags below roof_z between rings -- the collision shell has to clear this, not the curve."""
    rings = RINGS
    for r0, r1 in zip(rings, rings[1:]):
        if r1 <= rho <= r0:
            f = (r0 - rho) / (r0 - r1)
            return roof_z(r0) + f * (roof_z(r1) - roof_z(r0))
    return roof_z(min(rho, 1.0))


def shell_top(rho):
    return drawn_z(rho) - CLEAR


def dome_rho(x, y):
    return math.hypot(x / DA, y / DB)


# ---- the oval, analytically ------------------------------------------------------------
L_LAP = 4 * SL + 2 * math.pi * R


def locate(x, y):
    """(s along the lap from the bottom straight's west end, lateral OUTWARD, turn-ness 0..1)."""
    xp = x - SHIFT
    if abs(xp) <= SL:
        if y < 0:                                     # bottom straight, heading east
            s, lat = xp + SL, -y - R
        else:                                         # top straight, heading west
            s, lat = 2 * SL + math.pi * R + (SL - xp), y - R
        d_in = abs(xp) - SL                           # negative: metres short of a turn
    else:
        cx = SL if xp > 0 else -SL
        th = math.atan2(y, xp - cx)
        lat = math.hypot(xp - cx, y) - R
        if xp > 0:                                    # right turn, -90 .. +90 degrees
            s = 2 * SL + R * (th + math.pi / 2)
            into = R * (th + math.pi / 2)
        else:                                         # left turn, +90 .. 270 degrees
            th = th % (2 * math.pi)
            s = 4 * SL + math.pi * R + R * (th - math.pi / 2)
            into = R * (th - math.pi / 2)
        d_in = min(into, math.pi * R - into)
    return s % L_LAP, lat, float(smootherstep(-EASE, EASE, d_in))


def point_at(s):
    """(x, y, heading) on the centreline at arc length s."""
    s %= L_LAP
    if s < 2 * SL:
        return -SL + s + SHIFT, -R, (1.0, 0.0)
    s -= 2 * SL
    if s < math.pi * R:
        th = -math.pi / 2 + s / R
        return SL + R * math.cos(th) + SHIFT, R * math.sin(th), (-math.sin(th), math.cos(th))
    s -= math.pi * R
    if s < 2 * SL:
        return SL - s + SHIFT, R, (-1.0, 0.0)
    s -= 2 * SL
    th = math.pi / 2 + s / R
    return -SL + R * math.cos(th) + SHIFT, R * math.sin(th), (-math.sin(th), math.cos(th))


RAMPS = [                                            # (along-axis x0, x1, centre y, rising sign)
    (SHIFT - RAMP_GAP / 2 - RAMP_LEN, SHIFT - RAMP_GAP / 2, 0.0, +1),     # west: rises east to the gap
    (SHIFT + RAMP_GAP / 2, SHIFT + RAMP_GAP / 2 + RAMP_LEN, 0.0, -1),     # east: rises west to the gap
]


def ramp_profile(a):
    """Height at `a` metres along a ramp from its foot: the curved face H * f^p up to the lip
    at a = RAMP_LEN, then the back slope down to the floor over RAMP_BACK. The crest where they
    meet is ROUNDED -- a parabola tangent to both faces RAMP_CREST either side of the lip --
    because a sharp peak there jolted cars that landed on it."""
    L, H, r = RAMP_LEN, RAMP_H, RAMP_CREST
    s1 = H * RAMP_POW / L                                  # the face's slope at the lip
    s2 = -H / RAMP_BACK                                    # the back slope's
    if L - r <= a <= L + r:                                # the fillet
        t = a - (L - r)
        h0 = H * ((L - r) / L) ** RAMP_POW
        return h0 + s1 * t + (s2 - s1) / (4 * r) * t * t
    if a <= L:
        return H * max(0.0, a / L) ** RAMP_POW
    return max(0.0, H * (1 - (a - L) / RAMP_BACK))


def ramp_along(x, y):
    """(a, on_face) for a point over a ramp or its back slope -- `a` metres from that ramp's
    foot -- or None."""
    for x0, x1, yc, sign in RAMPS:
        if abs(y - yc) > RAMP_HALF_W:
            continue
        a = (x - x0) if sign > 0 else (x1 - x)
        if 0 <= a <= RAMP_LEN + RAMP_BACK:
            return a
    return None


def ramp_h(x, y):
    """Height over a ramp's FACE (foot to lip), else None."""
    a = ramp_along(x, y)
    return ramp_profile(a) if a is not None and a <= RAMP_LEN else None


def ramp_back(x, y):
    """Height over a ramp's gap-facing BACK slope, else None. It used to be a sheer drop
    squeezed into 0.6 m, and a near-vertical collision triangle acts as a wall for anything
    passing over it, however high: cars clearing the far lip still hit it."""
    a = ramp_along(x, y)
    return ramp_profile(a) if a is not None and a > RAMP_LEN else None


def height(x, y):
    r = ramp_h(x, y)
    if r is not None:
        return r
    r = ramp_back(x, y)
    if r is not None:
        return r
    _s, lat, w = locate(x, y)
    tb = math.tan(BANK * w)
    if lat <= -HW:
        return 0.0
    if lat <= HW:
        return (lat + HW) * tb
    st = stand_info(x, y)                               # the raked stands, up to the wall
    if st is not None:
        t, edge, _d, top = st
        return edge + (top - edge) * t
    return 2 * HW * tb                                  # the verge: level with the road's outer edge


def wall_lat(x, y, nx, ny):
    """Distance along (nx, ny) from (x, y) out to the dome's base ellipse."""
    a = (nx / DA) ** 2 + (ny / DB) ** 2
    b = 2 * (x * nx / DA ** 2 + y * ny / DB ** 2)
    c = (x / DA) ** 2 + (y / DB) ** 2 - 1
    return (-b + math.sqrt(max(0.0, b * b - 4 * a * c))) / (2 * a)


def stand_info(x, y):
    """(t, foot height, metres out from the foot, top height) for a point on the stands -- t 0 at
    their foot, STAND_VERGE beyond the road's outer edge, 1 at the wall -- or None if it isn't on
    them. The top is STAND_TOP, or lower where reaching it would be steeper than STAND_MAX."""
    s, lat, w = locate(x, y)
    foot = HW + STAND_VERGE
    if lat < foot - 1e-6:
        return None
    cx, cy, (tx, ty) = point_at(s)
    wl = wall_lat(cx, cy, ty, -tx)
    run = max(1.0, wl - foot)
    t = min(1.0, max(0.0, (lat - foot) / run))
    edge = 2 * HW * math.tan(BANK * w)
    return t, edge, lat - foot, min(STAND_TOP, edge + math.tan(STAND_MAX) * run)


# ---- art ----------------------------------------------------------------------------
def road_tex(size=256, seed=11):
    n = tile_noise(size, 16, 3, 0.5, seed)
    img = colourise(n, (52, 54, 58), (78, 80, 86))
    u = np.arange(size)[None, :] / size
    line = ((np.abs(u - 0.04) < 0.012) | (np.abs(u - 0.96) < 0.012))
    img[np.broadcast_to(line, img.shape[:2])] = [235, 235, 230]
    return to_img(img)


def floor_tex(size=256, seed=21):
    n = tile_noise(size, 8, 4, 0.5, seed)
    img = colourise(n, (150, 152, 150), (182, 184, 180))
    x = np.arange(size)[None, :] % 64
    y = np.arange(size)[:, None] % 64
    seam = (x < 2) | (y < 2)
    img[np.broadcast_to(seam, img.shape[:2])] = img[np.broadcast_to(seam, img.shape[:2])] * 0.8
    return to_img(img)


def ramp_tex(size=256, seed=51):
    """Stretched once over the whole ramp (u across, v from the foot to the lip): smooth grey
    concrete, a yellow line down each side, and a yellow band along the lip. Low contrast and
    no fine repeat, so it doesn't shimmer the way a tiled hazard pattern does at distance."""
    n = tile_noise(size, 4, 3, 0.5, seed)
    img = colourise(n, (118, 120, 124), (138, 140, 144))
    u = np.arange(size)[None, :] / size
    v = np.arange(size)[:, None] / size
    sides = np.broadcast_to((np.abs(u - 0.05) < 0.02) | (np.abs(u - 0.95) < 0.02), img.shape[:2])
    lip = np.broadcast_to(v > 0.92, img.shape[:2])
    img[sides | lip] = [226, 182, 40]
    return to_img(img)


def roof_tex(lamps=False, size=128, seed=31):
    n = tile_noise(size, 8, 3, 0.5, seed)
    img = colourise(n, (70, 78, 90), (96, 104, 118))
    u = np.arange(size)[None, :] / size
    v = np.arange(size)[:, None] / size
    rib = (u < 0.06) | (u > 0.94) | (v < 0.05) | (v > 0.95) | (np.abs(u - 0.5) < 0.015)
    img[np.broadcast_to(rib, img.shape[:2])] = [150, 156, 166]
    im = to_img(img)
    if lamps:
        d = ImageDraw.Draw(im)
        for k in range(3):
            cx = int(size * (0.22 + 0.28 * k))
            d.rectangle([cx - 9, size // 2 - 6, cx + 9, size // 2 + 6], fill=(255, 250, 225))
            d.rectangle([cx - 12, size // 2 - 9, cx + 12, size // 2 + 9], outline=(200, 200, 190))
    return im


def wall_tex(size=128, seed=41):
    n = tile_noise(size, 8, 3, 0.5, seed)
    img = colourise(n, (150, 150, 146), (178, 176, 170))
    v = np.arange(size)[:, None] / size
    band = (v > 0.72) & (v < 0.86)
    img[np.broadcast_to(band, img.shape[:2])] = [180, 40, 40]
    return to_img(img)


def night_sky(w=1024, h=512, seed=1976):
    """A starry night: deep blue-black, a faint milky-way band, stars, and a moon. The bottom
    edge is the horizon (hidden behind the dome's wall anyway)."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, h)[:, None]
    img = np.zeros((h, w, 3), np.float32)
    img[:] = (np.array([6, 8, 20]) * (1 - y) + np.array([18, 26, 52]) * y)[:, None, :].reshape(h, 1, 3)
    band = np.exp(-((np.linspace(0, 1, h)[:, None] - (0.35 + 0.15 * np.sin(np.linspace(0, 2 * np.pi, w))[None, :])) / 0.07) ** 2)
    noise = tile_noise(w, 32, 4, 0.55, seed)[:h, :w]
    img += (band * (0.5 + noise))[..., None] * np.array([28, 28, 40])
    for _ in range(2600):                                   # stars, mostly faint
        x, yy = rng.integers(0, w), rng.integers(0, int(h * 0.92))
        b = rng.choice([90, 140, 200, 255], p=[0.55, 0.25, 0.14, 0.06])
        tint = rng.choice([0, 1, 2])
        col = np.array([b, b, b], np.float32)
        col[tint] = min(255, b + 20)
        img[yy, x] = col
        if b == 255:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                img[min(h - 1, max(0, yy + dy)), (x + dx) % w] = col * 0.5
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.ellipse([700, 70, 736, 106], fill=(236, 234, 214))    # the moon
    d.ellipse([706, 76, 716, 86], fill=(214, 212, 196))
    return im


def check_tex(size=64):
    a = np.zeros((size, size, 3), np.uint8)
    for j in range(size):
        for i in range(size):
            a[j, i] = 245 if ((i // 8) + (j // 8)) % 2 else 20
    return Image.fromarray(a)


# ---- the neon infield (the user's pick of four mocked-up themes, mock_themes.py) ------------
CYAN, MAGENTA = (40, 190, 230), (240, 60, 190)


def _uv(size):
    return np.arange(size)[None, :] / size, np.arange(size)[:, None] / size


def _paint(img, mask, rgb, a=1.0):
    m = np.broadcast_to(mask, img.shape[:2]).astype(np.float32)[..., None] * a
    return img * (1 - m) + np.array(rgb, np.float32) * m


def neon_floor(size=256, seed=301):
    """Tiled every 32 m: dark with a glowing cyan line every 8 m (1.3 m wide, so it holds up
    at distance), and a soft halo round it."""
    u, v = _uv(size)
    img = colourise(tile_noise(size, 8, 3, 0.5, seed), (22, 24, 34), (34, 36, 50))
    line = (((u * 4) % 1.0) < 0.04) | (((v * 4) % 1.0) < 0.04)
    halo = (((u * 4) % 1.0) < 0.1) | (((v * 4) % 1.0) < 0.1)
    img = _paint(img, halo & ~line, CYAN, 0.18)
    return to_img(_paint(img, line, CYAN))


def neon_ramp(size=256, seed=311):
    """Stretched once over a ramp (u across, v foot -> lip): magenta edge lines, four big
    chevrons pointing up the slope, and a cyan lip."""
    u, v = _uv(size)
    img = colourise(tile_noise(size, 8, 3, 0.5, seed), (26, 26, 40), (38, 38, 56))
    img = _paint(img, (np.abs(u - 0.04) < 0.018) | (np.abs(u - 0.96) < 0.018), MAGENTA)
    for k in range(4):
        chev = np.abs((v - (0.18 + 0.2 * k)) - 0.35 * np.abs(u - 0.5)) < 0.018
        img = _paint(img, chev & (np.abs(u - 0.5) < 0.3), MAGENTA)
    return to_img(_paint(img, v > 0.95, CYAN))


def neon_wall(size=256, seed=321):
    """A ramp's side (v top -> bottom): dark, magenta trim along the top, cyan along the foot."""
    u, v = _uv(size)
    img = colourise(tile_noise(size, 8, 3, 0.5, seed), (22, 22, 34), (32, 32, 46))
    img = _paint(img, np.abs(v - 0.06) < 0.025, MAGENTA)
    return to_img(_paint(img, np.abs(v - 0.94) < 0.02, CYAN))


def neon_checker(size=256, seed=331, lo=(22, 24, 34), hi=(24, 110, 140)):
    """Tiled every 32 m: 8 m checks, dark navy and deep cyan (mock_checker.py). No thin lines,
    so nothing to break up or flicker at distance."""
    u, v = _uv(size)
    n = tile_noise(size, 8, 3, 0.5, seed)
    check = ((np.floor(u * 4) + np.floor(v * 4)) % 2).astype(bool)
    base = np.where(check[..., None], np.array(hi, np.float32), np.array(lo, np.float32))
    return Image.fromarray(np.clip(base * (0.92 + 0.16 * n[..., None]), 8, 255).astype(np.uint8))


def soft_checker(checks_per_tile=4, soft=0.35, size=256, seed=331, lo=(22, 24, 34), hi=(24, 110, 140)):
    """Tiled every 32 m: 8 m checks, dark navy and deep cyan, each square BLENDED into its
    neighbours over about a third of a check. Hard edges shimmered in game at a distance
    (moire); built from the product of two sine waves eased through zero, there are none.
    Chosen from mock_softcheck.py."""
    u, v = _uv(size)
    k = np.pi * checks_per_tile
    s = np.sin(k * u + 1e-3) * np.sin(k * v + 1e-3)
    t = np.clip(0.5 + s / (2 * np.sin(np.pi * soft / 2)), 0, 1)
    t = t * t * (3 - 2 * t)
    lo, hi = np.array(lo, np.float32), np.array(hi, np.float32)
    img = lo + (hi - lo) * t[..., None]
    n = tile_noise(size, 8, 3, 0.5, seed)
    return Image.fromarray(np.clip(img * (0.94 + 0.12 * n[..., None]), 8, 255).astype(np.uint8))


def soft_grid(spacing=16.0, sigma=2.6, halo=5.5, halo_amp=0.35, tile=32.0, size=256, seed=341,
              lo=(22, 24, 34), hi=CYAN):
    """Tiled every 32 m: a cyan grid line every 16 m, thick and BLURRED -- a Gaussian core about
    6 m across (sigma 2.6 m) inside a wider, fainter halo (sigma 5.5 m), with no hard edge
    anywhere, so nothing to shimmer at distance. Replaces the soft checks: bigger squares, and
    back to lines, at the user's call; then twice as thick and softer again."""
    u, v = _uv(size)
    m = tile / size                                        # metres per texel

    def dist(c):                                           # metres to the nearest line
        x = (c * tile) % spacing
        return np.minimum(x, spacing - x)

    def line(d):
        return np.minimum(1.0, np.exp(-(d / sigma) ** 2) + halo_amp * np.exp(-(d / halo) ** 2))

    glow = np.maximum(line(dist(u)), line(dist(v)))
    lo, hi = np.array(lo, np.float32), np.array(hi, np.float32)
    n = tile_noise(size, 8, 3, 0.5, seed)
    img = lo * (0.94 + 0.12 * n[..., None]) + (hi - lo) * glow[..., None]
    return Image.fromarray(np.clip(img, 8, 255).astype(np.uint8))


def glow_tiles():
    """The floor as the user picked it: soft_grid inverted -- deep-cyan panels about 10 m
    across, fading into soft navy 'grout' every 16 m (mock_invert.py, "invert_deep")."""
    return soft_grid(lo=(24, 110, 140), hi=(22, 24, 34))


TEXTURES = {"road.tex": road_tex, "floor.tex": glow_tiles, "ramp.tex": neon_ramp,
            "roof.tex": roof_tex, "roofl.tex": (lambda: roof_tex(True)), "wall.tex": wall_tex,
            "chequer.tex": check_tex, "rwall.tex": neon_wall}


# ---- the stands and the neon trim (mock_rake2.py "blocks", mock_stands.py) -----------------
def _glow(img, v, centre, width, rgb, strength=1.0):
    g = np.exp(-((v - centre) / width) ** 2)[..., None] * strength
    return img * (1 - g) + np.array(rgb, np.float32) * g


def seat_sections(size=256):
    """Empty seats: near-black seat rows on dark grey concrete steps -- four rows per tile, each seat
    back lit softly near its top -- with a pale aisle every 12 m. Deliberately quiet: the neon
    floor and ramps carry the colour. (Colour-striped sections competed with the floor.)"""
    u, v = _uv(size)
    row = (v * 4) % 1.0
    step = np.array([88, 90, 96], np.float32)                      # the concrete tread: dark grey
    seat = np.array([30, 32, 38], np.float32)                      # the seat backs: near black
    m = np.exp(-((row - 0.38) / 0.28) ** 2)                         # seats sit in the upper part of each row
    img = step * (1 - m[..., None]) + seat * m[..., None]
    img = img * (0.92 + 0.14 * np.exp(-((row - 0.3) / 0.12) ** 2))[..., None]   # a soft highlight on each seat
    uu = (u * 3) % 1.0
    aisle = np.exp(-(uu / 0.03) ** 2) + np.exp(-((uu - 1.0) / 0.03) ** 2)
    img = img * (1 - aisle[..., None]) + np.array([132, 134, 140], np.float32) * aisle[..., None]
    n = tile_noise(size, 8, 3, 0.5, 61)
    img = img * (0.95 + 0.1 * n[..., None])
    return Image.fromarray(np.clip(img, 8, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3.0))


def wall_neon(size=256, seed=41):
    """The dome's base wall, where it shows above the stands: concrete, a magenta glow along its
    top and a cyan one where the top row of seats meets it (v 0.02 = 25 m, 0.98 = the foot)."""
    img = colourise(tile_noise(size, 8, 3, 0.5, seed), (150, 150, 146), (178, 176, 170)).astype(np.float32)
    _u, v = _uv(size)
    img = _glow(img, v, 0.05, 0.035, MAGENTA)
    meet = 0.02 + (WALL - STAND_TOP) / (WALL + 0.5) * 0.96
    img = _glow(img, v, meet, 0.018, CYAN, 0.9)
    return Image.fromarray(np.clip(img, 8, 255).astype(np.uint8))


def rim_neon(size=64):
    """The rim of the roof opening: dark, with a soft cyan glow round it."""
    _u, v = _uv(size)
    img = np.broadcast_to(np.array([30, 32, 44], np.float32), (size, size, 3)).copy()
    img = _glow(img, v, 0.5, 0.18, CYAN)
    return Image.fromarray(np.clip(img, 8, 255).astype(np.uint8))


TEXTURES.update({"seats.tex": seat_sections, "wall.tex": wall_neon, "rimneon.tex": rim_neon})


# ---- the balls' colours -------------------------------------------------------------
# One solid colour per ball, twelve colours. A .mod has no vertex colours, so each colour is
# its own texture and mesh. The engine lights obstacles by their normals (mrModelDraw calls
# mrLightPlaceModel), and a gradient painted in -- bright at the top pole, darker toward the
# bottom -- deepens that. The paint turns with the ball, so it reads best at rest.
BALL_COLOURS = [(222, 38, 38), (245, 128, 20), (246, 212, 32), (150, 214, 40), (46, 172, 70), (24, 160, 150),
                (40, 196, 228), (70, 140, 236), (46, 70, 214), (132, 64, 210), (214, 52, 170), (244, 132, 178)]
BALL_RINGS, BALL_SEGS = 16, 24


def ball_tex(rgb, size=64):
    v = np.linspace(0, 1, size)[:, None]                  # 0 = top pole, 1 = bottom pole
    shade = 1.18 - 0.62 * v ** 1.2                        # 1.18 at the top, ~0.56 at the bottom
    img = np.array(rgb, np.float32)[None, None, :] * shade[..., None]
    img = np.broadcast_to(img, (size, size, 3))
    return Image.fromarray(np.clip(img, 12, 255).astype(np.uint8))


def ball_name(k):
    return f"bcol{k:02d}"


TEXTURES.update({f"{ball_name(k)}.tex": (lambda c=c: ball_tex(c)) for k, c in enumerate(BALL_COLOURS)})


# ---- the floor ------------------------------------------------------------------------
def floor_points(rng):
    pts = []
    n_st = int(L_LAP // 5)
    for k in range(n_st):
        x, y, (tx, ty) = point_at(k * L_LAP / n_st)
        nx, ny = ty, -tx                                     # outward: right of anticlockwise travel
        for lat in (-HW - 6, -HW - 2, -HW, -7, 0, 7, HW, HW + 2, HW + STAND_VERGE):
            px, py = x + nx * lat, y + ny * lat
            if dome_rho(px, py) < 0.995:
                pts.append((px, py))
        if k % 2 == 0:                                       # up the stands, every 10 m round the lap
            foot = HW + STAND_VERGE
            wl = wall_lat(x, y, nx, ny)
            for t in (0.2, 0.45, 0.7, 0.9):
                lat = foot + t * (wl - foot)
                pts.append((x + nx * lat, y + ny * lat))
    for x0, x1, yc, sign in RAMPS:                           # ramps: edges, with cliffs both sides of them
        lip_x = x1 if sign > 0 else x0
        alongs = list(np.linspace(x0, x1, 53))                 # every 1 m: the curve reads smooth
        alongs += [lip_x - sign * d for d in np.arange(0.5, RAMP_CREST + 0.01, 0.5)]   # the crest's face side
        for along in sorted({round(float(a), 4) for a in alongs}):    # (no duplicate points: Delaunay needs that)
            for dy in (-RAMP_HALF_W - 0.3, -RAMP_HALF_W + 0.3, -RAMP_HALF_W / 2, 0.0, RAMP_HALF_W / 2,
                       RAMP_HALF_W - 0.3, RAMP_HALF_W + 0.3):
                pts.append((along, yc + dy))
        lip = x1 if sign > 0 else x0                         # the back slope, lip to foot
        for along in [lip + sign * d for d in list(np.arange(0.5, RAMP_CREST + 0.01, 0.5))
                      + list(np.arange(RAMP_CREST + 1.0, RAMP_BACK + 0.01, 1.0))]:
            for dy in (-RAMP_HALF_W - 0.3, -RAMP_HALF_W + 0.3, -RAMP_HALF_W / 2, 0.0, RAMP_HALF_W / 2,
                       RAMP_HALF_W - 0.3, RAMP_HALF_W + 0.3):
                pts.append((along, yc + dy))
    for k in range(180):                                     # the floor's rim, under the wall
        a = 2 * math.pi * k / 180
        pts.append((DA * 0.999 * math.cos(a), DB * 0.999 * math.sin(a)))
    road_like = np.array(pts)
    for gx in np.arange(-DA, DA + 1, 28.0):                  # lattice elsewhere
        for gy in np.arange(-DB, DB + 1, 28.0):
            px, py = gx + rng.uniform(-5, 5), gy + rng.uniform(-5, 5)
            if dome_rho(px, py) >= 0.985:
                continue
            _s, lat, _w = locate(px, py)
            if lat > -HW - 12:                               # the infield only: the stands have their own
                continue
            if any(x0 - 6 <= px <= x1 + 6 and abs(py - yc) <= RAMP_HALF_W + 6 for x0, x1, yc, _ in RAMPS):
                continue
            if np.hypot(road_like[:, 0] - px, road_like[:, 1] - py).min() < 9:
                continue
            pts.append((px, py))
    return pts


def build_floor(scene, rng):
    pts = floor_points(rng)
    tris = delaunay(pts)
    Z = [height(x, y) for x, y in pts]
    batches = {"road": B.Batch(scene, "road", "road.tex", True), "floor": B.Batch(scene, "floor", "floor.tex", True),
               "ramp": B.Batch(scene, "ramp", "ramp.tex", True),
               "rwall": B.Batch(scene, "rwall", "rwall.tex", True),
               "stand": B.Batch(scene, "stand", "seats.tex", True)}
    counts = {k: 0 for k in batches}
    for t in tris:
        P = [(pts[i][0], pts[i][1], Z[i]) for i in t]
        cx, cy = sum(p[0] for p in P) / 3, sum(p[1] for p in P) / 3
        if dome_rho(cx, cy) > 1.0:
            continue
        s, lat, _w = locate(cx, cy)
        stands = [stand_info(p[0], p[1]) for p in P]
        if all(i is not None for i in stands):
            kind = "stand"                                # seat sections: u round the ring, v up the rake
            uv = []
            for p, (t, edge, d, _top) in zip(P, stands):
                sp = locate(p[0], p[1])[0]
                if abs(sp - s) > L_LAP / 2:                          # the lap's seam
                    sp += L_LAP if sp < s else -L_LAP
                uv.append((sp / SEAT_TILE_U, -math.hypot(d, p[2] - edge) / SEAT_TILE_V))
        elif ramp_h(cx, cy) is not None and all(ramp_h(p[0], p[1]) is not None for p in P):
            kind = "ramp"
            uv = []
            for p in P:                                   # once over the ramp: u across, v foot -> lip
                x0, x1, yc, sign = next(r for r in RAMPS if r[0] - 0.5 <= p[0] <= r[1] + 0.5)
                f = (p[0] - x0) / (x1 - x0) if sign > 0 else (x1 - p[0]) / (x1 - x0)
                uv.append((min(0.98, max(0.02, (p[1] - yc + RAMP_HALF_W) / (2 * RAMP_HALF_W))),
                           min(0.98, max(0.02, f))))
        elif (any(ramp_h(p[0], p[1]) is not None or ramp_back(p[0], p[1]) is not None for p in P)
              and max(p[2] for p in P) - min(p[2] for p in P) > 0.4):
            kind = "rwall"                                # a ramp's side or lip face: steep, part on it
            # u along the face (sides run along x, the lip face along y), v top -> bottom
            uv = [((p[0] + p[1]) / 14.0, min(0.98, max(0.02, 1.0 - p[2] / RAMP_H))) for p in P]
        elif -HW <= lat <= HW:
            kind = "road"
            uv = []
            for p in P:
                sp, lp, _ = locate(p[0], p[1])
                if abs(sp - s) > L_LAP / 2:                          # the lap's seam
                    sp += L_LAP if sp < s else -L_LAP
                uv.append((min(0.98, max(0.02, (lp + HW) / (2 * HW))), sp / 24.0))
        else:
            kind = "floor"
            uv = [(p[0] / 32.0, p[1] / 32.0) for p in P]
        grey = 0.92 if kind != "road" else 0.88
        batches[kind].tri(P, uv, grey)
        counts[kind] += 1
    for b in batches.values():
        b.flush()
    return counts


def add_start_line(scene):
    b = B.Batch(scene, "startln", "chequer.tex", False)
    x, y, _ = point_at(START_X + SL - SHIFT + SHIFT)          # s of the start line
    s0 = START_X + SL
    x, y, (tx, ty) = point_at(s0)
    nx, ny = ty, -tx
    q = [(x + nx * l + tx * d, y + ny * l + ty * d, height(x + nx * l, y + ny * l) + 0.05)
         for l, d in ((-HW, -1.5), (-HW, 1.5), (HW, 1.5), (HW, -1.5))]
    uv = [(0.02, 0.02), (0.98, 0.02), (0.98, 0.98), (0.02, 0.98)]
    b.tri(q[:3], uv[:3], 1.0)
    b.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 1.0)
    b.flush()


# ---- the dome -------------------------------------------------------------------------
def add_dome(scene):
    inside = (0.0, 0.0, 12.0)
    wall = B.Batch(scene, "dwall", "wall.tex", False)
    for k in range(SEGS):
        a0, a1 = 2 * math.pi * k / SEGS, 2 * math.pi * (k + 1) / SEGS
        p0, p1 = (DA * math.cos(a0), DB * math.sin(a0)), (DA * math.cos(a1), DB * math.sin(a1))
        q = [(p0[0], p0[1], -0.5), (p1[0], p1[1], -0.5), (p1[0], p1[1], WALL), (p0[0], p0[1], WALL)]
        uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        wall.tri([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], 0.85, up=inside)
        wall.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 0.85, up=inside)
    wall.flush()
    roof = {t: B.Batch(scene, "d" + t.split(".")[0], t, False) for t in ("roof.tex", "roofl.tex")}
    above = (0.0, 0.0, 3000.0)                         # the roof's outer face looks up at the sky
    for i in range(len(RINGS) - 1):
        r0, r1 = RINGS[i], RINGS[i + 1]
        z0, z1 = roof_z(r0), roof_z(r1)
        t = "roofl.tex" if i in LIGHT_RINGS else "roof.tex"
        grey = 1.0 if i in LIGHT_RINGS else 0.8
        for k in range(SEGS):
            a0, a1 = 2 * math.pi * k / SEGS, 2 * math.pi * (k + 1) / SEGS
            A = (DA * r0 * math.cos(a0), DB * r0 * math.sin(a0), z0)
            Bq = (DA * r0 * math.cos(a1), DB * r0 * math.sin(a1), z0)
            Cq = (DA * r1 * math.cos(a1), DB * r1 * math.sin(a1), z1)
            D = (DA * r1 * math.cos(a0), DB * r1 * math.sin(a0), z1)
            uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
            for face, g in ((inside, grey), (above, 0.55)):          # both faces: seen from above too
                roof[t].tri([A, Bq, Cq], [uv[0], uv[1], uv[2]], g, up=face)
                roof[t].tri([A, Cq, D], [uv[0], uv[2], uv[3]], g, up=face)
    for b in roof.values():
        b.flush()
    lip = B.Batch(scene, "dlip", "rimneon.tex", False)               # the opening's rim, both faces
    zr = roof_z(OPEN)
    for k in range(SEGS):
        a0, a1 = 2 * math.pi * k / SEGS, 2 * math.pi * (k + 1) / SEGS
        p0 = (DA * OPEN * math.cos(a0), DB * OPEN * math.sin(a0))
        p1 = (DA * OPEN * math.cos(a1), DB * OPEN * math.sin(a1))
        q = [(p0[0], p0[1], zr - 0.5), (p1[0], p1[1], zr - 0.5), (p1[0], p1[1], zr + LIP), (p0[0], p0[1], zr + LIP)]
        uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, zr)
        for face in ((0.0, 0.0, zr), (mid[0] * 2, mid[1] * 2, zr)):
            lip.tri([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], 0.9, up=face)
            lip.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 0.9, up=face)
    lip.flush()


def base_wall_quads():
    """The dome's base, solid up to where the roof leans in (the first shell terrace)."""
    quads = []
    n = 60
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        p0 = (DA * 0.995 * math.cos(a0), DB * 0.995 * math.sin(a0))
        p1 = (DA * 0.995 * math.cos(a1), DB * 0.995 * math.sin(a1))
        top = shell_top(SHELL[0])
        quads.append([(p0[0], p0[1], 0.0), (p1[0], p1[1], 0.0), (p1[0], p1[1], top), (p0[0], p0[1], top)])
    return quads


def roof_clear(p0, p1, width):
    """The highest a box on chord p0 -> p1, `width` across, may reach: CLEAR under the drawn
    roof at the lowest of its corners and edge midpoints."""
    n = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    nx, ny = -(p1[1] - p0[1]) / n, (p1[0] - p0[0]) / n
    pts = [(q[0] + nx * w, q[1] + ny * w) for q in (p0, ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2), p1)
           for w in (-width / 2, 0.0, width / 2)]
    return min(shell_top(min(0.995, dome_rho(*q))) for q in pts)


def flat_box(template, p0, p1, width, height, top):
    """A box on the source-frame chord p0 -> p1, `width` across and `height` tall, top at `top`."""
    return sol.box_from_segment(template, bc.game((p0[0], p0[1], top - height)),
                                bc.game((p1[0], p1[1], top - height)), height=height, thickness=width)


def shell_prims(template):
    """Terraces inward from the base wall: a flat tread across each ring band and an upright
    riser at its inner edge up to the next. Every piece's top comes from roof_clear over its
    own footprint, so no corner of the shell pokes through the drawn roof."""
    prims = []

    def at(rho, a):
        return (DA * rho * math.cos(a), DB * rho * math.sin(a))

    for k, r_out in enumerate(SHELL):
        r_in = SHELL[k + 1] if k + 1 < len(SHELL) else None
        if r_in is None:                                  # the opening: open to the sky
            break
        rm = (r_in + r_out) / 2
        perim = math.pi * (3 * (DA + DB) - math.sqrt((3 * DA + DB) * (DA + 3 * DB))) * rm
        n = max(16, int(round(perim / (30.0 if r_out > 0.9 else 60.0))))   # shorter where the roof is steep
        for j in range(n):
            a0, a1 = 2 * math.pi * j / n - 0.004, 2 * math.pi * (j + 1) / n + 0.004   # a little overlap
            am = (a0 + a1) / 2
            radius = math.hypot(DA * math.cos(am), DB * math.sin(am))
            span = (r_out - r_in) * radius
            # the tread: across the band, reaching 2 m inside r_in to lap over the riser
            t0, t1 = at(rm - 1.0 / radius, a0), at(rm - 1.0 / radius, a1)
            tread_top = roof_clear(t0, t1, span + 2.0)
            prims.append(flat_box(template, t0, t1, span + 2.0, 1.0, tread_top))
            # the riser at r_in: from under that tread up to just under the roof above it
            q0, q1 = at(r_in, a0), at(r_in, a1)
            top = roof_clear(q0, q1, 1.0)
            prims.append(flat_box(template, q0, q1, 1.0, max(1.0, top - (tread_top - 3.0)), top))
    return prims


# ---- balls ----------------------------------------------------------------------------
def ball_spots(rng):
    spots = []
    tries = 0
    while len(spots) < N_BALLS and tries < 200000:
        tries += 1
        if len(spots) < 0.3 * N_BALLS:                   # on the road, away from the grid
            s = rng.uniform(START_X + SL + 60, START_X + SL + L_LAP - 120)
            x, y, (tx, ty) = point_at(s)
            lat = rng.uniform(-HW + B.BALL_R, HW - B.BALL_R)
            x, y = x + ty * lat, y - tx * lat
        else:
            x, y = rng.uniform(-DA, DA), rng.uniform(-DB, DB)
            if dome_rho(x, y) > 0.9:
                continue
            _s, lat, _w = locate(x, y)
            if -HW - 12 < lat < HW + 20:
                continue
        # the jump lane: both ramps, the gap, and a 150 m run-up at each end
        if abs(y) <= 40 and abs(x - SHIFT) <= RAMP_GAP / 2 + RAMP_LEN + 150:
            continue
        if all(math.hypot(x - a, y - b) >= BALL_GAP for a, b in spots):
            spots.append((x, y))
    if len(spots) < N_BALLS:
        raise SystemExit(f"only placed {len(spots)} of {N_BALLS} balls")
    return spots


# ---- build ----------------------------------------------------------------------------
def main():
    rng = random.Random(SEED)
    n_line = int(L_LAP // 8)
    centre = []
    for k in range(n_line):
        s = START_X + SL + k * L_LAP / n_line
        x, y, _t = point_at(s)
        centre.append((x, y, height(x, y)))
    scene = trackgen.TrackScene(centreline=centre)
    line = bc.Line(centre)
    trackgen.add_checkpoints(scene, 4, half_width=HW + 2.0)
    grid = []
    for k in range(8):
        (gx, gy, gz), (tx, ty) = line.at(line.L - 16.0 - 10.0 * (k // 2))
        lat = 5.0 if k % 2 else -5.0
        grid.append((gx - ty * lat, gy + tx * lat, height(gx - ty * lat, gy + tx * lat)))
    scene.grid = grid
    counts = build_floor(scene, rng)
    add_start_line(scene)
    add_dome(scene)
    scene.walls = base_wall_quads()
    for k in range(len(BALL_COLOURS)):                   # anchors: the ball textures ship with the track
        a = B.Batch(scene, f"bank{k:02d}", f"{ball_name(k)}.tex", False)
        a.tri([(0, 0, -3), (0.1, 0, -3), (0, 0.1, -3)], [(0.5, 0.5)] * 3, 1.0)
        a.flush()
    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables)
    print(f"lap {L_LAP:.0f} m; floor triangles {counts}; largest chunk {biggest} verts; "
          f"collision triangles {collide}; surfaces {len(drawn)}; textures {sorted(wanted)}")
    if biggest > MAX_VERTS or collide > 16500:
        raise SystemExit("over budget")

    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True, corridor=CORRIDOR)
    print(f"assembled: {res.summary()}")
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        im = TEXTURES[name]()
        a = np.array(im)
        a[..., :3] = np.maximum(a[..., :3], 6)           # no black texels in an opaque texture
        im = Image.fromarray(a)
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), im.width, mode="opaque", wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = night_sky()                                  # through the open roof
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for k in range(6):
        a = 2 * math.pi * (k + 0.5) / 6
        pos = (DA * 0.9 * math.cos(a), DB * 0.9 * math.sin(a), 30.0)
        gpos, gtgt = bc.game(pos), bc.game((pos[0] * 0.3, pos[1] * 0.3, 2.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    for k in range(len(BALL_COLOURS)):
        mesh = B.ball_mesh(k, rings=BALL_RINGS, segs=BALL_SEGS, texture=f"{ball_name(k)}.tex")
        menv = envelope.parse(mod.build(mesh))
        ent.append(archive.ArchiveEntry(name=f"{ball_name(k)}.mod", tag=menv.tag, version=menv.version,
                                        payload=menv.payload))
    # the roof shell, onto the base wall the build already made
    e = next(x for x in ent if x.name.lower() == "track.sol")
    s0 = sol.parse(envelope.build(e.tag, e.version, e.payload))
    prims = list(s0.primitives) + shell_prims(sol.wall_template(s0))
    index, tail = sol.build_spatial_index(prims)
    env = envelope.parse(sol.build(sol.Sol(primitives=prims, index=index, tail=tail, version=s0.version)))
    e.tag, e.version, e.payload = env.tag, env.version, env.payload
    # the balls
    table = obt_mod.parse(envelope.build(by["track.obt"].tag, by["track.obt"].version, by["track.obt"].payload))
    recs = [r for r in table.records if r != obt_mod.TERMINATOR]
    spots = ball_spots(rng)
    for k, (x, y) in enumerate(spots):
        gx, _gh, gz = bc.game((x, y, 0.0))
        recs.append(f"obj obstacle ball {ball_name(k % len(BALL_COLOURS))}.mod {gx:.6f},{gz:.6f}:"
                    f"{rng.uniform(0, 360):.1f} {B.BALL_MASS:.6f}")
    table.records = recs + [obt_mod.TERMINATOR]
    by["track.obt"].payload = envelope.parse(obt_mod.build(table)).payload
    archive.write(ent, OUT)
    trackmap.install(OUT, OUT)
    out = DATA / f"{NAME}.tra"
    track.export_tra(OUT, out, layout="flat")
    print(f"{out.name}: {len(prims)} solids ({len(s0.primitives)} base wall), {len(spots)} balls, "
          f"{out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
