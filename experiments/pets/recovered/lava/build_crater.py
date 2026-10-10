"""Volcano crater: one big ramp jump over a lava pit onto a marked landing zone.

LAYOUT (source frame: x east, y north, z up; lap anticlockwise, infield on the left).
A stadium loop inside a crater: the jump straight along y = 0, the return straight
along y = 140, 70 m-radius ends. The infield is a lava lake.

    start line x = -100 ... runway ... ramp 385-420 (15 deg, lip at +6.7 m)
    pit 420-460: lava, 12.7 m below the lip ... landing zone 460-740, +2 m sloping to 0
    distance boards and stripes every 10 m from the lip, 50-300 m

LAVA BEHAVES AS WATER: it is surface code 14 on a flat floor, which the engine
floats a car on (confirmed on ridge-valley). The pit is part of the lake; its shores
slope up to the road, so falling in costs time and you drive out. The landing zone's
own shore lets you climb out beyond the pit, so the lava is a penalty, not a skip.

EVERYTHING DRIVABLE IS A RIBBON along the lap, sampled at stations and lateral
offsets, so no two surfaces share a point and nothing cracks:
    lat -40 .. -12   crater wall, drivable rock (a car flung over the barrier lands)
    lat -12 .. +12   road (ramp deck on the ramp, lava in the pit)
    lat +12 .. +30   shore, down to the lava
    inside +30       the lake: a fan of lava triangles
Beyond -40 the crater rises as drawn-only rock. A barrier stands at lat -12.3.
A cone rises from the lake, drawn, with a solid sphere at its foot.

Light is baked grey (tinted vertex colour order is unverified); the glow is in the
textures: hot rock along the shores, bright lava.
"""
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "circuit"))
sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
import build_circuit as bc  # noqa: E402
import lava_art as art  # noqa: E402
from vrmod import archive, camtab, envelope, mod, sky, sol, tex, trackbuild, trackgen, trackmap  # noqa: E402
from vrmod.trackgen import DIRT, GRASS, NO_COLLISION, ROAD, WATER  # noqa: E402

OUT = HERE / "crater.trk"
SLOT = "bemidji"
XS, XE, YB, R = -100.0, 740.0, 140.0, 70.0         # jump straight x-range, return straight y, turn radius
HALF, SHORE, ROCK = 12.0, 30.0, -40.0              # lateral: road half-width, shore edge, drivable rock edge
LAVA = -6.0                                        # lava level; road runs at 0
RAMP0, RAMP1, LIP = 385.0, 405.0, 420.0            # ramp: curved lead-in, then straight 15 deg to the lip
SLOPE = math.tan(math.radians(15.0))
GAP, LAND_H, LAND_RUN = 40.0, 2.0, 120.0           # pit width; landing top height; its run-out to 0
LAND = LIP + GAP
FACE = 2.5                                         # horizontal run of the lip and landing faces
WALL_X = -12.3                                     # barrier line (lat); solid from -10 to +20 m
LAKE_C = (320.0, 70.0)                             # lake centre; the cone stands here
MAX_VERTS = 990                                    # every chunk fits even retail 1.1's 1,000-vertex buffer
SURFACE_BUDGET, COLLISION_BUDGET = 600, 16500


# ------------------------------------------------------------------ the loop
def jump_height(x):
    """Road height along the jump straight (None over the pit)."""
    if x < RAMP0:
        return 0.0
    if x < RAMP1:
        return SLOPE * (x - RAMP0) ** 2 / (2 * (RAMP1 - RAMP0))
    if x <= LIP:
        return SLOPE * (RAMP1 - RAMP0) / 2 + SLOPE * (x - RAMP1)
    if x < LAND:
        return None
    if x < LAND + LAND_RUN:
        return LAND_H * (1 - (x - LAND) / LAND_RUN)
    return 0.0


LIP_H = jump_height(LIP)


