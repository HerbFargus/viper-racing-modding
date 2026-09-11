"""`.bpp` — a track's collision BSP: a triangle soup plus a 2D tree over the XZ plane.

WHAT IT IS. The largest file in every track, and the one the physics asks "what is
under / in front of the car". It is entirely separate from `.grf`, which is what
the track *looks* like -- nothing links a collision triangle to a render triangle.

That separation is not academic. Delete an object from `.grf` and it vanishes
visually while its collision triangles stay in the `.bpp`, so the car hits
something that is no longer drawn. Any tool that edits track geometry has to edit
both or it produces invisible walls.

LAYOUT (confirmed against `race.bin`'s own loader, not inferred):

    header, 20 bytes
      +00  u32    n_triangles
      +04  u32    n_nodes
      +08  u32    0
      +0c  u32    0
      +10  u32    root       index of the root node

    triangle x n_triangles, 56 bytes
      +00  float3 normal     unit length
      +0c  float  d          plane, with the convention  n.v + d = 0
      +10  float3 v0
      +1c  float3 v1
      +28  float3 v2
      +34  u32    flag       per-triangle surface bits, see below

    node x n_nodes, 28 bytes
      +00  float  a
      +04  float  b          splitting line in XZ:  a*x + b*z + c
      +08  float  c
      +0c  i32    tri0       triangle index, -1 = none
      +10  i32    tri1       triangle index, -1 = none
      +14  i32    less       child node index, -1 = null
      +18  i32    greater    child node index, -1 = null

`20 + 56*n_triangles + 28*n_nodes` equals the payload length exactly, with no
padding, on every stock track.

WHERE THE LAYOUT COMES FROM. `race.bin`'s loader at `0x468AB0` (v1.2.5) does
`lea eax,[esi+0x14]` for the payload start, then indexes the first section with
`n*7*8` and the second with `n*7*4` -- 20, 56 and 28 read straight off the
arithmetic. `fixup_tree` at `0x468B80` divides pointer differences by `0x1c` to
recover node indices, and rewrites `+0x14`/`+0x18` from indices into pointers,
leaving `+0x00`..`+0x10` alone. The traversal test computes `a*x + b*z + c`.

THE TRIANGLE FLAG IS A BITFIELD, not an enum -- bits 0..4 appear, in combinations,
and the values are wildly non-uniform. Two dominate and appear in every track
(`0` with 72,103 triangles and `10` with 19,081); the rest are rare and
track-specific (4 to 1,033 triangles, in one to three tracks). It correlates with
orientation, which is what suggests a surface classification rather than
bookkeeping: flag `14` is 99.2% horizontal while flag `16` is 91% non-horizontal.
What each bit MEANS is unconfirmed -- surface material, off-track, wall and pit
are all plausible -- so this module keeps the flag as an integer and does not
pretend to interpret it.

`tri0` AND `tri1` ARE THE LEAF PAYLOADS -- ✅ SOLVED, from the symbolised 1998
build. A leaf is not a node of its own. When a node's child pointer on one side
is null, that side's triangle index IS the answer: `tri0` for `less`, `tri1` for
`greater`. `bpp_find_point` is the whole story, a descent with no backtracking:

    d = a*x + b*z + c
    d <= 0 -> `less` child;    null => the answer is tri0
    d >  0 -> `greater` child; null => the answer is tri1

which is why they looked like nothing in particular: on an INNER node the slot is
dead, and about half of them carry a stale index the traversal never reads.

`.bpp` IS A 2.5D SURFACE, NOT A TRIANGLE SOUP -- ✅ CONFIRMED by measurement.
Across the shipped tracks no triangle has a downward normal, the median
|normal.y| is 0.99, and vertical faces number 0 to 45 per track (dundas, limbo
and uptown have none). No two triangles overlap in the XZ plane. That is what
makes an exact 2D point location possible at all: for any (x, z) there is at most
one collision triangle. Everything vertical -- walls, barriers -- is a `.sol`
primitive instead. Sampling 400 interior points per track on all eight, the
descent returns the exact containing triangle every time.

The segment query `bpp_find` adds backtracking to the same structure: descend the
side holding the first endpoint, then the other side if the second endpoint is
across the line, with |d| < 0.001 snapped to zero so a point on the line is
searched both ways. `BPPFinder::test_poly` then does the real 3D work, calling
`intersect_plane` and `point_in_poly`.
"""
from __future__ import annotations

