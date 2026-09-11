"""Checks for the collision tree: the traversal, and building one.

Runs against a synthetic grid, so it needs no game files. Point it at a folder of
extracted track resources to additionally validate the SHIPPED trees:

    python scripts/check_bpp.py "path/to/rescrack-trk-*"

WHAT IS BEING TESTED. Tree shape is not observable to the game -- only the
answers are -- so "correct" here means every query returns the triangle the
geometry says it should, never that a built tree matches `nhmkworld`'s.
"""
from __future__ import annotations

import glob
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import bpp, envelope, ili  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def tri(x0, z0, x1, z1, x2, z2, y=0.0, flag=0) -> bpp.Triangle:
    return bpp.Triangle(normal=(0.0, 1.0, 0.0), d=-y,
                        v=((x0, y, z0), (x1, y, z1), (x2, y, z2)), flag=flag)


def grid(n: int, step: float = 10.0) -> list[bpp.Triangle]:
    """An n x n grid of quads, each split into two triangles. No overlaps."""
    out = []
    for i in range(n):
        for j in range(n):
            x, z = i * step, j * step
            out.append(tri(x, z, x + step, z, x + step, z + step))
            out.append(tri(x, z, x + step, z + step, x, z + step))
    return out


def centroid(t):
    return (sum(v[0] for v in t.v) / 3.0, sum(v[2] for v in t.v) / 3.0)


def inside_xz(t, x, z, eps=1e-6):
    (x0, _, z0), (x1, _, z1), (x2, _, z2) = t.v
    d = (z1 - z2) * (x0 - x2) + (x2 - x1) * (z0 - z2)
    if abs(d) < 1e-12:
        return False
    a = ((z1 - z2) * (x - x2) + (x2 - x1) * (z - z2)) / d
    b = ((z2 - z0) * (x - x2) + (x0 - x2) * (z - z2)) / d
    return a >= -eps and b >= -eps and (1.0 - a - b) >= -eps


