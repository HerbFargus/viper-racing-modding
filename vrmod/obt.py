"""`track.obt` -- the track's placed-object table.

A `STAB` table (§4.3): a count, then fixed-width records of NUL-padded ASCII.
Unlike `.sol` this one is fully writable -- there is no spatial index, just a
list.

```
+00  int32  recordCount
+04  int32  fieldsPerRecord   (1 in every sample)
+08  int32  reserved          (0)
+0c  64 bytes                 uninitialised padding, zeros in 13 of 19 tracks
+4c  recordCount x 257 bytes  NUL-padded ASCII, one record each
```

The record start and width are not guesses: `76 + recordCount * 257` equals the
payload length exactly for every track examined, stock and community.

Every track opens with the same three records -- the compiler's own boilerplate,
naming the files it consumed -- then the placed objects, then a literal `end`:

```
out\\track.txt
map test.map
ai test.vf
obj car 204.725693,-152.139893              <- a starting-grid slot
obj checkpoint flag 163.68,-169.75 233.45,-166.57   <- a timing gate, two points
end
```

Object kinds across the tracks on hand: `obj wobble` (463), `obj car` (104),
`obj checkpoint flag` (50). Coordinates are the ground plane in the negated
frame the surface file uses, matching `.sol` and the compiled collision mesh.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import envelope

TAG = b"BATS"
VERSION = 0
DATA_START = 76
RECORD_SIZE = 257

# The three records every track opens with. MKWORLD writes the names of its own
# inputs here; the game does not appear to care, but they are reproduced so a
# generated table looks like a compiled one.
PREAMBLE = ("out\\track.txt", "map test.map", "ai test.vf")
TERMINATOR = "end"


class ObtError(ValueError):
    pass


@dataclass
class Obt:
    records: list[str] = field(default_factory=list)
    version: int = VERSION
    # 12..76 is uninitialised in the original compiler -- zeros in most tracks,
    # heap noise in a few. Carried through on a round-trip, zeroed when built.
    padding: bytes = bytes(DATA_START - 12)

    @property
    def objects(self) -> list[str]:
        """Just the placed objects, without the boilerplate or terminator."""
        return [r for r in self.records if r.startswith("obj ")]


def parse(data: bytes) -> Obt:
    """Parse a `.obt` from a complete file or a bare payload."""
    version = VERSION
    if data[:4] == envelope.MAGIC:
        env = envelope.parse(data)
        if env.tag != TAG:
            raise ObtError(f"expected tag {TAG!r}, got {env.tag!r}")
        version, payload = env.version, env.payload
    else:
        payload = data

    if len(payload) < DATA_START:
        raise ObtError(f"payload too short to be a .obt: {len(payload)} bytes")
    count, fields_per_record, _ = struct.unpack_from("<3i", payload, 0)
    need = DATA_START + count * RECORD_SIZE
    if need != len(payload):
        raise ObtError(
            f"header says {count} records, which needs {need:,} bytes, "
            f"but the payload is {len(payload):,}")

    records = []
    for i in range(count):
        raw = payload[DATA_START + i * RECORD_SIZE: DATA_START + (i + 1) * RECORD_SIZE]
        records.append(raw.split(b"\x00")[0].decode("latin-1"))
    return Obt(records=records, version=version, padding=payload[12:DATA_START])


def build(obt: Obt) -> bytes:
    """Serialise back to complete file bytes. Round-trips byte for byte."""
    body = bytearray(struct.pack("<3i", len(obt.records), 1, 0))
    pad = obt.padding if len(obt.padding) == DATA_START - 12 else bytes(DATA_START - 12)
    body += pad
    for r in obt.records:
        encoded = r.encode("latin-1")
        if len(encoded) >= RECORD_SIZE:
            raise ObtError(f"record longer than {RECORD_SIZE - 1} bytes: {r[:40]!r}...")
        body += encoded + bytes(RECORD_SIZE - len(encoded))
    return envelope.build(TAG, obt.version, bytes(body))


def car(x: float, y: float) -> str:
    """A starting-grid slot."""
    return f"obj car {x:.6f},{y:.6f}"


def checkpoint(x1: float, y1: float, x2: float, y2: float) -> str:
    """A timing gate, given the two points its line spans."""
    return f"obj checkpoint flag {x1:.6f},{y1:.6f} {x2:.6f},{y2:.6f}"


def create(objects: list[str]) -> Obt:
    """Build a table from placed objects, adding the boilerplate and terminator."""
    return Obt(records=[*PREAMBLE, *objects, TERMINATOR])


def parse_file(path: str | Path) -> Obt:
    return parse(Path(path).read_bytes())


def write_file(path: str | Path, obt: Obt) -> Path:
    p = Path(path)
    p.write_bytes(build(obt))
    return p
