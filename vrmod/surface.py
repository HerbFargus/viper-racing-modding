"""Does a track's drivable surface actually close?

WHY THIS IS SEPARATE from `bpp`. Building a collision tree proves the tree
faithfully represents the triangles it was handed. It says nothing about whether
those triangles cover the ground. A surface with a quad missing compiles to a
perfectly good tree -- measured: a 6x6 grid with two quads removed builds in 67
nodes with zero reported loss -- and every query inside the hole comes back
CONFIDENT, naming a triangle metres away. In game that is the car dropping onto
a surface that is not there, or riding an invisible ramp. Nothing in the compiler
can notice, because nothing is wrong with the compilation.

So this checks the INPUT, and it is the cheaper of the two: edge adjacency rather
than geometry intersection, O(n) against O(n^2).

WHAT IT LOOKS FOR. On a closed 2.5D surface every edge is shared by exactly two
triangles, except along the outer perimeter. So:

  * an edge used ONCE is a boundary edge. Those are legitimate around the rim and
    a defect anywhere else -- chain them into loops, and every loop past the
    largest is a HOLE.
  * an edge used THREE or more times is non-manifold: surfaces meeting in a way
    a single-valued heightfield cannot represent.
  * two triangles covering the same ground are an OVERLAP, and this is the fault
    that actually makes a track unrepresentable -- a 2D tree stores one triangle
    per point. Finding them costs more than the rest of this module put together,
    so it is opt-in: pass `find_overlapping=True`.
  * a vertex lying on another edge's interior is a T-JUNCTION. It is the usual
    cause of a crack: split one triangle's edge without splitting its neighbour
    and the two no longer share an edge at all, so both sides report as boundary.

T-junctions are why this matters for imported geometry. sunset-mesa's one
overlapping pair -- the mesa surface over the road surface -- are two triangles
whose "shared" vertices differ by up to half a metre. An intersection sweep found
it after a million pair tests; this finds that class of fault directly.

WELDING. Vertices are snapped to a tolerance before anything else, because
authored geometry rarely repeats a coordinate bit-for-bit. The tolerance is the
whole game: too tight and every seam reads as a crack, too loose and real gaps
vanish. `weld` defaults to 1 cm, which is far below anything a car notices and
far above float noise.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

DEFAULT_WELD = 0.01


@dataclass
class Loop:
    """A closed run of boundary edges."""

    vertices: list[tuple[float, float]]
    length: float
    area: float                       # signed area, |.| is what it encloses

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.vertices]
        zs = [p[1] for p in self.vertices]
        return (min(xs), min(zs), max(xs), max(zs))

    @property
    def centre(self) -> tuple[float, float]:
        return (sum(p[0] for p in self.vertices) / len(self.vertices),
                sum(p[1] for p in self.vertices) / len(self.vertices))


@dataclass
class TJunction:
    """A vertex sitting on another triangle's edge instead of at its end."""

    at: tuple[float, float]
    edge: tuple[tuple[float, float], tuple[float, float]]
    offset: float                     # how far along the edge, 0..1
    gap: float                        # perpendicular distance to the edge
    end_gap: float                    # distance to the NEARER end of the edge

    @property
    def near_duplicate(self) -> bool:
        """A vertex that missed welding, rather than a true mid-edge junction.

        The two want different repairs: weld the vertex, or split the neighbour.
        bemidji carries one of each kind 2.4 cm from an edge end; nfield has a
        real one 1.8 m along a 5.2 m edge.
        """
        return self.end_gap <= max(0.1, self.gap * 100.0)


@dataclass
class Overlap:
    """Two triangles covering the same ground, which .bpp cannot represent."""

    a: int
    b: int
    area: float
    height_gap: float                 # how far apart the two surfaces are there


@dataclass
class SurfaceReport:
    triangles: int = 0
    vertices: int = 0
    welded: int = 0                   # vertices merged by the weld tolerance
    degenerate: int = 0               # zero-area in projection
    boundary_edges: int = 0
    loops: list[Loop] = field(default_factory=list)
    non_manifold: list[tuple[tuple[float, float], tuple[float, float], int]] = \
        field(default_factory=list)
    t_junctions: list[TJunction] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    overlaps_checked: bool = False

    @property
    def rim(self) -> Loop | None:
        """The outer perimeter: the loop enclosing the most area."""
        return max(self.loops, key=lambda l: abs(l.area)) if self.loops else None

    @property
    def holes(self) -> list[Loop]:
        """Every loop but the rim. These are gaps in the surface.

        ONE FALSE POSITIVE TO KNOW ABOUT: a circuit swept as a ribbon is an
        ANNULUS, so it has two legitimate boundary loops -- the outer rim and
        the infield. This reports the infield as a hole, because loop topology
        alone cannot tell "gap in the track" from "the middle of the track,
        where there is no track". On a generated ring expect exactly one large
        spurious hole; a real gap is small and sits ON the ribbon.
        """
        if len(self.loops) <= 1:
            return []
        rim = self.rim
        return [l for l in self.loops if l is not rim]

    @property
    def closed(self) -> bool:
        return (not self.holes and not self.non_manifold and not self.t_junctions
                and not self.overlaps)

    def summary(self) -> str:
        if self.closed:
            return (f"closed: {self.triangles} triangles, one rim of "
                    f"{len(self.rim.vertices) if self.rim else 0} edges")
        bits = []
        if self.holes:
            worst = max(self.holes, key=lambda l: abs(l.area))
            bits.append(f"{len(self.holes)} hole(s), largest "
                        f"{abs(worst.area):.2f} m2 at "
                        f"({worst.centre[0]:.0f}, {worst.centre[1]:.0f})")
        if self.t_junctions:
            bits.append(f"{len(self.t_junctions)} T-junction(s)")
        if self.non_manifold:
            bits.append(f"{len(self.non_manifold)} non-manifold edge(s)")
        if self.overlaps:
            bits.append(f"{len(self.overlaps)} overlap(s), "
                        f"{sum(o.area for o in self.overlaps):.3f} m2")
        return "; ".join(bits)


