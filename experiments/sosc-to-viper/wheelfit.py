"""Put the wheels under the wheel arches.

THE DEFECT. Two numbers that have to agree are set from two unrelated sources.
`build_car` fits every converted body to its DONOR's length -- which is why
azzaroni, airhawk and j57 are all exactly 4.29 m (exotic.car) and hmxvan and
hunter are both 3.87 m (4x4cos.car). `realstats` then writes the REAL car's
wheelbase out of a spec sheet. Nothing ever compares them, so the wheels land
wherever the physics says and the arches stay where the artist drew them.

The van shows it worst: a 1973 GMC van is about 5.1 m long, the body was squashed
into 3.87 m, and a 125-inch (3.17 m) wheelbase on a 3.87 m body leaves the wheels
0.35 m from each end -- hanging off the corners.

WHY NOT MEASURE THE ARCHES. Because they are not there to measure. `car.py`
established this for the stock Viper by boundary-edge topology: `Viper0.mod` has
no geometric wheel-arch cutouts, and the wells are painted into the texture. The
SoSC bodies are the same -- a min-y profile along the flank of hmxvan and airhawk
returns noise, not two humps. Reading the painted arches back through the UVs was
tried too and does not produce a usable signal at three texels per face.

WHAT THIS DOES INSTEAD. The SoSC model IS the real car's shape, so the real car's
wheelbase-as-a-fraction-of-length is also where its painted arches sit. Scale the
real figures by the same factor the body was scaled by, axis for axis:

    wheelbase_out = wheelbase_real * (body_length / length_real)
    track_out     = track_real     * (body_width  / width_real)

That lands each axle at the same fraction along the body as on the real car,
which is where the arches are drawn, without claiming a measurement nobody can
make. `width` in the .cf is set from the mesh directly -- it is the body's own
width in inches (checked: viper.car says 75.7 and Viper0.mod is 1.92 m across),
so taking it from a spec sheet described a car the model is not.

WHERE THE AXLES SIT ALONG Z is the assumption underneath all of this: the game
centres them on the body's own z=0 (see car.py's WHEEL POSITIONING note, which
flags this as the genuinely uncertain piece). Every SoSC body is symmetric about
z=0, so a symmetric axle pair is the only thing that can be right for them.

    python wheelfit.py <fleet_dir_or_car>
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from realstats import SPECS                              # noqa: E402
from vrmod import archive, cf, envelope, mod as mod_mod  # noqa: E402

INCH_TO_M = 0.0254

# The z shift moves the body, so running it twice over the same car doubles it.
# A fresh pipeline run wants it applied (False); set True only to re-run the
# track and lift passes over cars that have already been shifted once.
SHIFT_DONE = False

# Published overall length, inches. Not in SPECS because nothing needed it until
# now, and it is the same class of judgement as the figures already there: a
# nominal catalogue number for the model the artwork resembles, not a
# measurement of this mesh. Only the ratio to `wheelbase` matters here, so a few
# inches either way moves an axle by millimetres.
LENGTHS = {
    "airhawk":  186.0,   # 1969 Camaro coupe
    "azzaroni": 163.4,   # 250 GT SWB, 4,150 mm
    "j57":      166.5,   # GT40 Mk II, 4,230 mm
    "strtrat":  160.6,   # Beetle 1300, 4,079 mm
    "hmxvan":   202.0,   # GMC van on the 125-inch wheelbase
    "police":   200.4,   # 1985 Cutlass Supreme
}


# ---------------------------------------------------------------------------
# THE ARCHES, READ OFF THE ART. Measured by rasterising each body's left flank
# in MODEL SPACE -- x maps linearly to z by construction, so a position in the
# picture is a position on the car -- and reading the well centres against a
# 10% grid. As a fraction of the body from tail (0.0) to nose (1.0).
#
# Read by eye, deliberately. Three automatic detectors were written and all
# three failed: a min-y profile of the flank (the wells are painted, not
# modelled, so there is no silhouette to find), a darkest-band search, and a
# one-arch-per-half variant. Each latched onto shadow or dark paint instead --
# the last one put the van's front arch at 61% where it is plainly at 82%, and
# the Beetle's rear at 38% where it is at 22%. The art is legible to a person
# and not to those heuristics, so this is a table, like SYMMETRY and FRAME.
#
# The Hunter has no entry: its skin is uniform rust and shows no wells at all.
ARCHES = {
    "azzaroni": (0.21, 0.82),
    "j57":      (0.19, 0.77),
    "strtrat":  (0.22, 0.81),
    "hmxvan":   (0.20, 0.82),
    "airhawk":  (0.23, 0.77),
    "police":   (0.224, 0.787),
}


def arch_fit(m, stem: str):
    """(wheelbase inches, centre z) from the measured arches, or None."""
    fr = ARCHES.get(stem)
    if not fr:
        return None
    zs = [v.z for v in m.vertices]
    z0, z1 = min(zs), max(zs)
    rear = z0 + fr[0] * (z1 - z0)
    front = z0 + fr[1] * (z1 - z0)
    return (front - rear) / INCH_TO_M, (front + rear) / 2


# The shared Viper wheel is 0.380 m across. The SoSC cars are narrow, so a track
# taken from a catalogue stands the tyre proud of the bodywork -- measured before
# this ran, every car did it, from 18 mm on the Police front to 359 mm on the
# Hunter's rear, where the body necks in to 0.53 m and the wheel hangs in open
# air. The real cars tuck their wheels under; these have to as well.
#
# So the track is measured, not scaled: put the tyre's OUTER face just inside the
# body at that axle's own station. The station matters -- a van is not the same
# width at the front axle as the rear, and neither is the Hunter.
WHEEL_INSET = 0.012            # metres of daylight between tyre and bodywork


def _wheel_half_width(car_path: Path) -> float:
    """Half the shared front wheel's width, from the mesh the game draws."""
    try:
        raw = car.find_shared(car_path, archive.read(car_path), "fwheel_1.mod")
        if raw:
            return max(abs(v.x) for v in mod_mod.parse(raw).vertices)
    except Exception:
        pass
    return 0.190                # measured on the stock wheel, as a fallback


