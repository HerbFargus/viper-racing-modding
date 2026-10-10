"""The scenic course with drivable terrain, a river, and a bridge over it.

THE RIVER runs from a lake in the infield, out under the back straight, and off
the map -- a closed track can only be crossed an even number of times, so the
water has to start inside the loop. It is carved into the land (Land.h takes the
lower of land and channel), its banks are seam points like the verge's, and the
water surface itself is the driveable surface there (code WATER); the land
triangles inside the channel are dropped, so no point carries two surfaces.

THE BRIDGE is the road itself: .bpp holds ONE surface per point, so a deck with
water under it is impossible -- the water stops at the bridge's edges and the
deck is the surface there. Under it: stone fascia, a soffit and two piers, plus
a render-only water patch so the river reads as continuous. Drive off the bridge
into the gorge and there is no ground under the span; that is the trade.


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


def _nearest_s(self, x, y):
    """Arc length of the nearest point on the centreline."""
    best = (1e18, 0.0)
    for i in range(self.n):
        a, b = self.p[i], self.p[(i + 1) % self.n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)))
        px, py = a[0] + t * dx, a[1] + t * dy
        d2 = (x - px) ** 2 + (y - py) ** 2
        if d2 < best[0]:
            best = (d2, self.cum[i] + t * math.dist(a[:2], b[:2]))
    return best[1]


bc.Line.nearest_s = _nearest_s


# ------------------------------------------------------------------ the river
RIVER_CTRL = [(322.0, 338.0), (296.0, 344.0), (258.0, 332.0), (208.0, 316.0), (150.0, 322.0),
              (40.0, 300.0), (-120.0, 292.0), (-260.0, 298.0), (-366.0, 302.0),
              (-470.0, 316.0), (-640.0, 330.0)]
# half-widths: a rounded lake head in the infield, tapering to a river
RIVER_WIDTH = [4.0, 26.0, 45.0, 42.0, 34.0, 24.0, 16.0, 12.0, 11.0, 14.0, 20.0]
RIVER_LEVEL_DROP = 9.0            # water sits this far below the road at the crossing
BANK_SLOPE = 0.32                 # how steeply the banks climb out of the channel
# The deck has to span the GORGE, not just the water: the banks climb at
# BANK_SLOPE, so the ravine is the channel plus a run of depth/slope either side.
# A span much longer than that leaves parapets standing in open grass, which is
# what the first build looked like.
BRIDGE_SPAN = 2 * 11.0 + 2 * (RIVER_LEVEL_DROP / BANK_SLOPE) + 14.0


class River:
    """A polyline with a half-width and a water level, both varying along it."""

    def __init__(self, line):
        pts = []
        for a, b, wa, wb in zip(RIVER_CTRL, RIVER_CTRL[1:], RIVER_WIDTH, RIVER_WIDTH[1:]):
            n = max(1, int(math.dist(a, b) / 10.0))
            for i in range(n):
                f = i / n
                pts.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), wa + f * (wb - wa)))
        pts.append((*RIVER_CTRL[-1], RIVER_WIDTH[-1]))
        self.p = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a[:2], b[:2]))
        self.L = self.cum[-1]
        # where it passes under the track, and the road height there
        best = min(range(len(pts)), key=lambda i: line.nearest(pts[i][0], pts[i][1])[0])
        self.cross_d, road_e = line.nearest(pts[best][0], pts[best][1])
        self.cross_s = self.cum[best]
        self.cross_track_s = min((line.cum[k] for k in range(line.n)),
                                 key=lambda t: math.dist(line.at(t)[0][:2], pts[best][:2]))
        self.level_at_cross = road_e - RIVER_LEVEL_DROP
        # a gentle fall: 3 m above the crossing level at the head, 4 m below at the mouth
        self.levels = [self.level_at_cross + 3.0 * (1 - c / self.cum[best])
                       if c <= self.cum[best] else
                       self.level_at_cross - 4.0 * (c - self.cum[best]) / (self.L - self.cum[best])
                       for c in self.cum]

    def nearest(self, x, y):
        """(distance, half-width, water level) at the nearest point of the river."""
        best = (1e18, 0.0, 0.0)
        for i in range(len(self.p) - 1):
            (ax, ay, aw), (bx, by, bw) = self.p[i], self.p[i + 1]
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            px, py = ax + t * dx, ay + t * dy
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < best[0]:
                best = (d2, aw + t * (bw - aw), self.levels[i] + t * (self.levels[i + 1] - self.levels[i]))
        return math.sqrt(best[0]), best[1], best[2]

    def polygon(self):
        """The channel's outline: left bank out, right bank back.

        The water surface is built from these same points, so using the polygon
        (not a distance to the centre) to decide which land triangles to drop
        makes the two boundaries identical -- no slivers of land under the water,
        which .bpp refuses as two surfaces at one point.
        """
        left, right = [], []
        for i in range(len(self.p)):
            (x, y), w, _wl, (nx_, ny_) = self.at(i)
            left.append((x + nx_ * w, y + ny_ * w))
            right.append((x - nx_ * w, y - ny_ * w))
        return left + right[::-1]

    def at(self, i):
        """Station i: centre, half-width, level, and the unit normal (left)."""
        (x, y, w) = self.p[i]
        j = min(i + 1, len(self.p) - 1); k = max(i - 1, 0)
        tx, ty = self.p[j][0] - self.p[k][0], self.p[j][1] - self.p[k][1]
        L = math.hypot(tx, ty) or 1.0
        return (x, y), w, self.levels[i], (-ty / L, tx / L)


# ------------------------------------------------------------------ height field
class Land:
    """The terrain height function (source frame), flush with the verge's edge."""

    def __init__(self, line, verge_drop, river=None):
        self.river = river
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
        h = self.base + (h - self.base) * bc.smoothstep(0.0, 160.0, edge)
        if self.river is not None:                       # the channel cuts through
            dr, w, wl = self.river.nearest(x, y)
            h = min(h, wl + max(0.0, dr - w) * BANK_SLOPE)
        return h, d


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
def corridor_loops(scene, line, cut):
    """The drivable corridor's edge per side, taken from the swept meshes.

    `cut` is (t0, t1): the two STATION lines the verges were trimmed on. Outside
    them the edge is the grass verge's outer vertices; between them the verges
    are gone and it is the road's own edge. The step between the two runs along
    the station line at t0 (and t1), which is exactly where the bands were cut,
    so the seam and the cut edges are the same line -- anything else leaves a
    wedge of land lying under the verge, and .bpp refuses two surfaces at a point.

    Call after trim_bands().
    """
    t0, t1 = cut
    loops = {}
    for side, u_road in (("l", 1.0), ("r", 0.0)):
        verge, road = [], []
        for name, m in scene.meshes.items():
            if name.startswith(f"grass{side}"):
                verge += [v for v in m.vertices if abs(v.u - 1.0) < 1e-9]
            elif name.startswith("asphalt"):
                road += [v for v in m.vertices if abs(v.u - u_road) < 1e-9]

        def tagged(vs):
            out = []
            for v in vs:
                src = (-v.x, -v.z, v.y)
                out.append((line.nearest_s(src[0], src[1]), src))
            out.sort(key=lambda q: q[0])
            ded = []
            for st, q in out:
                if not ded or math.dist(ded[-1][1][:2], q[:2]) > 1e-6:
                    ded.append((st, q))
            return ded

        verge, road = tagged(verge), tagged(road)
        ring = ([q for st, q in verge if st <= t0 + 1e-6]
                + [q for st, q in road if t0 - 1e-6 <= st <= t1 + 1e-6]
                + [q for st, q in verge if st >= t1 - 1e-6])
        out = []
        for q in ring:
            if not out or math.dist(out[-1][:2], q[:2]) > 1e-6:
                out.append(q)
        loops[side] = out
    return loops


