"""The scenic course with DRIVABLE terrain: walls only on three corners, the rest open.

The land has to join the verge watertight -- .bpp holds one surface per point, and
a crack is a hole a wheel falls through. So the terrain is a Delaunay
triangulation of two point sets:

  seam points   the grass verge's own outer-edge vertices, taken from the swept
                meshes and densified to <= 5 m -- so every seam segment is a
                Gabriel edge and comes out of the triangulation as an edge
  land points   a 20 m lattice, jittered, kept >= 9 m clear of the seam

Triangles whose centroid falls inside the corridor are dropped; what is left
tiles the plane exactly up to the verge. Every triangle is driveable (GRASS, or
DIRT on rock), and the whole collision set is held under the stock tracks' range.

Walls stand on the outside of T1, the hairpin and the final corner, with armco.
There is no perimeter fence -- as on most stock tracks, you can drive off the edge.
"""
import math
import random
import struct
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "targets"))
import build_scenic as bs  # noqa: E402
import build_circuit as bc  # noqa: E402
import build_targets as bt  # noqa: E402
from build_sticks import disc, stick, turn  # noqa: E402
from vrmod import archive, camtab, envelope, ili, mod, sky, sol, tex, trackbuild, trackgen  # noqa: E402
from vrmod.trackgen import DIRT, GRASS  # noqa: E402

# The road, widened to the stock median. Measured across all eight stock tracks'
# asphalt at the racing line: median 24.8 m, from nfield's 14.8 to limbo's 33.5.
# 12 m was narrower than any of them.
bc.HALF = 10.0
bc.GRASS_EDGE = bc.HALF + 0.9 + 1.0 + 20.0
bc.WALL_OFFSET = bc.GRASS_EDGE - 0.6

OUT = HERE / "limbo.trk"
MARGIN, LATTICE, JITTER, CLEAR, SEAM_STEP = 300.0, 20.0, 2.0, 9.0, 5.0
TILE = 240.0
COLLISION_BUDGET = 16500          # the stock tracks run 7,300 - 16,525 triangles
# (start m, end m, which side of travel) -- the outside of each corner
WALLED = [(540.0, 780.0, "right"), (1800.0, 2050.0, "left"), (2960.0, 3100.0, "right")]
FENCE_INSET, FENCE_H = 40.0, 4.0
BOULDERS = 130                    # solid, as .sol spheres: no collision triangles at all


# ------------------------------------------------------------------ height field
class Land:
    """The terrain height function (source frame), flush with the verge's edge."""

    def __init__(self, line, verge_drop):
        self.line = line
        self.drop = verge_drop                     # verge edge height relative to the road
        xs = [p[0] for p in line.p]; ys = [p[1] for p in line.p]
        self.x0, self.x1 = min(xs) - MARGIN, max(xs) + MARGIN
        self.y0, self.y1 = min(ys) - MARGIN, max(ys) + MARGIN
        self.base = min(p[2] for p in line.p) + verge_drop - 0.5
        self.samples = line.p[::3]

    def h(self, x, y):
        d, e = self.line.nearest(x, y)
        near = e + self.drop
        num = den = 0.0
        for p in self.samples:
            w = 1.0 / ((x - p[0]) ** 2 + (y - p[1]) ** 2 + 90.0 ** 2)
            num += w * p[2]; den += w
        hills = (9.0 * math.sin(x / 170.0 + 0.7) * math.cos(y / 220.0 - 0.4)
                 + 4.0 * math.sin(x / 61.0 + 1.3) * math.sin(y / 83.0 + 0.2))
        big = (22.0 * math.sin(x / 260.0 + 2.1) * math.cos(y / 310.0 + 0.9) + 12.0
               + 8.0 * math.sin(x / 140.0 - 0.6) * math.sin(y / 170.0 + 1.7))
        far = num / den + max(-2.0, hills) + max(0.0, big) * bc.smoothstep(60.0, 320.0, d)
        h = near + (far - near) * bc.smoothstep(bc.GRASS_EDGE + 4, bc.GRASS_EDGE + 150, d)
        edge = min(x - self.x0, self.x1 - x, y - self.y0, self.y1 - y)
        return self.base + (h - self.base) * bc.smoothstep(0.0, 160.0, edge), d


