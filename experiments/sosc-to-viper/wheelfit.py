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

    python wheelfit.py <fleet_dir_or_car> [--chassis=<Val's Viper.car>]

--chassis puts the cars that tipped on Val's chassis -- see CHASSIS_CARS.
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
    "hmxvan":   (0.232, 0.852),   # re-read against the drawn axles: both
                                 # wells sit ~3% further forward than first taken
    "airhawk":  (0.23, 0.77),
    "police":   (0.224, 0.820),   # front re-read against the drawn axle
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


def track_fit(m, z: float, half_w: float, radius: float = 0.330,
              span: float = 0.25) -> float | None:
    """Track in inches that tucks the tyre inside the body at station z.

    Measured only within the WHEEL'S OWN HEIGHT BAND, not over the full body.
    The van is why: at its front axle the body is 0.859 m half-wide taken
    overall, but the cab necks in to 0.677 m down where the tyre actually is --
    182 mm of difference, and setting the track from the wider number left the
    wheel hanging outside the cab. Every other car in the fleet measures the
    same either way, so this costs nothing where it is not needed.
    """
    base = min(v.y for v in m.vertices)
    xs = sorted(abs(v.x) for v in m.vertices
                if abs(v.z - z) < span and v.y <= base + 2 * radius)
    if not xs:
        return None
    # The 75th percentile, not the maximum: a fin or a flared arch lip is a few
    # vertices wide and should not set the track for the whole axle. The Hunter
    # and the Police are why -- their noses flare 89 mm and 85 mm past the body
    # beside them, which stood both front wheels out at the widest point. On the
    # five cars without a flare the two figures agree to within 3 inches, so
    # this only bites where something is actually sticking out.
    half = xs[int(0.75 * (len(xs) - 1))] - half_w - WHEEL_INSET
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
    "police":   0.119,   # large, and confirmed by eye before it was applied
}


# THE HUNTER, SET BY DRIVING. Everything above is measured off the art; this is
# not. The Hunter tipped in fast swerves through four one-field fixes (clearance2,
# drive split, CG height, track), because the cause was never one field: it was
# built on the 4x4cos, a community car, not a stock one, and 11 of that donor's 85
# physics values sit outside all five stock cars -- including more downforce than
# the Viper, which is exactly a "fine slow, over at speed" fault.
#
# What finally drove well was the airhawk's physics file with the Hunter's own
# tracks. The airhawk is exotic-built, and no exotic-built car has ever tipped.
# Recorded here as explicit values rather than "copy the airhawk at build time",
# so the result does not depend on which car the build happens to finish first.
#
# Applied LAST in fit(), over both the scaled and the measured figures, because
# fit() would otherwise re-tuck the tracks to 42.0 / 24.5 -- the numbers that put
# the car on its roof.
HAND_TUNED = {
    "hunter": {
        # the airhawk's physics
        "mass": 3550.0, "mx": 73598.0, "my": 73598.0, "mz": 21646.0,
        "fground_clearance1": 4.0, "fground_clearance2": 20.0,
        "rground_clearance1": 4.0, "rground_clearance2": 20.0,
        "weight_distribution": 56.0,
        "power_max": 375.0, "power_rpm": 5600.0,
        "torque_max": 415.0, "torque_rpm": 3600.0,
        "idle_speed": 700.0, "redline": 6000.0,
        "engine_inertia": 22.0, "engine_drag": 0.034, "fuel_capacity": 18.0,
        "torque_balance": 1.0, "num_gears": 4,
        "rear_end_ratio1": 3.55, "rear_end_ratio2": 4.7,
        "caster": 5.0, "cm_height": 11.0, "rolling_resistance": 0.54,
        "frontal_area": 21.5, "drag_coefficient": 0.45,
        "lat_drag": 13.0, "vert_drag": 16.0,
        # -0.0 as the stock files store it, so the result is bit-identical
        "front_lift": -0.0, "rear_lift": -0.0,
        "fspoiler_drag": 0.0, "rspoiler_drag": 0.0,
        # the exotic's tyres: 280/35 R18 front, 330/40 R18 rear. The 4x4cos put
        # the Viper's 275/40 R17 FRONT tyre on all four corners.
        "ftyre_width": 280.0, "ftyre_aspect": 35.0, "ftyre_rim": 18.0,
        "rtyre_width": 330.0, "rtyre_aspect": 40.0, "rtyre_rim": 18.0,
        # the Hunter's own geometry, as driven
        "wheelbase": 91.150002, "ftrack": 43.700001, "rtrack": 40.0,
    },
    # The Police as driven carries 101.4, where its arch fractions give 101.353
    # off the body -- 0.05 in, about a millimetre. The driven figure wins.
    "police": {"wheelbase": 101.4},
}


