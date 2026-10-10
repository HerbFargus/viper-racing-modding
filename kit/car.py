"""Building a car: the Willys recipe, generalised.

  1. fork a donor (the HMX van: sounds, cockpit, brake strip) to a new prefix
  2. our body as <prefix>0.mod, wheels as wheel_1..3 (rear) / fwheel_1..3 (front), our palette
  3. the brake strip moved to the tail
  4. the .cf on Val's "best handling" Viper, with our body fields, and one of two tunes:
       "val"   all of Val's file (350 hp, 9,000 rpm, 6 gears) -- right for a Viper-sized body
               (the Willys, confirmed "drives really well")
       "indy"  Val's chassis with the van's engine at `power` on a 3.50 final drive (the Indy
               Jeep): heavier, taller bodies; Val's full file felt swervy on a long one
  5. display name, write, `vrmod.cli modlod` for the LOD chain
  6. AFTER modlod: the horn ball (ball.mod, centred on its origin) and horn.sfx (a loop the
     game repeats while the horn is held; stock is 0.44 s)

Body frame: game frame, metres, ground at y = 0, the axle midpoint at z = 0, +z the nose.
Units in the .cf are inches and pounds. Read the .cf back after building -- cf.build writes
every key you pass, and a stray key once silently dropped fields.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import kit
from vrmod import archive, car, cf, envelope, mod, sfx

INCH = 0.0254


@dataclass
class CarSpec:
    prefix: str                       # <= 8 chars; the file is <prefix>.car
    display: str                      # the menu shows about 24 chars
    body: mod.Mesh
    front_wheel: mod.Mesh
    rear_wheel: mod.Mesh
    palette: archive.ArchiveEntry     # its own NAME per car (see shapes.Palette)
    wheelbase: float                  # metres
    ftrack: float
    rtrack: float
    height: float                     # the body without antennas, metres
    ftyre: tuple                      # (width mm, aspect %, rim in)
    rtyre: tuple
    tune: str = "val"                 # "val" | "indy"
    power: float = 210.0              # "indy" only
    horn_ball: mod.Mesh | None = None
    horn_wav: bytes | None = None     # 16-bit mono PCM WAV
    extra: list = field(default_factory=list)   # more ArchiveEntry members


def _bytes(e):
    return envelope.build(e.tag, e.version, e.payload)


def _upsert(entries, new):
    for i, e in enumerate(entries):
        if e.name.lower() == new.name.lower():
            entries[i] = new
            return
    entries.append(new)


def _mod_entry(name, mesh, like):
    return archive.ArchiveEntry(name=name, tag=like.tag, version=like.version,
                                payload=envelope.parse(mod.build(mesh, like.version)).payload)


def tyre_radius(t):
    """Metres, from (width mm, aspect %, rim in)."""
    return (t[2] * 25.4 / 2 + t[0] * t[1] / 100) / 1000


def build(spec: CarSpec, out: Path, donor: Path = kit.DONOR_CAR, val: Path = kit.VAL_CAR) -> Path:
    p = spec.prefix
    entries = car.fork_car(archive.read(donor), p)
    by = {e.name.lower(): e for e in entries}
    be = by[f"{p}0.mod"]
    be.payload = envelope.parse(mod.build(spec.body, be.version)).payload
    for n in ("wheel_1", "wheel_2", "wheel_3"):
        _upsert(entries, _mod_entry(f"{n}.mod", spec.rear_wheel, be))
    for n in ("fwheel_1", "fwheel_2", "fwheel_3"):
        _upsert(entries, _mod_entry(f"{n}.mod", spec.front_wheel, be))
    _upsert(entries, spec.palette)
    for e in spec.extra:
        _upsert(entries, e)

    xs = [v.x for v in spec.body.vertices]
    zs = [v.z for v in spec.body.vertices]
    bre = by[f"{p}b.mod"]
    bm = mod.parse(_bytes(bre))
    for v in bm.vertices:
        v.z = min(zs) - 0.02
        v.x *= (max(xs) - min(xs)) / 1.84 * 0.6
    bre.payload = envelope.parse(mod.build(bm, bre.version)).payload

    ce = by[f"{p}.cf"]
    van = cf.parse(_bytes(ce))
    val_raw = _bytes(next(e for e in archive.read(val) if e.name.lower().endswith(".cf")))
    vl = cf.parse(val_raw)
    vals = {
        "wheelbase": spec.wheelbase / INCH, "ftrack": spec.ftrack / INCH, "rtrack": spec.rtrack / INCH,
        "width": (max(xs) - min(xs)) / INCH, "height": spec.height / INCH,
        "fground_clearance1": van["fground_clearance1"], "rground_clearance1": van["rground_clearance1"],
        "ftyre_width": spec.ftyre[0], "ftyre_aspect": spec.ftyre[1], "ftyre_rim": spec.ftyre[2],
        "rtyre_width": spec.rtyre[0], "rtyre_aspect": spec.rtyre[1], "rtyre_rim": spec.rtyre[2]}
    if spec.tune == "indy":
        for k in ("power_rpm", "torque_rpm", "idle_speed", "redline", "engine_inertia", "engine_drag",
                  "fuel_consumption", "fuel_capacity", "num_gears", "trans_inertia", "trans_drag"):
            vals[k] = van[k]
        vals["torque_max"] = van["torque_max"] * spec.power / van["power_max"]
        vals["power_max"] = spec.power
        vals["drag_coefficient"] = van["drag_coefficient"] * van["frontal_area"] / vl["frontal_area"]
        vals["rear_end_ratio1"] = van["rear_end_ratio1"] * 3.5 / 4.1
        vals["rear_end_ratio2"] = van["rear_end_ratio2"] * 3.5 / 4.1
    elif spec.tune != "val":
        raise ValueError(f"tune {spec.tune!r}: 'val' or 'indy'")
    env = envelope.parse(val_raw)
    ce.tag, ce.version = env.tag, env.version
    ce.payload = envelope.parse(cf.build(val_raw, vals)).payload
    entries = car.set_car_name(entries, spec.display)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    archive.write(entries, out)
    r = subprocess.run([sys.executable, "-m", "vrmod.cli", "modlod", str(out)], cwd=str(kit.VRMOD_REPO),
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"modlod failed for {p}: {r.stderr[-800:]}")

    data = out.read_bytes()
    layout = archive.read_layout(data)
    entries = archive.read_bytes(data)
    names = {e.name.lower(): e for e in entries}
    if spec.horn_ball is not None:
        old = names["ball.mod"]
        old.payload = envelope.parse(mod.build(spec.horn_ball, old.version)).payload
    if spec.horn_wav is not None:
        h = envelope.parse(sfx.build(sfx.from_wav_bytes(spec.horn_wav)))
        _upsert(entries, archive.ArchiveEntry(name="horn.sfx", tag=h.tag, version=h.version, payload=h.payload))
    out.write_bytes(archive.to_bytes(entries, partitioned=layout.partitioned))
    return out


def report(path: Path) -> str:
    """One paragraph read back from the built file: sizes, the .cf, the horn."""
    back = {e.name.lower(): e for e in archive.read(path)}
    prefix = car.body_prefix(list(back.values()))
    worst = max((len(mod.parse(_bytes(e)).vertices), n) for n, e in back.items() if n.endswith(".mod"))
    v = cf.parse(_bytes(back[f"{prefix}.cf"]))
    hs = sfx.parse(_bytes(back["horn.sfx"])) if "horn.sfx" in back else None
    return (f"{path.name} '{car.read_car_name(list(back.values()))}': {path.stat().st_size:,} B, largest .mod "
            f"{worst[0]} v ({worst[1]}); power {v['power_max']:.0f} torque {v['torque_max']:.0f} final "
            f"{v['rear_end_ratio1']:.2f} gears {v['num_gears']:.0f}; wheelbase {v['wheelbase']:.1f} in, track "
            f"{v['ftrack']:.1f}/{v['rtrack']:.1f} in, height {v['height']:.1f} in, tyres "
            f"{v['ftyre_width']:.0f}/{v['ftyre_aspect']:.0f}R{v['ftyre_rim']:.0f} / "
            f"{v['rtyre_width']:.0f}/{v['rtyre_aspect']:.0f}R{v['rtyre_rim']:.0f}"
            + (f"; horn {len(hs.sample_data) / 2 / hs.sample_rate:.2f} s" if hs else "")
            + f"; textures {car.texture_provenance(path).get('verdict')}")