def stations():
    """(s, x, y, tx, ty, kind) round the lap. kind: road / ramp / lipface / pit / landface."""
    out = []
    xs = list(np.arange(XS, RAMP0, 10.0)) + list(np.arange(RAMP0, RAMP1, 2.0)) + \
        list(np.arange(RAMP1, LIP, 3.0)) + [LIP, LIP + FACE] + list(np.arange(LIP + FACE + 5, LAND - FACE, 5.0)) + \
        [LAND - FACE, LAND] + list(np.arange(LAND + 5, XE, 10.0))
    for x in xs:
        x = float(x)
        kind = ("ramp" if RAMP0 <= x < LIP else "lipface" if x == LIP else
                "pit" if LIP < x < LAND else "landface" if x == LAND else "road")
        out.append([x, 0.0, 1.0, 0.0, kind])
    for k in range(int(math.pi * R / 5)):                               # far turn
        a = -math.pi / 2 + math.pi * k / int(math.pi * R / 5)
        out.append([XE + R * math.cos(a), R + R * math.sin(a), -math.sin(a), math.cos(a), "road"])
    for x in np.arange(XE, XS, -10.0):
        out.append([float(x), YB, -1.0, 0.0, "road"])
    for k in range(int(math.pi * R / 5)):                               # near turn
        a = math.pi / 2 + math.pi * k / int(math.pi * R / 5)
        out.append([XS + R * math.cos(a), R + R * math.sin(a), -math.sin(a), math.cos(a), "road"])
    s = 0.0
    res = []
    for i, (x, y, tx, ty, kind) in enumerate(out):
        if i:
            s += math.hypot(x - out[i - 1][0], y - out[i - 1][1])
        res.append((s, x, y, tx, ty, kind))
    return res


def road_z(st):
    s, x, y, tx, ty, kind = st
    if y == 0.0 and tx == 1.0:
        h = jump_height(x)
        return LAVA if h is None else h
    return 0.0


def profile(st):
    """Lateral samples [(lat, z, band)] across a station, outer rock to shore edge."""
    s, x, y, tx, ty, kind = st
    z = road_z(st)
    noise = 3.0 * math.sin(s / 37.0) + 2.0 * math.sin(s / 13.0 + 1.1)
    if kind == "pit":
        road = [(-HALF, LAVA, "lava"), (-6.0, LAVA, "lava"), (0.0, LAVA, "lava"), (6.0, LAVA, "lava"), (HALF, LAVA, "lava")]
        shore = [(18.0, LAVA, "lava"), (24.0, LAVA, "lava"), (SHORE, LAVA, "lava")]
        base = LAVA
    else:
        road = [(-HALF, z, "road"), (-6.0, z, "road"), (0.0, z, "road"), (6.0, z, "road"), (HALF, z, "road")]
        drop = z - LAVA
        shore = [(18.0, z - 0.35 * drop, "shore"), (24.0, z - 0.75 * drop, "hot"), (SHORE, LAVA, "hot")]
        base = z
    rock = [(ROCK, max(base, 0.0) + 18.0 + noise, "rock"), (-20.0, base + 4.0 + 0.3 * noise, "rock")]
    return rock + road + shore


def to_game(x, y, z):
    return bc.game((x, y, z))


# ------------------------------------------------------------------ mesh assembly
class Batch:
    """Triangles for one texture, split into chunks under MAX_VERTS."""

    def __init__(self, scene, stem, texture, code, solid):
        self.scene, self.stem, self.texture, self.code, self.solid = scene, stem, texture, code, solid
        self.v, self.f, self.c, self.n = [], [], [], 0

    def tri(self, pts, uvs, greys, up=True, face_to=None):
        """pts in the source frame. up: wound to face +z; face_to: wound to face that point."""
        g = [to_game(*p) for p in pts]
        a, b, c = (np.array(q) for q in g)
        cr = np.cross(b - a, c - a)
        want = (np.array([0.0, 1.0, 0.0]) if face_to is None else np.array(to_game(*face_to)) - (a + b + c) / 3)
        order = [0, 1, 2] if np.dot(cr, want) >= 0 else [0, 2, 1]
        if len(self.v) + 3 > MAX_VERTS:
            self.flush()
        base = len(self.v)
        for k in order:
            self.v.append(mod.Vertex(*g[k], 0.0, 1.0, 0.0, *uvs[k]))
            self.c.append(bytes([int(max(40, min(255, greys[k] * 255)))] * 3 + [0xFF]))
        self.f.append((base, base + 1, base + 2))

    def quad(self, p, uv, gr, **kw):
        self.tri([p[0], p[1], p[2]], [uv[0], uv[1], uv[2]], [gr[0], gr[1], gr[2]], **kw)
        self.tri([p[0], p[2], p[3]], [uv[0], uv[2], uv[3]], [gr[0], gr[2], gr[3]], **kw)

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


def grey_at(x, y, z, band):
    """Baked light: brighter near the lava (the glow), darker up the crater wall."""
    if band == "lava":
        return 1.0
    d_lake = abs(math.hypot(x - LAKE_C[0], (y - LAKE_C[1]) * 4.0) - 0.0)
    near = math.exp(-max(z - LAVA, 0.0) / 10.0)
    return min(1.0, 0.52 + 0.4 * near) if band != "rock" else max(0.3, 0.62 - 0.012 * max(z, 0.0))


