"""
STAB -- cockpit.tab, a car's stored cockpit-view positions and gauge-needle
calibration. Same underlying container format as the already-solved camera.tab
(broadcast camera definitions): a small header, then fixed-size named records.

Header (0SER payload, first 12 bytes): recordCount, fieldsPerRecord, reserved
(3 x int32). cockpit.tab always has recordCount=6, fieldsPerRecord=4 (a name
"field" plus 3 numeric fields per record).

Between the header and the first record sits a short block of int32 values
(33, 42, 51, 60 in every sample seen) whose meaning isn't confirmed -- they
line up suspiciously well with the byte offsets of a record's field1/field2/
field3 slots and the record length derived independently below, but that's
an unconfirmed coincidence, not a verified fact, so build() below never tries
to regenerate this block: it's carried over byte-for-byte from a real base
file, the same "patch only what's named, preserve the rest" approach cf.py
uses for its own reserved/unidentified byte ranges.

RECORD LAYOUT (60 bytes each, confirmed byte-exact against every record in a
real cockpit.tab by reconstructing all 6 and diffing against the original):

    [0x00:0x07]  name, ASCII, left-justified, space-padded to 7 bytes
                 (e.g. "camera ", "rpm pt ", "mph dat")
    [0x07:0x21]  26 bytes, always zero in every sample -- reserved/unused
    [0x21:0x28]  field 1: number right-justified in 6 chars + 1 trailing
                 space, e.g. " -.408 ", "  -196 "
    [0x28:0x2A]  2 bytes, always zero
    [0x2A:0x30]  field 2: number centered in 6 chars (extra padding goes to
                 the right on an odd remainder), e.g. " .906 ", "  70  "
    [0x30:0x33]  3 bytes, always zero
    [0x33:0x3C]  field 3: a single leading space + the number, left-justified,
                 zero-padded to the end of the record (9 bytes of room)

NUMBER FORMAT: an integral value (e.g. 7000.0) is printed as a plain integer
("7000", no decimal point). Any other value is printed with exactly 3 decimal
digits, then a leading "0" before the decimal point is dropped (".906" not
"0.906", "-.408" not "-0.408"). Confirmed against all 6 records of a real
cockpit.tab (every "pt"/"camera"/"wheel" position uses the 3-decimal form,
every "dat" calibration value happens to be integral in the one sample seen).

RECORD SEMANTICS for cockpit.tab specifically (car-local coordinates, same
space as the car's own .mod meshes):

    camera   -- the static cockpit-view camera's eye position (x, y, z).
    wheel    -- the steering wheel's position (x, y, z). Confirmed correct by
                rendering it and checking against the real game.
    rpm pt   -- the tachometer needle's pivot point (x, y, z).
    mph pt   -- the speedometer needle's pivot point (x, y, z).
    rpm dat  -- INFERRED, not independently confirmed the way `wheel` was:
                (angle_at_0rpm_deg, angle_at_max_deg, max_rpm) -- the needle's
                rotation range mapped onto a 0..max_rpm reading.
    mph dat  -- same shape as rpm dat: (angle_at_0mph_deg, angle_at_max_deg,
                max_mph).
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import envelope

TAG = b"BATS"
VERSION = 0

HEADER_SIZE = 12
RECORD_SIZE = 60
NAME_FIELD_SIZE = 7
FIELD1_OFFSET = 0x21  # 33
FIELD2_OFFSET = 0x2A  # 42
FIELD3_OFFSET = 0x33  # 51

RECORD_NAMES = ["camera", "wheel", "rpm pt", "mph pt", "rpm dat", "mph dat"]

RECORD_INFO: dict[str, str] = {
    "camera": "static cockpit-view camera eye position (x y z)",
    "wheel": "steering wheel position (x y z)",
    "rpm pt": "tachometer needle pivot point (x y z)",
    "mph pt": "speedometer needle pivot point (x y z)",
    "rpm dat": "tach calibration (inferred): angle_at_0rpm_deg angle_at_max_deg max_rpm",
    "mph dat": "speedo calibration (inferred): angle_at_0mph_deg angle_at_max_deg max_mph",
}


def _format_number(v: float) -> str:
    if v == int(v):
        return str(int(v))
    s = f"{v:.3f}"
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s


def _build_record(name: str, values: tuple[float, float, float]) -> bytes:
    if len(name) > NAME_FIELD_SIZE:
        raise ValueError(f"record name {name!r} is longer than {NAME_FIELD_SIZE} chars")
    rec = bytearray(RECORD_SIZE)
    rec[0:NAME_FIELD_SIZE] = name.ljust(NAME_FIELD_SIZE).encode("ascii")

    f1 = _format_number(values[0])
    if len(f1) > 6:
        raise ValueError(f"{name!r} field 1 ({f1!r}) doesn't fit in 6 characters")
    f1s = f1.rjust(6) + " "
    rec[FIELD1_OFFSET:FIELD1_OFFSET + 7] = f1s.encode("ascii")

    f2 = _format_number(values[1])
    if len(f2) > 6:
        raise ValueError(f"{name!r} field 2 ({f2!r}) doesn't fit in 6 characters")
    pad = 6 - len(f2)
    left = pad // 2
    f2s = " " * left + f2 + " " * (pad - left)
    rec[FIELD2_OFFSET:FIELD2_OFFSET + 6] = f2s.encode("ascii")

    f3 = " " + _format_number(values[2])
    if len(f3) > RECORD_SIZE - FIELD3_OFFSET:
        raise ValueError(f"{name!r} field 3 ({f3!r}) doesn't fit in the record")
    f3b = f3.encode("ascii")
    rec[FIELD3_OFFSET:FIELD3_OFFSET + len(f3b)] = f3b

    return bytes(rec)


def parse(data: bytes) -> dict[str, tuple[float, float, float]]:
    """Parse a standalone cockpit.tab file's bytes (0SER envelope included)."""
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .tab/STAB file: tag {env.tag!r}, expected {TAG!r}")
    payload = env.payload
    rec_count, fields_per_record, _reserved = struct.unpack_from("<3i", payload, 0)
    if fields_per_record != 4:
        raise ValueError(f"unexpected fieldsPerRecord {fields_per_record} (expected 4)")

    text = payload[HEADER_SIZE:]
    tokens = [t for t in text.split(b"\x00") if t.strip()]
    tokens = [t.decode("ascii", errors="replace").strip() for t in tokens]
    # A short run of marker bytes (see module docstring) precedes the real
    # records -- skip anything before the first token that looks like a real
    # record name rather than a stray single character or bare number.
    start = 0
    while start < len(tokens) and (
        len(tokens[start]) <= 1 or tokens[start].lstrip("-.").replace(".", "", 1).isdigit()
    ):
        start += 1
    tokens = tokens[start:]

    records: dict[str, tuple[float, float, float]] = {}
    i = 0
    while i + 4 <= len(tokens) and len(records) < rec_count:
        name = tokens[i]
        try:
            vals = tuple(float(v) for v in tokens[i + 1:i + 4])
        except ValueError:
            break
        records[name] = vals
        i += 4
    return records