# VAL'S CHASSIS. The airhawk file above stopped the Hunter tipping; the Strtrat,
# the van and the Police kept tipping on their own donors (sedan, 4x4cos). What
# fixed all four, by driving, was one shared chassis: the physics file from Val's
# "best handling viper" (Viper.car, 22 Oct 2014, by Val in Moose Jaw; his readme
# gives permission to reuse its parts). Read at build time from --chassis, never
# stored here -- a .cf is more than its named fields, and his changes four
# unnamed words (0x218-0x224) too.
#
# A physics file splits three ways, and only one part is Val's:
#   chassis   Val's: mass, inertia, CG height, suspension, diffs, drive split,
#             downforce, brakes -- everything not listed below
#   engine    the car's own, power and torque scaled by Val's mass over the car's,
#             so each keeps its original weight per horsepower; drag coefficient
#             scaled the same way so total drag (Cd x frontal area) is unchanged
#   body      the car's own: size, wheelbase, ride height, tyre sizes
#
# The TRACK is the exception to "the body's own". Narrow tracks tucked the wheels
# in the wells and the cars would not turn, and a front narrower than the rear
# oversteered in proportion to the gap (van 12 in: swervy; Police 4 in: pulled).
# Even, and ~50 in or wider, is what drove: Strtrat 51.6 best, van 49.6 fine,
# Police tippy until 52. The wheels reach the Hunter's body sides at 52, which
# looked better anyway.
#
# The exotic-built three never tipped, but they went onto the same chassis too so
# the whole fleet drives as one family -- the stock exotic is itself a finicky
# car. Their tracks follow the same rule: the wider of front and rear, at least
# 52, but no wider than keeps the tyres inside the body (Azzaroni caps at 51.2).
CHASSIS_CARS = ("strtrat", "hmxvan", "police", "hunter",
                "airhawk", "azzaroni", "j57")
CHASSIS_BODY = ("width", "height", "wheelbase",
                "fground_clearance1", "rground_clearance1",
                "ftyre_width", "ftyre_aspect", "ftyre_rim",
                "rtyre_width", "rtyre_aspect", "rtyre_rim")
CHASSIS_ENGINE = ("power_rpm", "torque_rpm", "idle_speed", "redline",
                  "engine_inertia", "engine_drag", "fuel_consumption",
                  "fuel_capacity", "num_gears", "rear_end_ratio1",
                  "rear_end_ratio2", "trans_inertia", "trans_drag")
EVEN_TRACK = {
    "strtrat": 51.58858108520508,    # its fitted track, already even
    "hmxvan":  49.61811065673828,    # its fitted REAR track, front raised to match
    "police":  52.0,
    "hunter":  52.0,
    "airhawk": 52.0,                 # from 42.9 / 47.3
    "azzaroni": 51.21614074707031,   # body width less tyre width: 64.2 - 13.0
    "j57":     64.9143295288086,     # its fitted REAR track, front raised to match
}


