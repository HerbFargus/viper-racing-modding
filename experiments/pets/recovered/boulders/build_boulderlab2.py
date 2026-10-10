"""Boulder Lab 2: does a steeper slope make a boulder faster, and is a steep run-up chute worth it?

Five walled lanes side by side, each 30 m wide, all starting from the same top plateau (120 m up)
and ending on the same flat runout. In each, one red boulder (8 m, mass 30,000), released at race
start:
    lane A  5 degrees all the way            lane B  10 degrees
    lane C  15 degrees                       lane D  20 degrees
    lane E  CHUTE: 40 degrees, 50 m high, starting behind the plateau, then 10 degrees (as B)
Distance boards every 100 m in each lane, counted from that lane's boulder; signs over each lane
at the top. The lap runs down lane B and back up a 5-degree return road, but every lane opens off
the plateau, so you can drive down any of them and pace its boulder.

The lanes end at different heights, so their dividing walls are .sol boxes built here, one per
25 m section, each spanning from under the lower floor to 10 m above the higher one.
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_boulderlab as L1  # noqa: E402  (art, B, bc, fonts)

B, bc = L1.B, L1.bc
from build_river import delaunay  # noqa: E402
from vrmod import archive, camtab, envelope, mod, obt as obt_mod, sky, sol, tex, track, trackbuild, trackgen, trackmap  # noqa: E402

# `python build_boulderlab2.py [NAME MASS]`: Lab 3 is the same track with 100,000 lb boulders.
NAME = sys.argv[1] if len(sys.argv) > 2 else "BoulderLab2"
OUT = HERE / f"{NAME}.trk"
DATA = B.DATA
SLOT = "hastings"

H = 120.0                                              # the top plateau
X_TOP, X_BOT = -150.0, 1600.0                          # the field's ends
X_SEP0, X_SEP1 = -5.0, 1400.0                          # dividing walls run between these
SMOOTH = 24.0                                          # every change of slope is eased over this
DX = 0.5
CHUTE_DEG, CHUTE_RUN, CHUTE_BACK = 40.0, 60.0, -75.0   # the chute: 40 deg over 60 m, block back at -75

# lanes: (label, y_low, y_high, slope deg, chute?)
LANES = [("5°", -30.0, 0.0, 5.0, False), ("10°", -60.0, -30.0, 10.0, False), ("15°", -90.0, -60.0, 15.0, False),
         ("20°", -120.0, -90.0, 20.0, False), ("CHUTE", -150.0, -120.0, 10.0, True)]
RETURN = (0.0, 35.0, 5.0)                              # the return road: y band, slope
BOULDER_X, CHUTE_BOULDER_X = 12.0, -50.0
BOULDER_R, BOULDER_MASS = 4.0, float(sys.argv[2]) if len(sys.argv) > 2 else 30000.0
WALL_H, SEG = 10.0, 25.0
Y_LAP_DOWN, Y_LAP_UP = -45.0, 17.5                     # the lap: down lane B, up the return road
X_TURN_TOP, X_TURN_BOT = -100.0 - 0.3, 1450.0 - 0.3    # turn centres (off the 10 m grid: origin rule)

XS = np.arange(X_TOP, X_BOT + DX / 2, DX)


def profile(deg, chute=False):
    """Heights along x for a lane: its raw slope schedule, eased with a moving average (which
    keeps the total drop exact), integrated up from 0 at the bottom."""
    t = math.tan(math.radians(deg))
    x_end = H / t
    raw = np.where((XS >= 0) & (XS <= x_end), t, 0.0)
    if chute:
        raw = np.where((XS >= -CHUTE_RUN) & (XS < 0), math.tan(math.radians(CHUTE_DEG)), raw)
    k = int(SMOOTH / DX)
    sm = np.convolve(raw, np.ones(k) / k, mode="same")
    z = np.cumsum((sm * DX)[::-1])[::-1]
    z = z - z[-1]
    if chute:
        z = np.where(XS < CHUTE_BACK, H, z)                 # behind the chute: the plateau again
    return z


PROFILES = [profile(deg, ch) for _l, _a, _b, deg, ch in LANES]
RET_PROFILE = profile(RETURN[2])


def band_profile(y):
    if y >= RETURN[0]:
        return RET_PROFILE
    for (lab, lo, hi, _d, _c), prof in zip(LANES, PROFILES):
        if lo <= y < hi:
            return prof
    return PROFILES[-1]


def height(x, y):
    return float(np.interp(x, XS, band_profile(y)))


def dist_along(prof, x0, x1):
    i0, i1 = np.searchsorted(XS, [x0, x1])
    xs, zs = XS[i0:i1 + 1], prof[i0:i1 + 1]
    return float(np.sum(np.hypot(np.diff(xs), np.diff(zs))))


def x_at_dist(prof, x0, d):
    i0 = int(np.searchsorted(XS, x0))
    seg = np.hypot(np.diff(XS[i0:]), np.diff(prof[i0:]))
    cum = np.concatenate([[0], np.cumsum(seg)])
    j = int(np.searchsorted(cum, d))
    return float(XS[min(i0 + j, len(XS) - 1)])


# ---- art ----------------------------------------------------------------------------------------
def sign_tex(text, size=256):
    im = Image.new("RGB", (size, size // 2 * 2), (30, 34, 44))
    d = ImageDraw.Draw(im)
    d.rectangle([4, 4, size - 5, size - 5], outline=(210, 50, 50), width=8)
    f = L1._font(96 if len(text) > 3 else 130)
    bb = d.textbbox((0, 0), text, font=f)
    d.text(((size - (bb[2] - bb[0])) / 2 - bb[0], (size - (bb[3] - bb[1])) / 2 - bb[1]), text, fill=(245, 245, 240), font=f)
    return im


DISTS = list(range(100, 1501, 100))
SIGNS = {f"sgn{k}.tex": lab for k, (lab, *_r) in enumerate(LANES)}
TEXTURES = {"labflr.tex": L1.floor_tex, "labwall.tex": L1.wall_tex, "chequer.tex": L1.TEXTURES["chequer.tex"],
            "bld3.tex": L1.TEXTURES["bld3.tex"]}
TEXTURES.update({f"d{d:04d}.tex": (lambda d=d: L1.board_tex(str(d))) for d in DISTS})
TEXTURES.update({n: (lambda t=t: sign_tex(t)) for n, t in SIGNS.items()})


# ---- geometry ---------------------------------------------------------------------------------------
def floor_points():
    xs = set(np.round(np.arange(X_TOP, X_BOT + 0.1, 10.0), 3))
    blends = [0.0, -CHUTE_RUN, CHUTE_BACK] + [H / math.tan(math.radians(d)) for *_x, d, _c in LANES] + \
             [H / math.tan(math.radians(RETURN[2]))]
    pts = []
    bands = [(lo, hi) for _l, lo, hi, _d, _c in LANES] + [(RETURN[0], RETURN[1])]
    for lo, hi in bands:
        ys = [lo + 0.3, lo + 7.5, (lo + hi) / 2, hi - 7.5, hi - 0.3]
        extra = set()
        for b in blends:
            extra |= set(np.round(np.arange(b - SMOOTH, b + SMOOTH + 0.1, 3.0), 3))
        if lo == LANES[-1][1]:
            extra |= {CHUTE_BACK - 0.3, CHUTE_BACK + 0.3}
        for x in sorted(xs | extra):
            if X_TOP <= x <= X_BOT:
                pts += [(float(x), y) for y in ys]
    return pts


def build_floor(scene):
    pts = floor_points()
    tris = delaunay(pts)
    floor = B.Batch(scene, "floor", "labflr.tex", True)
    for t in tris:
        P = [(pts[i][0], pts[i][1], height(pts[i][0], pts[i][1])) for i in t]
        cx, cy = sum(p[0] for p in P) / 3, sum(p[1] for p in P) / 3
        # a triangle spanning two lanes is a cliff face between them: draw it, but it's under a wall
        floor.tri(P, [(p[0] / 64.0, p[1] / 64.0) for p in P], 0.95)
    floor.flush()
    return len(tris)


def wall_runs():
    """(y, x0, x1) for every wall: the dividers, the chute block's back, and the outer walls."""
    runs = [(0.0, X_SEP0, X_SEP1)] + [(hi, X_SEP0 if k < len(LANES) - 1 else CHUTE_BACK, X_SEP1)
                                     for k, (_l, lo, hi, _d, _c) in enumerate(LANES) if hi < 0]
    runs += [(RETURN[1], X_TOP, X_BOT), (LANES[-1][1], X_TOP, X_BOT)]
    return runs


