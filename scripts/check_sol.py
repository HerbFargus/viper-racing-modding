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

        # ---- TUBEs, the wobble primitives ---------------------------------
        # Which orientation a tube carries is decided entirely by whether it is
        # a wobble: 931 tubes across every shipped track, 0 exceptions. That is
        # why sol.tube_at WRITES the matrix instead of inheriting it -- bemidji's
        # only tube is a plain one, so copying a donor's would hand a wobble the
        # wrong orientation, and nothing would say so.
        tubes = [(n, p) for n, s in loaded for p in s.primitives
                 if p.type == sol.TUBE]
        if tubes:
            wrong = [(n, p.id) for n, p in tubes
                     if struct.unpack_from("<9f", p.raw, 0)
                     != (sol.TUBE_MATRIX_WOBBLE if p.id >= 0
                         else sol.TUBE_MATRIX_PLAIN)]
            check("a tube's orientation follows whether it is a wobble",
                  not wrong, f"{len(tubes)} tubes" if not wrong else str(wrong[:3]))

            # A tube is a capsule: radius +0x58, HALF-length +0x5c, and two
            # whole cap spheres that must agree with them. An earlier reading
            # took +0x5c for the radius, and the wobbles built on it were thin
            # posts with the template's radius and caps 5.75 m away.
            odd = []
            for n, p in tubes:
                r, h = struct.unpack_from("<2f", p.raw, 0x58)
                for cap, sign in zip(sol.CAP_OFFSETS, (1.0, -1.0)):
                    if (p.raw[cap + 0x14:cap + 0x18] != b"RHPS"
                            or struct.unpack_from("<f", p.raw, cap + 0x1c)[0] != r
                            or struct.unpack_from("<3f", p.raw, cap + 0x20)
                            != (0.0, 0.0, sign * h)):
                        odd.append((n, p.id))
            check("a tube's cap spheres sit at +-half-length with its radius",
                  not odd, f"{len(tubes)} tubes, so +0x58 is the radius and "
                  f"+0x5c the half-length" if not odd else str(odd[:3]))

        boxes = [(n, p) for n, s in loaded for p in s.primitives
                 if p.type == sol.BOX]
        if boxes:
            odd = [(n, p.id) for n, p in boxes
                   if struct.unpack_from("<f", p.raw, 0x64)[0]
                   != max(struct.unpack_from("<3f", p.raw, sol.BOX_EXTENTS))]
            check("a box stores the max of its three half-extents after them",
                  not odd, f"{len(boxes)} boxes -- BoxVolume's constructor does "
                  f"this, so +0x58..+0x60 are the extents" if not odd else str(odd[:3]))

            # An id names the facing model a wobble draws, so a track hands out
            # exactly as many as it has wobbles -- never one more.
            gaps = []
            for n, s in loaded:
                ids = sorted(p.id for p in s.primitives
                             if p.type == sol.TUBE and p.id >= 0)
                if ids and ids != list(range(len(ids))):
                    gaps.append((n, ids[:4]))
            check("wobble ids run contiguously from 0 on every track", not gaps,
                  f"{len(loaded)} tracks" if not gaps else str(gaps))

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
        def covering(x, z):
            """Every primitive whose footprint actually contains (x, z)."""
            out = set()
            for j, pr in enumerate(s.primitives):
                jx, _jy, jz = pr.position
                rr = sol.bounding_radius(pr)
                if abs(x - jx) <= rr and abs(z - jz) <= rr:
                    out.add(j)
            return out

        rng = random.Random(11)
        ok = probes = 0
        for _ in range(600):
            p = s.primitives[rng.randrange(len(s.primitives))]
            px, _py, pz = p.position
            x, z = px + rng.uniform(-30, 30), pz + rng.uniform(-30, 30)
            truth = covering(x, z)
            if not truth:
                continue
            probes += 1
            if truth <= set(sol.find(mine, x, z)):
                ok += 1
        # THE criterion, and not the one this check started with. "Does it agree
        # with MKWORLD's partition" is the wrong question -- two quadtrees over
        # the same solids legitimately put different things in the leaf at a
        # given point, and the SHIPPED trees score 48.5% against the test below.
        # A broad phase has to return everything covering the point: a surplus
        # candidate costs a narrow-phase test, a missing one costs a barrier the
        # car drives through.
        check("a built tree returns everything that covers the point",
              ok == probes,
              f"{ok}/{probes} on {name} -- 1,822/1,822 across all eight")

    print("\nsol -- wobble colliders")
    if loaded:
        tpl = next((p for _n, s2 in loaded for p in s2.primitives
                    if p.type == sol.TUBE), None)
        f32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]  # noqa: E731
        if tpl is not None:
            t = sol.tube_at(tpl, (1.0, 2.0, 3.0), radius=1.2, half_length=1.3, ident=4)
            r, h = struct.unpack_from("<2f", t.raw, 0x58)
            caps = [(struct.unpack_from("<f", t.raw, c + 0x1c)[0],
                     struct.unpack_from("<3f", t.raw, c + 0x20),
                     struct.unpack_from("<3f", t.raw, c + 0x2c))
                    for c in sol.CAP_OFFSETS]
            check("tube_at writes radius, half-length and both caps together",
                  (r, h) == (f32(1.2), f32(1.3))
                  and caps[0][:2] == (f32(1.2), (0.0, 0.0, f32(1.3)))
                  and caps[1][:2] == (f32(1.2), (0.0, 0.0, -f32(1.3)))
                  and caps[0][2] == caps[1][2] == (1.0, 2.0, 3.0),
                  "nothing geometric left over from the template")

    if loaded:
        box = next((p for _n, s2 in loaded for p in s2.primitives if p.type == sol.BOX), None)
        if box is not None:
            sp = sol.sphere_at(box, (10.0, 2.0, -30.0), radius=3.25)
            ok = (sp.type == sol.SPHERE and sp.id == -1
                  and struct.unpack_from("<f", sp.raw, 0x58)[0] == 3.25
                  and struct.unpack_from("<3f", sp.raw, 0x24) == (10.0, 2.0, -30.0)
                  and struct.unpack_from("<3f", sp.raw, 0x5c) == (0.0, 0.0, 0.0)
                  and struct.unpack_from("<3f", sp.raw, 0x68) == (10.0, 2.0, -30.0)
                  and sp.raw[0x50:0x54] == sol.SPHERE[::-1]
                  and sp.raw[0x74:] == bytes(len(sp.raw) - 0x74))
            check("sphere_at writes a SPHR the way the stock ones are written", ok,
                  "identity orientation, radius, zero local centre, cached world centre")
        # ...and the shipped ones agree with that reading
        sph = [(n, p) for n, s2 in loaded for p in s2.primitives if p.type == sol.SPHERE]
        if sph:
            odd = [(n, p.id) for n, p in sph
                   if struct.unpack_from("<3f", p.raw, 0x5c) != (0.0, 0.0, 0.0)
                   or struct.unpack_from("<3f", p.raw, 0x68) != p.position
                   or struct.unpack_from("<f", p.raw, 0x58)[0] <= 0.0]
            check("every shipped sphere caches its own centre and carries a radius",
                  not odd, f"{len(sph)} spheres" if not odd else str(odd[:3]))

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
