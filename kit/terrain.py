"""Track geometry: frames, triangle batches, Delaunay ground, the racing-line walker.

FRAMES. Three are in play, and mixing them up is the classic way to mirror a track:
  source  x east, y north, z up      -- TrackScene data: centreline, walls, grid, spheres
  game    x, y up, z                 -- meshes, .sol primitives, cameras, .obt X,Z
          game(p) = trackgen.to_viper(p) = (-x, z, -y)
  mockup  x east, y up, z SOUTH      -- the three.js pages; mockup_to_source = (x, -z, y)
          (a rotation, not a mirror)
Obstacle records take X, Z from game((x, y, 0)).

The ground pattern (the Coliseum's, then Cats vs Dogs'): ONE height(x, y) function for the
whole world, Delaunay over road stations + a jittered lattice, every triangle sorted by
kind into a Batch with its own texture and surface code. Ramps, roofs and basins all come
out of height() -- see tracks.py's notes for the slope rules that keep them drivable.

Moved from experiments/pets/recovered/{ballroom/build_ballroom.py (Batch), circuit/
build_river.py (delaunay), circuit/build_circuit.py (Line)}.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

import numpy as np

import kit  # noqa: F401
from vrmod import mod, trackgen
from vrmod.trackgen import GRASS, NO_COLLISION, ROAD

MAX_VERTS = 990        # per drawn chunk


def game(p):
    return trackgen.to_viper(p)


def mockup_to_source(mx, my, mz):
    return (float(mx), float(-mz), float(my))


def smoothstep(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def smootherstep(t):
    """C2-continuous: the rate of change eases in and out too (banking, ramp entries)."""
    t = min(1.0, max(0.0, t))
    return t * t * t * (t * (6 * t - 15) + 10)


class Batch:
    """Triangles for one texture (and one surface code), chunked under MAX_VERTS, with a grey
    baked into the vertex colours -- track geometry is drawn pre-lit, greys only.

    `solid` puts the chunks in scene.driveables (collided, in the .bpp, with `code`: ROAD 0,
    GRASS 10, WATER 14 -- the car floats on 14, with no grip --, RUMBLE 16, DIRT 20);
    otherwise they are drawn-only scenery (param1 = 3). Every Batch needs a UNIQUE stem:
    two with one stem silently overwrite each other's chunks (a whole roof once vanished)."""

    def __init__(self, scene, stem, texture, solid, code=ROAD):
        self.scene, self.stem, self.texture, self.solid, self.code = scene, stem, texture, solid, code
        self.v, self.f, self.c, self.n = [], [], [], 0

    def tri(self, P, uv, grey, up=True):
        """P in the SOURCE frame. The face is wound to show toward `up`: True = the sky, or a
        source-frame point the visible side faces (for props, centroid + outward normal)."""
        g = [game(tuple(p)) for p in P]
        a, b, c = (np.array(q) for q in g)
        want = np.array([0.0, 1.0, 0.0]) if up is True else np.array(game(tuple(up))) - (a + b + c) / 3
        order = [0, 1, 2] if np.dot(np.cross(b - a, c - a), want) >= 0 else [0, 2, 1]
        if len(self.v) + 3 > MAX_VERTS:
            self.flush()
        base = len(self.v)
        for k in order:
            self.v.append(mod.Vertex(*g[k], 0.0, 1.0, 0.0, *uv[k]))
            gv = int(max(40, min(255, grey * 255)))
            self.c.append(bytes([gv, gv, gv, 0xFF]))
        self.f.append((base, base + 1, base + 2))

    def quad(self, P, grey, up=True):
        uv = [(0.02, 0.02), (0.98, 0.02), (0.98, 0.98), (0.02, 0.98)]
        self.tri([P[0], P[1], P[2]], [uv[0], uv[1], uv[2]], grey, up)
        self.tri([P[0], P[2], P[3]], [uv[0], uv[2], uv[3]], grey, up)

    def flush(self):
        if not self.f:
            return
        name = f"{self.stem}{self.n}.mod"
        if name in self.scene.meshes:
            raise ValueError(f"mesh {name} already exists: Batch stems must be unique")
        self.scene.meshes[name] = mod.Mesh(vertices=self.v, faces=self.f, materials=[mod.Material(
            name=self.texture, vertex_start=0, vertex_end=len(self.v), face_start=0, face_end=len(self.f))])
        self.scene.colours[name] = self.c
        if self.solid:
            self.scene.driveables.append(trackgen.SceneObject(name, self.code))
        else:
            self.scene.scenery.append(trackgen.SceneObject(name, GRASS, NO_COLLISION))
        self.v, self.f, self.c, self.n = [], [], [], self.n + 1


