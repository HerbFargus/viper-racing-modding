"""Checks for the surface-closure test.

Runs against synthetic meshes, so it needs no game files. Point it at a folder of
extracted track resources to additionally report what the shipped tracks look
like:

    python scripts/check_surface.py "path/to/rescrack-trk-*"

WHAT THIS IS FOR. The collision-tree checks prove the tree represents the
triangles it was handed. They cannot prove the triangles cover the ground: a 6x6
grid with two quads removed builds a clean tree with zero reported loss, and
every query inside the hole answers CONFIDENTLY with a triangle metres away.
That is the car dropping through the world, and nothing in the compiler sees it.
So the cases below are built around faults the compiler is blind to.
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import bpp, envelope, surface  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def tri(x0, z0, x1, z1, x2, z2, y=0.0, flag=0):
    return bpp.Triangle(normal=(0.0, 1.0, 0.0), d=-y,
                        v=((x0, y, z0), (x1, y, z1), (x2, y, z2)), flag=flag)


def grid(n, step=10.0, skip=()):
    out = []
    for i in range(n):
        for j in range(n):
            if (i, j) in skip:
                continue
            x, z = i * step, j * step
            out.append(tri(x, z, x + step, z, x + step, z + step))
            out.append(tri(x, z, x + step, z + step, x, z + step))
    return out


def main() -> int:
    print("surface closure -- a sound surface")
    r = surface.check_closed(grid(6))
    check("a clean grid is closed", r.closed, r.summary())
    check("it has exactly one boundary loop", len(r.loops) == 1,
          f"{len(r.loops)} loop, {r.boundary_edges} boundary edges")
    check("the rim encloses the whole grid",
          r.rim is not None and abs(abs(r.rim.area) - 3600.0) < 1e-6,
          f"{abs(r.rim.area):.0f} m2 of an expected 3,600")
    check("no triangle is lost", r.triangles == 72, f"{r.triangles} counted")

    print("\nsurface closure -- holes")
    r = surface.check_closed(grid(6, skip={(2, 2), (2, 3)}))
    check("two missing quads read as one hole", len(r.holes) == 1,
          f"{len(r.holes)} hole from 2 removed quads -- they adjoin, so one gap")
    check("and it is measured correctly",
          r.holes and abs(abs(r.holes[0].area) - 200.0) < 1e-6,
          f"{abs(r.holes[0].area):.1f} m2 of an expected 200")
    check("the hole is located",
          r.holes and abs(r.holes[0].centre[0] - 25.0) < 1.0
          and abs(r.holes[0].centre[1] - 30.0) < 1.0,
          f"centre ({r.holes[0].centre[0]:.0f}, {r.holes[0].centre[1]:.0f})")
    check("a holed surface is not closed", not r.closed, r.summary())

    # Separated holes must not be merged into one.
    r = surface.check_closed(grid(8, skip={(1, 1), (6, 6)}))
    check("two separate holes stay separate", len(r.holes) == 2,
          f"{len(r.holes)} holes of {[round(abs(h.area)) for h in r.holes]} m2")

    print("\nsurface closure -- T-junctions")
    # Left quad has one long edge; the right pair splits that span at its middle,
    # so the long edge is shared by nobody and the seam cracks.
    t = [tri(0, 0, 10, 0, 10, 10), tri(0, 0, 10, 10, 0, 10),
         tri(10, 0, 20, 0, 20, 10), tri(10, 0, 20, 10, 10, 5),
         tri(10, 5, 20, 10, 10, 10)]
    r = surface.check_closed(t)
    check("a split edge against an unsplit neighbour is caught",
          len(r.t_junctions) == 1, f"{len(r.t_junctions)} found")
    j = r.t_junctions[0] if r.t_junctions else None
    check("the junction is located on its edge",
          j is not None and abs(j.at[0] - 10.0) < 1e-6 and abs(j.at[1] - 5.0) < 1e-6,
          f"at ({j.at[0]:.0f}, {j.at[1]:.0f}), {j.offset:.0%} along" if j else "none")
    check("and it reads as mid-edge, not a stray vertex",
          j is not None and not j.near_duplicate,
          f"{j.end_gap:.2f} m from the nearer end" if j else "none")

    # A vertex a hair from an edge END is a weld miss, which wants a different fix.
    t2 = [tri(0, 0, 10, 0, 10, 10), tri(0, 0, 10, 10, 0, 10),
          tri(10, 0, 20, 0, 20, 10), tri(10, 0, 20, 10, 10, 9.98),
          tri(10, 9.98, 20, 10, 10, 10)]
    r2 = surface.check_closed(t2)
    near = [x for x in r2.t_junctions if x.near_duplicate]
    check("a vertex that merely missed welding is told apart",
          bool(near), f"{len(near)} of {len(r2.t_junctions)} classed as weld misses")

    print("\nsurface closure -- welding")
    # The same grid with every coordinate nudged under the tolerance must still
    # close; nudged over it, the seams come apart.
    import random
    rng = random.Random(3)

    def jitter(tris, amount):
        out = []
        for t in tris:
            v = tuple((x + rng.uniform(-amount, amount), y,
                       z + rng.uniform(-amount, amount)) for x, y, z in t.v)
            out.append(bpp.Triangle(normal=t.normal, d=t.d, v=v, flag=t.flag))
        return out

    r = surface.check_closed(jitter(grid(5), 0.002), weld=0.01)
    check("sub-tolerance jitter still closes", r.closed, r.summary() or "closed")
    r = surface.check_closed(jitter(grid(5), 0.05), weld=0.001)
    check("jitter beyond the tolerance opens the seams", not r.closed,
          f"{len(r.holes)} holes once weld is 1 mm")

    print("\nsurface closure -- overlaps")
    # THE fault that actually makes a track unrepresentable: .bpp stores one
    # triangle per point, so two surfaces over the same ground cannot both be
    # kept. This was missing from the module at first, which is how three
    # shipped tracks got diagnosed as splitter faults when every one of them is
    # an overlap.
    stacked = grid(4) + [tri(5, 5, 25, 5, 25, 25, y=4.0),
                         tri(5, 5, 25, 25, 5, 25, y=4.0)]
    ov = surface.find_overlaps(stacked)
    check("a surface laid over another is found", len(ov) >= 2,
          f"{len(ov)} overlapping pair(s), {sum(o.area for o in ov):.0f} m2")
    check("and the height between them is measured",
          bool(ov) and abs(max(o.height_gap for o in ov) - 4.0) < 1e-6,
          f"{max(o.height_gap for o in ov):.2f} m apart" if ov else "none")

    # Coplanar overlap is harmless -- which triangle answers does not matter.
    flat = grid(4) + [tri(5, 5, 25, 5, 25, 25), tri(5, 5, 25, 25, 5, 25)]
    ovf = surface.find_overlaps(flat)
    check("a coplanar overlap reads as zero height gap",
          bool(ovf) and max(o.height_gap for o in ovf) < 1e-6,
          "the car cannot tell which it lands on")

    check("a clean grid has none", not surface.find_overlaps(grid(5)), "0 pairs")

    # The threshold is the whole game. Sweeping at 1 m2 reported Ridge Valley as
    # clean; its real overlaps are 0.039 and 0.069 m2, and they are exactly what
    # the collision builder refuses it for.
    small = [tri(0, 0, 10, 0, 10, 10), tri(9.7, 0.1, 10, 0, 10, 0.4, y=2.0)]
    check("a small overlap is found at the default threshold",
          bool(surface.find_overlaps(small)),
          f"{surface.find_overlaps(small)[0].area:.3f} m2"
          if surface.find_overlaps(small) else "missed")
    check("and is missed at a coarse one",
          not surface.find_overlaps(small, min_area=1.0),
          "which is the mistake that hid Ridge Valley")

    check("check_closed leaves the expensive pass off by default",
          not surface.check_closed(stacked).overlaps_checked
          and surface.check_closed(stacked, find_overlapping=True).overlaps_checked,
          "opt in with find_overlapping=True")

    # --- optional: the shipped tracks ---------------------------------------
    roots = [Path(p) for a in sys.argv[1:] for p in glob.glob(a)]
    files = sorted({f for r_ in roots for f in r_.glob("*.bpp")})
    if files:
        print(f"\nshipped tracks ({len(files)})")
        closed = 0
        for path in files:
            b = bpp.parse(envelope.parse(path.read_bytes()).payload)
            rep = surface.check_closed(b.triangles)
            closed += rep.closed
            worst = max(rep.holes, key=lambda l: abs(l.area)) if rep.holes else None
            name = path.parent.name.replace("rescrack-trk-", "")
            print(f"    {name:<10} {rep.triangles:>6} tris  "
                  f"{len(rep.holes)} hole(s)"
                  + (f", largest {abs(worst.area):,.1f} m2" if worst else "")
                  + (f", {len(rep.t_junctions)} T-junction(s)" if rep.t_junctions else ""))
        check("the check runs on every shipped track", True,
              f"{closed}/{len(files)} fully closed")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