import math
import random
import struct
import sys
from dataclasses import dataclass, field

HEADER = 20
TRIANGLE = 56
NODE = 28

NO_TRI = -1
NO_CHILD = -1


class BppError(ValueError):
    """The payload isn't a .bpp this module recognises."""


@dataclass
class Triangle:
    normal: tuple[float, float, float]
    d: float
    v: tuple[tuple[float, float, float], ...]      # exactly three vertices
    flag: int

    def on_plane_error(self) -> float:
        """Largest |n.v + d| over the three vertices -- 0 for well-formed data."""
        return max(abs(sum(n * c for n, c in zip(self.normal, vert)) + self.d)
                   for vert in self.v)


@dataclass
class Node:
    a: float
    b: float
    c: float
    tri0: int
    tri1: int
    less: int
    greater: int

    def side(self, x: float, z: float) -> float:
        """The splitting test the game itself performs: a*x + b*z + c."""
        return self.a * x + self.b * z + self.c


@dataclass
class Bpp:
    root: int = 0
    reserved: tuple[int, int] = (0, 0)             # header +08 and +0c, zero in stock data
    triangles: list[Triangle] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)

    @property
    def size(self) -> int:
        return HEADER + TRIANGLE * len(self.triangles) + NODE * len(self.nodes)


def parse(payload: bytes) -> Bpp:
    """Decode a .bpp payload (the bytes inside the 0SER envelope)."""
    if len(payload) < HEADER:
        raise BppError(f"too short to hold a header: {len(payload)} bytes")
    n_tri, n_node, r0, r1, root = struct.unpack_from("<5I", payload, 0)
    expect = HEADER + TRIANGLE * n_tri + NODE * n_node
    if expect != len(payload):
        raise BppError(
            f"header says {n_tri:,} triangles and {n_node:,} nodes, which needs "
            f"{expect:,} bytes, but the payload is {len(payload):,}")

    tris: list[Triangle] = []
    off = HEADER
    for _ in range(n_tri):
        f = struct.unpack_from("<13f", payload, off)
        flag = struct.unpack_from("<I", payload, off + 52)[0]
        tris.append(Triangle(normal=f[0:3], d=f[3],
                             v=(f[4:7], f[7:10], f[10:13]), flag=flag))
        off += TRIANGLE

    nodes: list[Node] = []
    for _ in range(n_node):
        a, b, c = struct.unpack_from("<3f", payload, off)
        tri0, tri1, less, greater = struct.unpack_from("<4i", payload, off + 12)
        nodes.append(Node(a, b, c, tri0, tri1, less, greater))
        off += NODE

    return Bpp(root=root, reserved=(r0, r1), triangles=tris, nodes=nodes)


def build(b: Bpp) -> bytes:
    """Re-encode. parse -> build reproduces the original payload byte for byte."""
    out = bytearray()
    out += struct.pack("<5I", len(b.triangles), len(b.nodes),
                       b.reserved[0], b.reserved[1], b.root)
    for t in b.triangles:
        if len(t.v) != 3:
            raise BppError(f"a triangle has {len(t.v)} vertices, not 3")
        out += struct.pack("<13f", *t.normal, t.d, *t.v[0], *t.v[1], *t.v[2])
        out += struct.pack("<I", t.flag)
    for n in b.nodes:
        out += struct.pack("<3f", n.a, n.b, n.c)
        out += struct.pack("<4i", n.tri0, n.tri1, n.less, n.greater)
    return bytes(out)


