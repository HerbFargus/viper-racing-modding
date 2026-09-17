"""`camera.tab` — a track's broadcast (TV) cameras.

The same `STAB` container as `cockpit.tab`, but with SEVEN fields per record and a
leading type name. Read by `load_tv_cameras()` in `race.exe`, which parses it as a
generic StringTable: column 0 is matched case-insensitively against `fixed`, `pan`,
`pan_zoom` and `chase` (anything else is a `LogPanic`), and columns 1–6 are `atof`'d
into a 28-byte `TVCamera` record.

    +0x00  int32   type: 0 fixed, 1 pan, 2 pan_zoom, 3 chase
    +0x04  float   x        position, in the GAME frame, NOT flipped
    +0x08  float   y        height
    +0x0c  float   z
    +0x10  float   a1       fixed: axis-angle rotation, degrees
    +0x14  float   a2       pan/pan_zoom: a1 = gain, a2 = distance threshold
    +0x18  float   a3       unread for pan/pan_zoom

THE ROTATION IS AXIS-ANGLE, NOT EULER. `update_camera` scales all three by pi/180 and
builds a Rodrigues matrix, so the triple's direction is the rotation axis and its
magnitude in radians is the angle. **Forward is column 2 of that matrix**, which for the
dominant near-vertical case reduces to `(sin yaw, 0, cos yaw)` — a compass heading from
`+Z` toward `+X`. Confirmed three ways: from the disassembly, against all ten shipped
`fixed` cameras (median 6.7 m from the racing line), and in game.

TWO TRAPS.

* The position is in the **unflipped** game frame, unlike `obj checkpoint` and `obj car`
  in the `.obt` — which is the same STAB family — where coordinates are negated.
* The runtime array is a **fixed 32 slots** (`TVCamera[32]` at 0x520cb8) and the loader
  never bounds-checks against it, trusting `StringTableNumRows`. More than 32 records
  would overrun it. nfield ships the most of any retail track, at 20.

Also: camera selection scans from index 1, so **slot 0 is never auto-selected**. Every
shipped track puts a `fixed` camera there.

See docs/reference/file-formats.md §4.3 for the full write-up.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

from . import envelope

TAG = b"BATS"
VERSION = 0

HEADER_SIZE = 76            # 19 int32: count, fields, 7 offsets, 9 zero, record size
FIELD_OFFSETS = (0, 13, 22, 31, 40, 49, 58)
FIELDS = len(FIELD_OFFSETS)
NAME_WIDTH = 13
NUM_WIDTH = 9
RECORD_SIZE = FIELD_OFFSETS[-1] + NUM_WIDTH      # 67
SIZE_AT = 72                # where the header stores the record size

MAX_CAMERAS = 32            # TVCamera[32]; the loader does not check
TYPES = ("fixed", "pan", "pan_zoom", "chase")


class CamTabError(ValueError):
    pass


@dataclass
class Camera:
    """One camera. `a1..a3` are an axis-angle rotation in degrees for `fixed`,
    and (gain, threshold, unused) for `pan`/`pan_zoom`."""
    type: str
    x: float
    y: float
    z: float
    a1: float = 0.0
    a2: float = 0.0
    a3: float = 0.0

    @property
    def forward(self) -> tuple[float, float, float]:
        """The unit vector this camera looks along — column 2 of its rotation."""
        return forward(self.a1, self.a2, self.a3)


def _payload(data: bytes) -> bytes:
    return envelope.parse(data).payload if data[:4] == envelope.MAGIC else data


def parse_raw(data: bytes) -> list[list[str]]:
    """Every record as its stored text, UNTRIMMED.

    The padding is part of the bytes: retail spells the same value several ways
    (' 32  ' carries two trailing spaces, limbo writes ' .2 ' not ' 0.2 '), so
    stripping here would make build_raw() unable to reproduce a shipped file.
    parse() trims, because it is converting to floats anyway.
    """
    pay = _payload(data)
    n, fields = struct.unpack_from("<2i", pay, 0)
    size = struct.unpack_from("<i", pay, SIZE_AT)[0]
    if fields != FIELDS:
        raise CamTabError(f"{fields} fields per record, expected {FIELDS}")
    if HEADER_SIZE + n * size != len(pay):
        raise CamTabError(
            f"header says {n} records of {size} bytes, which needs "
            f"{HEADER_SIZE + n * size}, but the payload is {len(pay)}")
    widths = [(FIELD_OFFSETS[i + 1] - FIELD_OFFSETS[i]) if i + 1 < FIELDS
              else size - FIELD_OFFSETS[i] for i in range(FIELDS)]
    rows = []
    for r in range(n):
        base = HEADER_SIZE + r * size
        rows.append([pay[base + o: base + o + w].split(b"\x00")[0].decode("latin-1")
                     for o, w in zip(FIELD_OFFSETS, widths)])
    return rows


def build_raw(rows: list[list[str]]) -> bytes:
    """A payload from stored text. Round-trips every shipped file byte-identically."""
    head = bytearray(HEADER_SIZE)
    struct.pack_into("<2i", head, 0, len(rows), FIELDS)
    for i, off in enumerate(FIELD_OFFSETS):
        struct.pack_into("<i", head, 8 + 4 * i, off)
    struct.pack_into("<i", head, SIZE_AT, RECORD_SIZE)
    body = bytearray()
    for row in rows:
        rec = bytearray(RECORD_SIZE)
        for i, (off, text) in enumerate(zip(FIELD_OFFSETS, row)):
            width = NAME_WIDTH if i == 0 else NUM_WIDTH
            enc = text.encode("latin-1")[:width]
            rec[off:off + len(enc)] = enc
        body += rec
    return bytes(head) + bytes(body)


def parse(data: bytes) -> list[Camera]:
    out = []
    for row in parse_raw(data):
        kind = row[0].strip().lower()
        if kind not in TYPES:
            raise CamTabError(
                f"unknown camera type {row[0].strip()!r}; the engine LogPanics on this")
        out.append(Camera(kind, *(float(v.strip() or 0) for v in row[1:])))
    return out


def _num(v: float) -> str:
    """Stock style: the value wrapped in spaces, e.g. ' 194 ', ' -1.4 '."""
    if abs(v) < 1e-9:
        v = 0.0
    return f" {round(v, 4):g} "


def build(cameras: list[Camera]) -> bytes:
    """A complete payload from Camera objects, in a canonical number format.

    Note this is NOT byte-identical to a shipped file even for identical values:
    retail formatting is inconsistent (' 32  ' carries two trailing spaces, limbo
    writes ' .2 ' rather than ' 0.2 '). Use build_raw() to reproduce bytes exactly.
    """
    if len(cameras) > MAX_CAMERAS:
        raise CamTabError(
            f"{len(cameras)} cameras; the runtime array holds {MAX_CAMERAS} and the "
            f"loader does not bounds-check, so the rest would overrun it")
    rows = []
    for c in cameras:
        if c.type.lower() not in TYPES:
            raise CamTabError(f"unknown camera type {c.type!r}")
        rows.append([c.type.upper(), _num(c.x), _num(c.y), _num(c.z),
                     _num(c.a1), _num(c.a2), _num(c.a3)])
    return build_raw(rows)


def parse_file(path: str | Path) -> list[Camera]:
    return parse(Path(path).read_bytes())


def rotation(a1: float, a2: float, a3: float) -> list[list[float]]:
    """The Rodrigues matrix for an axis-angle triple in degrees."""
    n = math.sqrt(a1 * a1 + a2 * a2 + a3 * a3)
    if n < 1e-9:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    ang = math.radians(n)
    kx, ky, kz = a1 / n, a2 / n, a3 / n
    c, s, t = math.cos(ang), math.sin(ang), 1.0 - math.cos(ang)
    return [[t*kx*kx + c,    t*kx*ky - s*kz, t*kx*kz + s*ky],
            [t*kx*ky + s*kz, t*ky*ky + c,    t*ky*kz - s*kx],
            [t*kx*kz - s*ky, t*ky*kz + s*kx, t*kz*kz + c]]


def forward(a1: float, a2: float, a3: float) -> tuple[float, float, float]:
    """The direction a camera with this rotation looks: column 2 of its matrix."""
    m = rotation(a1, a2, a3)
    return (m[0][2], m[1][2], m[2][2])


def aim(position, target) -> tuple[float, float, float]:
    """The rotation that points a camera at `target`, both in the game frame.

    Returns the MINIMAL rotation taking a camera's rest direction (+Z, the
    identity case) onto the line of sight, with no roll about it. A direction
    does not determine a rotation uniquely -- any amount of roll about the view
    axis aims identically -- and the game's own free-roam camera produces
    rotations carrying some roll, so its numbers differ from these while looking
    at the same thing. Verified against free-roam readings at three pitches.

    Height is honoured: pass a target above or below and the camera tilts.
    """
    dx = target[0] - position[0]
    dy = target[1] - position[1]
    dz = target[2] - position[2]
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n < 1e-9:
        raise CamTabError("camera and target are at the same point")
    dx, dy, dz = dx / n, dy / n, dz / n
    # the rotation taking (0,0,1) to d: axis = (0,0,1) x d, angle = acos(d.z)
    ax, ay = -dy, dx
    span = math.hypot(ax, ay)
    ang = math.degrees(math.acos(max(-1.0, min(1.0, dz))))
    if span < 1e-9:                      # already along +Z, or straight behind
        return (0.0, 0.0, 0.0) if dz > 0 else (0.0, 180.0, 0.0)
    ax, ay = ax / span, ay / span
    return (round(ax * ang, 1), round(ay * ang, 1), 0.0)


def to_text(cameras: list[Camera]) -> str:
    lines = []
    for c in cameras:
        lines.append(f"{c.type} {c.x:g} {c.y:g} {c.z:g} {c.a1:g} {c.a2:g} {c.a3:g}")
    return "\n".join(lines) + "\n"


def parse_text(text: str) -> list[Camera]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        parts = line.split()
        if len(parts) != FIELDS:
            raise CamTabError(f"expected {FIELDS} fields, got {len(parts)}: {line!r}")
        out.append(Camera(parts[0].lower(), *(float(v) for v in parts[1:])))
    return out


def build_file(path: str | Path, cameras: list[Camera]) -> Path:
    p = Path(path)
    p.write_bytes(envelope.build(TAG, VERSION, build(cameras)))
    return p