def _xz(tri):
    """The three (x, z) corners of a triangle, from a bpp.Triangle or a tuple."""
    v = getattr(tri, "v", tri)
    return [(p[0], p[2]) if len(p) == 3 else (p[0], p[1]) for p in v]


def _tri_area(p):
    return abs((p[1][0] - p[0][0]) * (p[2][1] - p[0][1])
               - (p[2][0] - p[0][0]) * (p[1][1] - p[0][1])) / 2.0


def _clip_half(poly, line):
    """The part of `poly` on the <= 0 side of `line`."""
    a, b, c = line
    out = []
    n = len(poly)
    for i in range(n):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % n]
        d0 = a * x0 + b * z0 + c
        d1 = a * x1 + b * z1 + c
        if d0 <= 0:
            out.append((x0, z0))
        if (d0 <= 0) != (d1 <= 0):
            t = d0 / (d0 - d1) if (d0 - d1) else 0.0
            out.append((x0 + t * (x1 - x0), z0 + t * (z1 - z0)))
    return out


def _poly_area(poly):
    if len(poly) < 3:
        return 0.0
    s2 = 0.0
    for i in range(len(poly)):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % len(poly)]
        s2 += x0 * z1 - x1 * z0
    return abs(s2) / 2.0


def _height_at(t, x, z):
    n = getattr(t, "normal", None)
    if not n or abs(n[1]) < 1e-9:
        return _xz_y(t)
    return -(n[0] * x + n[2] * z + getattr(t, "d", 0.0)) / n[1]


def _xz_y(t):
    v = getattr(t, "v", t)
    return sum(p[1] for p in v) / 3.0