# THE COCKPITS, SET BY CALIBRATING IN GAME. cockpits.py copies viper.car's
# cockpit.tab, which knows nothing about a SoSC dash, and the body shift above
# then moves its positions. These are the six records as calibrated by eye in the
# mod manager and checked in game -- needle pivots, sweeps, wheel, camera -- and
# they are FINAL, in the shifted frame, so they are written after the shift
# rather than shifted again. Same "the driven result has the last word" rule as
# HAND_TUNED.
#
# Notes that matter if you touch these:
#   - "mph dat"'s third number is METRES PER SECOND (see vrmod/cockpit_tab.py).
#   - The needle pivots sit a few mm in front of their dash: at the dash face
#     the game hides the needle. They were pulled forward ALONG THE LINE OF SIGHT
#     (the mod manager's "Toward eye"), so x and y moved with z.
#   - Two dashes are shared, and the pairs were calibrated once and copied with
#     the dash offset: airhawk -> police, hunter -> j57.
#   - A flat SoSC dash is a painted picture, and a strip speedometer (airhawk,
#     police) cannot be tracked exactly by a rotating needle. Close is the ceiling.
COCKPIT_TUNED = {
    "airhawk": {
        "camera": (-0.408, 0.906, -0.791), "wheel": (-0.491, 0.625, -0.15),
        "rpm pt": (-0.668, 0.632, -0.148), "mph pt": (-0.423, 0.655, -0.14),
        "rpm dat": (-90.0, 90.0, 7000.0), "mph dat": (-79.0, 79.0, 53.6),
    },
    "azzaroni": {
        "camera": (-0.408, 0.948, -0.855), "wheel": (-0.491, 0.709, -0.278),
        "rpm pt": (-0.785, 0.742, -0.22), "mph pt": (-0.506, 0.738, -0.22),
        "rpm dat": (-180.0, 180.0, 7000.0), "mph dat": (-141.0, 180.0, 89.0),
    },
    "j57": {
        "camera": (-0.408, 0.95, -0.705), "wheel": (-0.491, 0.669, -0.088),
        "rpm pt": (-0.692, 0.77, -0.064), "mph pt": (-0.124, 0.777, -0.064),
        "rpm dat": (-130.0, 130.0, 8000.0), "mph dat": (-145.0, 130.0, 94.0),
    },
    "strtrat": {
        "camera": (-0.408, 0.954, -0.856), "wheel": (-0.491, 0.721, -0.28),
        "rpm pt": (-0.819, 0.746, -0.22), "mph pt": (-0.522, 0.706, -0.215),
        "rpm dat": (-77.0, 90.0, 5000.0), "mph dat": (-133.0, 130.0, 40.2),
    },
    "hmxvan": {
        "camera": (-0.408, 0.908, -0.953), "wheel": (-0.491, 0.629, -0.474),
        "rpm pt": (-0.41, 0.749, -0.302), "mph pt": (-0.676, 0.757, -0.312),
        "rpm dat": (-139.0, 139.0, 7000.0), "mph dat": (-142.0, 142.0, 71.5),
    },
    "police": {
        "camera": (-0.408, 1.025, -0.886), "wheel": (-0.491, 0.744, -0.245),
        "rpm pt": (-0.668, 0.751, -0.243), "mph pt": (-0.423, 0.774, -0.235),
        "rpm dat": (-90.0, 90.0, 7000.0), "mph dat": (-79.0, 79.0, 53.6),
    },
    "hunter": {
        "camera": (-0.408, 0.906, -0.791), "wheel": (-0.491, 0.625, -0.174),
        "rpm pt": (-0.692, 0.726, -0.15), "mph pt": (-0.124, 0.733, -0.15),
        "rpm dat": (-130.0, 130.0, 8000.0), "mph dat": (-145.0, 130.0, 94.0),
    },
}


def _apply_cockpit_tuned(car_path: Path, stem: str) -> bool:
    """Write COCKPIT_TUNED's records over the car's cockpit.tab. False if none."""
    records = COCKPIT_TUNED.get(stem)
    if not records:
        return False
    from vrmod import cockpit_tab
    entries = archive.read(car_path)
    e = next((x for x in entries if x.name.lower() == "cockpit.tab"), None)
    if e is None:
        return False
    blob = cockpit_tab.build(envelope.build(e.tag, e.version, e.payload), records)
    archive.write([archive.ArchiveEntry(name=x.name, tag=x.tag, version=x.version,
                                        payload=blob[20:]) if x is e else x
                   for x in entries], car_path)
    return True


def load_chassis(car_path: Path) -> bytes:
    """The .cf of a car, whole, as the base every chassis car is built on."""
    e = next(x for x in archive.read(car_path) if x.name.lower().endswith(".cf"))
    return envelope.build(e.tag, e.version, e.payload)


