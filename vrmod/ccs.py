"""`.ccs` / `.csu` — a saved CAR SETUP.

Read by `CarFileLoadSetupRes` in `race.exe`, which checks version 2 and a size of
exactly 0x8c and then copies all 35 dwords straight into a `CarSetupData`. So
field N of the file is offset N*4 of that struct, with no reordering.

THE VALUES ARE SLIDER POSITIONS, NOT PHYSICAL QUANTITIES. `CarFileCombine`
consumes each one as `lerp(min, max, value)` against a min/max pair in the car's
own `.cf` — see RANGES below. A setup is therefore meaningless without the car it
was made for: the same 0.5 is a different spring rate on a different `.cf`. Use
resolve() to turn a setup into real numbers.

Two containers, one payload:

    .ccs   an archive member, `0SER` envelope, tag `0SCC`, version 2, 140 bytes
    .csu   a saved setup on disk, UNWRAPPED: the same 140 bytes, then
           int32 version(=1), int32 size(=212), then 64 bytes of description

The full write-up, including how the field list was confirmed three independent
ways, is in docs/reference/file-formats.md §4.4.
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import envelope

TAG = b"0SCC"
VERSION = 2
COUNT = 35
PAYLOAD_SIZE = COUNT * 4          # 0x8c, which the loader checks exactly

CSU_VERSION = 1
CSU_SIZE = 212
CSU_DESC = CSU_SIZE - PAYLOAD_SIZE - 8      # 64 bytes, blank in a default save

# name -> (payload offset, "f" float32 or "i" int32)
#
# The five ui_graph_* fields are NOT physics. CarFileCombine never reads them and
# the game never exports them; the only code that touches them is the garage's
# shock-curve renderer. They do vary between shipped tracks, so they are live
# data, but changing one cannot alter how a car behaves.
FIELD_MAP: dict[str, tuple[int, str]] = {
    "final_drive":      (0x00, "f"),
    "drivetrain_scale": (0x04, "f"),   # 1.0 in every shipped file
    "brake_bias":       (0x08, "f"),   # shown as (v - 0.5) * 100 with an F/R suffix
    "ui_graph_3":       (0x0C, "f"),
    "fbump":            (0x10, "f"),
    "ui_graph_5":       (0x14, "f"),
    "rbump":            (0x18, "f"),
    "ui_graph_7":       (0x1C, "f"),
    "frebound":         (0x20, "f"),
    "ui_graph_9":       (0x24, "f"),
    "rrebound":         (0x28, "f"),
    "ui_graph_11":      (0x2C, "f"),
    "fsway":            (0x30, "f"),   # anti-roll
    "rsway":            (0x34, "f"),
    "fsprings":         (0x38, "f"),
    "rsprings":         (0x3C, "f"),
    "fheight":          (0x40, "f"),   # ride height
    "rheight":          (0x44, "f"),
    "fspoiler":         (0x48, "f"),
    "rspoiler":         (0x4C, "f"),
    "gear1":            (0x50, "f"),
    "gear2":            (0x54, "f"),
    "gear3":            (0x58, "f"),
    "gear4":            (0x5C, "f"),
    "gear5":            (0x60, "f"),
    "gear6":            (0x64, "f"),
    "gear7_unused":     (0x68, "f"),   # 0.0 everywhere; nothing ships 7 gears
    "unknown_ratio":    (0x6C, "f"),   # 2.66 everywhere; NOT the displayed final drive
    "aero_kit":         (0x70, "i"),   # 0 adjustable, 1 low drag, 2 high downforce
    "fuel_load":        (0x74, "f"),
    "fcamber":          (0x78, "f"),
    "rcamber":          (0x7C, "f"),
    "ftoe":             (0x80, "f"),
    "rtoe":             (0x84, "f"),
    "wheel_lock":       (0x88, "f"),
}

# setup field -> the pair of .cf fields it interpolates between
RANGES: dict[str, tuple[str, str]] = {
    "final_drive": ("rear_end_ratio1", "rear_end_ratio2"),
    "fbump":     ("fbump1", "fbump2"),        "rbump":     ("rbump1", "rbump2"),
    "frebound":  ("frebound1", "frebound2"),  "rrebound":  ("rrebound1", "rrebound2"),
    "fsway":     ("fsway1", "fsway2"),        "rsway":     ("rsway1", "rsway2"),
    "fsprings":  ("fsprings1", "fsprings2"),  "rsprings":  ("rsprings1", "rsprings2"),
    "fheight":   ("fground_clearance1", "fground_clearance2"),
    "rheight":   ("rground_clearance1", "rground_clearance2"),
    "fspoiler":  ("fspoiler1", "fspoiler2"),  "rspoiler":  ("rspoiler1", "rspoiler2"),
    "fcamber":   ("fcamber1", "fcamber2"),    "rcamber":   ("rcamber1", "rcamber2"),
    "ftoe":      ("ftoe1", "ftoe2"),          "rtoe":      ("rtoe1", "rtoe2"),
}

# setup field -> the single .cf field it scales
SCALED: dict[str, str] = {"wheel_lock": "wheel_lock", "fuel_load": "fuel_capacity"}

AERO_KIT = {0: "adjustable", 1: "low drag", 2: "high downforce"}


class CcsError(ValueError):
    pass


def _payload(data: bytes) -> bytes:
    """The 140-byte setup payload, from either container."""
    if data[:4] == envelope.MAGIC:
        env = envelope.parse(data)
        if env.tag != TAG:
            raise CcsError(f"not a .ccs file: tag {env.tag!r}, expected {TAG!r}")
        body = env.payload
    else:
        body = data                       # a .csu, which carries no envelope
    if len(body) < PAYLOAD_SIZE:
        raise CcsError(f"setup payload is {len(body)} bytes, need {PAYLOAD_SIZE}")
    return body[:PAYLOAD_SIZE]


def parse(data: bytes) -> dict[str, float]:
    """Parse a `.ccs` or a `.csu` — the payload is identical in both."""
    body = _payload(data)
    out: dict[str, float] = {}
    for name, (off, kind) in FIELD_MAP.items():
        out[name] = struct.unpack_from("<f" if kind == "f" else "<i", body, off)[0]
    return out


def build(data: bytes, values: dict[str, float]) -> bytes:
    """A copy of a real setup file with named fields overwritten.

    Only the named fields change; every other byte — the container, and a .csu's
    version, size and description tail — is carried through from `data`, which
    must be a real, complete setup file to use as the base.
    """
    enveloped = data[:4] == envelope.MAGIC
    env = envelope.parse(data) if enveloped else None
    if enveloped and env.tag != TAG:
        raise CcsError(f"not a .ccs file: tag {env.tag!r}, expected {TAG!r}")
    body = bytearray(env.payload if enveloped else data)
    for name, value in values.items():
        if name not in FIELD_MAP:
            raise KeyError(f"unknown setup field: {name!r}")
        off, kind = FIELD_MAP[name]
        struct.pack_into("<f" if kind == "f" else "<i", body, off,
                         float(value) if kind == "f" else int(value))
    return envelope.build(env.tag, env.version, bytes(body)) if enveloped else bytes(body)


def parse_file(path: str | Path) -> dict[str, float]:
    return parse(Path(path).read_bytes())


def resolve(values: dict[str, float], cf_values: dict[str, float]) -> dict[str, float]:
    """Slider positions -> the physical numbers the garage shows, for one car.

    Needs that car's own `.cf`: the stored value is a position between a pair of
    limits which differ car to car. Fields with no `.cf` pairing (the gears, the
    enum, the graph state) are returned unchanged.
    """
    out: dict[str, float] = {}
    for name, v in values.items():
        if name in RANGES:
            lo, hi = RANGES[name]
            if lo in cf_values and hi in cf_values:
                out[name] = cf_values[lo] + (cf_values[hi] - cf_values[lo]) * v
                continue
        if name in SCALED and SCALED[name] in cf_values:
            out[name] = v * cf_values[SCALED[name]]
            continue
        out[name] = v
    return out


def to_text(values: dict[str, float]) -> str:
    lines = []
    for name, (_, kind) in FIELD_MAP.items():
        v = values[name]
        lines.append(f"{name} {int(v) if kind == 'i' else v}")
    return "\n".join(lines) + "\n"


def parse_text(text: str) -> dict[str, float]:
    """Parse `name value` lines back into a values dict.

    An unrecognised name raises immediately, so a typo in a hand-edited file
    fails loudly rather than being silently dropped.
    """
    values: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise CcsError(f"expected 'name value', got {line!r}")
        name, raw = parts
        if name not in FIELD_MAP:
            raise KeyError(f"unknown setup field: {name!r}")
        values[name] = float(raw)
    return values


def write_file(path: str | Path, data: bytes, values: dict[str, float]) -> Path:
    p = Path(path)
    p.write_bytes(build(data, values))
    return p