def trim_bands(scene, line, s0, s1):
    """Cut the verge bands away across the bridge: the deck is the road alone.

    Trims on the nearest STATION lines at or outside (s0, s1) and returns them,
    so the seam can step in on the very same lines.
    """
    t0 = max((c for c in line.cum[:line.n] if c <= s0), default=s0)
    t1 = min((c for c in line.cum[:line.n] if c >= s1), default=s1)
    removed = 0
    for name in list(scene.meshes):
        if not any(name.startswith(p_) for p_ in ("rumbl", "side", "grass")):
            continue
        m = scene.meshes[name]
        faces = []
        for f in m.faces:
            gx = sum(m.vertices[i].x for i in f) / 3
            gy = sum(m.vertices[i].y for i in f) / 3
            gz = sum(m.vertices[i].z for i in f) / 3
            st = line.nearest_s(-gx, -gz)
            if t0 < st < t1:
                removed += 1
                continue
            faces.append(f)
        if len(faces) == len(m.faces):
            continue
        if not faces:
            scene.meshes.pop(name)
            scene.driveables[:] = [o for o in scene.driveables if o.name != name]
            scene.scenery[:] = [o for o in scene.scenery if o.name != name]
            continue
        used = sorted({i for f in faces for i in f})
        remap = {old: new for new, old in enumerate(used)}
        m.vertices = [m.vertices[i] for i in used]
        m.faces = [tuple(remap[i] for i in f) for f in faces]
        m.materials[0].vertex_end = len(m.vertices)
        m.materials[0].face_end = len(m.faces)
    return removed, (t0, t1)


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
        if math.dist(a[:2], b[:2]) < 1e-6:                 # never emit a duplicate point
            continue
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
def build_terrain(scene, line, river, cut):
    span = cut
    loops = corridor_loops(scene, line, cut)
    drops = []
    for ring in loops.values():
        for pt in ring[::7]:
            d, e = line.nearest(pt[0], pt[1])
            drops.append(pt[2] - e)
    drop = float(np.median(drops))
    land = Land(line, drop, river)

    # seam points: the verge's outer edge, and both banks of the river
    seam = []
    verge_runs = []
    for side in ("l", "r"):
        ring = densify(loops[side], SEAM_STEP)
        verge_runs.append((len(seam), len(ring)))
        seam += [("seam", p) for p in ring]
    corr_xy = np.array([[q[1][0], q[1][1]] for q in seam])
    banks = []
    for i in range(len(river.p)):
        (rx, ry), w, wl, (nx_, ny_) = river.at(i)
        for sgn in (1.0, -1.0):
            bx, by = rx + nx_ * w * sgn, ry + ny_ * w * sgn
            # Banks run right up to the deck, as Ridge Valley's lake does; only a
            # point inside the corridor itself (the road strip, across the bridge)
            # is dropped.
            st_b = line.nearest_s(bx, by)
            d_b = line.nearest(bx, by)[0]
            on_bridge = span[0] <= st_b <= span[1]
            if d_b <= (bc.HALF + 0.5 if on_bridge else bc.GRASS_EDGE + 0.5):
                continue
            # ...and not crowding the corridor seam, which would cost those
            # segments the Gabriel property the watertight join depends on
            if np.min((corr_xy[:, 0] - bx) ** 2 + (corr_xy[:, 1] - by) ** 2) <= CLEAR ** 2:
                continue
            banks.append(("bank", (bx, by, wl)))
    seam += banks

    # Land points must clear the SEAM itself, not just the centreline: the step
    # where the seam cuts in to the road edge at the bridge runs radially, so a
    # point can sit far from the road and still be on top of the seam. Anything
    # within CLEAR of a seam point would break the Gabriel property those
    # segments need to survive the triangulation.
    seam_xy = np.array([[q[1][0], q[1][1]] for q in seam])
    rng = random.Random(5)
    keep = []
    y = land.y0
    while y <= land.y1 + 1e-6:
        x = land.x0
        while x <= land.x1 + 1e-6:
            on_border = x <= land.x0 or y <= land.y0 or x + LATTICE > land.x1 or y + LATTICE > land.y1
            px = x + (0.0 if on_border else rng.uniform(-JITTER, JITTER))
            py = y + (0.0 if on_border else rng.uniform(-JITTER, JITTER))
            d, _ = line.nearest(px, py)
            st = line.nearest_s(px, py)
            edge_here = bc.HALF if span[0] <= st <= span[1] else bc.GRASS_EDGE
            dr, w, _wl = river.nearest(px, py)
            if d > edge_here + CLEAR and dr > w + CLEAR:
                if np.min((seam_xy[:, 0] - px) ** 2 + (seam_xy[:, 1] - py) ** 2) > CLEAR ** 2:
                    keep.append(("land", (px, py)))
            x += LATTICE
        y += LATTICE
    points = seam + keep
    P = [q[1][:2] for q in points]
    print(f"triangulating {len(seam)} seam ({len(banks)} river bank) + {len(keep)} land points ...")
    tris = delaunay(P)

    edgeset = set()
    for a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            edgeset.add(tuple(sorted(e)))
    missing = 0
    for start, m in verge_runs:
        for i in range(m):
            if tuple(sorted((start + i, start + (i + 1) % m))) not in edgeset:
                missing += 1

    cx = np.array([(P[a][0] + P[b][0] + P[c][0]) / 3 for a, b, c in tris])
    cy = np.array([(P[a][1] + P[b][1] + P[c][1]) / 3 for a, b, c in tris])
    in_corr = point_in_poly(cx, cy, [q[:2] for q in loops["l"]]) ^ point_in_poly(cx, cy, [q[:2] for q in loops["r"]])
    in_river = point_in_poly(cx, cy, river.polygon())
    kept = [t for t, bad, wet in zip(tris, in_corr, in_river) if not bad and not wet]
    wet_tris = [t for t, bad, wet in zip(tris, in_corr, in_river) if not bad and wet]

    H = []
    for kind, q in points:
        H.append(q[2] if kind in ("seam", "bank") else land.h(q[0], q[1])[0])

    def shade_at(i):
        x, y = P[i]
        if points[i][0] == "seam":
            return 0.96
        hx = (land.h(x + 1.5, y)[0] - land.h(x - 1.5, y)[0]) / 3.0
        hy = (land.h(x, y + 1.5)[0] - land.h(x, y - 1.5)[0]) / 3.0
        nrm = np.array([-hx, -hy, 1.0]); nrm /= np.linalg.norm(nrm)
        return float(np.clip(0.34 + 0.62 * max(0.0, nrm @ bs.SUN) / bs.SUN[2], 0.3, 1.0))
    shade = [shade_at(i) for i in range(len(P))]

    groups = defaultdict(list)
    for a, b, c in kept:
        mx = (P[a][0] + P[b][0] + P[c][0]) / 3; my = (P[a][1] + P[b][1] + P[c][1]) / 3
        ux, uy, uz = P[b][0] - P[a][0], P[b][1] - P[a][1], H[b] - H[a]
        vx, vy, vz = P[c][0] - P[a][0], P[c][1] - P[a][1], H[c] - H[a]
        nz = ux * vy - uy * vx
        nx, ny = uy * vz - uz * vy, uz * vx - ux * vz
        slope = math.hypot(nx, ny) / abs(nz) if nz else 9.0
        d, _ = line.nearest(mx, my)
        dr, w, _wl = river.nearest(mx, my)
        if slope > 0.45:
            kind = "rock.tex"
        elif dr < w + 14:
            kind = "dirt.tex"                             # a shingle bank at the water's edge
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
            uvs = 8.0 if kind in ("rock.tex", "dirt.tex") else 12.0
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
                a_, b_, c_ = (verts[k] for k in f)
                ny_ = (b_.z - a_.z) * (c_.x - a_.x) - (b_.x - a_.x) * (c_.z - a_.z)
                faces.append(tuple(f) if ny_ > 0 else (f[0], f[2], f[1]))
            name = f"g{count:03d}{kind[0]}.mod"
            scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
                mod.Material(name=kind, vertex_start=0, vertex_end=len(verts),
                             face_start=0, face_end=len(faces))])
            scene.colours[name] = cols
            scene.driveables.append(trackgen.SceneObject(name, DIRT if kind in ("rock.tex", "dirt.tex") else GRASS))
            count += 1
    # WATER: the channel's triangles, every vertex at the river's own level there.
    # Vertices shared with the land or the deck's edge get their own copy at water
    # level, so the deck stands above the water exactly as Ridge Valley's does.
    wl_at = {}
    def level(i):
        if i not in wl_at:
            wl_at[i] = river.nearest(P[i][0], P[i][1])[2]
        return wl_at[i]
    wchunks = 0
    wgroups = defaultdict(list)
    for a, b, c in wet_tris:
        mx = (P[a][0] + P[b][0] + P[c][0]) / 3; my = (P[a][1] + P[b][1] + P[c][1]) / 3
        wgroups[(int((mx - land.x0) // TILE), int((my - land.y0) // TILE))].append((a, b, c))
    for key, tl in sorted(wgroups.items()):
        for start in range(0, len(tl), 900):
            idx, verts, cols, faces = {}, [], [], []
            for tri in tl[start:start + 900]:
                f = []
                for i in tri:
                    if i not in idx:
                        idx[i] = len(verts)
                        g = bc.game((P[i][0], P[i][1], level(i)))
                        verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, P[i][0] / 14.0, P[i][1] / 14.0))
                        cols.append(bs.grey(0.95))
                    f.append(idx[i])
                a_, b_, c_ = (verts[k] for k in f)
                ny_ = (b_.z - a_.z) * (c_.x - a_.x) - (b_.x - a_.x) * (c_.z - a_.z)
                faces.append(tuple(f) if ny_ > 0 else (f[0], f[2], f[1]))
            name = f"water{wchunks:03d}.mod"
            scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
                mod.Material(name="water.tex", vertex_start=0, vertex_end=len(verts),
                             face_start=0, face_end=len(faces))])
            scene.colours[name] = cols
            scene.driveables.append(trackgen.SceneObject(name, trackgen.WATER))
            wchunks += 1
    build_terrain.water = (len(wet_tris), wchunks)
    return land, count, len(kept), missing, drop, len(tris) - len(kept)