def build_ribbons(scene, st):
    B = {"road": Batch(scene, "road", "ash.tex", ROAD, True), "ramp": Batch(scene, "ramp", "ramp.tex", ROAD, True),
         "lava": Batch(scene, "lava", "lava.tex", WATER, True), "shore": Batch(scene, "shore", "basalt.tex", DIRT, True),
         "hot": Batch(scene, "hot", "hot.tex", DIRT, True), "rock": Batch(scene, "rock", "basalt.tex", DIRT, True),
         "face": Batch(scene, "face", "hot.tex", DIRT, True)}
    n = len(st)
    for i in range(n):
        a, b = st[i], st[(i + 1) % n]
        pa, pb = profile(a), profile(b)
        # a station pair straddling a jump face: the face itself
        if a[5] in ("lipface",) or b[5] == "landface":
            pass
        for j in range(len(pa) - 1):
            (la0, za0, band_a), (la1, za1, _) = pa[j], pa[j + 1]
            (lb0, zb0, band_b), (lb1, zb1, _) = pb[j], pb[j + 1]
            band = band_a
            if a[5] == "lipface" or b[5] == "landface":
                band = "face" if band_a != "rock" else "rock"
            elif band_a == "road" and a[5] == "ramp":
                band = "ramp"
            elif band_a != band_b:
                band = "lava" if "lava" in (band_a, band_b) and band_a != "rock" else band_a
            P = [(a[1] - a[4] * la0, a[2] + a[3] * la0, za0), (b[1] - b[4] * lb0, b[2] + b[3] * lb0, zb0),
                 (b[1] - b[4] * lb1, b[2] + b[3] * lb1, zb1), (a[1] - a[4] * la1, a[2] + a[3] * la1, za1)]
            if band in ("road", "ramp"):
                span = 7.0 if band == "ramp" else 12.0
                uv = [((la0 + HALF) / (2 * HALF), a[0] / span), ((lb0 + HALF) / (2 * HALF), b[0] / span),
                      ((lb1 + HALF) / (2 * HALF), b[0] / span), ((la1 + HALF) / (2 * HALF), a[0] / span)]
            elif band == "lava":
                uv = [(p[0] / 20.0, p[1] / 20.0) for p in P]
            else:
                uv = [(p[0] / 14.0 + p[2] / 30.0, p[1] / 14.0 + p[2] / 30.0) for p in P]
            gr = [grey_at(p[0], p[1], p[2], band) for p in P]
            B[band].quad(P, uv, gr)
    for b in B.values():
        b.flush()
    return B


def build_lake(scene, st):
    """The lake: a fan from its centre to every station's shore edge, all at lava level."""
    lb = Batch(scene, "lake", "lava.tex", WATER, True)
    edge = []
    for s, x, y, tx, ty, kind in st:
        edge.append((x - ty * SHORE, y + tx * SHORE, LAVA))
    c = (LAKE_C[0], LAKE_C[1], LAVA)
    for i in range(len(edge)):
        p, q = edge[i], edge[(i + 1) % len(edge)]
        lb.tri([c, p, q], [(c[0] / 20, c[1] / 20), (p[0] / 20, p[1] / 20), (q[0] / 20, q[1] / 20)], [1.0, 1.0, 1.0])
    lb.flush()


def build_walls(scene, st):
    """Barrier boxes along the outer edge, and the crater beyond as drawn rock."""
    walls = []
    outer = Batch(scene, "crater", "basalt.tex", GRASS, False)
    n = len(st)
    for i in range(n):
        a, b = st[i], st[(i + 1) % n]
        pa = (a[1] - a[4] * WALL_X, a[2] + a[3] * WALL_X)
        pb = (b[1] - b[4] * WALL_X, b[2] + b[3] * WALL_X)
        walls.append([(pa[0], pa[1], -10.0), (pb[0], pb[1], -10.0), (pb[0], pb[1], 20.0), (pa[0], pa[1], 20.0)])
        # drawn crater: from the drivable rock's outer edge up to the rim
        rows = []
        for st_ in (a, b):
            s, x, y, tx, ty, kind = st_
            base = profile(st_)[0][1]
            noise = 6.0 * math.sin(s / 53.0 + 0.4) + 4.0 * math.sin(s / 19.0)
            rows.append([(ROCK, base), (-70.0, 44.0 + noise), (-110.0, 58.0 + 0.5 * noise)])
        for j in range(2):
            (la0, za0), (la1, za1) = rows[0][j], rows[0][j + 1]
            (lb0, zb0), (lb1, zb1) = rows[1][j], rows[1][j + 1]
            P = [(a[1] - a[4] * la0, a[2] + a[3] * la0, za0), (b[1] - b[4] * lb0, b[2] + b[3] * lb0, zb0),
                 (b[1] - b[4] * lb1, b[2] + b[3] * lb1, zb1), (a[1] - a[4] * la1, a[2] + a[3] * la1, za1)]
            uv = [(p[0] / 18.0 + p[2] / 18.0, p[1] / 18.0 + p[2] / 18.0) for p in P]
            outer.quad(P, uv, [max(0.3, 0.6 - 0.006 * p[2]) for p in P], face_to=(LAKE_C[0], LAKE_C[1], 0.0))
    outer.flush()
    return walls


