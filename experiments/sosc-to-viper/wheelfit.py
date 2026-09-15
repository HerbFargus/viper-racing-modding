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
    if spec and length_real:
        zk = body_len / length_real
        xk = body_wid / spec["width"]
        new["wheelbase"] = spec["wheelbase"] * zk
        new["ftrack"] = spec["ftrack"] * xk
        new["rtrack"] = spec["rtrack"] * xk

    # Only the named fields are written; every other byte of the .cf carries
    # over untouched, same as realstats does it.
    raw = cf.build(envelope.build(ce.tag, ce.version, ce.payload), new)
    out = [archive.ArchiveEntry(name=x.name, tag=x.tag, version=x.version,
                                payload=raw[20:]) if x is ce else x
           for x in entries]
    archive.write(out, car_path)
    return {"stem": stem, "length": body_len, "before": before, "after": new,
            "scaled": bool(spec and length_real)}


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