def add_water(scene, line, river, span):
    """Draw the river UNDER the deck: the road strip over the channel, at water level.

    Drawn only -- the deck is the surface at those points. It spans exactly the
    road's width, so it meets the solid water beside the deck edge to edge
    instead of lying on top of it.
    """
    poly = river.polygon()
    under = []
    ks = [k for k in range(line.n) if span[0] <= line.cum[k] <= span[1]]
    for k in ks[:-1]:
        (ax, ay, _az), (tax, tay) = line.at(line.cum[k])
        (bx, by, _bz), (tbx, tby) = line.at(line.cum[k + 1])
        mid = np.array([(ax + bx) / 2]), np.array([(ay + by) / 2])
        near_water = river.nearest(float(mid[0][0]), float(mid[1][0]))
        if near_water[0] > near_water[1] + 12.0:
            continue                                    # this stretch of deck is over land
        wl = near_water[2]
        h = bc.HALF
        under.append([(ax - tay * h, ay + tax * h, wl), (bx - tby * h, by + tbx * h, wl),
                      (bx + tby * h, by - tbx * h, wl), (ax + tay * h, ay - tax * h, wl)])
    if not under:
        return 0, 0, 0
    verts, cols, faces = [], [], []
    for corners in under:
        base = len(verts)
        for cx_, cy_, cz in corners:
            g = bc.game((cx_, cy_, cz))
            verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, cx_ / 14.0, cy_ / 14.0))
            cols.append(bs.grey(0.85))
        tri = [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        a_, b_, c_ = (verts[k] for k in tri[0])
        ny_ = (b_.z - a_.z) * (c_.x - a_.x) - (b_.x - a_.x) * (c_.z - a_.z)
        faces += tri if ny_ > 0 else [(t[0], t[2], t[1]) for t in tri]
    scene.meshes["wunder.mod"] = mod.Mesh(vertices=verts, faces=faces, materials=[
        mod.Material(name="water.tex", vertex_start=0, vertex_end=len(verts),
                     face_start=0, face_end=len(faces))])
    scene.colours["wunder.mod"] = cols
    scene.scenery.append(trackgen.SceneObject("wunder.mod", trackgen.WATER, trackgen.NO_COLLISION))
    return 1, 0, len(under)


def add_bridge(scene, line, river, land, walls_out, span):
    """Stone fascia, soffit and piers under the deck, and parapets you can lean on."""
    s0, s1 = span
    deck_drop = 4.0                                        # depth of the deck structure
    verts, cols, faces = [], [], []

    def quad(p0, p1, p2, p3, tone, uv):
        base = len(verts)
        for (px, py, pz), (u, v) in zip((p0, p1, p2, p3), uv):
            g = bc.game((px, py, pz))
            verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, u, v))
            cols.append(bs.grey(tone))
        faces.extend([(base, base + 1, base + 2), (base, base + 2, base + 3),
                      (base, base + 2, base + 1), (base, base + 3, base + 2)])   # both sides

    step = 10.0
    s = s0
    edge = bc.HALF + 0.35                       # the deck's edge, just outside the road
    while s < s1:
        e = min(s + step, s1)
        (ax, ay, az), (tax, tay) = line.at(s)
        (bx, by, bz), (tbx, tby) = line.at(e)
        for sgn in (1.0, -1.0):
            a = (ax - tay * sgn * edge, ay + tax * sgn * edge, az - 0.1)
            b = (bx - tby * sgn * edge, by + tbx * sgn * edge, bz - 0.1)
            u0, u1 = s / 6.0, e / 6.0
            quad((a[0], a[1], a[2]), (b[0], b[1], b[2]),
                 (b[0], b[1], b[2] - deck_drop), (a[0], a[1], a[2] - deck_drop), 0.9,
                 ((u0, 0.0), (u1, 0.0), (u1, 1.0), (u0, 1.0)))                     # fascia
            quad((a[0], a[1], a[2] + 1.0), (b[0], b[1], b[2] + 1.0),
                 (b[0], b[1], b[2]), (a[0], a[1], a[2]), 1.0,
                 ((u0, 0.0), (u1, 0.0), (u1, 0.35), (u0, 0.35)))                   # parapet
            walls_out.append([(a[0], a[1], a[2]), (b[0], b[1], b[2]),
                              (b[0], b[1], b[2] + 1.0), (a[0], a[1], a[2] + 1.0)])
        la = (ax - tay * edge, ay + tax * edge, az - 0.1 - deck_drop)
        ra = (ax + tay * edge, ay - tax * edge, az - 0.1 - deck_drop)
        lb = (bx - tby * edge, by + tbx * edge, bz - 0.1 - deck_drop)
        rb = (bx + tby * edge, by - tbx * edge, bz - 0.1 - deck_drop)
        quad(la, lb, rb, ra, 0.55, ((s / 8, 0.0), (e / 8, 0.0), (e / 8, 1.0), (s / 8, 1.0)))  # soffit
        s = e

    # Piers: UNDER the deck, one each side of the river, 20 m along the road from
    # the crossing -- on the gorge's slopes, as wide as the road. (The first
    # version offset them sideways, which stood them in the river beside the
    # bridge instead of under it.)
    for ds in (-20.0, 20.0):
        (px, py, pz), (tx, ty) = line.at(river.cross_track_s + ds)
        half_along, half_across = 2.5, bc.HALF - 1.0
        nx_, ny_ = -ty, tx                                 # sideways (left)
        corners = [(px - tx * half_along - nx_ * half_across, py - ty * half_along - ny_ * half_across),
                   (px + tx * half_along - nx_ * half_across, py + ty * half_along - ny_ * half_across),
                   (px + tx * half_along + nx_ * half_across, py + ty * half_along + ny_ * half_across),
                   (px - tx * half_along + nx_ * half_across, py - ty * half_along + ny_ * half_across)]
        base = min(land.h(cx_, cy_)[0] for cx_, cy_ in corners) - 1.5   # footed in the slope
        top = pz - 0.1 - deck_drop
        for (q0x, q0y), (q1x, q1y) in zip(corners, corners[1:] + corners[:1]):
            quad((q0x, q0y, base), (q1x, q1y, base), (q1x, q1y, top), (q0x, q0y, top),
                 0.72, ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)))
    scene.meshes["bridge.mod"] = mod.Mesh(vertices=verts, faces=faces, materials=[
        mod.Material(name="stone.tex", vertex_start=0, vertex_end=len(verts),
                     face_start=0, face_end=len(faces))])
    scene.colours["bridge.mod"] = cols
    scene.scenery.append(trackgen.SceneObject("bridge.mod", GRASS, trackgen.NO_COLLISION))
    return s0, s1, len(verts)


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