def wall_boxes(template):
    prims = []

    def box(p0, p1, bottom, top):
        return sol.box_from_segment(template, bc.game((p0[0], p0[1], bottom)), bc.game((p1[0], p1[1], bottom)),
                                    height=top - bottom, thickness=0.6)

    def span(x0, x1, y):
        xs = np.linspace(x0, x1, 12)
        zs = [height(x, y + s) for x in xs for s in (-0.6, 0.6)]
        return min(zs) - 2.0, max(zs) + WALL_H

    for y, x0, x1 in wall_runs():                           # along x
        n = max(1, int(math.ceil((x1 - x0) / SEG)))
        for k in range(n):
            a, b = x0 + (x1 - x0) * k / n, x0 + (x1 - x0) * (k + 1) / n
            lo, hi = span(a, b, y)
            prims.append(box((a - 0.5, y), (b + 0.5, y), lo, hi))
    ends = [(X_TOP, LANES[-1][1], RETURN[1]), (X_BOT, LANES[-1][1], RETURN[1]),
            (CHUTE_BACK, LANES[-1][1], LANES[-1][2])]
    for x, y0, y1 in ends:                                  # across y
        n = max(1, int(math.ceil((y1 - y0) / SEG)))
        for k in range(n):
            a, b = y0 + (y1 - y0) * k / n, y0 + (y1 - y0) * (k + 1) / n
            zs = [height(x + s, y) for y in np.linspace(a, b, 8) for s in (-0.6, 0.6)]
            prims.append(box((x, a - 0.5), (x, b + 0.5), min(zs) - 2.0, max(zs) + WALL_H))
    return prims