# ---------------------------------------------------------------------------
# Building a tree
#
# WHAT THE GAME DOES WITH IT, read from the symbolised 1998 build. `bpp_find_point`
# is a plain descent with no backtracking:
#
#     d = a*x + b*z + c
#     d <= 0 -> `less` child;    null => the answer is this node's tri0
#     d >  0 -> `greater` child; null => the answer is this node's tri1
#
# So a leaf is not a node of its own: the triangle lives on the PARENT, in the
# slot for the side whose child pointer is null. That is what tri0 and tri1 are,
# a question this module's header used to leave open. `bpp_find`, the segment
# query, adds backtracking -- descend the side holding the first endpoint, then
# the other side if the second endpoint is across the line, with |d| < 0.001
# snapped to zero so a point on the line is searched both ways.
#
# WHY A 2D TREE IS ENOUGH. Collision triangles do not overlap in the XZ plane.
# Measured across the shipped tracks: no triangle has a downward normal, the
# median |normal.y| is 0.99, and vertical faces number 0 to 45 per track (three
# tracks have none at all). The .bpp is the drivable ground -- a 2.5D surface --
# and everything vertical is a .sol primitive instead. That is why an exact point
# location is possible at all, and it is the assumption this builder rests on.
#
# THE SPLITTING LINES the original compiler used are the triangles' own edges:
# 98.0%-99.3% of nodes across the shipped tracks lie exactly on the XZ line
# through some triangle edge. This builder does the same.
#
# It does NOT try to reproduce `nhmkworld`'s exact output -- tree shape is not
# observable to the game, only the answers are. Correctness here means every
# query returns what the geometry says it should, which is what check_bpp.py
# tests against the shipped trees.

_ON_EPS = 1e-6


def _edge_line(t: Triangle, i: int) -> tuple[float, float, float] | None:
    """The XZ line through edge i of a triangle, as (a, b, c)."""
    (x0, _, z0) = t.v[i]
    (x1, _, z1) = t.v[(i + 1) % 3]
    a, b = (z1 - z0), -(x1 - x0)
    if abs(a) < 1e-12 and abs(b) < 1e-12:
        return None                       # degenerate edge in projection
    return (a, b, -(a * x0 + b * z0))


def _normalise(line: tuple[float, float, float]) -> tuple[float, float, float]:
    """Scale to unit (a, b), so a*x + b*z + c is a true signed distance.

    The shipped files mostly scale to |c| = 1 instead, and this used to copy
    them on the grounds that only the SIGN matters so the choice is cosmetic.
    It is not. A cell out at x = -1026 has |c| ~ 8099, and dividing through by it
    leaves a ~ 0.001 against c = 1 -- the evaluation then cancels three digits
    and a collapsed sliver comes out on BOTH sides of its own edge. Cells like
    that could never be separated, so they recursed to the depth cap. With unit
    (a, b) every term stays the same magnitude and the sign is reliable.
    """
    a, b, c = line
    m = math.hypot(a, b) or 1.0
    return (a / m, b / m, c / m)


def _classify(t: Triangle, line: tuple[float, float, float]) -> int:
    """-1 entirely on the `less` side, +1 entirely `greater`, 0 straddling.

    The query sends d <= 0 to `less`, so a triangle whose largest d is <= 0 sits
    wholly in the less region -- the boundary belongs to less.
    """
    a, b, c = line
    ds = [a * x + b * z + c for (x, _, z) in t.v]
    if max(ds) <= _ON_EPS:
        return -1
    if min(ds) > _ON_EPS:
        return 1
    return 0


def _clip(poly, line, keep_less):
    """Sutherland-Hodgman: the part of `poly` on one side of `line`.

    Points exactly on the line are kept by both sides, which matches the query
    rule (d <= 0 goes left) and keeps shared edges intact.
    """
    a, b, c = line
    out = []
    n = len(poly)
    for i in range(n):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % n]
        d0 = a * x0 + b * z0 + c
        d1 = a * x1 + b * z1 + c
        if not keep_less:
            d0, d1 = -d0, -d1
        in0, in1 = d0 <= _ON_EPS, d1 <= _ON_EPS
        if in0:
            out.append((x0, z0))
        if in0 != in1:
            t = d0 / (d0 - d1) if (d0 - d1) else 0.0
            out.append((x0 + t * (x1 - x0), z0 + t * (z1 - z0)))
    return out