def built_height(land, x, y):
    """The height the BUILT ground has here, not the height function's.

    The land is triangulated from a lattice LATTICE metres apart, so between
    those points the surface is flat while the function still curves. Anything
    placed with the function alone floats (or sinks) by the difference, which on
    the gorge's walls is metres. Interpolating the function at the surrounding
    lattice corners is what the triangles actually do.
    """
    gx = land.x0 + math.floor((x - land.x0) / LATTICE) * LATTICE
    gy = land.y0 + math.floor((y - land.y0) / LATTICE) * LATTICE
    fx = (x - gx) / LATTICE; fy = (y - gy) / LATTICE
    h00 = land.h(gx, gy)[0]; h10 = land.h(gx + LATTICE, gy)[0]
    h01 = land.h(gx, gy + LATTICE)[0]; h11 = land.h(gx + LATTICE, gy + LATTICE)[0]
    return ((h00 * (1 - fx) + h10 * fx) * (1 - fy) + (h01 * (1 - fx) + h11 * fx) * fy)


def steepness(land, x, y):
    """|gradient| of the height function -- how steep the ground is at (x, y)."""
    hx = (land.h(x + 2.0, y)[0] - land.h(x - 2.0, y)[0]) / 4.0
    hy = (land.h(x, y + 2.0)[0] - land.h(x, y - 2.0)[0]) / 4.0
    return math.hypot(hx, hy)


