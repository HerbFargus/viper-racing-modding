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

    # Geometry: the road comes out the width it was asked for.
    road = scene.meshes["asphalt.mod"]
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
