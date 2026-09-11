"""Self-check for `vrmod trackgen`, against vrTrackMaker's own output.

We have Sucahyo's tool, his test spline, and the exact 21 files it produced from
it -- so the generator can be checked against a reference implementation rather
than against our own expectations. That is a better position than most
from-scratch format work, and this script is what keeps it.

Run:  python scripts/check_trackgen.py [path-to-vtm-test-folder]

The reference folder needs `path10.ASE` plus the `fooland*.txt` that vrTrackMaker
wrote from it. Checks that need the reference are skipped, loudly, when it is
absent; the invariants below hold regardless.
"""

from __future__ import annotations

import math
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import mod, trackgen as tg  # noqa: E402

DEFAULT_REF = Path.home() / "Desktop" / "vtm-test"
_VERT = re.compile(r"vert\(([-\d.]+), ([-\d.]+), ([-\d.]+)\)")

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))
        failures.append(name)


def ring(n: int = 240, radius: float = 300.0) -> list[tg.Point]:
    """A synthetic closed centreline, so the invariants can be checked with no
    reference data present."""
    return [
        (radius * math.cos(2 * math.pi * i / n), radius * math.sin(2 * math.pi * i / n), 0.0)
        for i in range(n)
    ]


def check_invariants() -> None:
    print("invariants (no reference data needed)")
    scene = tg.sweep(ring())
    tg.add_checkpoints(scene, 3)
    tg.add_grid(scene, 8)

    surface = tg.write_surface(scene)
    graphic = tg.write_graphic(scene)

    # The reason this module exists: the same driveables, in both files, always.
    def modobjects(text: str) -> list[str]:
        return re.findall(r"modobject\(([^)]*)\)", text)

    s_drive = [m for m in modobjects(surface)]
    g_drive = [m for m in modobjects(graphic) if not m.startswith("wall")]
    check("driveables identical in both scene files", s_drive == g_drive,
          f"{len(s_drive)} objects")

    # Only codes the generator is allowed to emit.
    codes = {int(m.split(",")[3]) for m in s_drive}
    check("emits only surface codes 0/10/16", codes <= {0, 10, 16}, f"got {sorted(codes)}")

    # Frames differ between the two files, which is measured behaviour. Assert it
    # against the scene's own stored gate rather than a hardcoded sign, so the
    # check holds for any centreline.
    s_pts = [tuple(map(float, m)) for m in _VERT.findall(surface)]
    gate = scene.markers["check1"]
    flipped = all(
        abs(w[0] + g[0]) < 1e-3 and abs(w[1] + g[1]) < 1e-3
        for w, g in zip(s_pts[:2], gate)
    )
    check("surface file negates the ground axes; graphic file does not", flipped,
          f"scene {gate[0][0]:.2f},{gate[0][1]:.2f} -> written {s_pts[0][0]:.2f},{s_pts[0][1]:.2f}")

    # The engine panics with "Couldn't find any checkpoints!" and dies before the
    # green flag if a track carries fewer than two gates. Every shipped track has
    # two or three; a generated one had one, which is how this was found.
    check("places at least two checkpoints", len(scene.markers) >= 2,
          f"{len(scene.markers)}: {', '.join(scene.markers)}")
    try:
        tg.add_checkpoints(scene, 1)
        check("refuses a single checkpoint", False, "it did not raise")
    except ValueError:
        check("refuses a single checkpoint", True)
        tg.add_checkpoints(scene, 3)

    # Shipped gates run 15-80 m against a ~12 m road, so a car running wide still
    # crosses one. A gate spanning only the asphalt can be missed entirely.
    import math as _m
    widths = [_m.dist(g[0][:2], g[1][:2]) for g in scene.markers.values()]
    check("gates are wider than the road", all(w > 12.0 for w in widths),
          f"{min(widths):.0f}-{max(widths):.0f} m")

    # An empty marker block is rejected by nhmkworld, and writing one is exactly
    # the bug this emitter shipped with: the reference was first read through a
    # filter that hid the gate verts, and the artifact was mistaken for the
    # format itself. Both files must carry the gate.
    def gate_verts(text):
        head, _, rest = text.partition("marker(check1)")
        if not rest:
            return 0
        block, _, _ = rest.partition("end")
        return block.count("vert(")

    check("both files carry the gate verts (empty marker breaks nhmkworld)",
          gate_verts(surface) == 2 and gate_verts(graphic) == 2,
          f"surface={gate_verts(surface)} graphic={gate_verts(graphic)}")

    # CRLF is not cosmetic -- the original reader splits on it.
    check("both files use CRLF", surface.count("\r\n") > 0 and graphic.count("\r\n") > 0)
    check("no bare LF in output",
          "\n" not in surface.replace("\r\n", "") and "\n" not in graphic.replace("\r\n", ""))

    # Chunking. The renderer culls per chunk, so a chunk spanning the whole map
    # is always "visible" and never usefully culled. Shipped tracks subdivide
    # heavily -- bemidji 446 chunks over ~60 m, dundas 1,117 over ~40 m. Sweeping
    # each band as one track-length ribbon gave 7 chunks with a 1,632 m footprint
    # and the track did not draw at all.
    import statistics as _stats
    foot = []
    for mesh in scene.meshes.values():
        xs = [v.x for v in mesh.vertices]
        zs = [v.z for v in mesh.vertices]
        foot.append(max(max(xs) - min(xs), max(zs) - min(zs)))
    median = _stats.median(foot)
    check("geometry is cut into many small chunks, as shipped tracks are",
          len(scene.meshes) > 50 and median < 200,
          f"{len(scene.meshes)} meshes, median footprint {median:.0f} m")

    # A closed ring must have no hole at the seam. path10.ASE is flagged
    # *SHAPE_CLOSED but its knots stop 201 m short of closing, and sweeping it
    # as open left exactly that hole in the main straight -- with the start line
    # sitting in it, so cars spawned over the gap and fell through the world.
    round_trip = tg.resample(ring(), 10.0, closed=True)
    seam = math.dist(round_trip[-1][:2], round_trip[0][:2])
    check("a closed resample leaves no seam gap", seam < 15.0, f"seam {seam:.1f} m")

    # Recovering a centreline from a road SURFACE, which is what a modeller
    # exports when it will not give you a curve -- Bob's Track Builder being the
    # case that prompted it. Checked against the mesh our own sweep produced,
    # where the answer is known exactly.
    from vrmod import mod as _mod
    road = [m for n, m in scene.meshes.items() if n.startswith("asphalt")]
    recovered = tg.centreline_from_meshes(road)
    src = [(-p[0], -p[1]) for p in scene.centreline]
    worst = max(min(math.dist(r[:2], (-s[0], -s[1])) for s in src) for r in recovered[::7])
    check("a centreline can be recovered from the road surface alone",
          worst < 2.0, f"{len(recovered)} points, worst {worst:.2f} m from the true line")

    # Elevation. A Point's third component carries height, and it has to survive
    # recovery, resampling and the sweep -- generated tracks were flat because
    # the ribbon builder passed a literal zero instead of the station's height.
    hilly = [(math.cos(a) * 300, math.sin(a) * 300, 20.0 + 30.0 * math.sin(a * 3))
             for a in [i * 2 * math.pi / 240 for i in range(240)]]
    rs = tg.resample(hilly, 10.0, closed=True)
    check("resample carries elevation",
          abs(max(p[2] for p in rs) - 50.0) < 1.0 and abs(min(p[2] for p in rs) - -10.0) < 1.0,
          f"{min(p[2] for p in rs):.1f}..{max(p[2] for p in rs):.1f} m")
    hs = tg.sweep(rs, closed=True)
    ys = [v.y for m in hs.meshes.values() for v in m.vertices]
    check("the sweep follows the centreline's elevation",
          max(ys) - min(ys) > 50.0, f"mesh spans {min(ys):.1f}..{max(ys):.1f} m")

    # Field 10 of a racing line is a record INDEX with a kind tag, stored in a
    # float slot. Writing it as a constant leaves every waypoint claiming to be
    # waypoint zero: the AI still drives, because it follows positions, but
    # resetting the car teleports it off the track.
    import struct as _struct
    from vrmod import ili as _ili
    line = _ili.generate([(i * 10.0, 0.0, 0.0) for i in range(8)], speed=50, closed=False)
    ids = [_struct.unpack("<i", _struct.pack("<f", r[10]))[0] & 0xFFFFFFFF for r in line.records]
    check("racing-line records carry an incrementing index",
          ids == [0xFF000000 + i for i in range(8)], f"{[hex(v) for v in ids[:3]]}...")
    # track.ild is not one line: every shipped track splits it into three
    # sub-lines tagged 0x01/0x02/0x03, changing where the lap crosses a
    # checkpoint, with the index running continuously across all three.
    ild = _ili.generate([(i * 10.0, 0.0, 0.0) for i in range(90)], speed=50,
                        closed=True, kind=_ili.KIND_ILD, sectors=True,
                        gates=[0.0, 300.0, 600.0])
    ik = [_struct.unpack("<i", _struct.pack("<f", r[10]))[0] & 0xFFFFFFFF for r in ild.records]
    kinds = sorted({(v >> 16) & 0xFF for v in ik})
    check("track.ild carries three sector tags", kinds == [1, 2, 3], f"{[hex(k) for k in kinds]}")
    check("track.ild's index runs continuously across sectors",
          [v & 0xFFFF for v in ik] == list(range(len(ik))), "0..n-1")
    plain = _ili.generate([(i * 10.0, 0.0, 0.0) for i in range(20)], speed=50, closed=True)
    pk = {(_struct.unpack("<i", _struct.pack("<f", r[10]))[0] >> 16) & 0xFF for r in plain.records}
    check("default.ili stays a single kind-0 line", pk == {0}, f"{[hex(k) for k in pk]}")

    # Field 5 is a corridor half-width, not the sentinel it looks like in the AI
    # lines. A track.ild full of -20000 puts the car outside the corridor at
    # every station, which is what the game reports as "press space to reset"
    # seconds after the green flag.
    check("track.ild carries a positive corridor, not the sentinel",
          all(r[5] > 0.0 for r in ild.records), f"f5 = {ild.records[0][5]}")
    check("track.ild's speed field is the flat 100 the stock tracks carry",
          all(abs(r[6] - _ili.ILD_SPEED) < 1e-6 for r in ild.records),
          f"f6 = {ild.records[0][6]}")
    check("an AI line keeps the -20000 the stock AI lines carry",
          all(r[5] == _ili.MARK_VALUE for r in plain.records), f"f5 = {plain.records[0][5]}")
    check("a requested corridor reaches the records",
          _ili.generate([(i * 10.0, 0.0, 0.0) for i in range(20)], speed=50,
                        closed=True, corridor=17.5).records[0][5] == 17.5, "17.5 m")
    try:
        _ili.generate([(i * 10.0, 0.0, 0.0) for i in range(20)], speed=50,
                      closed=True, corridor=-20000.0)
    except ValueError:
        check("a non-positive corridor is refused", True, "raises ValueError")
    else:
        check("a non-positive corridor is refused", False, "accepted -20000")

    # Importing an existing model, rather than sweeping a new road.
    import math as _m
    circle = [(_m.cos(t / 40.0 * _m.tau) * 200.0, _m.sin(t / 40.0 * _m.tau) * 200.0, 0.0)
            for t in range(40)]
    swept = tg.sweep(circle, closed=True)
    imported = tg.scene_from_meshes(
        {"road.mod" if n.startswith("asphalt") else "grass.mod": m
         for n, m in list(swept.meshes.items())[:1]},
        centreline=circle, chunk_size=50.0)
    check("an imported model keeps its own geometry",
          len(imported.meshes) > 0, f"{len(imported.meshes)} chunks")
    check("imported road classifies as road, not grass",
          all(o.code == tg.ROAD for o in imported.driveables),
          f"codes {sorted({o.code for o in imported.driveables})}")

    # Chunking: the renderer culls per chunk, so a whole-track mesh draws as
    # nothing at all. Every chunk must also stay inside the u16 index limit.
    big = next(iter(swept.meshes.values()))
    pieces = tg.chunk_mesh(big, size=50.0)
    check("chunking preserves every triangle",
          sum(len(c.faces) for c in pieces) == len(big.faces),
          f"{sum(len(c.faces) for c in pieces)} vs {len(big.faces)}")
    check("no chunk exceeds the u16 vertex index limit",
          all(len(c.vertices) <= 0xFFFF for c in pieces),
          f"largest {max(len(c.vertices) for c in pieces)}")
    check("chunk footprints land in the shipped 40-60 m range",
          all(max(max(v.x for v in c.vertices) - min(v.x for v in c.vertices),
                  max(v.z for v in c.vertices) - min(v.z for v in c.vertices)) < 120.0
              for c in pieces), "under 120 m")

    # A .tra name field is 16 bytes and a modeller's texture names exceed it.
    # Viper resolves textures by name, so a mesh asking for one the archive does
    # not hold is a crash, not a missing texture.
    fitted = tg.fit_texture_names(
        ["road_tarmac001.tex", "ground_grass001.tex", "road_tarmac002.tex"])
    check("texture names are shortened to fit the archive name field",
          all(len(v) <= tg.TEX_NAME_LIMIT for v in fitted.values()),
          f"{sorted(fitted.values())}")
    check("texture names are 8.3, as every shipped texture is",
          tg.TEX_NAME_LIMIT == 12 and all(len(v) <= 12 and v[:-4].isalnum()
                                          for v in fitted.values()),
          f"{sorted(fitted.values())}")
    check("the texture size ceiling matches what the game ships",
          tg.TEX_MAX_SIZE == 256, f"{tg.TEX_MAX_SIZE} (no shipped texture exceeds 256)")
    check("shortened texture names stay unique",
          len(set(fitted.values())) == len(fitted), f"{len(set(fitted.values()))} distinct")

    # Exporters differ in how much structure they keep, silently. BTB writes one
    # object per material; a Blender OBJ of the same track is a single object
    # carrying both. Classifying by the mesh name gives the second one surface
    # code for the whole track -- a road the game treats as grass. Both must
    # import identically, so classification goes by MATERIAL.
    from vrmod import mod as _mod
    split_scene = tg.sweep(circle, closed=True)
    road_mesh = next(m for n, m in split_scene.meshes.items() if n.startswith("asphalt"))
    grass_mesh = next(m for n, m in split_scene.meshes.items() if n.startswith("grass"))
    merged_v = list(road_mesh.vertices) + list(grass_mesh.vertices)
    off = len(road_mesh.vertices)
    merged_f = list(road_mesh.faces) + [(a + off, b + off, c + off)
                                        for a, b, c in grass_mesh.faces]
    merged = _mod.Mesh(
        vertices=merged_v,
        materials=[_mod.Material("road_tarmac001.tex", 0, off, 0, len(road_mesh.faces)),
                   _mod.Material("ground_grass001.tex", off, len(merged_v),
                                 len(road_mesh.faces), len(merged_f))],
        faces=merged_f,
    )
    pieces = tg.split_by_material(merged)
    check("a multi-material mesh splits into one mesh per material",
          len(pieces) == 2, f"{sorted(pieces)}")
    check("splitting preserves every triangle",
          sum(len(m.faces) for m in pieces.values()) == len(merged_f),
          f"{sum(len(m.faces) for m in pieces.values())} of {len(merged_f)}")
    one_object = tg.scene_from_meshes({"track.obj": merged}, centreline=circle,
                                      chunk_size=50.0)
    per_object = tg.scene_from_meshes(
        {"road_tarmac001.mod": pieces["road_tarmac001.tex"],
         "ground_grass001.mod": pieces["ground_grass001.tex"]},
        centreline=circle, chunk_size=50.0)
    import collections as _c
    a = _c.Counter(o.code for o in one_object.driveables)
    b = _c.Counter(o.code for o in per_object.driveables)
    check("a single-object export classifies the same as a per-material one",
          a == b, f"{dict(a)} vs {dict(b)}")
    check("the road in a single-object export is road, not grass",
          a.get(tg.ROAD, 0) > 0, f"{a.get(tg.ROAD, 0)} road chunks")

    # Roles. A surface code says what a mesh drives like, not whether it is a
    # driving surface at all. BTB names material slots generically -- a concrete
    # barrier's material is "road24" and seven traffic cones are "road1" -- so
    # classifying a wall by its material makes it asphalt and the car drives up
    # it. The source FILE name is the reliable signal, with textures as backup.
    check("BTB's file naming resolves roles",
          [tg.mesh_role(n) for n in ("t_0_s0", "ta0000", "wall0_s0", "obj00000")]
          == [tg.SURFACE, tg.SURFACE, tg.WALL, tg.PROP], "track/terrain/wall/prop")
    check("a texture resolves a role the file name does not",
          [tg.mesh_role("mesh17", [t]) for t in
           ("Cone.tex", "wall_cement001.tex", "Tree04_leaves.tex", "GuardRail.tex")]
          == [tg.PROP, tg.WALL, tg.PROP, tg.WALL], "cone/wall/tree/guardrail")
    check("an unrecognised mesh stays a driving surface",
          tg.mesh_role("whatever", ["mystery.tex"]) == tg.SURFACE,
          "no silent demotion to scenery you fall through")

    roled = tg.scene_from_meshes(
        {"road_a.mod": road_mesh, "wall0_s0.mod": grass_mesh},
        centreline=circle, chunk_size=50.0)
    check("a wall is routed to scenery, not to driveables",
          all(not o.name.startswith("wall") for o in roled.driveables)
          and any(o.name.startswith("wall") for o in roled.scenery),
          f"{len(roled.driveables)} driveable, {len(roled.scenery)} scenery")
    check("scenery carries NO_COLLISION",
          all(o.param1 == tg.NO_COLLISION for o in roled.scenery),
          "param1=3, so it stays out of .bpp")
    rg, rs = tg.write_graphic(roled), tg.write_surface(roled)
    check("scenery reaches the graphic file but not the surface file",
          "wall0_s0" in rg and "wall0_s0" not in rs, "drawn, not driven on")

    # Walls. .sol was long treated as unwritable because its spatial tail is
    # not understood -- but it does not have to be synthesised: the surface file
    # declares wall quads, and MKWORLD turns each into one .sol primitive.
    walled = tg.sweep(circle, closed=True)
    quads = tg.add_walls(walled, offset=10.0, height=1.5, stride=4)
    check("walls produce one quad per side per stride",
          quads == len(walled.centreline) // 4 * 2, f"{quads} quads")
    surf, graph = tg.write_surface(walled), tg.write_graphic(walled)
    check("wall quads reach the surface file",
          surf.count("object(wall.tga,1,0)") == quads, f"{quads} declared")
    # Walls do not share the markers' frame: vrTrackMaker writes its gate verts
    # in the mesh frame and its wall verts negated on both ground axes, and
    # MKWORLD negates walls back on the way into .sol. A wall written in the
    # mesh frame compiles mirrored through the origin -- barriers land across
    # the track as invisible walls in the road.
    #
    # The ring above is centred on the origin, where the two frames are
    # indistinguishable, so this uses an OFF-CENTRE loop that can tell them
    # apart.
    import re as _re
    off = [(math.cos(t / 40.0 * math.tau) * 200.0 + 600.0,
            math.sin(t / 40.0 * math.tau) * 200.0 + 250.0, 0.0) for t in range(40)]
    offscene = tg.sweep(off, closed=True)
    tg.add_walls(offscene, offset=10.0, height=1.5, stride=4)
    otxt = tg.write_surface(offscene)
    ov = [tuple(map(float, t)) for t in _re.findall(
        r"vert\(([-\d.]+), ([-\d.]+), ([-\d.]+)\)",
        _re.findall(r"object\(wall\.tga,1,0\)(.*?)quad", otxt, _re.S)[0])]
    # source frame: near the centreline itself. mesh frame: near its negation.
    d_src = min(math.dist((v[0], v[1]), (p[0], p[1])) for v in ov for p in off)
    d_mesh = min(math.dist((v[0], v[1]), (-p[0], -p[1])) for v in ov for p in off)
    check("wall verts are written in the source frame, not the mesh frame",
          d_src < 15.0 and d_mesh > 100.0,
          f"{d_src:.1f} m from the centreline, {d_mesh:.0f} m from its mirror")

    # The COLLISION half of a wall is surface-file only. (The appearance half is
    # an ordinary mesh in the graphic file at param1=3, which add_walls does not
    # emit -- vrTrackMaker ships four of them per track.)
    check("wall collision quads stay OUT of the graphic file",
          "wall.tga" not in graph,
          "surface file only; the visible mesh is a separate, non-colliding object")
    for bad in (0.0, -1.0):
        try:
            tg.add_walls(walled, offset=bad)
        except ValueError:
            pass
        else:
            check("a non-positive wall offset is refused", False, f"accepted {bad}")
            break
    else:
        check("a non-positive wall offset is refused", True, "raises ValueError")

    # Geometry: the road comes out the width it was asked for.
    # segments are named asphalt000.mod, asphalt001.mod, ...
    road = next(m for n, m in scene.meshes.items() if n.startswith("asphalt"))
    a, b = road.vertices[0], road.vertices[1]
    width = math.dist((a.x, a.z), (b.x, b.z))
    check("road width matches road_half_width * 2", abs(width - 12.0) < 1e-6, f"{width:.4f} m")

    # Orientation. Bands swept left of the centreline and bands swept right come
    # out with opposite winding unless the ribbon builder corrects for it, and the
    # first version of this shipped with asphalt and the left bands inside-out.
    # Every mesh vrTrackMaker emits faces up, so ours must too.
    for name, mesh in scene.meshes.items():
        up = 0
        sample = mesh.faces[:200]
        for a, b, c in sample:
            va, vb, vc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
            if (vb.z - va.z) * (vc.x - va.x) - (vb.x - va.x) * (vc.z - va.z) > 0:
                up += 1
        if up != len(sample):
            check(f"{name} faces up", False, f"{up}/{len(sample)}")
            break
    else:
        check(f"all {len(scene.meshes)} meshes face up (no inside-out bands)", True)

    # Every emitted mesh must survive our own reader.
    with tempfile.TemporaryDirectory() as tmp:
        for name, mesh in scene.meshes.items():
            p = Path(tmp) / name
            p.write_bytes(mod.build(mesh))
            back = mod.parse_file(p)
            if len(back.vertices) != len(mesh.vertices) or len(back.faces) != len(mesh.faces):
                check(f"{name} round-trips", False,
                      f"{len(mesh.vertices)}v/{len(mesh.faces)}f -> "
                      f"{len(back.vertices)}v/{len(back.faces)}f")
                break
        else:
            check(f"all {len(scene.meshes)} meshes round-trip through vrmod", True)


def check_against_reference(ref: Path) -> None:
    ase = ref / "path10.ASE"
    ref_graphic = ref / "foolandgraphic.txt"
    ref_surface = ref / "foolandsurface.txt"
    print(f"\nagainst vrTrackMaker's output ({ref})")
    if not ase.exists():
        print(f"  SKIP  no {ase.name} -- pass the folder as argv[1] to enable these")
        return

    pts = tg.read_ase(ase)
    check("reads the spline vrTrackMaker reported", len(pts) == 3546,
          f"{len(pts)} knots, tool said 3546")

    # The .ase and the graphic file's path share a frame; the first point is the
    # one station no resampling can move, so it must agree exactly.
    if ref_graphic.exists():
        ref_pts = [tuple(map(float, m)) for m in _VERT.findall(ref_graphic.read_text())]
        scene = tg.sweep(tg.resample(pts, 10.9))
        ours = [tuple(map(float, m)) for m in _VERT.findall(tg.write_graphic(scene))]
        check("graphic path starts on the reference's first vert",
              ours[0] == ref_pts[0], f"{ours[0]} vs {ref_pts[0]}")

        # Our resampling is uniform; vrTrackMaker's decimation is adaptive, its
        # spacing opening from 10.90 to 14.49 as the curvature eases. The two
        # paths are therefore not expected to share stations beyond the opening
        # straight, and their lengths differ for a reason worth recording: the
        # reference path is 3,997 m against the 3,748 m of the knot polyline it
        # was built from. The .ase is flagged SHAPE_CLOSED but its knots leave a
        # 201 m gap from last to first, which the tool closes and smooths. So
        # fidelity here is measured against the INPUT, which is the thing we are
        # actually responsible for, and against the reference only by extent.
        def polylen(ps):
            return sum(math.dist(a[:2], b[:2]) for a, b in zip(ps, ps[1:]))

        src = polylen(pts)
        got = polylen(ours)
        check("resampled path preserves the input spline's length",
              abs(got - src) / src < 0.001, f"{got:,.1f} m vs {src:,.1f} m of input")

        def extent(ps):
            xs, ys = [q[0] for q in ps], [q[1] for q in ps]
            return max(xs) - min(xs), max(ys) - min(ys)

        ex_ours, ex_ref = extent(ours), extent(ref_pts)
        check("covers the same ground as the reference",
              all(abs(a - b) / b < 0.02 for a, b in zip(ex_ours, ex_ref)),
              f"{ex_ours[0]:,.0f}x{ex_ours[1]:,.0f} vs {ex_ref[0]:,.0f}x{ex_ref[1]:,.0f} m")

        near = sum(1 for a, b in zip(ours[:8], ref_pts[:8]) if math.dist(a[:2], b[:2]) < 0.05)
        check("stations agree across the opening straight, where both are uniform",
              near >= 6, f"{near}/8 within 5 cm")

    if ref_surface.exists():
        # Deliberately NOT compared against vrTrackMaker's gate any more. Its
        # surface-file gate spans exactly the road (12 m) and it writes one gate;
        # a track built that way made the engine panic with "Couldn't find any
        # checkpoints!". The shipped tracks are the better authority -- two or
        # three gates each, 15-80 m wide -- so that is what these assert.
        ref_gate = [tuple(map(float, m)) for m in _VERT.findall(ref_surface.read_text())][:2]
        scene = tg.sweep(tg.resample(pts, 10.9))
        tg.add_checkpoints(scene, 3)
        ours = [tuple(map(float, m)) for m in _VERT.findall(tg.write_surface(scene))][:2]
        span_ref = math.dist(ref_gate[0][:2], ref_gate[1][:2])
        span_ours = math.dist(ours[0][:2], ours[1][:2])
        check("gates are wider than vrTrackMaker's, matching shipped tracks",
              span_ours > span_ref, f"{span_ours:.0f} m vs its {span_ref:.0f} m")
        check("first gate still sits on the start of the centreline",
              math.dist(((ours[0][0] + ours[1][0]) / 2, (ours[0][1] + ours[1][1]) / 2),
                        ((ref_gate[0][0] + ref_gate[1][0]) / 2,
                         (ref_gate[0][1] + ref_gate[1][1]) / 2)) < 1.0,
              "gate centre unchanged; only its width and count differ")

    # The mesh frame, which was measured rather than assumed.
    ref_asphalt = ref / "asphalt.mod"
    if ref_asphalt.exists():
        m = mod.parse_file(ref_asphalt)
        ax, ay = pts[0][0], pts[0][1]
        target = (-ax, -ay)
        best = min(m.vertices, key=lambda v: (v.x - target[0]) ** 2 + (v.z - target[1]) ** 2)
        d = math.dist((best.x, best.z), target)
        check("mesh frame is (-x, height, -y), road edge 6 m from centreline",
              abs(d - 6.0) < 0.5, f"nearest vertex {d:.3f} m away")


if __name__ == "__main__":
    ref = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REF
    check_invariants()
    check_against_reference(ref)
    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        print("failed: " + ", ".join(failures))
        sys.exit(1)