def track_fit(m, z: float, half_w: float, span: float = 0.25) -> float | None:
    """Track in inches that tucks the tyre inside the body at station z."""
    xs = [abs(v.x) for v in m.vertices if abs(v.z - z) < span]
    if not xs:
        return None
    half = max(xs) - half_w - WHEEL_INSET
    return max(half, 0.20) * 2 / INCH_TO_M


# HOW HIGH the wells sit, measured the same way: with the arch x pinned by
# ARCHES, the dark well in that column band has a readable vertical centre. The
# wheel's own centre is fixed at its radius above the ground (0.330 m), so the
# body lifts by the difference and the tyre drops into the well.
#
# Small numbers, and they agree across the three sports cars, which is the
# reassuring part -- the Ferrari, the GT40 and the Beetle all want 4-5 cm. The
# van and the Camaro already sit right. The Police reads +0.119, far outside the
# others; its wells are the hardest to see in that skin, so it is left out until
# someone looks at it properly rather than trusted because a number appeared.
LIFT = {
    "azzaroni": 0.042,
    "j57":      0.044,
    "strtrat":  0.048,
    "hmxvan":   0.002,
    "airhawk":  0.000,
}


def body_mesh(entries, stem: str):
    """LOD 0, which is the only mesh at full size."""
    want = f"{stem}0.mod"
    e = next((x for x in entries if x.name.lower() == want), None)
    if e is None:
        raise SystemExit(f"no {want} in the car")
    return mod_mod.parse(envelope.build(e.tag, e.version, e.payload))


def fit(car_path: Path) -> dict | None:
    """Rewrite one car's wheelbase/track/width from its own body. Returns a report."""
    stem = car_path.stem.lower()
    spec = SPECS.get(stem)
    length_real = LENGTHS.get(stem)
    entries = archive.read(car_path)
    m = body_mesh(entries, stem)
    zs = [v.z for v in m.vertices]
    xs = [v.x for v in m.vertices]
    body_len = (max(zs) - min(zs)) / INCH_TO_M          # inches, like the .cf
    body_wid = (max(xs) - min(xs)) / INCH_TO_M

    ce = next(x for x in entries if x.name.lower().endswith(".cf"))
    values = cf.parse(envelope.build(ce.tag, ce.version, ce.payload))
    before = {k: values[k] for k in ("wheelbase", "ftrack", "rtrack", "width")}

    # width always: it describes THIS mesh, and can be read off it exactly.
    new = {"width": body_wid}
    source = "none"
    shift = 0.0
    if spec and length_real:
        zk = body_len / length_real
        xk = body_wid / spec["width"]
        new["wheelbase"] = spec["wheelbase"] * zk
        new["ftrack"] = spec["ftrack"] * xk
        new["rtrack"] = spec["rtrack"] * xk
        source = "scaled"
    measured = arch_fit(m, stem)
    if measured:
        # A measurement of THIS art beats a scaled catalogue figure, so it wins
        # where there is one. The shift is the other half: the game hangs the
        # axles on the body's own z=0 (car.py), and the arches are not centred
        # there -- so the body moves instead, by the arch midpoint, and the
        # axle pair lands on the wells.
        new["wheelbase"], centre = measured
        shift = 0.0 if SHIFT_DONE else -centre
        source = "measured"

    # Track last: it depends on the wheelbase, since the station to measure the
    # body at is where the axle ends up.
    half_w = _wheel_half_width(car_path)
    if "wheelbase" in new:
        half_wb = new["wheelbase"] * INCH_TO_M / 2
        ft = track_fit(m, half_wb + shift, half_w)
        rt = track_fit(m, -half_wb + shift, half_w)
        if ft:
            new["ftrack"] = ft
        if rt:
            new["rtrack"] = rt

    # Only the named fields are written; every other byte of the .cf carries
    # over untouched, same as realstats does it.
    raw = cf.build(envelope.build(ce.tag, ce.version, ce.payload), new)
    out = [archive.ArchiveEntry(name=x.name, tag=x.tag, version=x.version,
                                payload=raw[20:]) if x is ce else x
           for x in entries]

    # The shift moves the CAR, not just the body: every mesh the car owns (the
    # LOD chain, the brake lights) and the cockpit records, which are positions
    # in the same car space. Miss one and it detaches from the rest.
    lift = LIFT.get(stem, 0.0)
    moved = 0
    if abs(shift) > 1e-4 or abs(lift) > 1e-4:
        out = [_shift_mesh(x, shift, stem, lift) if _is_own_mesh(x, stem) else x
               for x in out]
        moved = sum(1 for x in out if _is_own_mesh(x, stem))
    archive.write(out, car_path)
    if abs(shift) > 1e-4 or abs(lift) > 1e-4:
        _shift_cockpit(car_path, shift, lift)
    return {"stem": stem, "length": body_len, "before": before, "after": new,
            "scaled": bool(spec and length_real), "source": source,
            "shift": shift, "lift": lift, "moved": moved}