def find_overlaps(triangles, *, min_area: float = 0.01, cell: float = 60.0):
    """Pairs of triangles covering the same ground.

    THE FAULT THAT ACTUALLY BREAKS .bpp. A 2D tree stores one triangle per point,
    so two surfaces over the same (x, z) cannot both be represented -- the
    collision builder has to discard one, and the car then meets the wrong
    surface, or the wrong height.

    `min_area` matters more than it looks. Sweeping the shipped tracks at 1 m2
    reported hastings as clean; its real overlaps are 0.039 and 0.069 m2, and
    they are exactly what the builder refuses it for. Default 0.01 m2, which is
    a 10 cm square.
    """
    from collections import defaultdict

    polys = []
    for t in triangles:
        v = getattr(t, "v", t)
        polys.append([(p[0], p[2]) for p in v])

    grid = defaultdict(list)
    for i, poly in enumerate(polys):
        xs = [p[0] for p in poly]
        zs = [p[1] for p in poly]
        for gx in range(int(min(xs) // cell), int(max(xs) // cell) + 1):
            for gz in range(int(min(zs) // cell), int(max(zs) // cell) + 1):
                grid[(gx, gz)].append(i)

    def clip_to(sub, j):
        p = polys[j]
        s2 = sum(p[k][0] * p[(k + 1) % 3][1] - p[(k + 1) % 3][0] * p[k][1]
                 for k in range(3))
        if s2 < 0:
            p = p[::-1]
        out = sub
        for k in range(3):
            x0, z0 = p[k]
            x1, z1 = p[(k + 1) % 3]
            a, b = (z1 - z0), -(x1 - x0)
            out = _clip_half(out, (a, b, -(a * x0 + b * z0)))
            if len(out) < 3:
                return []
        return out

    seen = set()
    found = []
    for ids in grid.values():
        if len(ids) > 400:                  # a huge triangle spans many cells
            continue
        for ai in range(len(ids)):
            for bi in range(ai + 1, len(ids)):
                i, j = ids[ai], ids[bi]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                region = clip_to(polys[i], j)
                area = _poly_area(region)
                if area <= min_area:
                    continue
                cx = sum(p[0] for p in region) / len(region)
                cz = sum(p[1] for p in region) / len(region)
                gap = abs(_height_at(triangles[i], cx, cz)
                          - _height_at(triangles[j], cx, cz))
                found.append(Overlap(a=i, b=j, area=area, height_gap=gap))
    found.sort(key=lambda o: -o.area)
    return found


def check_closed(triangles, *, weld: float = DEFAULT_WELD,
                 find_t_junctions: bool = True,
                 find_overlapping: bool = False,
                 overlap_min_area: float = 0.01) -> SurfaceReport:
    """Report whether a set of surface triangles closes.

    `triangles` may be `bpp.Triangle`s or plain 3-tuples of points; only the XZ
    projection is used, since that is the plane the collision tree partitions.
    """
    rep = SurfaceReport()

    # ---- weld ------------------------------------------------------------
    # Snap to a grid of `weld`, then take the first vertex seen in each bucket
    # as canonical. Checking the 8 neighbouring buckets as well keeps two points
    # either side of a bucket boundary from being split apart.
    canon: dict[tuple[int, int], int] = {}
    points: list[tuple[float, float]] = []
    raw = 0

    def vid(p):
        nonlocal raw
        raw += 1
        gx, gz = int(math.floor(p[0] / weld)), int(math.floor(p[1] / weld))
        for dx in (0, -1, 1):
            for dz in (0, -1, 1):
                hit = canon.get((gx + dx, gz + dz))
                if hit is not None:
                    q = points[hit]
                    if abs(q[0] - p[0]) <= weld and abs(q[1] - p[1]) <= weld:
                        return hit
        points.append(p)
        canon[(gx, gz)] = len(points) - 1
        return len(points) - 1

    edges: dict[tuple[int, int], int] = defaultdict(int)
    for t in triangles:
        p = _xz(t)
        if _tri_area(p) <= 0.0:
            rep.degenerate += 1
            continue
        rep.triangles += 1
        ids = [vid(q) for q in p]
        if len(set(ids)) < 3:
            rep.degenerate += 1          # collapsed by welding
            continue
        for i in range(3):
            a, b = ids[i], ids[(i + 1) % 3]
            edges[(a, b) if a < b else (b, a)] += 1

    rep.vertices = len(points)
    rep.welded = raw - len(points)

    boundary = [e for e, n in edges.items() if n == 1]
    rep.boundary_edges = len(boundary)
    rep.non_manifold = [(points[a], points[b], n) for (a, b), n in edges.items() if n > 2]

    # ---- chain boundary edges into loops ---------------------------------
    adj: dict[int, list[int]] = defaultdict(list)
    for a, b in boundary:
        adj[a].append(b)
        adj[b].append(a)

    unused = set(boundary)
    while unused:
        a, b = next(iter(unused))
        unused.discard((a, b))
        chain = [a, b]
        while True:
            cur, prev = chain[-1], chain[-2]
            nxt = None
            for cand in adj[cur]:
                if cand == prev:
                    continue
                key = (cur, cand) if cur < cand else (cand, cur)
                if key in unused:
                    nxt = cand
                    unused.discard(key)
                    break
            if nxt is None:
                break
            if nxt == chain[0]:
                break                     # closed
            chain.append(nxt)
        pts = [points[i] for i in chain]
        length = sum(math.dist(pts[i], pts[(i + 1) % len(pts)])
                     for i in range(len(pts)))
        s2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                 - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
        rep.loops.append(Loop(vertices=pts, length=length, area=s2 / 2.0))

    # ---- T-junctions -----------------------------------------------------
    # Only boundary edges can carry one: an interior edge already has both its
    # triangles, so a vertex landing on it would have shown up as non-manifold.
    if find_t_junctions and boundary:
        cell = max(weld * 50.0, 1.0)
        grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, p in enumerate(points):
            grid[(int(p[0] // cell), int(p[1] // cell))].append(i)
        for a, b in boundary:
            pa, pb = points[a], points[b]
            vx, vz = pb[0] - pa[0], pb[1] - pa[1]
            L = vx * vx + vz * vz
            if L <= 0:
                continue
            gx0, gx1 = sorted((int(pa[0] // cell), int(pb[0] // cell)))
            gz0, gz1 = sorted((int(pa[1] // cell), int(pb[1] // cell)))
            for gx in range(gx0 - 1, gx1 + 2):
                for gz in range(gz0 - 1, gz1 + 2):
                    for i in grid.get((gx, gz), ()):
                        if i == a or i == b:
                            continue
                        p = points[i]
                        t = ((p[0] - pa[0]) * vx + (p[1] - pa[1]) * vz) / L
                        if not (1e-6 < t < 1 - 1e-6):
                            continue
                        gap = math.hypot(p[0] - pa[0] - t * vx, p[1] - pa[1] - t * vz)
                        if gap <= weld:
                            span = math.sqrt(L)
                            rep.t_junctions.append(TJunction(
                                at=p, edge=(pa, pb), offset=t, gap=gap,
                                end_gap=min(t, 1.0 - t) * span))

    # Off by default: this is the expensive pass, O(n^2) within a grid cell
    # rather than the edge-adjacency the rest of this module runs on.
    if find_overlapping:
        rep.overlaps = find_overlaps(triangles, min_area=overlap_min_area)
        rep.overlaps_checked = True
    return rep
