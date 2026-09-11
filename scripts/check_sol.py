"""Checks for the `.sol` spatial index.

The structural claims are checked against the SHIPPED files, because that is
where they came from and they are the part that is certain. The builder is
checked for self-consistency and measured against the shipped trees; it is not
exact, and the check records what it actually achieves rather than asserting
something it does not.

    python scripts/check_sol.py path/to/Data
"""
from __future__ import annotations

import math
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, envelope, sol  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def load(path: Path):
    e = next((x for x in archive.read(path) if x.name.lower().endswith(".sol")), None)
    if e is None:
        return None
    return sol.parse(envelope.build(e.tag, e.version, e.payload))


def main() -> int:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    tracks = sorted(data.glob("*.trk")) if data and data.is_dir() else []

    print("sol -- the tail is a quadtree")
    if not tracks:
        print("  no Data folder given -- pass one to check the shipped files")
    loaded = [(p.stem, load(p)) for p in tracks]
    loaded = [(n, s) for n, s in loaded if s and s.primitives]

    if loaded:
        # Each of these is a structural consequence of the node format read out
        # of collide_object: (first: u16, last: u16, child: u32), four children
        # consecutive from `child`.
        bad = [n for n, s in loaded if len(s.tail) % 8]
        check("every tail is a whole number of 8-byte nodes", not bad,
              f"{len(loaded)} tracks" if not bad else str(bad))

        bad = [n for n, s in loaded if (len(s.tail) // 8 - 1) % 4]
        check("node count is 4k + 1 -- a root plus four children per split",
              not bad, f"e.g. {len(loaded[0][1].tail)//8} = 4*"
                       f"{(len(loaded[0][1].tail)//8 - 1)//4} + 1")

        worst = []
        for n, s in loaded:
            nodes = [struct.unpack_from("<HHI", s.tail, i * 8)
                     for i in range(len(s.tail) // 8)]
            kids = sorted(c for _f, _l, c in nodes if c)
            gaps = {b - a for a, b in zip(kids, kids[1:])}
            if gaps - {4}:
                worst.append((n, sorted(gaps)[:3]))
        check("child indices are spaced exactly four apart", not worst,
              "four children per internal node" if not worst else str(worst))

        bad = []
        for n, s in loaded:
            nodes = [struct.unpack_from("<HHI", s.tail, i * 8)
                     for i in range(len(s.tail) // 8)]
            if any(l > len(s.index) or f > len(s.index) for f, l, _ in nodes):
                bad.append(n)
        check("every [first, last) lies inside the index list", not bad,
              f"{len(loaded)} tracks")

        bad = []
        for n, s in loaded:
            nodes = [struct.unpack_from("<HHI", s.tail, i * 8)
                     for i in range(len(s.tail) // 8)]
            if max((l for _f, l, _c in nodes), default=0) != len(s.index):
                bad.append(n)
        check("the ranges reach exactly the end of the index list", not bad,
              "so they tile it" if not bad else str(bad))

        # INTERNAL nodes carry primitives too -- a solid too big to fit any one
        # quadrant is parked on the ancestor. That is why a query accumulates
        # index ranges along its whole path instead of reading the leaf alone.
        # Returning only the leaf finds a primitive at its own centre 190 times
        # in 300.
        withprims = 0
        for n, s in loaded:
            nodes = [struct.unpack_from("<HHI", s.tail, i * 8)
                     for i in range(len(s.tail) // 8)]
            withprims += any(c and l > f for f, l, c in nodes)
        check("internal nodes carry primitives too, not just leaves",
              withprims == len(loaded),
              f"{withprims}/{len(loaded)} tracks -- so a query accumulates along its path")

        print("\nsol -- the descent")
        name, s = loaded[0]
        rng = random.Random(3)
        inside = 0
        for _ in range(300):
            p = s.primitives[rng.randrange(len(s.primitives))]
            px, _py, pz = p.position
            got = sol.find(s, px, pz)
            inside += p is s.primitives[got[0]] or any(
                s.primitives[g] is p for g in got) if got else 0
        check("a primitive's own centre descends to a leaf holding it",
              inside >= 285, f"{inside}/300 on {name}")

        far = sol.find(s, 3_000_000.0, 3_000_000.0)
        check("a point far outside the track finds nothing", not far,
              "empty leaf")

    print("\nsol -- building one")
    if loaded:
        name, s = loaded[0]
        idx, tail = sol.build_spatial_index(s.primitives, max_per_leaf=32)
        check("a built tail is a whole number of nodes", len(tail) % 8 == 0,
              f"{len(tail)//8} nodes for {len(s.primitives)} primitives")
        check("and is 4k + 1", (len(tail) // 8 - 1) % 4 == 0, "same shape as shipped")
        check("the index fits the u16 field", len(idx) <= 0xFFFF, f"{len(idx):,} entries")

        mine = sol.Sol(primitives=s.primitives, index=idx, tail=tail, version=s.version)
        rng = random.Random(11)
        ok = 0
        for _ in range(600):
            p = s.primitives[rng.randrange(len(s.primitives))]
            px, _py, pz = p.position
            x, z = px + rng.uniform(-30, 30), pz + rng.uniform(-30, 30)
            if set(sol.find(s, x, z)) <= set(sol.find(mine, x, z)):
                ok += 1
        # NOT asserted at 100%: measured at 99.4% across the eight shipped
        # tracks, and the residual is not understood. Recorded so a change that
        # makes it worse is visible.
        check("a built tree covers what the shipped one does", ok >= 570,
              f"{ok}/600 on {name} -- measured 99.4% across all eight, not exact")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