def _area(poly) -> float:
    if len(poly) < 3:
        return 0.0
    s2 = 0.0
    for i in range(len(poly)):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % len(poly)]
        s2 += x0 * z1 - x1 * z0
    return abs(s2) / 2.0


def build_tree(triangles: list[Triangle], *, seed: int = 0,
               candidates: int = 10, min_area: float = 1e-4,
               max_depth: int = 160, max_nodes: int | None = None,
               height_tol: float = 0.01, contact_area: float = 0.01,
               strict: bool = True) -> Bpp:
    """Build a .bpp tree over `triangles`, ready for `build()` to encode.

    The triangles must not overlap in the XZ plane -- see the note above.

    This is a planar-subdivision BSP: a cell carries the triangles' CLIPPED
    fragments, not whole triangles. Clipping is what makes it terminate --
    classifying whole triangles against each line instead leaves distant ones
    straddling every line forever.

    TERMINATION rests on one property: a triangle lies entirely on one side of
    the line through its own edge. So splitting on an edge of some fragment in
    the cell always removes that triangle from one side, and that side's
    distinct-triangle count strictly drops. `choose` requires exactly that.

    A cell holding one triangle becomes a leaf -- which is a null child on the
    parent, with the index in that side's tri0/tri1.

    WHAT A DROPPED FRAGMENT COSTS. Not every one is a defect, and treating them
    alike made this look far worse than it is. Where the replacement is the same
    surface code at the same height -- which is what adjacent coplanar triangles
    are -- the query returns a different index for the same answer and nothing
    about the car changes. Only a different code (wrong grip) or a different
    height (a step in the road) is a real error, and only above `contact_area`,
    since below a tyre's contact patch the car can never be predominantly on the
    fragment. `strict` weighs exactly that, and nothing else.

    On a generated track this is the whole story: a wiggly 2,800-triangle
    centreline drops 210 fragments and NONE of them is material -- sampled, 2
    query points in 4,000 return a different index, and the height error at
    those points is 0.000 m.

    KNOWN LIMIT, at full track scale. Five of the eight shipped tracks build
    whole -- bemidji, dundas, heaven, limbo and uptown -- at depth 17-18 and
    1.93-2.47 nodes per triangle, TIGHTER than the shipped trees' 3.08-3.56,
    with 1,500/1,500 sampled queries correct on each. Both generated test tracks
    build. Three are still refused, and the sizes say they are not one problem:
    hastings loses 0.47 m^2, kenyon 31.71 m^2, and nfield 1,776 m^2 across four
    fragments. Fragments that big suggest nfield genuinely overlaps in XZ rather
    than merely being awkward to split, which would put it outside what this
    structure can represent at all -- worth measuring before assuming the
    splitter is at fault.

    `min_area` discards fragments slimmer than the geometry's own precision.
    Adjacent triangles that share an edge can otherwise leave sub-millimetre
    slivers in a cell that no line usefully separates. `max_depth` is a backstop
    for the same pathology: past it, the largest fragment in the cell wins and
    the rest are dropped. Both are reported in `build_report`.
    """
    if not triangles:
        raise BppError("no triangles to build a tree from")

    rng = random.Random(seed)
    nodes: list[Node] = []
    report = {"dropped_slivers": 0, "depth_capped": 0, "max_depth": 0,
              "dropped_area": 0.0, "total_area": 0.0,
              "material_area": 0.0, "material_fragments": 0,
              "subpatch_area": 0.0, "subpatch_fragments": 0}
    # Capping depth alone does not bound the work: a bad split sequence branches
    # wide instead of deep and the builder runs for hours. The shipped trees sit
    # at ~3.3 nodes per triangle, so this ceiling is generous and still finite.
    budget = max_nodes if max_nodes is not None else 64 * len(triangles) + 1024

    class _Budget(BppError):
        pass

    def choose(items, distinct):
        """A line whose sides each hold strictly fewer distinct triangles."""
        best, best_score = None, None
        n = len(distinct)
        pool = items if len(items) <= candidates else rng.sample(items, candidates)

        def consider(line):
            nonlocal best, best_score
            # Score the normalised line, because that is the one split() will
            # clip with. Scoring the raw line and clipping with another is how
            # an accepted split turned into a rejected one further down.
            line = _normalise(line)
            lo, hi = set(), set()
            area_lo = area_hi = area_cut = 0.0
            for ti, poly in items:
                la = _area(_clip(poly, line, True))
                ga = _area(_clip(poly, line, False))
                if la > min_area:
                    lo.add(ti)
                    area_lo += la
                if ga > min_area:
                    hi.add(ti)
                    area_hi += ga
                if la > min_area and ga > min_area:
                    area_cut += min(la, ga)
            if not lo or not hi:
                return
            # Both sides must be simpler than the parent, or the recursion can
            # hand a child the whole set again and never bottom out.
            if len(lo) >= n or len(hi) >= n:
                return
            # Rank by AREA, not by count. Counting treats a sliver as the equal
            # of a whole triangle, so a count-balanced split is happy to shave
            # slivers off -- which is precisely how the unseparable fragments get
            # manufactured. Cutting a fragment in two is what costs, so the area
            # lost to duplication dominates the score.
            total = area_lo + area_hi - area_cut or 1.0
            score = (max(len(lo), len(hi)),
                     4.0 * area_cut / total + abs(area_lo - area_hi) / total)
            if best_score is None or score < best_score:
                best, best_score = line, score

        for ti, _poly in pool:
            for e in range(3):
                line = _edge_line(triangles[ti], e)
                if line is not None:
                    consider(line)

        # Axis-aligned candidates are considered ALONGSIDE the edges, not merely
        # as a fallback. A long thin triangle's edge line slices the whole cell
        # and peels one triangle at a time; an axis split bisects a cluster
        # whatever shape its triangles are. Tracks differ sharply here -- dundas
        # has a median XZ aspect ratio of 4.4 against bemidji's 2.2 -- and
        # without these the sliver-heavy ones run to hundreds of levels deep.
        xs = sorted(pt[0] for _t, poly in items for pt in poly)
        zs = sorted(pt[1] for _t, poly in items for pt in poly)
        for frac in (0.5, 0.3, 0.7):
            consider((1.0, 0.0, -xs[int(len(xs) * frac)]))
            consider((0.0, 1.0, -zs[int(len(zs) * frac)]))

        if best is None and len(items) > len(pool):
            for ti, _poly in items:
                for e in range(3):
                    line = _edge_line(triangles[ti], e)
                    if line is not None:
                        consider(line)
        return best

    def _height_at(t: Triangle, x: float, z: float) -> float:
        """Where the triangle's plane sits at (x, z). n.v + d = 0, so solve for y."""
        ny = t.normal[1]
        if abs(ny) < 1e-9:
            return t.v[0][1]
        return -(t.normal[0] * x + t.normal[2] * z + t.d) / ny

    def biggest(items) -> int:
        """Keep the largest fragment; charge the rest to the error budget.

        Not every dropped fragment is a defect. Where the replacement is the
        same surface code at the same height -- which is what adjacent coplanar
        triangles are -- the query returns a different index for the same
        answer, and nothing about the car's behaviour changes. Only a fragment
        replaced by a DIFFERENT code, or by a plane at a different height, is a
        real error: wrong grip, or a step in the road. They are counted apart.
        """
        best = max(items, key=lambda it: _area(it[1]))
        keep = best[0]
        kept = triangles[keep]
        for ti, poly in items:
            if ti == keep:
                continue
            a = _area(poly)
            report["dropped_area"] += a
            cx = sum(pt[0] for pt in poly) / len(poly)
            cz = sum(pt[1] for pt in poly) / len(poly)
            dy = abs(_height_at(kept, cx, cz) - _height_at(triangles[ti], cx, cz))
            if triangles[ti].flag != kept.flag or dy > height_tol:
                # Below a tyre's contact patch the car can never be
                # predominantly on the fragment, so a different code there
                # cannot express itself. Counted, but not held against the
                # build. A real contact patch is 0.02-0.05 m^2; the default
                # here is smaller still.
                if a >= contact_area:
                    report["material_area"] += a
                    report["material_fragments"] += 1
                else:
                    report["subpatch_area"] += a
                    report["subpatch_fragments"] += 1
        return keep

    def split(items, depth):
        report["max_depth"] = max(report["max_depth"], depth)
        distinct = {ti for ti, _ in items}
        if len(distinct) == 1:
            return ("tri", items[0][0])
        if depth >= max_depth:
            report["depth_capped"] += 1
            report["dropped_slivers"] += len(distinct) - 1
            return ("tri", biggest(items))
        line = choose(items, distinct)
        if line is None:
            # Nothing separates them. With non-overlapping input this is a
            # numerical sliver, so keep the largest and account for the rest.
            report["dropped_slivers"] += len(distinct) - 1
            return ("tri", biggest(items))
        a, b, c = line          # already normalised by choose()
        less, greater = [], []
        for ti, poly in items:
            lp = _clip(poly, line, True)
            if _area(lp) > min_area:
                less.append((ti, lp))
            gp = _clip(poly, line, False)
            if _area(gp) > min_area:
                greater.append((ti, gp))
        if not less or not greater:
            report["dropped_slivers"] += len(distinct) - 1
            return ("tri", biggest(items))
        if len(nodes) >= budget:
            raise _Budget(
                f"gave up after {len(nodes)} nodes for {len(triangles)} triangles "
                f"({len(nodes)/max(1,len(triangles)):.1f} per triangle; the shipped "
                f"trees run about 3.3). The geometry has slivers this splitter "
                f"cannot separate -- simplify it, or raise max_nodes")
        n = Node(a=a, b=b, c=c, tri0=NO_TRI, tri1=NO_TRI,
                 less=NO_CHILD, greater=NO_CHILD)
        nodes.append(n)
        here = len(nodes) - 1
        kind, val = split(less, depth + 1)
        if kind == "tri":
            n.tri0 = val
        else:
            n.less = val
        kind, val = split(greater, depth + 1)
        if kind == "tri":
            n.tri1 = val
        else:
            n.greater = val
        return ("node", here)

    items = []
    for i, t in enumerate(triangles):
        poly = [(t.v[0][0], t.v[0][2]), (t.v[1][0], t.v[1][2]), (t.v[2][0], t.v[2][2])]
        if _area(poly) > min_area:
            items.append((i, poly))
    if not items:
        raise BppError("every triangle is degenerate in the XZ plane")
    report["total_area"] = sum(_area(poly) for _ti, poly in items)

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, max_depth * 8 + 1000))
    try:
        kind, val = split(items, 1)
    except _Budget as e:
        raise BppError(str(e)) from None
    finally:
        sys.setrecursionlimit(limit)
    if kind == "tri":
        nodes.append(Node(a=1.0, b=0.0, c=0.0, tri0=val, tri1=val,
                          less=NO_CHILD, greater=NO_CHILD))
        val = len(nodes) - 1
    out = Bpp(root=val, reserved=(0, 0), triangles=list(triangles), nodes=nodes)
    out.build_report = report        # type: ignore[attr-defined]
    # A tree that had to discard fragments answers some queries with the wrong
    # triangle -- the car would fall through or land on the wrong surface there.
    # That must not be shippable by accident, so it raises unless asked for.
    if strict and report["material_fragments"]:
        raise BppError(
            f"{report['material_fragments']} fragments covering "
            f"{report['material_area']:.2f} m^2 would answer with a different "
            f"surface code or a different height -- wrong grip, or a step in the "
            f"road. ({report['dropped_slivers']} fragments were dropped in total; "
            f"the rest are adjacent coplanar triangles of the same code, where a "
            f"different index is the same answer.) Simplify the geometry, or pass "
            f"strict=False")
    return out


