"""`track.bsp` -- the track's world-bounds record.

Despite the name this is not a BSP tree. It is a **fixed 108-byte structure**
holding a world bounding box and a small set of plane normals, and it is the same
108 bytes in every shipped track. The collision tree everyone means when they say
"BSP" lives in `track.bpp` (see `bpp.py`); this file sits beside it.

How that was established, since "it's a constant" is a claim worth showing:

  - All 8 stock tracks and a freshly compiled track produce a 108-byte payload,
    regardless of track size or complexity -- dundas has four times bemidji's
    collision geometry and an identical `.bsp`.
  - 7 of the 8 stock payloads are byte-identical. The eighth (heaven) differs in
    a single byte, inside the padding described below.
  - The values are all recognisable and none are track-derived: extents of
    +/-100000, an up-normal (0, 1, 0), a down-normal (0, 0, -1), and canted
    normals built from 2/sqrt(5) = 0.894427 and 1/sqrt(5) = 0.447214.

Two fields are noise rather than data:

  - **Bytes 13-15 are uninitialised.** MKWORLD never writes them. Stock tracks
    carry `03 30 00` (heaven `02 30 00`); a track compiled here came out
    `e3 e3 e3`, the repeating fill pattern of untouched heap. This module emits
    the value 7 of the 8 shipped tracks carry, on the grounds that it is the
    best-attested known-good byte sequence.
  - **The unit normals drift by 1 ULP.** A freshly compiled track has
    0.99999994 where stock has exactly 1.0, because the compiler derives the
    normal from geometry that is not perfectly axis-aligned. This module emits
    the exact values.
"""

from __future__ import annotations

import struct
from pathlib import Path

from . import envelope

TAG = b"TPSB"
VERSION = 0
SIZE = 108

# The canonical payload, taken from bemidji and matching 7 of the 8 stock tracks.
PAYLOAD = bytes.fromhex(
    "0c000000000000000000000000033000"
    "000000000000803f0000000000000080"
    "0050c3c7000000000050c3c700000000"
    "000000000050c3470050c34700000000"
    "0050c3c72ef964bf000000002ef9e43e"
    "2ef9643f000000802ef9e43e00000000"
    "00000000000080bf00000000"
)
assert len(PAYLOAD) == SIZE

# Offsets of the fields that are actually legible, for anyone checking the claim
# above or extending this later.
FIELD_COUNT = 0          # int32, always 12
PADDING = slice(13, 16)  # uninitialised; see the module docstring
EXTENT_MIN = 32          # float32, -100000
EXTENT_MAX = 52          # float32, +100000
NORMAL_UP = 20           # float32, +1
NORMAL_DOWN = 100        # float32, -1


class BspError(ValueError):
    pass


def build() -> bytes:
    """Return a complete `track.bsp`, envelope included.

    Takes no arguments, which is the whole point: nothing about this file
    depends on the track. If that ever turns out to be wrong for some track we
    have not seen, `parse()` will say so.
    """
    return envelope.build(TAG, VERSION, PAYLOAD)


def parse(data: bytes) -> bytes:
    """Validate a `.bsp` and return its payload.

    Accepts either a complete file or a bare payload. Raises BspError when the
    payload is not the expected size, and returns normally -- but with a
    difference the caller can inspect via `differences()` -- when it is the right
    size but not the canonical content.
    """
    payload = envelope.parse(data).payload if data[:4] == envelope.MAGIC else data
    if len(payload) != SIZE:
        raise BspError(f"expected a {SIZE}-byte payload, got {len(payload)}")
    return payload


def differences(payload: bytes, *, ignore_noise: bool = True) -> list[int]:
    """Byte offsets where `payload` departs from the canonical record.

    With `ignore_noise` (the default) the uninitialised padding and 1-ULP normal
    drift described in the module docstring are not reported, so a clean result
    means "equivalent", not "identical". Pass False to see every byte.
    """
    diffs = [i for i in range(SIZE) if payload[i] != PAYLOAD[i]]
    if not ignore_noise:
        return diffs

    noise = set(range(PADDING.start, PADDING.stop))
    for off in (NORMAL_UP, NORMAL_DOWN):
        got = struct.unpack_from("<f", payload, off)[0]
        want = struct.unpack_from("<f", PAYLOAD, off)[0]
        if abs(abs(got) - abs(want)) <= 2e-7 and (got > 0) == (want > 0):
            noise.update(range(off, off + 4))
    return [i for i in diffs if i not in noise]


def write_file(path: str | Path) -> Path:
    p = Path(path)
    p.write_bytes(build())
    return p