def draw_walls(scene):
    wb = B.Batch(scene, "wall", "labwall.tex", False)

    def quad(p0, p1, face):
        (x0, y0, lo0, hi0), (x1, y1, lo1, hi1) = p0, p1
        q = [(x0, y0, lo0), (x1, y1, lo1), (x1, y1, hi1), (x0, y0, hi0)]
        uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        wb.tri([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], 0.85, up=face)
        wb.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 0.85, up=face)

    for y, x0, x1 in wall_runs():
        n = max(1, int(math.ceil((x1 - x0) / 10.0)))
        for k in range(n):
            a, b = x0 + (x1 - x0) * k / n, x0 + (x1 - x0) * (k + 1) / n
            ends = []
            for x in (a, b):
                zs = (height(x, y - 0.6), height(x, y + 0.6))
                ends.append((x, y, min(zs) - 0.5, max(zs) + WALL_H))
            for s in (1, -1):
                quad(ends[0], ends[1], ((a + b) / 2, y + 5 * s, max(e[3] for e in ends) - 5))
    for x, y0, y1 in [(X_TOP, LANES[-1][1], RETURN[1]), (X_BOT, LANES[-1][1], RETURN[1]),
                      (CHUTE_BACK, LANES[-1][1], LANES[-1][2])]:
        n = max(1, int(math.ceil((y1 - y0) / 10.0)))
        for k in range(n):
            a, b = y0 + (y1 - y0) * k / n, y0 + (y1 - y0) * (k + 1) / n
            ends = []
            for yy in (a, b):
                zs = (height(x - 0.6, yy), height(x + 0.6, yy))
                ends.append((x, yy, min(zs) - 0.5, max(zs) + WALL_H))
            for s in (1, -1):
                quad(ends[0], ends[1], (x + 5 * s, (a + b) / 2, max(e[3] for e in ends) - 5))
    wb.flush()


def add_boards(scene):
    """Distance boards on each lane's +y wall, facing into the lane (u = 0 at the smaller x for a
    viewer facing +y), and a sign over each lane at the top of its slope."""
    batches = {}

    def batch(t):
        if t not in batches:
            batches[t] = B.Batch(scene, t.split(".")[0] + "b", t, False)
        return batches[t]

    for k, ((lab, lo, hi, deg, ch), prof) in enumerate(zip(LANES, PROFILES)):
        x_start = CHUTE_BOULDER_X if ch else BOULDER_X
        y = hi - 0.2
        for d in DISTS:
            x = x_at_dist(prof, x_start, d)
            if x + 7 > X_SEP1:
                break
            z0, z1 = height(x - 7, y - 1), height(x + 7, y - 1)
            q = [(x - 7, y, z0 + 3), (x + 7, y, z1 + 3), (x + 7, y, z1 + 9), (x - 7, y, z0 + 9)]
            uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
            face = (x, y - 5, (z0 + z1) / 2 + 6)
            b = batch(f"d{d:04d}.tex")
            b.tri([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], 1.0, up=face)
            b.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 1.0, up=face)
        # the lane's sign: hung across it, facing back up the plateau (viewer faces +x: u = 0 at larger y)
        xs = -4.0 if not ch else CHUTE_BACK - 1.0
        zb = (H if not ch else height(CHUTE_BACK + 1, (lo + hi) / 2)) + 12.0
        q = [(xs, hi - 2, zb), (xs, lo + 2, zb), (xs, lo + 2, zb + 14), (xs, hi - 2, zb + 14)]
        uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        b = batch(f"sgn{k}.tex")
        face = (xs - 10, (lo + hi) / 2, zb + 7)
        b.tri([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], 1.0, up=face)
        b.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 1.0, up=face)
    for b in batches.values():
        b.flush()