def find_point(b: Bpp, x: float, z: float) -> int:
    """The game's `bpp_find_point`: the triangle index at (x, z), or NO_TRI.

    Kept here so a built tree can be checked against the geometry it came from.
    """
    n = b.root
    for _ in range(len(b.nodes) + 2):
        node = b.nodes[n]
        if node.side(x, z) <= 0.0:
            if node.less == NO_CHILD:
                return node.tri0
            n = node.less
        else:
            if node.greater == NO_CHILD:
                return node.tri1
            n = node.greater
    raise BppError("descent did not terminate -- the tree has a cycle")


def walk(b: Bpp):
    """Yield node indices reachable from the root, depth first, without revisiting.

    Guards against cycles rather than trusting the data: a malformed tree would
    otherwise hang the caller.
    """
    seen: set[int] = set()
    stack = [b.root]
    while stack:
        i = stack.pop()
        if i < 0 or i >= len(b.nodes) or i in seen:
            continue
        seen.add(i)
        yield i
        n = b.nodes[i]
        stack.append(n.greater)
        stack.append(n.less)


def retag(b: Bpp, mapping: dict[int, int], *,
          region: tuple[float, float, float, float] | None = None) -> int:
    """Rewrite triangle surface codes in place. Returns the number changed.

    `mapping` is {old_code: new_code} -- e.g. {10: 20} turns grass into dirt, or
    {10: 14} floods the grass with water. Codes not in the mapping are left alone.

    `region`, if given, is an axis-aligned XZ box (min_x, min_z, max_x, max_z) in
    world units; only triangles whose centroid falls inside it are retouched. That
    is the difference between "make all grass dirt" and "make the grass in THIS
    corner dirt". Y is ignored, matching the game's own 2D (XZ) surface model.

    The surface code is what the physics reads at a contact point (see the
    reference): it selects drag, dust and float behaviour. This edits only that
    field, so the collision shape is untouched -- the car still hits exactly what
    it hit before, it just behaves differently on contact.
    """
    changed = 0
    for t in b.triangles:
        if t.flag not in mapping:
            continue
        if region is not None:
            cx = (t.v[0][0] + t.v[1][0] + t.v[2][0]) / 3.0
            cz = (t.v[0][2] + t.v[1][2] + t.v[2][2]) / 3.0
            if not (region[0] <= cx <= region[2] and region[1] <= cz <= region[3]):
                continue
        t.flag = mapping[t.flag]
        changed += 1
    return changed


def surface_histogram(b: Bpp) -> dict[int, int]:
    """{surface code: triangle count} -- what to feed a retag decision."""
    out: dict[int, int] = {}
    for t in b.triangles:
        out[t.flag] = out.get(t.flag, 0) + 1
    return dict(sorted(out.items()))


def to_obj(b: Bpp, name: str = "collision") -> str:
    """The collision soup as Wavefront OBJ, for looking at beside the render mesh.

    This is the quickest way to see what a track actually collides with -- and to
    spot geometry that is present here but missing from `.grf`, which is what an
    invisible wall looks like from the outside.
    """
    lines = [f"# {name}: {len(b.triangles):,} collision triangles from .bpp", f"o {name}"]
    for t in b.triangles:
        for vert in t.v:
            lines.append(f"v {vert[0]:.5f} {vert[1]:.5f} {vert[2]:.5f}")
    for i in range(len(b.triangles)):
        a = i * 3 + 1
        lines.append(f"f {a} {a+1} {a+2}")
    return "\n".join(lines) + "\n"
