"""Read a SimCity 2000 city (.sc2), the map format Streets of SimCity drives on.

FORMAT. An IFF container: "FORM", a big-endian length, the form type "SCDH",
then chunks of (4-char id, big-endian u32 length, data). The ones that shape the
ground and what stands on it:

    ALTM   128x128 big-endian u16, uncompressed. Low 5 bits: ground altitude
           level. Bits 5-9: water altitude level.
    XTER   terrain per tile: flat, a slope or corner raising some of the tile's
           corners by one level, high ground, or the water variants of those
    XBLD   what stands on the tile, as a SimCity 2000 tile id (roads 29-43,
           trees 6-12, buildings from 112 up ...)
    XZON   zone in the low nibble; the high nibble marks which corner of a
           multi-tile building this tile is (0b1111 = a 1x1 building)
    XUND   underground (pipes, subway)
    XBIT   per-tile flags; 0b0010 turns bridges, runways and ramps, 0b0100 water
    MISC   city-wide values; the view rotation is the big-endian u32 at 0x08

Every chunk except ALTM and CNAM is run-length encoded: a byte n < 128 means
"n literal bytes follow", n >= 128 means "repeat the next byte n - 127 times".

AXES. A decompressed grid is NOT laid out row by row the way it looks. Stream
position n belongs to tile x = n // 128, y = n % 128 -- the first coordinate
changes slowest. Reading it the other way round mirrors the city across its
diagonal, which a symmetric arena will not reveal and a real city will.

References, read for the facts only: the SimCity 2000 file notes at
http://djm.cc/simcity-2000-info.txt, and alekasm/SC2KRender, a C++ viewer that
confirmed the axis order, the ALTM bit split and the XZON corner nibble. That
project has no licence, so nothing here is copied from it.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

SIZE = 128
TILE_M = 16.0                 # a SimCity 2000 tile, in metres (see README)

# The RLE-compressed per-tile chunks this reader expands into grids.
GRID_CHUNKS = ("XTER", "XBLD", "XZON", "XUND", "XBIT")


def unrle(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        n = data[i]
        i += 1
        if n < 128:
            out += data[i:i + n]
            i += n
        else:
            out += bytes([data[i]]) * (n - 127)
            i += 1
    return bytes(out)


def chunks(blob: bytes) -> dict[str, bytes]:
    if blob[:4] != b"FORM" or blob[8:12] != b"SCDH":
        raise ValueError("not a SimCity 2000 city: expected FORM/SCDH")
    out: dict[str, bytes] = {}
    i = 12
    while i + 8 <= len(blob):
        cid = blob[i:i + 4].decode("latin-1")
        n = struct.unpack_from(">I", blob, i + 4)[0]
        out[cid] = blob[i + 8:i + 8 + n]
        i += 8 + n
    return out


@dataclass
class City:
    name: str
    rotation: int
    altitude: list[list[int]]          # [x][y], ground level 0-31
    water: list[list[int]]             # [x][y], water level 0-31
    grids: dict[str, list[list[int]]] = field(default_factory=dict)

    def tile(self, x: int, y: int) -> dict[str, int]:
        t = {"altitude": self.altitude[x][y], "water": self.water[x][y]}
        for k, g in self.grids.items():
            t[k.lower()] = g[x][y]
        return t

    def bounds(self, chunk: str = "XBLD") -> tuple[int, int, int, int]:
        """(x0, y0, x1, y1) of the tiles where `chunk` is non-zero, inclusive."""
        g = self.grids[chunk]
        pts = [(x, y) for x in range(SIZE) for y in range(SIZE) if g[x][y]]
        if not pts:
            raise ValueError(f"{chunk} is empty")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def _grid(stream: bytes, what: str) -> list[list[int]]:
    if len(stream) != SIZE * SIZE:
        raise ValueError(f"{what}: {len(stream)} tiles, expected {SIZE * SIZE}")
    return [[stream[x * SIZE + y] for y in range(SIZE)] for x in range(SIZE)]


def read(path: str | Path) -> City:
    c = chunks(Path(path).read_bytes())
    name = c["CNAM"].split(b"\0", 1)[0].replace(b"\x1f", b"").decode("latin-1")
    misc = unrle(c["MISC"])
    rotation = struct.unpack_from(">I", misc, 0x08)[0]
    raw = struct.unpack(f">{SIZE * SIZE}H", c["ALTM"])
    altitude = [[raw[x * SIZE + y] & 0x1F for y in range(SIZE)] for x in range(SIZE)]
    water = [[(raw[x * SIZE + y] >> 5) & 0x1F for y in range(SIZE)] for x in range(SIZE)]
    grids = {k: _grid(unrle(c[k]), k) for k in GRID_CHUNKS}
    return City(name=name, rotation=rotation, altitude=altitude, water=water, grids=grids)
