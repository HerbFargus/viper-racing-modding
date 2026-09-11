"""`track.sol` -- the track's collision solids.

Not a mesh: an array of collision primitives (boxes, capsules and spheres), the
complement to `.bpp`'s triangle soup. Static world surfaces live in the BSP;
discrete objects live here. The layout is documented in
VIPER_RACING_FILE_FORMATS.md §4.8, read from the loader at `0x42FEE0`.

```
header          20 bytes   n_primitives, n_index, then zeros
primitives      224 each   orientation, centre, type FourCC, extents
index list      2 each     n_index * u16, primitive indices per spatial cell
tail            varies     spatial index -- see the caveat below
```

**A populated `.sol` does not need synthesising.** Barriers reach one through
MKWORLD: the surface scene file declares each as an `object(<texture>,1,0)` with
four verts and a `quad(0,1,2,3)`, and MKWORLD compiles one primitive per quad,
tail and all. 246 declared quads produced a 69,262-byte `.sol` carrying 246
primitives at version 2 -- the same MKWORLD run the pipeline already makes for
`.bsp`. See `trackgen.add_walls`; confirmed in game 2026-09-10, walls on both
sides of the track. The unsolved tail below matters only if a `.sol` ever has to
be built without MKWORLD.

**What this module can and cannot do.** It parses every field, and it rebuilds
any `.sol` it has parsed byte for byte, so solids can be read, moved, retyped or
removed. It can also synthesise the empty case from nothing.

It does not synthesise a *populated* `.sol` from nothing, because the tail is a
spatial index that has not been fully cracked. Measured behaviour, from
compiling controlled wall layouts through MKWORLD:

| layout                | prims | index | tail bytes |
|-----------------------|-------|-------|------------|
| 1 wall                | 1     | 4     | 2,472      |
| 2 walls adjacent      | 2     | 8     | 2,472      |
| 2 walls 100 m apart   | 2     | 6     | 2,600      |
| 2 walls 5000 m apart  | 2     | 8     | 3,240      |
| 10 walls in a line    | 10    | 24    | 2,472      |
| 10 walls over 500 m   | 10    | 26    | 5,928      |

Ten solids in a line occupy exactly the same tail as one solid; two solids far
apart need more. So the tail is sized by how solids are *distributed*, not how
many there are, and its first record counts primitives-per-cell rather than
primitives (10 solids spread in 2D report 16, because a solid spanning a cell
boundary is listed in both). That is consistent with an occupancy structure over
space. Until it is understood well enough to generate, `build()` refuses to
invent one and asks for the original tail back.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import envelope

TAG = b"LBOS"
HEADER_SIZE = 20
RECORD_SIZE = 224

# Type tags as they appear on disk. Like every FourCC in these formats they are
# byte-reversed, so "BOX " reads as " XOB".
BOX = b"BOX "
SPHERE = b"SPHR"
TUBE = b"TUBE"

TYPE_OFFSET = 0x34
POSITION_OFFSET = 0x24
ID_OFFSET = 0x30


class SolError(ValueError):
    pass


@dataclass
class Primitive:
    """One collision solid. `raw` is the complete 224-byte record.

    The interesting fields are surfaced as properties; everything else -- the
    serialised C++ vtable pointers, the compiled-in class defaults at +0x48 and
    +0x4c, the runtime workspace -- rides along in `raw` so a rebuild is exact.
    """

    raw: bytes

    @property
    def type(self) -> bytes:
        """The primitive's type tag, un-reversed: BOX, SPHR or TUBE."""
        return self.raw[TYPE_OFFSET:TYPE_OFFSET + 4][::-1]

    @property
    def position(self) -> tuple[float, float, float]:
        return struct.unpack_from("<3f", self.raw, POSITION_OFFSET)

    @position.setter
    def position(self, xyz: tuple[float, float, float]) -> None:
        buf = bytearray(self.raw)
        struct.pack_into("<3f", buf, POSITION_OFFSET, *xyz)
        self.raw = bytes(buf)

    @property
    def id(self) -> int:
        return struct.unpack_from("<i", self.raw, ID_OFFSET)[0]


@dataclass
class Sol:
    primitives: list[Primitive] = field(default_factory=list)
    index: list[int] = field(default_factory=list)
    tail: bytes = b""
    version: int = 2
    header_extra: bytes = bytes(12)

    @property
    def is_empty(self) -> bool:
        return not self.primitives and not self.index


def parse(data: bytes) -> Sol:
    """Parse a `.sol`, from either a complete file or a bare payload."""
    version = 2
    if data[:4] == envelope.MAGIC:
        env = envelope.parse(data)
        if env.tag != TAG:
            raise SolError(f"expected tag {TAG!r}, got {env.tag!r}")
        version, payload = env.version, env.payload
    else:
        payload = data

    if len(payload) < HEADER_SIZE:
        # The empty form is 28 zero bytes; anything shorter is not a .sol.
        raise SolError(f"payload too short to be a .sol: {len(payload)} bytes")

    n, n_index = struct.unpack_from("<2I", payload, 0)
    need = HEADER_SIZE + n * RECORD_SIZE + n_index * 2
    if need > len(payload):
        raise SolError(
            f"header says {n:,} primitives and {n_index:,} index entries, which "
            f"needs {need:,} bytes, but the payload is {len(payload):,}")

    prims = [Primitive(payload[HEADER_SIZE + i * RECORD_SIZE:
                               HEADER_SIZE + (i + 1) * RECORD_SIZE]) for i in range(n)]
    idx_at = HEADER_SIZE + n * RECORD_SIZE
    index = list(struct.unpack_from(f"<{n_index}H", payload, idx_at)) if n_index else []

    return Sol(primitives=prims, index=index, tail=payload[idx_at + n_index * 2:],
               version=version, header_extra=payload[8:HEADER_SIZE])


def build(sol: Sol) -> bytes:
    """Serialise a Sol back to complete file bytes, envelope included.

    Rebuilding a parsed `.sol` reproduces the input byte for byte. Building a
    populated `.sol` whose `tail` was not carried over from a parse raises,
    rather than emitting a file with an index that does not describe its
    contents -- see the module docstring.
    """
    if sol.is_empty and not sol.tail:
        return envelope.build(TAG, sol.version, bytes(28))

    if sol.primitives and not sol.tail:
        raise SolError(
            "cannot synthesise the spatial index tail for a populated .sol -- "
            "build from a parsed file, or use an empty .sol until the tail is "
            "understood (see the module docstring)")

    body = bytearray()
    body += struct.pack("<2I", len(sol.primitives), len(sol.index))
    body += sol.header_extra
    for p in sol.primitives:
        if len(p.raw) != RECORD_SIZE:
            raise SolError(f"primitive record must be {RECORD_SIZE} bytes, got {len(p.raw)}")
        body += p.raw
    if sol.index:
        body += struct.pack(f"<{len(sol.index)}H", *sol.index)
    body += sol.tail
    return envelope.build(TAG, sol.version, bytes(body))


def empty(version: int = 3) -> bytes:
    """A complete `.sol` with no solids.

    This is exactly what MKWORLD emits for a scene with no walls -- 28 zero
    bytes under a version-3 envelope -- and it is what a generated track uses
    until wall authoring lands.
    """
    return envelope.build(TAG, version, bytes(28))


def parse_file(path: str | Path) -> Sol:
    return parse(Path(path).read_bytes())


def write_file(path: str | Path, sol: Sol) -> Path:
    p = Path(path)
    p.write_bytes(build(sol))
    return p
