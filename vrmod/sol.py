"""`track.sol` -- the track's collision solids.

Not a mesh: an array of collision primitives (boxes, capsules and spheres), the
complement to `.bpp`'s triangle soup. Static world surfaces live in the BSP;
discrete objects live here. The layout is documented in
docs/reference/file-formats.md §4.8, read from the loader at `0x42FEE0`.

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

Solids reach the **AI**, not only the physics: an opponent met a barrier placed
across the racing line -- one that did not exist when its line was generated --
and steered around it. So `.sol` is read for obstacle avoidance at runtime, and
adding barriers or props to a track does not require regenerating its lines.

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

import math
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



# ---------------------------------------------------------------------------
# The spatial index -- the tail
#
# SOLVED, from the symbolised 1998 build. It is a QUADTREE over the XZ plane,
# and the whole of it is in `collide_object` (physics:phystask.obj):
#
#     esi = word [node + 4]                 ; child index; 0 means leaf
#     midX = (x0 + x1) / 2                  ; integer halving, truncating
#     midZ = (z0 + z1) / 2
#     queryZ <= midZ ? (queryX <= midX ? +0 : +1)
#                    : (queryX <= midX ? +2 : +3)
#
# so each node is EIGHT BYTES -- (first: u16, last: u16, child: u32) -- a leaf
# names index[first:last], and an internal node's four children are consecutive
# from `child`. The quadrant order is (-x,-z), (+x,-z), (-x,+z), (+x,+z).
#
# COORDINATES ARE INTEGER TENTHS. `collide_object`'s caller multiplies the
# query position by 10.0 and truncates, and the root box is +/-4,000,000 world
# units -- `fld [0x4db7b8]` (4000000.0) `fmul [0x4db7d4]` (10.0) -- so the tree
# spans +/-40,000,000 in those units. Halving from there is what makes the tail
# sized by how solids are DISTRIBUTED rather than how many there are, which was
# the measured behaviour nobody could explain.
#
# The structure was confirmed against the shipped files before any of this was
# written: every tail is an exact multiple of 8, every [first, last) lies inside
# the index list, `max last` equals n_index exactly on all eight tracks, and the
# child indices are spaced exactly 4 apart -- 319 of 319 gaps on bemidji, 399 of
# 399 on kenyon, with 1281 = 4*320 + 1 and 1601 = 4*400 + 1 nodes.
#
# This builder does NOT reproduce MKWORLD's tree. Like the .bpp one it does not
# need to: the shape is not observable, only the answers are.

SCALE = 10.0                  # world units -> the integers the tree indexes in
ROOT_EXTENT = 40_000_000      # +/- this, i.e. +/-4,000,000 world units
MAX_DEPTH = 24                # a leaf at this depth is ~5 world units across


def bounding_radius(prim: "Primitive") -> float:
    """A radius about the primitive's centre that contains all of it.

    Read per type from the serialised volume (see BOX_EXTENTS and tube_at):
    a BOX's three half-extents at +0x58, a TUBE's radius and half-length at
    +0x58/+0x5c (a capsule reaches radius + half-length from its centre), and a
    SPHR's radius at +0x58.

    NOT +0x38, which looks like a float field and is a runtime POINTER --
    `StaticObjectListGet` overwrites it with `ebp+0x3c` on load, so the shipped
    bytes there are 1998 heap addresses. (An earlier version read +0x5c..+0x64
    for every type. For a box that is height, length and the max -- which
    over-covers, safely -- but for a tube it is the half-length, a vtable and a
    zero, which misses the radius.)
    """
    if prim.type == BOX:
        hx, hy, hz = struct.unpack_from("<3f", prim.raw, BOX_EXTENTS)
        return math.sqrt(hx * hx + hy * hy + hz * hz)
    if prim.type == TUBE:
        r, h = struct.unpack_from("<2f", prim.raw, 0x58)
        return r + h
    return struct.unpack_from("<f", prim.raw, 0x58)[0]


def _xz_bounds(prim: "Primitive") -> tuple[float, float, float, float]:
    """A primitive's footprint in XZ, from its centre and bounding radius.

    A CIRCUMSCRIBING radius rather than the exact oriented box: it cannot
    under-cover whatever the orientation, and a broad phase that under-covers
    loses a barrier entirely. The cost is duplicate index entries.
    """
    x, _y, z = prim.position
    r = bounding_radius(prim)
    return (x - r, z - r, x + r, z + r)


def build_spatial_index(primitives, *, max_depth: int = MAX_DEPTH,
                        max_per_leaf: int = 32):
    """Build the index list and quadtree tail for a set of primitives.

    Returns `(index_list, tail_bytes)`.

    A primitive is listed in every quadrant its footprint touches, which is why
    the shipped index lists carry about 2.8 entries per primitive rather than
    one. The descent accumulates along its whole path, so a solid listed on an
    ancestor is still found from any leaf beneath it.

    CORRECT, BY THE CRITERION THAT MATTERS. Every primitive whose footprint
    covers the query point is returned -- 1,822 of 1,822 probes across the eight
    shipped tracks.

    It does NOT reproduce MKWORLD's partition, and an earlier version of this
    note reported that as "98.6% accurate". That was the wrong measure: two
    different quadtrees over the same solids put different things in the leaf at
    a given point and both can be right. Held to the same geometric test the
    SHIPPED trees score 48.5%, because they index by the true oriented footprint
    while this uses a circumscribing one.

    Which way to err is not a free choice. A broad phase must OVER-return -- the
    narrow phase (`Collide`) filters, so a surplus candidate costs a test and a
    missing one costs a barrier the car drives through.
    """
    boxes = [_xz_bounds(p) for p in primitives]
    ib = [(int(x0 * SCALE), int(z0 * SCALE), int(x1 * SCALE), int(z1 * SCALE))
          for x0, z0, x1, z1 in boxes]

    nodes: list[list] = [[0, 0, 0]]        # first, last, child
    index: list[int] = []

    def emit_leaf(node: int, ids: list[int]) -> None:
        nodes[node][0] = len(index)
        index.extend(ids)
        nodes[node][1] = len(index)

    def build(node: int, ids: list[int], x0: int, z0: int, x1: int, z1: int,
              depth: int) -> None:
        if not ids:
            return
        # Enforced DURING the recursion, not on the finished list. Checking the
        # u16 limit at the end lets a runaway build exhaust memory first, which
        # it did -- a MemoryError twenty-one frames deep. The .bpp builder has
        # the same guard for the same reason: a depth cap alone does not bound
        # the work, because a bad split branches wide rather than deep.
        if len(index) > 0xFFFF:
            raise SolError(
                f"index passed {len(index):,} entries while building, and the "
                f"field is u16 -- the footprints are duplicating into too many "
                f"cells. Raise max_per_leaf, or lower max_depth")
        if len(ids) <= max_per_leaf or depth >= max_depth:
            emit_leaf(node, ids)
            return

        mx, mz = (x0 + x1) // 2, (z0 + z1) // 2
        quads = [(x0, z0, mx, mz), (mx, z0, x1, mz),
                 (x0, mz, mx, z1), (mx, mz, x1, z1)]
        buckets: list[list[int]] = [[], [], [], []]
        for i in ids:
            bx0, bz0, bx1, bz1 = ib[i]
            for q, (qx0, qz0, qx1, qz1) in enumerate(quads):
                if bx0 <= qx1 and bx1 >= qx0 and bz0 <= qz1 and bz1 >= qz0:
                    buckets[q].append(i)

        # Nothing separated: a primitive spans the whole node, so halving will
        # never divide it. Keep it here rather than recurse forever.
        if all(len(b) == len(ids) for b in buckets):
            emit_leaf(node, ids)
            return

        first_child = len(nodes)
        nodes[node][2] = first_child
        nodes.extend([[0, 0, 0] for _ in range(4)])
        for q in range(4):
            build(first_child + q, buckets[q], *quads[q], depth + 1)

    build(0, list(range(len(primitives))),
          -ROOT_EXTENT, -ROOT_EXTENT, ROOT_EXTENT, ROOT_EXTENT, 0)

    if len(index) > 0xFFFF:
        raise SolError(f"{len(index):,} index entries; the field is u16")
    tail = bytearray()
    for first, last, child in nodes:
        tail += struct.pack("<HHI", first, last, child)
    return index, bytes(tail)


def find(sol: "Sol", x: float, z: float) -> list[int]:
    """The game's own descent: which primitives sit at (x, z).

    Mirrors `collide_object` exactly, so a built tree can be checked against the
    tree it replaced.
    """
    qx, qz = int(x * SCALE), int(z * SCALE)
    tail = sol.tail
    x0 = z0 = -ROOT_EXTENT
    x1 = z1 = ROOT_EXTENT
    node = 0
    out: list[int] = []
    for _ in range(64):
        first, last, child = struct.unpack_from("<HHI", tail, node * 8)
        # EVERY node on the path contributes, not just the leaf. collide_object
        # reads first/last at the current node and only then descends, so a
        # solid too big to fit a child is parked on the ancestor and found by
        # every query passing through it. Returning the leaf alone finds a
        # primitive's own centre only 190 times in 300.
        out.extend(sol.index[first:last])
        if not child:
            return out
        mx, mz = (x0 + x1) // 2, (z0 + z1) // 2
        if qz <= mz:
            z1 = mz
            if qx <= mx:
                x1, node = mx, child
            else:
                x0, node = mx, child + 1
        else:
            z0 = mz
            if qx <= mx:
                x1, node = mx, child + 2
            else:
                x0, node = mx, child + 3
    raise SolError("descent did not terminate -- the tree has a cycle")



# A BOX is a serialised BoxVolume from +0x3c. Its constructor (0x433990) takes
# three half-extents and also stores the LARGEST of them, so in the file:
#
#   +0x58 +0x5c +0x60   half-extents along local x, y, z
#   +0x64               the max of the three -- every stock box, no exception
#
# which is why a wall's half length "appears twice": along is its longest side.
BOX_EXTENTS = 0x58


def _pack_box_extents(raw: bytearray, hx: float, hy: float, hz: float) -> None:
    if min(hx, hy, hz) <= 0.0:
        raise SolError(f"box half-extents {hx}, {hy}, {hz} must all be positive")
    struct.pack_into("<4f", raw, BOX_EXTENTS, hx, hy, hz, max(hx, hy, hz))


def box_from_segment(template: "Primitive", a, b, *, height: float,
                     thickness: float = 0.1) -> "Primitive":
    """A wall BOX spanning `a` to `b`, built by patching a shipped record.

    Everything this format needs that nobody has decoded -- the serialised C++
    vtable pointers, the class defaults at +0x48 and +0x4c, the runtime
    workspace -- is carried over from `template` untouched. Only the fields whose
    meaning is established get written: the orientation at +0x00, the centre at
    +0x24, and the half-extents at +0x58 (see BOX_EXTENTS).

    CONFIRMED IN GAME 2026-09-11: a generated track carrying 148 of these stops
    the car, on both sides of the road, from a `.sol` MKWORLD never touched.

    ONE OPEN FAULT. That same session panicked on EXIT with "Memory still
    allocated: 2912084 bytes" -- the build's shutdown leak check. Stock bemidji
    exits clean, so it is ours. It is not the load path: `StaticObjectListGet`
    allocates nothing per primitive (its two virtual calls are `Update` and
    `SetSurfaceType`), and `StaticObjectListForget` releases the whole `.sol`
    through `ResourceForget` as one resource. Whether the walls cause it at all
    is not yet established -- the discriminating test is a generated track with
    no walls, exited the same way.

    THE CONVENTIONS, read off bemidji's barrier boxes:

        row 1 of the matrix is (0, 1, 0)        -- up
        row 2 runs ALONG the wall
        row 0 is the normal, perpendicular in XZ
        half-extents, local x y z, are (half thickness, half height, half length)

    `thickness` defaults to 0.1 m, which is what stock walls are. Until the
    BoxVolume constructor was read, +0x58 was not known to be the thickness, so
    this parameter was accepted and never written, and every generated wall
    carried the template's.
    """
    import math as _math

    ax, ay, az = a
    bx, by, bz = b
    dx, dz = bx - ax, bz - az
    length = _math.hypot(dx, dz)
    if length <= 0.0:
        raise SolError("a wall segment needs two distinct ends")
    ux, uz = dx / length, dz / length

    raw = bytearray(template.raw)
    # row0 normal, row1 up, row2 along
    struct.pack_into("<9f", raw, 0x00,
                     -uz, 0.0, ux,
                     0.0, 1.0, 0.0,
                     ux, 0.0, uz)
    struct.pack_into("<3f", raw, POSITION_OFFSET,
                     (ax + bx) / 2.0, (ay + by) / 2.0 + height / 2.0,
                     (az + bz) / 2.0)
    _pack_box_extents(raw, thickness / 2.0, height / 2.0, length / 2.0)
    struct.pack_into("<4s", raw, TYPE_OFFSET, BOX[::-1])
    return Primitive(raw=bytes(raw))


def wall_template(donor: "Sol") -> "Primitive":
    """A shipped barrier BOX to patch. Raises if the donor has none."""
    for prim in donor.primitives:
        if prim.type == BOX:
            return prim
    raise SolError("the donor .sol carries no BOX primitive to use as a template")


# The only two orientations any shipped TUBE carries, and which one a tube gets
# is decided entirely by whether it is a wobble: across 931 tubes on 7 tracks,
# every tube with an id carries WOBBLE and every tube without one carries PLAIN,
# with ZERO exceptions. So the matrix is written here rather than inherited from
# the template -- bemidji's only tube is a plain one, and a wobble built by
# copying it would carry the wrong orientation.
TUBE_MATRIX_PLAIN = (1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0)
TUBE_MATRIX_WOBBLE = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)


# A TUBE is a serialised TubeVolume -- a CAPSULE -- starting at +0x3c, the same
# place every primitive's volume object starts. Read from TubeVolume's
# constructors (0x4336b0, and 0x4337a0, the one the loader uses, which keeps the
# serialised fields and only restores vtables) and Setup (0x433830):
#
#   +0x58  radius                 volume +0x1c
#   +0x5c  HALF-length            volume +0x20; the cylinder runs -h..+h on local z
#   +0x60  cap sphere, 64 bytes   volume +0x24: SphereVolume, centre (0, 0, +h)
#   +0xa0  cap sphere, 64 bytes   volume +0x64: SphereVolume, centre (0, 0, -h)
#
# Each cap is a whole SphereVolume: +0x00 vtable (0x00417210, the tool's), +0x0c
# and +0x10 the same 50000.0 / 0.2 class defaults as the tube, +0x14 'SPHR',
# +0x18 100, +0x1c radius, +0x20 local centre, +0x2c a cached world centre that
# every shipped tube sets to the tube's own position. collide_sphere_tube tests
# the cylinder, then both caps, so a stale cap is a live collider.
CAP_OFFSETS = (0x60, 0xa0)


def tube_at(template: "Primitive", position, *, radius: float,
            half_length: float, ident: int = -1) -> "Primitive":
    """A TUBE (capsule) at `position`, built by patching a shipped record.

    The capsule's axis is local z; TUBE_MATRIX_WOBBLE and TUBE_MATRIX_PLAIN both
    stand it upright. It is centred on `position`, so a wobble centred on the
    ground buries half its cylinder, and what stands above ground is
    `half_length` of cylinder plus a hemispherical cap of `radius`.

    A WOBBLE PIVOTS ON THIS POINT. Wobble::Update pins the body's position back
    to its origin every frame and only lets it rotate, stopping it about 5
    degrees short of flat. That is why a wobble is centred at its foot.

    THE FRAME IS NEVER TURNED. A wobble draws its model in this tube's frame,
    so rotating the matrix would turn the model too -- but no stock track does
    it: every wobble tube carries TUBE_MATRIX_WOBBLE exactly, and a sign that
    faces some other way has the turn baked into its vertices (nfield's chevrons
    measure 0.93 x 0.36, 0.48 x 0.87, ... across the same 1 m board).

    A WOBBLE MUST BE A TUBE. The Wobble constructor binds whatever primitive
    carries its id, so a BOX binds too -- but collide_sphere_box opens with
    ASSERT_MSG("Colliding a dynamic box--not supported") and only ever pushes
    the sphere, so a box wobble stands like a wall. Tried in game 2026-09-17:
    square panels on box colliders drew and blocked but never fell. A flat
    sign goes on a capsule as wide as it is; stock puts its 2 m square signs on
    a 0.25 m post, which a car finds and a ball mostly misses.

    An earlier version of this function wrote its `radius` at +0x5c, believing a
    tube had no height. +0x5c is the half-length: every such wobble was a thin
    post with the template's radius (0.23 m from bemidji), and its cap spheres
    stayed at the template's +-5.75 m. Everything a tube's geometry depends on
    is written here, so nothing can be inherited stale from the template.

    `ident` is the wobble id, and -1 means an ordinary solid. Give an id ONLY to
    a tube that has a matching `obj wobble` record and facing node: a tube
    claiming an id no wobble uses is a dangling claim on that slot. Stock hands
    out exactly as many ids as a track has wobbles.
    """
    if ident >= 512:
        raise SolError(f"wobble id {ident} outside 0..511")
    if radius <= 0.0 or half_length < 0.0:
        raise SolError(f"tube radius {radius} / half-length {half_length}: "
                       f"the radius must be positive and the half-length not negative")
    raw = bytearray(template.raw)
    matrix = TUBE_MATRIX_WOBBLE if ident >= 0 else TUBE_MATRIX_PLAIN
    struct.pack_into("<9f", raw, 0x00, *matrix)
    struct.pack_into("<3f", raw, POSITION_OFFSET, *position)
    struct.pack_into("<2f", raw, 0x58, radius, half_length)
    for cap, sign in zip(CAP_OFFSETS, (1.0, -1.0)):
        struct.pack_into("<f", raw, cap + 0x1c, radius)
        struct.pack_into("<3f", raw, cap + 0x20, 0.0, 0.0, sign * half_length)
        struct.pack_into("<3f", raw, cap + 0x2c, *position)
    struct.pack_into("<i", raw, ID_OFFSET, ident)
    struct.pack_into("<4s", raw, TYPE_OFFSET, TUBE[::-1])
    return Primitive(raw=bytes(raw))


def tube_template(donor: "Sol") -> "Primitive":
    """A shipped TUBE to patch. Raises if the donor has none."""
    for prim in donor.primitives:
        if prim.type == TUBE:
            return prim
    raise SolError(
        "the donor .sol carries no TUBE primitive to use as a template -- "
        "bemidji has one, and hastings, uptown, kenyon, heaven, nfield and "
        "dundas have many; limbo has none")


def from_segments(segments, template: "Primitive", *, height: float = 1.5,
                  version: int = 2) -> "Sol":
    """A complete populated `.sol` from a list of (a, b) wall segments."""
    prims = [box_from_segment(template, a, b, height=height) for a, b in segments]
    index, tail = build_spatial_index(prims)
    return Sol(primitives=prims, index=index, tail=tail, version=version)


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
            "a populated .sol needs its quadtree tail -- carry it over from a "
            "parsed file, or build one with build_spatial_index() (see "
            "from_segments() for the wall case)")

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