def build(data: bytes, records: dict[str, tuple[float, float, float]]) -> bytes:
    """Return a copy of a real cockpit.tab file's bytes with named records
    overwritten. Only the records present in `records` are changed -- every
    other byte, including any record not mentioned and the unidentified
    marker block before the first record, is carried over unmodified from
    `data`, which must be a real, complete cockpit.tab to use as a base.
    """
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .tab/STAB file: tag {env.tag!r}, expected {TAG!r}")
    payload = bytearray(env.payload)
    for name, values in records.items():
        marker = name.ljust(NAME_FIELD_SIZE).encode("ascii")
        off = payload.find(marker, HEADER_SIZE)
        if off == -1:
            raise KeyError(f"record {name!r} not found in this cockpit.tab -- can't add new records, only edit existing ones")
        payload[off:off + RECORD_SIZE] = _build_record(name, values)
    return envelope.build(env.tag, env.version, bytes(payload))


def parse_file(path: str | Path) -> dict[str, tuple[float, float, float]]:
    return parse(Path(path).read_bytes())


def to_text(records: dict[str, tuple[float, float, float]]) -> str:
    """Tab-separated `name<TAB>x<TAB>y<TAB>z` lines, one per record, with a
    comment header explaining what each record controls -- record names like
    "rpm pt" contain a literal space, so fields are tab-separated rather than
    whitespace-separated to keep the name unambiguous.
    """
    lines = ["# cockpit.tab -- see vrmod/cockpit_tab.py for field meanings"]
    for name in RECORD_NAMES:
        if name in RECORD_INFO:
            lines.append(f"#   {name}: {RECORD_INFO[name]}")
    for name in RECORD_NAMES:
        if name not in records:
            continue
        x, y, z = records[name]
        lines.append(f"{name}\t{x}\t{y}\t{z}")
    for name, (x, y, z) in records.items():
        if name not in RECORD_NAMES:
            lines.append(f"{name}\t{x}\t{y}\t{z}")
    return "\n".join(lines) + "\n"


def parse_text(text: str) -> dict[str, tuple[float, float, float]]:
    """Parse `name<TAB>x<TAB>y<TAB>z` lines (as produced by to_text) back into
    a records dict. Unrecognized field names are accepted as-is (a car's
    cockpit.tab could in principle carry different record names), but a line
    that isn't exactly 4 tab-separated fields raises immediately.
    """
    records = {}
    for line in text.splitlines():
        line = line.strip("\r\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            raise ValueError(f"expected name<TAB>x<TAB>y<TAB>z, got {line!r}")
        name, x, y, z = parts
        records[name.strip()] = (float(x), float(y), float(z))
    return records
