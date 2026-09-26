"""
CARF -- .cf car physics config.

A fixed-layout struct of named float32 (and one int32) fields -- mass, dimensions,
engine curve, transmission, per-corner suspension, brakes, drag/aero. Field offsets
below are payload-relative (i.e. relative to the byte right after the 20-byte 0SER
envelope) and were recovered by cross-referencing every field name and real-world
value from a community .cf-to-text conversion tool's output against the raw bytes of
viper.cf -- every one of the 85 fields matched a unique float32 (or, for num_gears,
int32) at a 4-byte-aligned offset, byte-exact, with no ambiguity once ties between
identically-valued fields (e.g. several suspension fields sharing the value 5) were
broken using their local declaration order and the surrounding confirmed offsets'
contiguous layout. The rest were named later, mostly by tracing the v1.0 race.exe
(CarFileCombine, apply_upgrade): every one of the 138 dwords in the payload is now
named.
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import envelope

TAG = b"FRAC"
VERSION = 6

# name -> (payload offset, "f" for float32 or "i" for int32)
FIELD_MAP: dict[str, tuple[int, str]] = {
    "mass": (0x00, "f"), "mx": (0x04, "f"), "my": (0x08, "f"), "mz": (0x0C, "f"),
    "width": (0x10, "f"), "height": (0x14, "f"), "ftrack": (0x18, "f"), "rtrack": (0x1C, "f"),
    "fground_clearance1": (0x20, "f"), "fground_clearance2": (0x24, "f"),
    "rground_clearance1": (0x28, "f"), "rground_clearance2": (0x2C, "f"),
    "wheelbase": (0x30, "f"), "weight_distribution": (0x34, "f"),
    "power_max": (0x38, "f"), "power_rpm": (0x3C, "f"),
    "torque_max": (0x40, "f"), "torque_rpm": (0x44, "f"),
    "idle_speed": (0x48, "f"), "redline": (0x4C, "f"),
    "engine_inertia": (0x50, "f"), "engine_drag": (0x54, "f"),
    "fuel_consumption": (0x58, "f"), "fuel_capacity": (0x5C, "f"),
    # Upgrade slots, traced through CarFileCombine. A .ugs upgrade is a list of
    # (.cf offset, value) pairs that apply_upgrade pokes into the loaded .cf, and
    # viper.ugs gives each part its own slot (AirInduction -> power_add1,
    # WeightReduction1 -> mass_add1, ...). Power and torque are both scaled by
    # every non-zero power_mult times (1 + sum of power_add hp / power_max);
    # the mass_adds (lb) are added to mass. No shipped .cf or upgrade sets a
    # power_mult, power_add10-12 or mass_add5-8.
    **{f"power_mult{i + 1}": (0x60 + 4 * i, "f") for i in range(6)},
    **{f"power_add{i + 1}": (0x78 + 4 * i, "f") for i in range(12)},
    **{f"mass_add{i + 1}": (0xA8 + 4 * i, "f") for i in range(8)},
    "torque_balance": (0xD0, "f"),
    "fdiff_stiff": (0xD4, "f"), "rdiff_stiff": (0xD8, "f"), "cdiff_stiff": (0xDC, "f"),
    "trans_inertia": (0xE0, "f"), "trans_drag": (0xE4, "f"),
    # A fixed gearbox: when gear_ratio1 is non-zero these replace the setup's
    # gear sliders (0 in every .cf; the CloseRatioGearbox upgrade fills them,
    # RacingGearbox zeroes them to make the gears adjustable again). The physics
    # never reads gear_ratio8 -- reverse is gear 1 negated -- though viper.ugs
    # writes 2.9 there, the real Viper's reverse ratio.
    **{f"gear_ratio{i + 1}": (0xE8 + 4 * i, "f") for i in range(8)},
    "num_gears": (0x108, "i"),
    "rear_end_ratio1": (0xC8, "f"), "rear_end_ratio2": (0xCC, "f"),
    "fsprings1": (0x10C, "f"), "rsprings1": (0x110, "f"),
    "fbump1": (0x114, "f"), "rbump1": (0x118, "f"),
    "frebound1": (0x11C, "f"), "rrebound1": (0x120, "f"),
    "fsway1": (0x124, "f"), "rsway1": (0x128, "f"),
    "fcamber1": (0x12C, "f"), "rcamber1": (0x130, "f"),
    "ftoe1": (0x134, "f"), "rtoe1": (0x138, "f"),
    "fsprings2": (0x13C, "f"), "rsprings2": (0x140, "f"),
    "fbump2": (0x144, "f"), "rbump2": (0x148, "f"),
    "frebound2": (0x14C, "f"), "rrebound2": (0x150, "f"),
    "fsway2": (0x154, "f"), "rsway2": (0x158, "f"),
    "fcamber2": (0x15C, "f"), "rcamber2": (0x160, "f"),
    "ftoe2": (0x164, "f"), "rtoe2": (0x168, "f"),
    "caster": (0x16C, "f"), "anti_dive": (0x170, "f"), "anti_squat": (0x174, "f"),
    "fbump_camber": (0x178, "f"), "rbump_camber": (0x17C, "f"),
    "fbump_toe": (0x180, "f"), "rbump_toe": (0x184, "f"),
    # Traced from the v1.0 race.exe (Wheel::Setup reads CarData, CarFileCombine
    # maps it to these offsets) rather than matched against the community tool's
    # listing. Compliance is degrees per 1000 lbf of lateral tyre force -- 0 on
    # every car except plane.car. The grip and tyre-stiffness scales multiply
    # the .tir friction and stiffness (1.0 on every car); static rolling
    # resistance is 0 on every car.
    "ftoe_compliance": (0x188, "f"), "rtoe_compliance": (0x18C, "f"),
    "fcamber_compliance": (0x190, "f"), "rcamber_compliance": (0x194, "f"),
    "cm_height": (0x198, "f"), "wheel_lock": (0x19C, "f"),
    # Tyre size, as printed on the sidewall: width in mm, aspect ratio, rim in
    # inches. Identified against viper.car, which reads 275/40 R17 front and
    # 335/35 R17 rear -- exactly the real 1996 Viper GTS. Stock sedan is 245/35 R18
    # all round; plane is 225/50 R15 front on 225/50 R10 rear.
    "ftyre_width": (0x1A0, "f"), "ftyre_aspect": (0x1A4, "f"), "ftyre_rim": (0x1A8, "f"),
    "rtyre_width": (0x1AC, "f"), "rtyre_aspect": (0x1B0, "f"), "rtyre_rim": (0x1B4, "f"),
    "fgrip_scale": (0x1B8, "f"), "rgrip_scale": (0x1BC, "f"),
    "ftyre_stiffness_scale": (0x1C0, "f"), "rtyre_stiffness_scale": (0x1C4, "f"),
    "fbrake1": (0x1C8, "f"), "rbrake1": (0x1CC, "f"),
    "fbrake2": (0x1D0, "f"), "rbrake2": (0x1D4, "f"),
    "rolling_resistance": (0x1D8, "f"), "static_rolling_resistance": (0x1DC, "f"),
    "cp_height": (0x1E4, "f"), "cp_long": (0x1E8, "f"),
    "frontal_area": (0x1E0, "f"), "drag_coefficient": (0x1EC, "f"),
    "lat_drag": (0x1F0, "f"), "vert_drag": (0x1F4, "f"),
    "front_lift": (0x1F8, "f"), "rear_lift": (0x1FC, "f"),
    "fspoiler1": (0x200, "f"), "rspoiler1": (0x204, "f"),
    "fspoiler2": (0x208, "f"), "rspoiler2": (0x20C, "f"),
    "fspoiler_drag": (0x210, "f"), "rspoiler_drag": (0x214, "f"),
    # Spoiler values for the setup's aero kit (1 Low Drag, 2 High Downforce),
    # used in place of the fspoiler/rspoiler lerp when non-zero.
    "fspoiler_low_drag": (0x218, "f"), "rspoiler_low_drag": (0x21C, "f"),
    "fspoiler_downforce": (0x220, "f"), "rspoiler_downforce": (0x224, "f"),
}


def parse(data: bytes) -> dict[str, float]:
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .cf file: tag {env.tag!r}, expected {TAG!r}")
    payload = env.payload
    values = {}
    for name, (off, kind) in FIELD_MAP.items():
        fmt = "<f" if kind == "f" else "<i"
        values[name] = struct.unpack_from(fmt, payload, off)[0]
    return values


def build(data: bytes, values: dict[str, float]) -> bytes:
    """Return a copy of a real .cf file's bytes with named fields overwritten.

    Only the fields present in `values` are changed; every other byte is carried
    over unmodified from `data`, which must be a real, complete .cf file to use as
    the base.
    """
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .cf file: tag {env.tag!r}, expected {TAG!r}")
    payload = bytearray(env.payload)
    for name, value in values.items():
        if name not in FIELD_MAP:
            raise KeyError(f"unknown .cf field: {name!r}")
        off, kind = FIELD_MAP[name]
        fmt = "<f" if kind == "f" else "<i"
        struct.pack_into(fmt, payload, off, int(value) if kind == "i" else float(value))
    return envelope.build(env.tag, env.version, bytes(payload))


def parse_file(path: str | Path) -> dict[str, float]:
    return parse(Path(path).read_bytes())


def to_text(values: dict[str, float]) -> str:
    lines = []
    for name, (_, kind) in FIELD_MAP.items():
        v = values[name]
        lines.append(f"{name} {int(v) if kind == 'i' else v}")
    return "\n".join(lines) + "\n"


def parse_text(text: str) -> dict[str, float]:
    """Parse `name value` lines (as produced by to_text) back into a values dict.

    Unrecognized field names raise immediately, same as build(), so a typo in a
    hand-edited .txt fails loudly rather than being silently ignored.
    """
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        name, value = line.split(None, 1)
        if name not in FIELD_MAP:
            raise KeyError(f"unknown .cf field: {name!r}")
        values[name] = float(value)
    return values