def _near_fractions(b, line, within):
    """Per surface code, the fraction of triangles within `within` of the line."""
    import math
    from collections import defaultdict

    cell = 40.0
    grid = defaultdict(list)
    for i, (x, z) in enumerate(line):
        bx, bz = line[(i + 1) % len(line)]
        for k in range(11):
            mx, mz = x + (bx - x) * k / 10.0, z + (bz - z) * k / 10.0
            grid[(int(mx // cell), int(mz // cell))].append(i)

    def dist(px, pz):
        best = float("inf")
        gx, gz = int(px // cell), int(pz // cell)
        for r in range(6):
            for ix in range(gx - r, gx + r + 1):
                for iz in range(gz - r, gz + r + 1):
                    if r and max(abs(ix - gx), abs(iz - gz)) != r:
                        continue
                    for i in grid.get((ix, iz), ()):
                        ax, az = line[i]
                        bx2, bz2 = line[(i + 1) % len(line)]
                        vx, vz = bx2 - ax, bz2 - az
                        L = vx * vx + vz * vz
                        t = 0.0 if L < 1e-12 else max(0.0, min(
                            1.0, ((px - ax) * vx + (pz - az) * vz) / L))
                        best = min(best, math.hypot(px - ax - t * vx, pz - az - t * vz))
            if best < (r + 1) * cell:
                break
        return best

    tally = defaultdict(lambda: [0, 0])
    for t in b.triangles:
        cx = sum(v[0] for v in t.v) / 3.0
        cz = sum(v[2] for v in t.v) / 3.0
        rec = tally[t.flag]
        rec[1] += 1
        rec[0] += dist(cx, cz) <= within
    return {fl: hit / n for fl, (hit, n) in tally.items() if n >= 20}


def main() -> int:
    print("collision tree -- building")
    tris = grid(6)                                   # 72 triangles
    tree = bpp.build_tree(tris, seed=1)
    check("a clean grid builds", len(tree.nodes) > 0,
          f"{len(tris)} triangles -> {len(tree.nodes)} nodes "
          f"({len(tree.nodes)/len(tris):.2f} per triangle)")
    check("nothing was dropped", tree.build_report["dropped_slivers"] == 0
          and tree.build_report["depth_capped"] == 0,
          f"depth {tree.build_report['max_depth']}")

    # Every triangle's own centroid must come back as that triangle.
    hits = sum(1 for i, t in enumerate(tris)
               if bpp.find_point(tree, *centroid(t)) == i)
    check("every triangle is found at its centroid", hits == len(tris),
          f"{hits}/{len(tris)}")

    # And random interior points must land on a triangle containing them.
    rng = random.Random(4)
    ok = 0
    for _ in range(300):
        t = tris[rng.randrange(len(tris))]
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2
        r3 = 1 - r1 - r2
        x = t.v[0][0] * r1 + t.v[1][0] * r2 + t.v[2][0] * r3
        z = t.v[0][2] * r1 + t.v[1][2] * r2 + t.v[2][2] * r3
        got = bpp.find_point(tree, x, z)
        ok += 0 <= got < len(tris) and inside_xz(tris[got], x, z)
    check("random interior points land on a containing triangle", ok == 300,
          f"{ok}/300")

    # Encoding must survive a round trip, and the tree must still answer.
    blob = bpp.build(tree)
    again = bpp.parse(blob)
    check("encodes and re-parses byte for byte", bpp.build(again) == blob,
          f"{len(blob)} bytes")
    check("the re-parsed tree answers identically",
          all(bpp.find_point(again, *centroid(t)) == bpp.find_point(tree, *centroid(t))
              for t in tris[:40]), "40 probes")
    check("the payload length matches the layout",
          len(blob) == again.size, f"{again.size} bytes")

    print("\ncollision tree -- refusing what it cannot do")
    # Overlapping geometry breaks the 2.5D assumption the whole structure rests
    # on, and must not produce a quietly wrong tree.
    stacked = [tri(0, 0, 10, 0, 10, 10), tri(0, 0, 10, 0, 10, 10, y=5.0)]
    try:
        bpp.build_tree(stacked)
        check("overlapping triangles are refused", False, "built anyway")
    except bpp.BppError as e:
        check("overlapping triangles are refused", True, str(e)[:52])

    try:
        bpp.build_tree([])
        check("an empty triangle list is refused", False, "built anyway")
    except bpp.BppError:
        check("an empty triangle list is refused", True, "raises")

    # A node budget, because capping depth alone does not bound the work: a bad
    # split sequence branches wide instead of deep and the builder never returns.
    try:
        bpp.build_tree(grid(6), max_nodes=8)
        check("a runaway build is cut off by the node budget", False, "no limit hit")
    except bpp.BppError as e:
        check("a runaway build is cut off by the node budget", "max_nodes" in str(e)
              or "gave up" in str(e), str(e)[:48])

    # strict=False is the only way to get a lossy tree, and it must say so.
    lossy = bpp.build_tree(grid(6), seed=1, max_depth=2, strict=False)
    check("strict=False returns a tree and reports the loss",
          lossy.build_report["dropped_slivers"] > 0,
          f"{lossy.build_report['dropped_slivers']} fragments dropped")

    print("\ncollision tree -- far from the origin")
    # THE regression that matters. Splitting lines used to be scaled to |c| = 1,
    # which is fine near the origin and ruinous away from it: at x = -1026 that
    # leaves a ~ 0.001 against c = 1, the evaluation cancels three digits, and a
    # collapsed sliver lands on BOTH sides of its own edge. Cells like that could
    # never be separated and recursed to the depth cap -- on kenyon, 76 of them
    # ran the tree to 160 levels. A grid far from the origin must build like one
    # at the origin.
    import math

    near = bpp.build_tree(grid(6), seed=1)
    shift_x, shift_z = -4000.0, 2500.0
    far_tris = [bpp.Triangle(
        normal=t.normal,
        d=t.d - (t.normal[0] * shift_x + t.normal[2] * shift_z),
        v=tuple((x + shift_x, y, z + shift_z) for x, y, z in t.v),
        flag=t.flag) for t in grid(6)]
    far = bpp.build_tree(far_tris, seed=1)
    check("a grid far from the origin builds like one at the origin",
          far.build_report["max_depth"] <= near.build_report["max_depth"] + 4
          and len(far.nodes) <= len(near.nodes) * 2,
          f"depth {near.build_report['max_depth']} near vs "
          f"{far.build_report['max_depth']} far; "
          f"{len(near.nodes)} vs {len(far.nodes)} nodes")
    hits = sum(1 for i, t in enumerate(far_tris)
               if bpp.find_point(far, *centroid(t)) == i)
    check("and it answers correctly out there", hits == len(far_tris),
          f"{hits}/{len(far_tris)} centroids")
    check("splitting lines are scaled to unit (a, b)",
          all(abs(math.hypot(n.a, n.b) - 1.0) < 1e-6 for n in far.nodes),
          "so a*x + b*z + c is a true signed distance")

    # The shape that actually broke: thin triangles far from the origin, where
    # clipping collapses fragments to near-lines. On kenyon these were cells of
    # 0.05 m2 at x = -1026 that ran the tree to 160 levels. A clean grid out
    # there does NOT reproduce it -- the slivers are the point.
    X, Z = -1026.5, -149.0
    thin = []
    for i in range(28):
        x = X + i * 0.13
        thin.append(tri(x, Z, x + 0.13, Z + 0.77, x + 0.26, Z))
        thin.append(tri(x + 0.13, Z + 0.77, x + 0.26, Z, x + 0.39, Z + 0.77))
    sl = bpp.build_tree(thin, seed=1, strict=False)
    check("thin geometry far from the origin does not run away",
          sl.build_report["max_depth"] <= 40 and len(sl.nodes) < len(thin) * 8,
          f"depth {sl.build_report['max_depth']}, {len(sl.nodes)} nodes "
          f"for {len(thin)} triangles")

    print("\ncollision tree -- which losses actually matter")
    # Not every dropped fragment is a defect. Where the replacement is the same
    # surface code at the same height, the query returns a different index for
    # the same answer and the car cannot tell. Only a different code, or a
    # different height, changes what happens to it.
    flat_same = bpp.build_tree(grid(6), seed=1, max_depth=2, strict=False)
    check("dropping a coplanar same-code neighbour is not a defect",
          flat_same.build_report["dropped_slivers"] > 0
          and flat_same.build_report["material_fragments"] == 0,
          f"{flat_same.build_report['dropped_slivers']} dropped, 0 material")
    check("and strict accepts that tree",
          bpp.build_tree(grid(6), seed=1, max_depth=2) is not None,
          "builds")

    # Same geometry, different surface codes -> the loss IS material.
    mixed = grid(6)
    for i, t in enumerate(mixed):
        if i % 2:
            mixed[i] = bpp.Triangle(normal=t.normal, d=t.d, v=t.v, flag=10)
    mx = bpp.build_tree(mixed, seed=1, max_depth=2, strict=False)
    check("dropping a DIFFERENT-code neighbour is a defect",
          mx.build_report["material_fragments"] > 0,
          f"{mx.build_report['material_fragments']} material fragments, "
          f"{mx.build_report['material_area']:.1f} m2")
    try:
        bpp.build_tree(mixed, seed=1, max_depth=2)
        check("strict refuses a materially lossy tree", False, "returned it")
    except bpp.BppError as e:
        check("strict refuses a materially lossy tree", True, str(e)[:44])

    # A step in the road matters even when the code matches.
    stepped = grid(6)
    for i, t in enumerate(stepped):
        if i % 2:
            v = tuple((x, y + 3.0, z) for (x, y, z) in t.v)
            stepped[i] = bpp.Triangle(normal=t.normal, d=t.d - 3.0, v=v, flag=t.flag)
    st = bpp.build_tree(stepped, seed=1, max_depth=2, strict=False)
    check("a height difference counts as material too",
          st.build_report["material_fragments"] > 0,
          f"{st.build_report['material_fragments']} fragments at a different height")

    # Below a tyre contact patch a different code cannot express itself.
    big = bpp.build_tree(mixed, seed=1, max_depth=2, contact_area=1e9, strict=False)
    check("fragments under the contact patch are not held against the build",
          big.build_report["material_fragments"] == 0
          and big.build_report["subpatch_fragments"] > 0,
          f"{big.build_report['subpatch_fragments']} below threshold")

    # --- optional: the shipped trees -----------------------------------------
    roots = [Path(p) for a in sys.argv[1:] for p in glob.glob(a)]
    files = sorted({f for r in roots for f in r.glob("*.bpp")})
    if files:
        print(f"\nshipped trees ({len(files)} files)")
        exact = total = 0
        flat = True
        for path in files:
            b = bpp.parse(envelope.parse(path.read_bytes()).payload)
            if any(t.normal[1] < -0.1 for t in b.triangles):
                flat = False
            rng = random.Random(11)
            for _ in range(60):
                ti = rng.randrange(len(b.triangles))
                t = b.triangles[ti]
                r1, r2 = rng.random(), rng.random()
                if r1 + r2 > 1:
                    r1, r2 = 1 - r1, 1 - r2
                r3 = 1 - r1 - r2
                x = t.v[0][0] * r1 + t.v[1][0] * r2 + t.v[2][0] * r3
                z = t.v[0][2] * r1 + t.v[1][2] * r2 + t.v[2][2] * r3
                total += 1
                exact += bpp.find_point(b, x, z) == ti
        check("the game's descent locates the exact triangle", exact == total,
              f"{exact}/{total} across {len(files)} tracks")
        check("no shipped triangle faces downward", flat,
              "so .bpp is a 2.5D surface, not a soup")

        # Surface codes have a spatial signature: the road is ON the driving
        # line and grass is the band just outside it. The format reference
        # settles what the codes MEAN from engine code; this is an independent
        # check that they are laid out the way that meaning implies -- and the
        # same invariant a generated track has to satisfy.
        near_road, near_grass, tracks = [], [], 0
        for path in files:
            ild = path.parent / "track.ild"
            if not ild.is_file():
                continue
            line = [(w.x, w.z) for w in ili.parse(ild.read_bytes())]
            if len(line) < 8:
                continue
            b = bpp.parse(envelope.parse(path.read_bytes()).payload)
            frac = _near_fractions(b, line, 12.0)
            if frac.get(0) is None or frac.get(10) is None:
                continue
            tracks += 1
            near_road.append(frac[0])
            near_grass.append(frac[10])
        if tracks:
            check("code 0 (road) hugs the driving line",
                  min(near_road) > 0.80,
                  f"{min(near_road):.0%}-{max(near_road):.0%} within 12 m, "
                  f"{tracks} tracks")
            check("code 10 (grass) sits outside it",
                  max(near_grass) < 0.20,
                  f"{min(near_grass):.0%}-{max(near_grass):.0%} within 12 m")

        # Building over REAL geometry is the only thing that catches the
        # normalisation pathology behaviourally -- synthetic slivers do not
        # reproduce it, and neither does every track: under the old scaling
        # bemidji still built to depth 16 while kenyon ran to 160 with
        # 15,116 nodes. So this sweeps them all and reports the worst. It is
        # the slow check here; skip it by running with no path argument.
        worst, worst_name, worst_nodes = 0, '', 0
        for path in files:
            sample = bpp.parse(envelope.parse(path.read_bytes()).payload)
            built = bpp.build_tree(sample.triangles[:4000], seed=1,
                                   strict=False)
            d = built.build_report["max_depth"]
            if d > worst:
                worst, worst_name, worst_nodes = d, path.parent.name, len(built.nodes)
        check("every real 4,000-triangle set builds to a sane depth",
              worst <= 40,
              f"worst is {worst_name} at depth {worst}, {worst_nodes} nodes")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
