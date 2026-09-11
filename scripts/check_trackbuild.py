"""Checks for whole-track assembly.

Needs a stock track as a donor, because three members are configuration rather
than compiled output and a real track is where they come from:

    python scripts/check_trackbuild.py path/to/Data/bemidji.trk

It exits 0 with a note if none is given, so it is safe to run anywhere.

WHAT THESE GUARD. Every member of a track archive is a separate small format,
and getting one wrong does not fail loudly -- it fails at load, or renders as
flat colour, or drops the car through the road. Two faults found while writing
this, both of which parse-everything catches and eyeballing does not:

  * `build_obt` returns a COMPLETE file, envelope and all. Storing that as a
    member payload wraps it twice, and the reader then reads "0SER" as a record
    count -- 1,380,274,992 records.
  * the swept meshes ask for `grass.tex`, and a stock track calls it `grs.tex`.
    Fuzzy-matching the names silently dropped three of the four textures.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import (archive, bpp, envelope, grf, ili, obt as obt_mod,  # noqa: E402
                   tex, trackbuild, trackgen)

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def ring(n=96, rx=300.0, rz=200.0, cx=900.0, cz=-450.0):
    """A test loop placed OFF the origin.

    Centred on the origin it would be symmetric under negation, and a mirrored
    racing line would lie on the road just as well as a correct one -- the check
    below could not tell them apart. This project has already been caught by an
    origin-centred ring once, on the walls.
    """
    import math
    return [(cx + rx * math.cos(2 * math.pi * i / n),
             cz + rz * math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]


def main() -> int:
    if len(sys.argv) < 2:
        print("no donor track given -- pass a stock .trk")
        print("  e.g. python scripts/check_trackbuild.py path/to/Data/bemidji.trk")
        return 0
    donor = Path(sys.argv[1])

    scene = trackgen.sweep(ring())
    trackgen.add_checkpoints(scene, 3, half_width=trackgen.DEFAULT_ROAD_HALF_WIDTH)
    trackgen.add_grid(scene, 8)
    trackgen.add_ground(scene)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "generated.trk"
        r = trackbuild.assemble(scene, donor=donor, out_path=out, slot="bemidji")
        print(f"assembled {r.summary()}")

        got = {e.name.lower(): e for e in archive.read(out)}
        ref = {e.name.lower(): e for e in archive.read(donor)}

        # Every member a stock track has, this must have -- a missing one is a
        # track that will not load, with nothing to say why.
        want = {n for n in ref if not n.endswith(".tex")}
        check("carries every non-texture member a stock track does",
              not (want - set(got)), f"missing {sorted(want - set(got))}"
              if want - set(got) else f"{len(want)} members")
        check("tags and versions match the stock ones",
              all(got[n].tag == ref[n].tag and got[n].version == ref[n].version
                  for n in want & set(got)),
              "every shared member")

        # Each member has to parse with its own reader. This is what catches a
        # double-wrapped envelope, which is otherwise invisible.
        def env(n):
            return envelope.build(got[n].tag, got[n].version, got[n].payload)

        b = bpp.parse(got["track.bpp"].payload)
        check("track.bpp parses", len(b.triangles) > 0 and len(b.nodes) > 0,
              f"{len(b.triangles):,} triangles, {len(b.nodes):,} nodes")
        check("track.grf parses", grf.parse(env("track.grf")) is not None,
              "render geometry")
        try:
            obt_mod.parse(env("track.obt"))
            check("track.obt parses", True, "not double-wrapped")
        except Exception as e:                                   # noqa: BLE001
            check("track.obt parses", False, str(e)[:56])
        for n in ("default.ili", "rdefault.ili", "track.ild"):
            w = ili.parse(env(n))
            check(f"{n} parses", len(w) > 8, f"{len(w)} waypoints")
        bad = []
        for n in got:
            if n.endswith(".tex"):
                try:
                    tex.parse(env(n))
                except Exception as e:                           # noqa: BLE001
                    bad.append(n)
        check("every texture parses", not bad, f"{len([n for n in got if n.endswith('.tex')])} textures")

        # A mesh whose texture is absent renders as flat colour with no error.
        wanted = {m.name.lower() for mesh in scene.meshes.values()
                  for m in mesh.materials}
        check("every texture the meshes reference is in the archive",
              not (wanted - set(got)), f"missing {sorted(wanted - set(got))}"
              if wanted - set(got) else f"{len(wanted)} referenced")
        check("the sky is present",
              all(s in got for s in trackbuild.SKY_TEXTURES), "4 members")

        # The collision tree must answer for the geometry it was built from.
        import random
        rng = random.Random(5)
        ok = 0
        for _ in range(400):
            t = b.triangles[rng.randrange(len(b.triangles))]
            r1, r2 = rng.random(), rng.random()
            if r1 + r2 > 1:
                r1, r2 = 1 - r1, 1 - r2
            r3 = 1 - r1 - r2
            x = t.v[0][0] * r1 + t.v[1][0] * r2 + t.v[2][0] * r3
            z = t.v[0][2] * r1 + t.v[1][2] * r2 + t.v[2][2] * r3
            ok += bpp.find_point(b, x, z) == b.triangles.index(t)
        check("the collision tree locates its own triangles", ok >= 396,
              f"{ok}/400")

        # THE one that only shows up by driving it: the centreline is in the
        # SOURCE frame and the meshes are not, so a line built from the raw
        # centreline is mirrored through the origin. The AI then drives a
        # perfect lap of a road that is not there.
        import math
        road = [t for t in b.triangles if t.flag == 0]
        w = ili.parse(env("default.ili"))

        def near(x, z):
            return min(math.dist((x, z), (v[0], v[2]))
                       for t in road for v in t.v)

        probes = list(w)[::5][:24]
        on = sum(1 for q in probes if near(q.x, q.z) < 12.0)
        flipped = sum(1 for q in probes if near(-q.x, -q.z) < 12.0)
        check("the racing line lies ON the road, not mirrored through the origin",
              on == len(probes) and flipped < len(probes),
              f"{on}/{len(probes)} on the road, {flipped}/{len(probes)} if negated")

        # A ground plane must be drawn but NOT collided: it overlaps the road in
        # XZ, and .bpp stores one surface per point.
        ground = [n for n in scene.meshes if n.startswith("ground")]
        if ground:
            check("a ground plane stays out of the collision set",
                  not any(o.name in ground for o in scene.driveables),
                  "scenery only")

        # Winding decides whether a surface is DRAWN. to_viper() negates both
        # ground axes, which reverses it, so geometry built corner-by-corner in
        # the source frame comes out facing down -- present in the .grf, and
        # invisible from the track. Vertex normals do not save it; the renderer
        # culls on winding.
        def faces_up(mesh):
            for f in mesh.faces:
                a, b2, c2 = (mesh.vertices[i] for i in f)
                ux, uz = b2.x - a.x, b2.z - a.z
                wx, wz = c2.x - a.x, c2.z - a.z
                if (uz * wx - ux * wz) <= 0.0:
                    return False
            return True

        downward = [n for n, m in scene.meshes.items() if not faces_up(m)]
        check("every generated surface is wound face-up",
              not downward, f"{len(scene.meshes)} meshes"
              if not downward else f"facing down: {downward[:3]}")

        # A donor with no stand-in for a texture must fail loudly, not quietly
        # drop the member.
        try:
            trackbuild.assemble(scene, donor=donor, out_path=out, slot="x",
                                textures={"asphalt.tex": "nosuch.tex"})
            check("an unmatched texture is refused", False, "built anyway")
        except ValueError as e:
            check("an unmatched texture is refused", True, str(e)[:44])

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