# ------------------------------------------------------------------ Delaunay
def delaunay(P):
    """Bowyer-Watson over points P [(x, y)], bucketed by circumcircle. Returns index triangles."""
    xs = [p[0] for p in P]; ys = [p[1] for p in P]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    pts = list(P) + [(cx - 30 * span, cy - 30 * span), (cx + 30 * span, cy - 30 * span), (cx, cy + 30 * span)]
    n = len(P)
    B = 40.0
    nbx, nby = int((maxx - minx) / B) + 1, int((maxy - miny) / B) + 1
    buckets = defaultdict(set)
    tris = {}
    next_id = [0]

    def circ(a, b, c):
        (ax, ay), (bx, by), (cx_, cy_) = pts[a], pts[b], pts[c]
        d = 2 * (ax * (by - cy_) + bx * (cy_ - ay) + cx_ * (ay - by))
        ux = ((ax * ax + ay * ay) * (by - cy_) + (bx * bx + by * by) * (cy_ - ay) + (cx_ * cx_ + cy_ * cy_) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (cx_ - bx) + (bx * bx + by * by) * (ax - cx_) + (cx_ * cx_ + cy_ * cy_) * (bx - ax)) / d
        return ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2

    def cells(ux, uy, r2):
        r = math.sqrt(r2)
        i0 = max(0, int((ux - r - minx) // B)); i1 = min(nbx - 1, int((ux + r - minx) // B))
        j0 = max(0, int((uy - r - miny) // B)); j1 = min(nby - 1, int((uy + r - miny) // B))
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]

    def add(a, b, c):
        ux, uy, r2 = circ(a, b, c)
        t = next_id[0]; next_id[0] += 1
        cs = cells(ux, uy, r2)
        tris[t] = (a, b, c, ux, uy, r2, cs)
        for k in cs:
            buckets[k].add(t)

    def remove(t):
        for k in tris[t][6]:
            buckets[k].discard(t)
        del tris[t]

    add(n, n + 1, n + 2)
    order = list(range(n)); random.Random(3).shuffle(order)
    for p in order:
        px, py = pts[p]
        k = (min(nbx - 1, int((px - minx) // B)), min(nby - 1, int((py - miny) // B)))
        bad = [t for t in buckets[k] if (px - tris[t][3]) ** 2 + (py - tris[t][4]) ** 2 < tris[t][5] * (1 - 1e-12)]
        edges = defaultdict(int)
        for t in bad:
            a, b, c = tris[t][:3]
            for e in ((a, b), (b, c), (c, a)):
                edges[tuple(sorted(e))] += 1
        for t in bad:
            remove(t)
        for (a, b), cnt in edges.items():
            if cnt == 1:
                add(a, b, p)
    return [(a, b, c) for a, b, c, *_ in tris.values() if a < n and b < n and c < n]


def point_in_poly(x, y, poly):
    """Vectorised even-odd test: arrays x, y against a closed polygon [(x, y)]."""
    px = np.array([p[0] for p in poly]); py = np.array([p[1] for p in poly])
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    inside = np.zeros(len(x), bool)
    for ax, ay, bx, by in zip(px, py, qx, qy):
        cond = (ay > y) != (by > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = ax + (y - ay) * (bx - ax) / (by - ay)
        inside ^= cond & (x < xint)
    return inside


# ------------------------------------------------------------------ the seam
def verge_loops(scene):
    """The grass verge's outer edge on each side, as closed loops of (x, y, z) source points."""
    loops = {}
    for side in ("l", "r"):
        names = sorted(n for n in scene.meshes if n.startswith(f"grass{side}"))
        ring = []
        for nm in names:
            m = scene.meshes[nm]
            outer = [v for v in m.vertices if abs(v.u - 1.0) < 1e-9]
            outer.sort(key=lambda v: v.v)
            for v in outer:
                p = (-v.x, -v.z, v.y)                       # game -> source
                if not ring or math.dist(ring[-1][:2], p[:2]) > 1e-6:
                    ring.append(p)
        if math.dist(ring[0][:2], ring[-1][:2]) < 1e-6:
            ring.pop()
        loops[side] = ring
    return loops


def densify(ring, step):
    out = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        k = max(1, math.ceil(math.dist(a[:2], b[:2]) / step))
        for i in range(k):
            f = i / k
            out.append(tuple(a[j] + f * (b[j] - a[j]) for j in range(3)))
    return out


# ------------------------------------------------------------------ walls
def wall_quads(line, walls_out):
    quads = []
    for s0, s1, side in WALLED:
        sign = -1.0 if side == "right" else 1.0            # left of travel is +normal
        s = s0
        while s < s1:
            e = min(s + 20.0, s1)
            (ax, ay, az), (tax, tay) = line.at(s)
            (bx, by, bz), (tbx, tby) = line.at(e)
            a = (ax - tay * sign * bc.WALL_OFFSET, ay + tax * sign * bc.WALL_OFFSET, az)
            b = (bx - tby * sign * bc.WALL_OFFSET, by + tbx * sign * bc.WALL_OFFSET, bz)
            quads.append([a, b, (b[0], b[1], b[2] + 1.5), (a[0], a[1], a[2] + 1.5)])
            walls_out.append((s, e, sign))
            s = e
    return quads


def fence_quads(land):
    x0, x1 = land.x0 + FENCE_INSET, land.x1 - FENCE_INSET
    y0, y1 = land.y0 + FENCE_INSET, land.y1 - FENCE_INSET
    z = land.base - 1.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    out = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        out.append([(ax, ay, z), (bx, by, z), (bx, by, z + FENCE_H + 40.0), (ax, ay, z + FENCE_H + 40.0)])
    return out


def add_armco_sections(scene, line, sections):
    chunks = 0
    groups = defaultdict(list)
    for s, e, sign in sections:
        groups[(sign, int(s // 120))].append((s, e, sign))
    for key, segs in sorted(groups.items()):
        verts, cols, faces = [], [], []
        for s, e, sign in segs:
            (ax, ay, az), (tax, tay) = line.at(s)
            (bx, by, bz), (tbx, tby) = line.at(e)
            off = bc.WALL_OFFSET - 0.05
            a = (ax - tay * sign * off, ay + tax * sign * off, az - 0.1)
            b = (bx - tby * sign * off, by + tbx * sign * off, bz - 0.1)
            L = math.dist(a[:2], b[:2])
            base = len(verts)
            for p, u in ((a, s / 4.0), (b, s / 4.0 + L / 4.0)):
                for hgt, v, c in ((bs.ARMCO_H, 0.0, 1.0), (0.0, 1.0, 0.78)):
                    g = bc.game((p[0], p[1], p[2] + hgt))
                    verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, u, v))
                    cols.append(bs.grey(c))
            t0, b0, t1, b1 = base, base + 1, base + 2, base + 3
            quad = [(t0, b0, b1), (t0, b1, t1)]
            va, vb, vc = (verts[i] for i in quad[0])
            nrm = np.cross([vb.x - va.x, vb.y - va.y, vb.z - va.z], [vc.x - va.x, vc.y - va.y, vc.z - va.z])
            (mx, my, mz), _ = line.at((s + e) / 2)
            toward = np.array(bc.game((mx, my, mz))) - np.array([va.x, va.y, va.z])
            if np.dot(nrm, toward) < 0:
                quad = [(p, r, q) for p, q, r in quad]
            faces += quad
        name = f"armco{chunks:03d}.mod"
        scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
            mod.Material(name="armco.tex", vertex_start=0, vertex_end=len(verts),
                         face_start=0, face_end=len(faces))])
        scene.colours[name] = cols
        scene.scenery.append(trackgen.SceneObject(name, GRASS, trackgen.NO_COLLISION))
        chunks += 1
    return chunks


# ------------------------------------------------------------------ terrain
def build_terrain(scene, line):
    loops = verge_loops(scene)
    # the verge edge's height relative to the road, read off the built meshes
    drops = []
    for ring in loops.values():
        for p in ring[::7]:
            d, e = line.nearest(p[0], p[1])
            drops.append(p[2] - e)
    drop = float(np.median(drops))
    land = Land(line, drop)

    seam = []
    for side in ("l", "r"):
        seam += [("seam", p) for p in densify(loops[side], SEAM_STEP)]
    rng = random.Random(5)
    lattice = []
    y = land.y0
    while y <= land.y1 + 1e-6:
        x = land.x0
        while x <= land.x1 + 1e-6:
            on_border = x in (land.x0,) or y in (land.y0,) or x + LATTICE > land.x1 or y + LATTICE > land.y1
            jx = 0.0 if on_border else rng.uniform(-JITTER, JITTER)
            jy = 0.0 if on_border else rng.uniform(-JITTER, JITTER)
            lattice.append((x + jx, y + jy))
            x += LATTICE
        y += LATTICE
    keep = []
    for x, y in lattice:
        d, _ = line.nearest(x, y)
        if d > bc.GRASS_EDGE + CLEAR:
            keep.append(("land", (x, y)))
    points = seam + keep
    P = [p[1][:2] for p in points]
    print(f"triangulating {len(seam)} seam + {len(keep)} land points ...")
    tris = delaunay(P)

    # every seam segment must survive as an edge -- that is the watertight join
    edgeset = set()
    for a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            edgeset.add(tuple(sorted(e)))
    off = 0
    missing = 0
    for side in ("l", "r"):
        m = len(densify(loops[side], SEAM_STEP))
        for i in range(m):
            if tuple(sorted((off + i, off + (i + 1) % m))) not in edgeset:
                missing += 1
        off += m
    # drop what lies in the corridor: between the two verge loops
    cx = np.array([(P[a][0] + P[b][0] + P[c][0]) / 3 for a, b, c in tris])
    cy = np.array([(P[a][1] + P[b][1] + P[c][1]) / 3 for a, b, c in tris])
    in_corr = point_in_poly(cx, cy, [p[:2] for p in loops["l"]]) ^ point_in_poly(cx, cy, [p[:2] for p in loops["r"]])
    kept = [t for t, bad in zip(tris, in_corr) if not bad]

    # heights, shading
    H = []
    for kind, p in points:
        H.append(p[2] if kind == "seam" else land.h(p[0], p[1])[0])
    def shade_at(i):
        x, y = P[i]
        if points[i][0] == "seam":
            return 0.96
        hx = (land.h(x + 1.5, y)[0] - land.h(x - 1.5, y)[0]) / 3.0
        hy = (land.h(x, y + 1.5)[0] - land.h(x, y - 1.5)[0]) / 3.0
        nrm = np.array([-hx, -hy, 1.0]); nrm /= np.linalg.norm(nrm)
        return float(np.clip(0.34 + 0.62 * max(0.0, nrm @ bs.SUN) / bs.SUN[2], 0.3, 1.0))
    shade = [shade_at(i) for i in range(len(P))]

    # chunk by tile and ground type
    groups = defaultdict(list)
    for a, b, c in kept:
        mx = (P[a][0] + P[b][0] + P[c][0]) / 3; my = (P[a][1] + P[b][1] + P[c][1]) / 3
        ux, uy, uz = P[b][0] - P[a][0], P[b][1] - P[a][1], H[b] - H[a]
        vx, vy, vz = P[c][0] - P[a][0], P[c][1] - P[a][1], H[c] - H[a]
        nz = ux * vy - uy * vx
        nx, ny = uy * vz - uz * vy, uz * vx - ux * vz
        slope = math.hypot(nx, ny) / abs(nz) if nz else 9.0
        d, _ = line.nearest(mx, my)
        if slope > 0.45:
            kind = "rock.tex"
        elif d > 45 and bs.vnoise(mx, my, 140.0, 3) > 0.55:
            kind = "meadow.tex"
        else:
            kind = "grass.tex"
        groups[(int((mx - land.x0) // TILE), int((my - land.y0) // TILE), kind)].append((a, b, c))
    count = 0
    for (ti, tj, kind), tl in sorted(groups.items()):
        for start in range(0, len(tl), 900):
            part = tl[start:start + 900]
            idx, verts, cols, faces = {}, [], [], []
            uvs = 8.0 if kind == "rock.tex" else 12.0
            for tri in part:
                f = []
                for i in tri:
                    if i not in idx:
                        idx[i] = len(verts)
                        g = bc.game((P[i][0], P[i][1], H[i]))
                        verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, P[i][0] / uvs, P[i][1] / uvs))
                        jitter = 0.94 + 0.08 * bs.vnoise(P[i][0], P[i][1], 23.0, 9)
                        cols.append(bs.grey(shade[i] * (1.0 if points[i][0] == "seam" else jitter)))
                    f.append(idx[i])
                # face up: in the game frame, (b-a)x(c-a) must have +y
                a_, b_, c_ = (verts[k] for k in f)
                ny_ = (b_.z - a_.z) * (c_.x - a_.x) - (b_.x - a_.x) * (c_.z - a_.z)
                faces.append(tuple(f) if ny_ > 0 else (f[0], f[2], f[1]))
            name = f"g{count:03d}{kind[0]}.mod"
            scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
                mod.Material(name=kind, vertex_start=0, vertex_end=len(verts),
                             face_start=0, face_end=len(faces))])
            scene.colours[name] = cols
            scene.driveables.append(trackgen.SceneObject(name, DIRT if kind == "rock.tex" else GRASS))
            count += 1
    return land, count, len(kept), missing, drop, len(tris) - len(kept)


SCORES = ((1.4, 30, "tgt30.tex"), (3.0, 20, "tgt20.tex"), (99.0, 10, "tgt10.tex"))
TGT_SIZE = 128


def score_for(width):
    """Smaller boards score more: 30 up to 1.4 m, 20 up to 3 m, 10 beyond."""
    for limit, value, texname in SCORES:
        if width <= limit:
            return value, texname
    raise ValueError(width)


def target_face(value):
    """A bullseye with its score painted in the middle: rings, then the number.

    Grey outside the circle, so a stick sampling the texture's corner stays grey,
    and nothing anywhere decodes to black (which the engine would key out).
    """
    from PIL import Image, ImageDraw, ImageFont
    size = TGT_SIZE
    img = Image.new("RGB", (size, size), bt.GREY)
    d = ImageDraw.Draw(img)
    c, rad = (size - 1) / 2.0, size / 2.0
    px = img.load()
    for y in range(size):
        for x in range(size):
            dist = math.hypot(x - c, y - c) / rad
            if dist <= 1.0:
                k = min(bt.BANDS - 1, int(dist * bt.BANDS))
                px[x, y] = bt.RED if k % 2 == 0 else bt.WHITE
    r0 = rad * 0.46                                   # a solid red disc to read the number on
    d.ellipse([c - r0, c - r0, c + r0, c + r0], fill=bt.RED)
    for name, pt in (("segoeuib.ttf", int(size * 0.44)), ("arialbd.ttf", int(size * 0.44))):
        try:
            font = ImageFont.truetype(name, pt)
            break
        except OSError:
            font = None
    text = str(value)
    if font is None:                       # no system face: blocky fallback
        font = ImageFont.load_default()
    d.text((c + 1.5, c + 1.5), text, fill=(120, 18, 18), font=font, anchor="mm")
    d.text((c, c), text, fill=(252, 252, 250), font=font, anchor="mm")
    return img


def target_head(radius, texname):
    """A bullseye disc of any size, origin at its bottom edge, facing +Z, grey back.

    build_sticks.disc() is fixed at 0.6 m; a target's collider is a capsule of the
    same radius reaching the head's top, so the two must agree.
    """
    verts, faces = [], []

    def add(x, y, z, u, v):
        verts.append((x, y, z, u, v))
        return len(verts) - 1
    seg = bt.SEG
    # u runs 0.5 - 0.5cos, NOT 0.5 + 0.5cos: the game draws left-handed, so a
    # viewer facing the front sees local +x on their LEFT. Painted numbers would
    # read backwards without this (the chevrons needed the same flip).
    c = add(0.0, radius, 0.0, 0.5, 0.5)
    rim = [add(radius * math.cos(a), radius + radius * math.sin(a), 0.0,
               0.5 - 0.5 * math.cos(a), 0.5 - 0.5 * math.sin(a))
           for a in (2 * math.pi * i / seg for i in range(seg))]
    faces += [(c, rim[i], rim[(i + 1) % seg]) for i in range(seg)]
    cb = add(0.0, radius, -0.02, *bt.GREY_UV)
    rimb = [add(radius * math.cos(a), radius + radius * math.sin(a), -0.02, *bt.GREY_UV)
            for a in (2 * math.pi * i / seg for i in range(seg))]
    faces += [(cb, rimb[(i + 1) % seg], rimb[i]) for i in range(seg)]
    return verts, faces, texname


# ------------------------------------------------------------------ boulders
ICO_T = (1 + 5 ** 0.5) / 2
ICO_V = [(-1, ICO_T, 0), (1, ICO_T, 0), (-1, -ICO_T, 0), (1, -ICO_T, 0),
         (0, -1, ICO_T), (0, 1, ICO_T), (0, -1, -ICO_T), (0, 1, -ICO_T),
         (ICO_T, 0, -1), (ICO_T, 0, 1), (-ICO_T, 0, -1), (-ICO_T, 0, 1)]
ICO_F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
         (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
         (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]


def boulder(rng, radius):
    """A low-poly rock: a lumpy icosahedron, 12 vertices and 20 faces, flat-shaded."""
    verts = []
    for vx, vy, vz in ICO_V:
        L = math.sqrt(vx * vx + vy * vy + vz * vz)
        k = radius * rng.uniform(0.72, 1.18) / L
        verts.append((vx * k, vy * k * rng.uniform(0.6, 0.85), vz * k))
    return verts, ICO_F


def add_boulders(scene, land, line, rng):
    """Scatter boulders on the open ground: drawn as meshes, solid as .sol spheres."""
    placed = []
    guard = 0
    while len(placed) < BOULDERS and guard < 40000:
        guard += 1
        x = rng.uniform(land.x0 + 60, land.x1 - 60); y = rng.uniform(land.y0 + 60, land.y1 - 60)
        h, d = land.h(x, y)
        if d < bc.GRASS_EDGE + 3 or d > 260:
            continue
        near_track = d < bc.GRASS_EDGE + 25
        if not near_track and rng.random() > 0.45:
            continue
        r = rng.uniform(1.0, 2.6) * (0.8 if near_track else 1.15)
        if any(math.dist((x, y), (q[0], q[1])) < (r + q[3]) * 2.5 for q in placed):
            continue
        placed.append((x, y, h, r))
    groups = {}
    for x, y, h, r in placed:
        groups.setdefault((int(x // 320), int(y // 320)), []).append((x, y, h, r))
    chunks = 0
    for key, members in sorted(groups.items()):
        verts, cols, faces = [], [], []
        for x, y, h, r in members:
            vs, fs = boulder(rng, r)
            base = len(verts)
            cy = h + 0.45 * r                                  # sits ~half buried
            for vx, vy, vz in vs:
                g = bc.game((x + vx, y + vz, cy + vy))
                verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0,
                                        (x + vx) / 7.0, (y + vz) / 7.0))
                up = vy / (abs(vy) + abs(vx) + abs(vz) + 1e-6)
                cols.append(bs.grey(0.62 + 0.34 * max(0.0, up + 0.45)))
            for a, b, c in fs:
                fa, fb, fc = base + a, base + b, base + c
                va, vb, vc = verts[fa], verts[fb], verts[fc]
                nx_ = ((vb.y - va.y) * (vc.z - va.z) - (vb.z - va.z) * (vc.y - va.y))
                ny_ = ((vb.z - va.z) * (vc.x - va.x) - (vb.x - va.x) * (vc.z - va.z))
                nz_ = ((vb.x - va.x) * (vc.y - va.y) - (vb.y - va.y) * (vc.x - va.x))
                outward = (va.x + vb.x + vc.x) / 3 - bc.game((x, y, cy))[0], 0, 0
                dot = nx_ * outward[0] + ny_ * ((va.y + vb.y + vc.y) / 3 - cy) + nz_ * 0
                faces.append((fa, fb, fc) if dot >= 0 else (fa, fc, fb))
            # solid: one sphere, a little under the drawn size so it never juts out
            scene.spheres.append(((x, y, cy), r * 0.82))
        name = f"rock{chunks:03d}.mod"
        scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
            mod.Material(name="rock.tex", vertex_start=0, vertex_end=len(verts),
                         face_start=0, face_end=len(faces))])
        scene.colours[name] = cols
        scene.scenery.append(trackgen.SceneObject(name, GRASS, trackgen.NO_COLLISION))
        chunks += 1
    return len(placed), chunks


# ------------------------------------------------------------------ build
def main():
    raw = trackgen.read_centreline(HERE / "circuit.obj")
    pts = trackgen.resample(raw, 10.0, closed=True)
    line = bc.Line(pts)
    scene = trackgen.sweep(pts, bands=bs.BANDS, road_half_width=bc.HALF, closed=True,
                           segment_length=bs.SEGMENT)
    trackgen.add_checkpoints(scene, 4, half_width=bc.HALF)
    trackgen.add_grid(scene, 8)

    land, chunks, ntri, missing, drop, dropped = build_terrain(scene, line)
    print(f"terrain: {ntri} driveable triangles in {chunks} chunks ({dropped} dropped inside the "
          f"corridor); verge edge sits {drop:+.2f} m off the road; seam segments missing: {missing}")
    if missing:
        raise SystemExit("the land does not meet the verge watertight")

    sections = []
    # No perimeter fence: like most stock tracks, drive far enough and you leave the
    # world. (fence_quads() is kept for anyone who wants one.)
    scene.walls = wall_quads(line, sections)
    scene.wall_texture = "wall.tga"
    armco = add_armco_sections(scene, line, sections)

    trackgen.add_ground(scene, margin=MARGIN + 1600.0, drop=-(land.base - min(p[2] for p in pts)) + 0.3)
    scene.colours["ground.mod"] = [bs.grey(0.84)] * 4

    # vegetation over the new land
    class T:                                               # the placement API build_scenic expects
        pass
    t = T()
    t.x0, t.x1, t.y0, t.y1 = land.x0, land.x1, land.y0, land.y1
    trees = []
    rng = random.Random(11)
    for _ in range(26000):
        x = rng.uniform(land.x0 + 60, land.x1 - 60); y = rng.uniform(land.y0 + 60, land.y1 - 60)
        h, d = land.h(x, y)
        if d < bc.GRASS_EDGE + 6:
            continue
        forest = bs.vnoise(x, y, 180.0, 21)
        if forest > 0.58 and rng.random() < (forest - 0.5) * 1.6:
            kind = "pine.tex" if (h > 6 or rng.random() < 0.6) else "oak.tex"
        elif d < 70 and rng.random() < 0.05:
            kind = "bush.tex"
        elif rng.random() < 0.012:
            kind = "oak.tex"
        else:
            continue
        lo, hi, aspect = bs.KINDS[kind]
        trees.append((kind, x, y, h - 0.2, rng.uniform(lo, hi), aspect, rng.uniform(0, 180), rng.uniform(0.82, 1.0)))
    veg = bs.add_vegetation(scene, trees)
    n_rock, rock_chunks = add_boulders(scene, land, line, random.Random(23))

    # chevrons and targets, as proven
    for n, s in enumerate([1860 + 24 * k for k in range(6)]):
        (x, y, z), (tx, ty) = line.at(s)
        (_, _, _), (ax, ay) = line.at(s - 20)
        (_, _, _), (bx, by) = line.at(s + 20)
        turn_left = (ax * by - ay * bx) > 0
        side = -1.0 if turn_left else 1.0
        pos = (x - ty * side * (bc.HALF + 3.5), y + tx * side * (bc.HALF + 3.5), z)
        name = f"chev{n:02d}.mod"
        scene.meshes[name] = bc.chevron_mesh(bc.yaw_facing_traffic(tx, ty), arrow_right=not turn_left)
        scene.wobbles.append(trackgen.Wobble(position=pos, mesh=name, radius=0.5, height=2.5))
    # Eighteen targets, 2.4 m across: twelve down the back straight, six on the
    # main straight. Hinged low so the horn ball meets each head well above the
    # hinge, which is what tips it (runtime.md 3).
    stations = [2440 + 50 * k for k in range(12)] + [90 + 60 * k for k in range(6)]
    trng = random.Random(29)
    # Sizes from a 0.8 m bullseye to a 3.6 m board, and each hinged low enough that
    # the ball still crosses its face at least ~0.5 m above the hinge -- the
    # leverage that tips it. Bigger heads hinge a little higher, as real signs do.
    tgt_rows = []
    for n, s in enumerate(stations):
        radius = trng.choice((0.4, 0.6, 0.6, 0.9, 0.9, 1.2, 1.2, 1.8))
        hinge = round(min(0.5, 0.15 + 0.15 * radius), 2)
        lat = round(trng.uniform(bc.HALF + 2.0, bc.HALF + 10.0), 1) * (1 if n % 2 else -1)
        tgt_rows.append((s, radius, hinge, lat))
    score_tex = [score_for(2 * r)[1] for _s, r, _h, _l in tgt_rows]
    for n, (s, radius, hinge, lat) in enumerate(tgt_rows):
        (x, y, z), (tx, ty) = line.at(s)
        foot = (x - ty * lat, y + tx * lat, z)
        yaw = bc.yaw_facing_traffic(tx, ty)
        name = f"tgt{n:02d}.mod"
        v, f, texname = target_head(radius, score_tex[n])
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, texname)
        scene.wobbles.append(trackgen.Wobble(position=(foot[0], foot[1], z + hinge), mesh=name,
                                             radius=radius, height=2 * radius))
        sv, sf = stick(0.0, hinge)
        g = bc.game(foot)
        gv = [mod.Vertex(vx + g[0], vy + g[1], vz + g[2], 0.0, 1.0, 0.0, u, w)
              for vx, vy, vz, u, w in turn(sv, yaw)]
        sname = f"stk{n:02d}.mod"
        scene.meshes[sname] = mod.Mesh(vertices=gv, faces=sf, materials=[
            mod.Material(name=score_tex[n], vertex_start=0, vertex_end=len(gv),
                         face_start=0, face_end=len(sf))])
        scene.scenery.append(trackgen.SceneObject(sname, GRASS, trackgen.NO_COLLISION))

    tally = {}
    for _s, r, _h, _l in tgt_rows:
        v, _t = score_for(2 * r)
        tally[v] = tally.get(v, 0) + 1
    print("targets: " + ", ".join(f"{2 * r:.1f} m at {h:.2f} m worth {score_for(2 * r)[0]}"
                                  for _s, r, h, _l in tgt_rows))
    print("         " + ", ".join(f"{n} x {v}-pointers" for v, n in sorted(tally.items())))
    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn) + len(scene.wobbles)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    print(f"armco {armco} chunks over {len(sections)} wall sections; vegetation {veg} chunks, "
          f"{len(trees)} plants; boulders {n_rock} in {rock_chunks} chunks (solid as spheres)")
    print(f"surfaces {surfaces} (budget {bs.SURFACE_BUDGET}); largest chunk {biggest} verts (limit "
          f"{bs.MAX_VERTS}); collision triangles {collide} (budget {COLLISION_BUDGET})")
    if surfaces > bs.SURFACE_BUDGET or biggest > bs.MAX_VERTS or collide > COLLISION_BUDGET:
        raise SystemExit("over budget")

    for _limit, value, texname in SCORES:
        bs.GENERATED[texname] = ((lambda v=value: target_face(v)), "opaque")
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot="limbo",
                              textures={t_: "asph.tex" for t_ in wanted}, closed=True,
                              corridor=ili.corridor_for(bc.HALF * 2.0))
    print(f"assembled: {res.summary()}")

    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        fn, mode = bs.GENERATED[name]
        im = fn(); a = np.array(im)
        if mode == "opaque":
            if int((a.sum(axis=2) == 0).sum()):
                raise SystemExit(f"{name} has black texels")
            data = im.tobytes()
        else:
            data = np.dstack([a, np.where(a.sum(axis=2) > 0, 255, 0).astype(np.uint8)]).tobytes()
        enc = envelope.parse(tex.encode_to_tex(data, im.width, mode=mode, wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = bs.art.sky()
    for tname, raw_tile in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw_tile)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for k in range(10):
        s = k * line.L / 10
        (x, y, z), (tx, ty) = line.at(s)
        (ax, ay, az), _ = line.at(s + 45)
        side = 1.0 if k % 2 == 0 else -1.0
        cxs, cys = x - ty * side * 33.0, y + tx * side * 33.0
        gpos, gtgt = bc.game((cxs, cys, land.h(cxs, cys)[0] + 6.0)), bc.game((ax, ay, az + 1.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)

    by = {e.name.lower(): e for e in archive.read(OUT)}
    for name in sorted(wanted) + list(sky.TILES):
        tex.parse(envelope.build(by[name].tag, by[name].version, by[name].payload))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    ids = sorted(q.id for q in so.primitives if q.id >= 0)
    spheres = [q for q in so.primitives if q.type == sol.SPHERE]
    radii = [struct.unpack_from("<f", q.raw, 0x58)[0] for q in spheres]
    print(f"textures all decode; wobbles {ids[0]}..{ids[-1]}; "
          f"{sum(1 for q in so.primitives if q.type == sol.BOX)} wall boxes; "
          f"{len(spheres)} boulder spheres, radius {min(radii):.1f}-{max(radii):.1f} m; {len(cams)} cameras")
    if len(spheres) != n_rock or any(q.id != -1 for q in spheres):
        raise SystemExit("boulder spheres wrong")
    if ids != list(range(6 + len(stations))):
        raise SystemExit("wobble ids wrong")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