def build_cone(scene):
    """A volcanic cone in the lake: drawn rock, a glowing mouth, a solid sphere at its foot."""
    cone = Batch(scene, "cone", "hot.tex", GRASS, False)
    mouth = Batch(scene, "mouth", "lava.tex", GRASS, False)
    cx, cy = LAKE_C
    rings = [(28.0, LAVA), (20.0, 14.0), (12.0, 30.0), (9.0, 36.0)]
    seg = 20
    for r in range(len(rings) - 1):
        (r0, z0), (r1, z1) = rings[r], rings[r + 1]
        for k in range(seg):
            a0, a1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
            P = [(cx + r0 * math.cos(a0), cy + r0 * math.sin(a0), z0), (cx + r0 * math.cos(a1), cy + r0 * math.sin(a1), z0),
                 (cx + r1 * math.cos(a1), cy + r1 * math.sin(a1), z1), (cx + r1 * math.cos(a0), cy + r1 * math.sin(a0), z1)]
            am = (a0 + a1) / 2
            out = (cx + 100 * math.cos(am), cy + 100 * math.sin(am), (z0 + z1) / 2)
            uv = [(k / 4.0, p[2] / 12.0) for p in P[:2]] + [((k + 1) / 4.0, p[2] / 12.0) for p in P[2:]]
            uv = [(a0 * 3, P[0][2] / 12), (a1 * 3, P[1][2] / 12), (a1 * 3, P[2][2] / 12), (a0 * 3, P[3][2] / 12)]
            cone.quad(P, uv, [0.55 + 0.4 * (1 - p[2] / 40.0) for p in P], face_to=out)
    top = (cx, cy, 33.0)
    r1, z1 = rings[-1]
    for k in range(seg):
        a0, a1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
        p = (cx + r1 * math.cos(a0), cy + r1 * math.sin(a0), z1)
        q = (cx + r1 * math.cos(a1), cy + r1 * math.sin(a1), z1)
        mouth.tri([top, p, q], [(0.5, 0.5), (0.5 + 0.5 * math.cos(a0), 0.5 + 0.5 * math.sin(a0)),
                                (0.5 + 0.5 * math.cos(a1), 0.5 + 0.5 * math.sin(a1))], [1.0, 1.0, 1.0])
    cone.flush(); mouth.flush()
    scene.spheres.append(((cx, cy, LAVA - 18.0), 30.0))


def build_markers(scene):
    """Stripes across the landing zone and boards both sides, every 10 m from the lip."""
    stripes = Batch(scene, "stripe", "paint.tex", GRASS, False)
    boards = Batch(scene, "board", "nums.tex", GRASS, False)
    for d in art.MARKS:
        x = LIP + d
        z = jump_height(x) + 0.04
        w = 0.6 if d % 50 else 1.4
        u0, u1 = (0.52, 0.98) if d % 50 == 0 else (0.02, 0.48)
        P = [(x - w / 2, -HALF + 0.5, z), (x + w / 2, -HALF + 0.5, z), (x + w / 2, HALF - 0.5, z), (x - w / 2, HALF - 0.5, z)]
        stripes.quad(P, [(u0, 0.1), (u1, 0.1), (u1, 0.9), (u0, 0.9)], [1.0] * 4)
        cu0, cv0, cu1, cv1 = art.cell_of(d)
        for lat in (-15.0, 15.0):
            zb = (jump_height(x) if lat < 0 else jump_height(x) - 1.0) + 2.0
            y0, y1 = lat - 3.0, lat + 3.0
            P = [(x, y1, zb), (x, y0, zb), (x, y0, zb + 3.0), (x, y1, zb + 3.0)]      # seen from the ramp (-x)
            boards.quad(P, [(cu0, cv1), (cu1, cv1), (cu1, cv0), (cu0, cv0)], [1.0] * 4, face_to=(x - 50.0, lat, zb))
            Q = [(x + 0.05, y0, zb), (x + 0.05, y1, zb), (x + 0.05, y1, zb + 3.0), (x + 0.05, y0, zb + 3.0)]
            boards.quad(Q, [(cu0, cv1), (cu1, cv1), (cu1, cv0), (cu0, cv0)], [0.8] * 4, face_to=(x + 50.0, lat, zb))
            post = [(x, lat - 0.15, zb - 2.0 - 0.5), (x, lat + 0.15, zb - 2.0 - 0.5), (x, lat + 0.15, zb), (x, lat - 0.15, zb)]
            for side in (-50.0, 50.0):
                boards.quad(post, [(0.99, 0.99)] * 4, [0.6] * 4, face_to=(x + side, lat, zb))
    stripes.flush(); boards.flush()