def on_chassis(car_raw: bytes, chassis_raw: bytes, stem: str) -> bytes:
    """Val's .cf, carrying this car's engine and body. See VAL'S CHASSIS."""
    mine, val = cf.parse(car_raw), cf.parse(chassis_raw)
    new = {k: mine[k] for k in CHASSIS_BODY + CHASSIS_ENGINE}
    k = val["mass"] / mine["mass"]
    new["power_max"] = mine["power_max"] * k
    new["torque_max"] = mine["torque_max"] * k
    new["drag_coefficient"] = (mine["drag_coefficient"] * mine["frontal_area"]
                               / val["frontal_area"])
    new["ftrack"] = new["rtrack"] = EVEN_TRACK[stem]
    return cf.build(chassis_raw, new)


def body_mesh(entries, stem: str):
    """LOD 0, which is the only mesh at full size."""
    want = f"{stem}0.mod"
    e = next((x for x in entries if x.name.lower() == want), None)
    if e is None:
        raise SystemExit(f"no {want} in the car")
    return mod_mod.parse(envelope.build(e.tag, e.version, e.payload))


def fit(car_path: Path, chassis: bytes | None = None) -> dict | None:
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
    # Even a car with no arch measurement gets its track fitted -- the Hunter
    # has no readable wells, but its wheels still have to sit inside its body,
    # and its existing wheelbase says where they are.
    if "wheelbase" not in new:
        new["wheelbase"] = values["wheelbase"]
    if "wheelbase" in new:
        half_wb = new["wheelbase"] * INCH_TO_M / 2
        ft = track_fit(m, half_wb + shift, half_w)
        rt = track_fit(m, -half_wb + shift, half_w)
        if ft:
            new["ftrack"] = ft
        if rt:
            new["rtrack"] = rt

    # A car tuned by driving has the last word -- see HAND_TUNED.
    if stem in HAND_TUNED:
        new.update(HAND_TUNED[stem])
        source = "hand-tuned"

    # Only the named fields are written; every other byte of the .cf carries
    # over untouched, same as realstats does it.
    raw = cf.build(envelope.build(ce.tag, ce.version, ce.payload), new)
    # Val's chassis goes on over the finished file, so the engine and body it
    # carries across are exactly what the steps above produced.
    if chassis is not None and stem in CHASSIS_CARS:
        raw = on_chassis(raw, chassis, stem)
        new = dict(new, ftrack=EVEN_TRACK[stem], rtrack=EVEN_TRACK[stem])
        source += " on Val's chassis"
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
    # the calibrated cockpit has the last word -- see COCKPIT_TUNED
    if _apply_cockpit_tuned(car_path, stem):
        source += ", calibrated cockpit"
    return {"stem": stem, "length": body_len, "before": before, "after": new,
            "scaled": bool(spec and length_real), "source": source,
            "shift": shift, "lift": lift, "moved": moved}



def _is_own_mesh(entry, stem: str) -> bool:
    """A mesh that lives in car space and must move with the body.

    NOT the steering wheel (<stem>w.mod). It is placed by cockpit.tab's "wheel"
    record, which _shift_cockpit already moves -- shifting its vertices too moved
    it twice, and worse, left the hub off the model's own origin, which is the
    point the game turns it about. The Police's wheel swung around a point
    11.9 cm below its hub. The stock wheels are centred on their origin; this
    keeps the generated ones that way.
    """
    n = entry.name.lower()
    return n.endswith(".mod") and n.startswith(stem) and n != f"{stem}w.mod"


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
    flags = [a for a in argv if a.startswith("--chassis=")]
    args = [a for a in argv if not a.startswith("--chassis=")]
    if len(args) != 1:
        raise SystemExit("wheelfit.py <fleet_dir_or_car> [--chassis=<Val's Viper.car>]")
    chassis = load_chassis(Path(flags[-1].split("=", 1)[1])) if flags else None
    target = Path(args[0])
    cars = sorted(target.rglob("*.car")) if target.is_dir() else [target]
    if not cars:
        raise SystemExit(f"no .car under {target}")
    if chassis is None and any(p.stem.lower() in CHASSIS_CARS for p in cars):
        print("  no --chassis: " + ", ".join(CHASSIS_CARS)
              + " stay on their donors' physics, which tip")
    for p in cars:
        r = fit(p, chassis)
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
