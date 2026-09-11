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

from vrmod import bpp, envelope  # noqa: E402

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
    try:
        bpp.build_tree(grid(6), seed=1, max_depth=2)
        check("strict refuses that same tree", False, "returned it")
    except bpp.BppError:
        check("strict refuses that same tree", True, "raises")

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

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