# ------------------------------------------------------------------ build
def main():
    st = stations()
    centre = []
    for k in np.arange(0.0, st[-1][0] + 5.0, 10.0):
        i = max(j for j in range(len(st)) if st[j][0] <= k)
        a = st[i]
        centre.append((a[1] + (k - a[0]) * a[3], a[2] + (k - a[0]) * a[4], road_z(a)))
    scene = trackgen.TrackScene(centreline=centre)
    line = bc.Line(centre)
    trackgen.add_checkpoints(scene, 4, half_width=HALF + 1.0)
    grid = []
    for k in range(8):                                        # behind the start line, as on every track
        (gx, gy, _gz), (tx, ty) = line.at(line.L - 12.0 - 10.0 * (k // 2))
        lat = 5.0 if k % 2 else -5.0
        grid.append((gx - ty * lat, gy + tx * lat, 0.0))
    scene.grid = grid

    build_ribbons(scene, st)
    build_lake(scene, st)
    scene.walls = build_walls(scene, st)
    build_cone(scene)
    build_markers(scene)
    trackgen.add_ground(scene, texture="basalt.tex", margin=500.0, drop=40.0)
    scene.colours["ground.mod"] = [bytes([60, 60, 60, 255])] * 4

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn) + len(scene.wobbles)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    print(f"lap {st[-1][0]:.0f} m; {len(st)} stations; ramp lip +{LIP_H:.2f} m, pit {GAP:.0f} m to the landing "
          f"(+{LAND_H:g} m), lava {LAVA:g} m")
    print(f"surfaces {surfaces} (budget {SURFACE_BUDGET}); largest chunk {biggest} verts; collision triangles "
          f"{collide} (budget {COLLISION_BUDGET}); walls {len(scene.walls)}; textures {sorted(wanted)}")
    if surfaces > SURFACE_BUDGET or biggest > MAX_VERTS or collide > COLLISION_BUDGET:
        raise SystemExit("over budget")

    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True, corridor=SHORE)
    print(f"assembled: {res.summary()}")
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        fn, mode = art.ALL[name]
        im = fn()
        a = np.array(im)
        if int((a.sum(axis=2) == 0).sum()):
            raise SystemExit(f"{name} has black texels")
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), im.width, mode=mode, wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = art.crater_sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for pos, tgt in (((RAMP0 - 20, -HALF - 6, 5.0), (LIP, 0, LIP_H)),              # beside the runway, on the ramp
                     ((LIP - 5, HALF + 14, LIP_H + 8), (LAND + 60, 0, 1.0)),       # over the pit, down the landing
                     ((LAND + 180, -HALF - 6, 8.0), (LIP + 60, 0, 6.0)),           # the landing zone, back at the jump
                     ((XE + R, R, 10.0), (XE, 0, 1.0)),                           # far turn
                     ((200.0, YB + HALF + 6, 8.0), (320.0, 70.0, 10.0)),          # return straight, the cone
                     ((XS - 10, R, 10.0), (XS + 60, 0, 1.0))):                   # near turn, onto the runway
        gpos, gtgt = bc.game(pos), bc.game(tgt)
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)
    trackmap.install(OUT, OUT)

    by = {e.name.lower(): e for e in archive.read(OUT)}
    for name in sorted(wanted) + list(sky.TILES):
        tex.parse(envelope.build(by[name].tag, by[name].version, by[name].payload))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    boxes = sum(1 for q in so.primitives if q.type == sol.BOX)
    print(f"textures decode; {boxes} barrier boxes, {len(so.primitives) - boxes} other solids; {len(cams)} cameras; "
          f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")
    return scene, st


if __name__ == "__main__":
    main()