def delaunay(P):
    """Bowyer-Watson over points P [(x, y)], bucketed by circumcircle. Returns index triangles.
    Points must be unique (round and dedupe first)."""
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


class Line:
    """A closed source-frame polyline [(x, y, z)] with arc length: at(s) -> ((x, y, z), (tx, ty))."""

    def __init__(self, pts):
        self.p = pts
        n = len(pts)
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.L = self.cum[-1]
        self.n = n

    def at(self, s):
        s %= self.L
        k = max(i for i in range(self.n) if self.cum[i] <= s)
        a, b = self.p[k], self.p[(k + 1) % self.n]
        f = (s - self.cum[k]) / (self.cum[k + 1] - self.cum[k])
        pos = tuple(a[j] + f * (b[j] - a[j]) for j in range(3))
        tx, ty = b[0] - a[0], b[1] - a[1]
        L = math.hypot(tx, ty)
        return pos, (tx / L, ty / L)


class CatmullRom:
    """three.js's CatmullRomCurve3(points, closed=True, 'centripetal') over 2-D control points,
    so a lap drawn in a mockup page comes out identical here.
      at(seg, frac, off) -> ((x, z), tangent, left), the mockups' JS at() (mockup frame)
      stations(step)     -> arc lengths, points, tangents, lefts in the SOURCE frame
      ctrl_s[i]          -> arc length of control point i"""

    def __init__(self, ctrl):
        self.ctrl = [tuple(map(float, c)) for c in ctrl]
        self.n = len(self.ctrl)
        self.segs = [self._segment(i) for i in range(self.n)]
        dense, cum, self.ctrl_s = [], [0.0], []
        for i in range(self.n):
            f, _ = self.segs[i]
            self.ctrl_s.append(cum[-1] if dense else 0.0)
            for k in range(200):
                p = f(k / 200)
                if dense:
                    cum.append(cum[-1] + float(np.hypot(*(p - dense[-1]))))
                dense.append(p)
        self.length = cum[-1] + float(np.hypot(*(dense[0] - dense[-1])))
        self._dense, self._cum = np.array(dense), np.array(cum)

    def _segment(self, i):
        p0, p1, p2, p3 = (np.array(self.ctrl[(i + k) % self.n], float) for k in (-1, 0, 1, 2))

        def dt(a, b):
            return float(np.sum((b - a) ** 2)) ** 0.25
        d0, d1, d2 = dt(p0, p1), dt(p1, p2), dt(p2, p3)
        if d1 < 1e-4:
            d1 = 1.0
        if d0 < 1e-4:
            d0 = d1
        if d2 < 1e-4:
            d2 = d1
        t1 = ((p1 - p0) / d0 - (p2 - p0) / (d0 + d1) + (p2 - p1) / d1) * d1
        t2 = ((p2 - p1) / d1 - (p3 - p1) / (d1 + d2) + (p3 - p2) / d2) * d1
        c0, c1, c2, c3 = p1, t1, -3 * p1 + 3 * p2 - 2 * t1 - t2, 2 * p1 - 2 * p2 + t1 + t2
        return (lambda u: c0 + c1 * u + c2 * u * u + c3 * u ** 3), (lambda u: c1 + 2 * c2 * u + 3 * c3 * u * u)

    def at(self, seg, frac, off=0.0):
        f, df = self.segs[seg % self.n]
        p, t = f(frac), df(frac)
        t = t / np.linalg.norm(t)
        left = np.array([t[1], -t[0]])                 # JS: (tg.z, 0, -tg.x)
        q = p + left * off
        return (float(q[0]), float(q[1])), (float(t[0]), float(t[1])), (float(left[0]), float(left[1]))

    def _at_s(self, s):
        s %= self.length
        k = int(np.searchsorted(self._cum, s, side="right") - 1)
        a, b = self._dense[k], self._dense[(k + 1) % len(self._dense)]
        seg_len = (self._cum[k + 1] if k + 1 < len(self._cum) else self.length) - self._cum[k]
        t = (s - self._cum[k]) / max(seg_len, 1e-9)
        return a + (b - a) * t, (b - a) / max(np.hypot(*(b - a)), 1e-9)

    def stations(self, step=1.0):
        S = np.arange(0.0, self.length, step)
        pts = [self._at_s(s) for s in S]
        xy = np.array([[p[0], -p[1]] for p, _ in pts])          # mockup (x, z) -> source (x, y)
        t = np.array([[d[0], -d[1]] for _, d in pts])
        left = np.stack([-t[:, 1], t[:, 0]], axis=1)
        return S, xy, t, left