def add_boulders(scene, land, line, rng, river):
    """Scatter boulders on the open ground: drawn as meshes, solid as .sol spheres."""
    placed = []
    guard = 0
    while len(placed) < BOULDERS and guard < 40000:
        guard += 1
        x = rng.uniform(land.x0 + 60, land.x1 - 60); y = rng.uniform(land.y0 + 60, land.y1 - 60)
        h, d = land.h(x, y)
        dr, w, _wl = river.nearest(x, y)
        if d < bc.GRASS_EDGE + 3 or d > 260 or dr < w + 3:
            continue
        # The ground is BUILT from points 20 m apart, so on a steep slope it can
        # sit metres below the height function a rock was placed with -- which
        # leaves boulders hanging in the air over the gorge.
        if steepness(land, x, y) > 0.3:
            continue
        h = min(h, built_height(land, x, y))              # sit on the built ground
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

    river = River(line)
    span = (river.cross_track_s - BRIDGE_SPAN / 2, river.cross_track_s + BRIDGE_SPAN / 2)
    cut_faces, cut = trim_bands(scene, line, *span)
    land, chunks, ntri, missing, drop, dropped = build_terrain(scene, line, river, cut)
    print(f"bridge deck: the road alone, {2 * bc.HALF:.0f} m wide; {cut_faces} verge faces cut away "
          f"between the station lines at {cut[0]:.0f} and {cut[1]:.0f} m")
    print(f"terrain: {ntri} driveable triangles in {chunks} chunks ({dropped} dropped inside the "
          f"corridor); verge edge sits {drop:+.2f} m off the road; seam segments missing: {missing}")
    if missing:
        raise SystemExit("the land does not meet the verge watertight")

    wchunks, wet, under = add_water(scene, line, river, span)
    sections = []
    scene.walls = wall_quads(line, sections)
    bridge_s0, bridge_s1, bridge_verts = add_bridge(scene, line, river, land, scene.walls, cut)
    print(f"river: {river.L:.0f} m from the infield lake to the map edge, crossing the track at "
          f"{river.cross_track_s:.0f} m; water {build_terrain.water[0]} triangles driveable in "
          f"{build_terrain.water[1]} chunks, right up to the deck's edges; {under} quads drawn under "
          f"the deck; bridge {bridge_s0:.0f}-{bridge_s1:.0f} m, {bridge_verts} verts, "
          f"deck {RIVER_LEVEL_DROP:.0f} m above the water")
    scene.wall_texture = "wall.tga"
    armco = add_armco_sections(scene, line, sections)

    # Below the RIVER, not just below the land: the horizon plane was drawing
    # green over the water where the channel cuts deeper than the lowest verge.
    floor = min(min(river.levels), land.base) - 2.0
    trackgen.add_ground(scene, margin=MARGIN + 1600.0, drop=min(p[2] for p in pts) - floor)
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
        dr, w, _wl = river.nearest(x, y)
        if d < bc.GRASS_EDGE + 6 or dr < w + 4 or steepness(land, x, y) > 0.35:
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
        h = min(h, built_height(land, x, y))              # sit on the built ground
        trees.append((kind, x, y, h - 0.2, rng.uniform(lo, hi), aspect, rng.uniform(0, 180), rng.uniform(0.82, 1.0)))
    veg = bs.add_vegetation(scene, trees)
    n_rock, rock_chunks = add_boulders(scene, land, line, random.Random(23), river)

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