def centreline():
    pts = []
    for x in np.arange(-20.3, X_TURN_BOT + 0.01, 10.0):
        pts.append((float(x), Y_LAP_DOWN))
    cy, r = (Y_LAP_DOWN + Y_LAP_UP) / 2, (Y_LAP_UP - Y_LAP_DOWN) / 2
    n = int(math.ceil(math.pi * r / 10.0))
    for k in range(1, n):
        a = -math.pi / 2 + math.pi * k / n
        pts.append((X_TURN_BOT + r * math.cos(a), cy + r * math.sin(a)))
    for x in np.arange(X_TURN_BOT, X_TURN_TOP - 0.01, -10.0):
        pts.append((float(x), Y_LAP_UP))
    for k in range(1, n):
        a = math.pi / 2 + math.pi * k / n
        pts.append((X_TURN_TOP + r * math.cos(a), cy + r * math.sin(a)))
    for x in np.arange(X_TURN_TOP, -30.3 + 0.01, 10.0):
        pts.append((float(x), Y_LAP_DOWN))
    return [(x, y, height(x, y)) for x, y in pts]


def main():
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=12.0)
    grid = []
    for k in range(8):
        (gx, gy, _), (tx, ty) = line.at(line.L - 12.0 - 8.0 * (k // 2))
        lat = 5.0 if k % 2 else -5.0
        grid.append((gx - ty * lat, gy + tx * lat, height(gx - ty * lat, gy + tx * lat)))
    scene.grid = grid
    nf = build_floor(scene)
    draw_walls(scene)
    add_boards(scene)
    trackgen.add_ground(scene, texture="labflr.tex", margin=600.0, drop=2.0)
    scene.colours["ground.mod"] = [bytes([150, 150, 150, 255])] * 4
    a = B.Batch(scene, "banc", "bld3.tex", False)
    a.tri([(0, 20, -5), (0.1, 20, -5), (0, 20.1, -5)], [(0.5, 0.5)] * 3, 1.0)
    a.flush()
    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables)
    print(f"floor triangles {nf}; collision {collide}; largest chunk {biggest}; surfaces {len(drawn)}; lap {line.L:.0f} m")
    if biggest > B.MAX_VERTS or collide > 16500:
        raise SystemExit("over budget")
    trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                        textures={t: "asph.tex" for t in wanted}, closed=True, corridor=30.0)
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
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
    for cx in (60.0, 250.0, 500.0, 900.0, 1350.0):
        gpos = bc.game((cx, RETURN[1] + 40.0, H + 30.0))
        gtgt = bc.game((cx + 60.0, -75.0, height(cx + 60.0, -75.0)))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    B.BALL_R = BOULDER_R
    menv = envelope.parse(mod.build(B.ball_mesh(3, rings=10, segs=14, texture="bld3.tex")))
    ent.append(archive.ArchiveEntry(name="bld3.mod", tag=menv.tag, version=menv.version, payload=menv.payload))
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
    for _l, lo, hi, _d, ch in LANES:
        gx, _gh, gz = bc.game((CHUTE_BOULDER_X if ch else BOULDER_X, (lo + hi) / 2, 0.0))
        recs.append(f"obj obstacle ball bld3.mod {gx:.6f},{gz:.6f}:0.0 {BOULDER_MASS:.6f}")
    table.records = recs + [obt_mod.TERMINATOR]
    by["track.obt"].payload = envelope.parse(obt_mod.build(table)).payload
    archive.write(ent, OUT)
    trackmap.install(OUT, OUT)
    out = DATA / f"{NAME}.tra"
    track.export_tra(OUT, out, layout="flat")
    tops = {lab: round(float(np.interp(-1.0, XS, p)), 1) for (lab, *_r), p in zip(LANES, PROFILES)}
    print(f"{out.name}: {len(prims)} wall boxes, {len(LANES)} boulders; plateau heights {tops}; "
          f"chute top {float(np.interp(CHUTE_BOULDER_X, XS, PROFILES[-1])):.1f} m; {out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
