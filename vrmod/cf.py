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
contiguous layout.

Not every byte in the payload is named here -- several stretches (e.g. right after
fuel_capacity, and a short run before cm_height) are reserved/unidentified and are
left untouched by build().
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
    "torque_balance": (0xD0, "f"),
    "fdiff_stiff": (0xD4, "f"), "rdiff_stiff": (0xD8, "f"), "cdiff_stiff": (0xDC, "f"),
    "trans_inertia": (0xE0, "f"), "trans_drag": (0xE4, "f"),
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
    "cm_height": (0x198, "f"), "wheel_lock": (0x19C, "f"),
    "fbrake1": (0x1C8, "f"), "rbrake1": (0x1CC, "f"),
    "fbrake2": (0x1D0, "f"), "rbrake2": (0x1D4, "f"),
    "rolling_resistance": (0x1D8, "f"),
    "cp_height": (0x1E4, "f"), "cp_long": (0x1E8, "f"),
    "frontal_area": (0x1E0, "f"), "drag_coefficient": (0x1EC, "f"),
    "lat_drag": (0x1F0, "f"), "vert_drag": (0x1F4, "f"),
    "front_lift": (0x1F8, "f"), "rear_lift": (0x1FC, "f"),
    "fspoiler1": (0x200, "f"), "rspoiler1": (0x204, "f"),
    "fspoiler2": (0x208, "f"), "rspoiler2": (0x20C, "f"),
    "fspoiler_drag": (0x210, "f"), "rspoiler_drag": (0x214, "f"),
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

    Only the fields present in `values` are changed; every other byte (including
    the unnamed/reserved stretches of the payload) is carried over unmodified from
    `data`, which must be a real, complete .cf file to use as the base.
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