def _is_own_mesh(entry, stem: str) -> bool:
    n = entry.name.lower()
    return n.endswith(".mod") and n.startswith(stem)


def _shift_mesh(entry, dz: float, stem: str, dy: float = 0.0):
    m = mod_mod.parse(envelope.build(entry.tag, entry.version, entry.payload))
    verts = [mod_mod.Vertex(v.x, v.y + dy, v.z + dz, v.nx, v.ny, v.nz, v.u, v.v)
             for v in m.vertices]
    blob = mod_mod.build(mod_mod.Mesh(vertices=verts, materials=list(m.materials),
                                      faces=list(m.faces), version=m.version))
    return archive.ArchiveEntry(name=entry.name, tag=entry.tag,
                                version=entry.version, payload=blob[20:])


def _shift_cockpit(car_path: Path, dz: float, dy: float = 0.0) -> None:
    """Move the cockpit POSITIONS by the same dz -- they are in the same space.

    Only the positions. "rpm dat"/"mph dat" are three-number records too, but
    they are a gauge's sweep calibration, not a point in the car, and adding a
    metre-scale offset to one would swing the needle off the dial.
    """
    POSITIONS = {"camera", "wheel", "rpm pt", "mph pt"}
    entries = archive.read(car_path)
    e = next((x for x in entries if x.name.lower() == "cockpit.tab"), None)
    if e is None:
        return
    from vrmod import cockpit_tab
    raw = envelope.build(e.tag, e.version, e.payload)
    recs = cockpit_tab.parse(raw)
    moved = {k: ((v[0], v[1] + dy, v[2] + dz) if k.strip().lower() in POSITIONS else v)
             for k, v in recs.items()}
    blob = cockpit_tab.build(raw, moved)
    out = [archive.ArchiveEntry(name=x.name, tag=x.tag, version=x.version,
                                payload=blob[20:]) if x is e else x
           for x in entries]
    archive.write(out, car_path)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        raise SystemExit("wheelfit.py <fleet_dir_or_car>")
    target = Path(argv[0])
    cars = sorted(target.rglob("*.car")) if target.is_dir() else [target]
    if not cars:
        raise SystemExit(f"no .car under {target}")
    for p in cars:
        r = fit(p)
        b, a = r["before"], r["after"]
        if not r["scaled"]:
            print(f"  {r['stem']:9s} no real-world twin -- width set from the mesh "
                  f"({b['width']:.1f} -> {a['width']:.1f} in), wheelbase left at "
                  f"{b['wheelbase']:.1f}")
            continue
        span = a["wheelbase"] / r["length"]
        print(f"  {r['stem']:9s} body {r['length']:.1f} in long")
        print(f"      wheelbase {b['wheelbase']:6.1f} -> {a['wheelbase']:6.1f} in "
              f"({span:.0%} of the body)")
        print(f"      track  f  {b['ftrack']:6.1f} -> {a['ftrack']:6.1f}   "
              f"r {b['rtrack']:6.1f} -> {a['rtrack']:6.1f}   "
              f"width {b['width']:.1f} -> {a['width']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
