"""`.bpp` — a track's collision BSP: a triangle soup plus a 2D tree over the XZ plane.

WHAT IT IS. The largest file in every track, and the one the physics asks "what is
under / in front of the car". It is entirely separate from `.grf`, which is what
the track *looks* like -- nothing links a collision triangle to a render triangle.

That separation is not academic. Delete an object from `.grf` and it vanishes
visually while its collision triangles stay in the `.bpp`, so the car hits
something that is no longer drawn. Any tool that edits track geometry has to edit
both or it produces invisible walls.

LAYOUT (confirmed against `race.bin`'s own loader, not inferred):

    header, 20 bytes
      +00  u32    n_triangles
      +04  u32    n_nodes
      +08  u32    0
      +0c  u32    0
      +10  u32    root       index of the root node

    triangle x n_triangles, 56 bytes
      +00  float3 normal     unit length
      +0c  float  d          plane, with the convention  n.v + d = 0
      +10  float3 v0
      +1c  float3 v1
      +28  float3 v2
      +34  u32    flag       per-triangle surface bits, see below

    node x n_nodes, 28 bytes
      +00  float  a
      +04  float  b          splitting line in XZ:  a*x + b*z + c
      +08  float  c
      +0c  i32    tri0       triangle index, -1 = none
      +10  i32    tri1       triangle index, -1 = none
      +14  i32    less       child node index, -1 = null
      +18  i32    greater    child node index, -1 = null

`20 + 56*n_triangles + 28*n_nodes` equals the payload length exactly, with no
padding, on every stock track.

WHERE THE LAYOUT COMES FROM. `race.bin`'s loader at `0x468AB0` (v1.2.5) does
`lea eax,[esi+0x14]` for the payload start, then indexes the first section with
`n*7*8` and the second with `n*7*4` -- 20, 56 and 28 read straight off the
arithmetic. `fixup_tree` at `0x468B80` divides pointer differences by `0x1c` to
recover node indices, and rewrites `+0x14`/`+0x18` from indices into pointers,
leaving `+0x00`..`+0x10` alone. The traversal test computes `a*x + b*z + c`.

THE TRIANGLE FLAG IS A BITFIELD, not an enum -- bits 0..4 appear, in combinations,
and the values are wildly non-uniform. Two dominate and appear in every track
(`0` with 72,103 triangles and `10` with 19,081); the rest are rare and
track-specific (4 to 1,033 triangles, in one to three tracks). It correlates with
orientation, which is what suggests a surface classification rather than
bookkeeping: flag `14` is 99.2% horizontal while flag `16` is 91% non-horizontal.
What each bit MEANS is unconfirmed -- surface material, off-track, wall and pit
are all plausible -- so this module keeps the flag as an integer and does not
pretend to interpret it.

WHAT `tri0` AND `tri1` MEAN IS STILL OPEN. They are triangle indices -- their
range is exactly `0..n_triangles-1` -- but they are not a range (`tri0 > tri1`
about half the time), not the same triangle twice (never), and not the triangle
whose plane produced the split (the node's line is parallel to `tri0`'s plane
only 5-10% of the time). `fixup_tree` does not touch them, so they are consumed
at query time. This module round-trips them as opaque integers, which is why it
can be byte-exact without knowing the answer.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER = 20
TRIANGLE = 56
NODE = 28

NO_TRI = -1
NO_CHILD = -1


class BppError(ValueError):
    """The payload isn't a .bpp this module recognises."""


@dataclass
class Triangle:
    normal: tuple[float, float, float]
    d: float
    v: tuple[tuple[float, float, float], ...]      # exactly three vertices
    flag: int

    def on_plane_error(self) -> float:
        """Largest |n.v + d| over the three vertices -- 0 for well-formed data."""
        return max(abs(sum(n * c for n, c in zip(self.normal, vert)) + self.d)
                   for vert in self.v)


@dataclass
class Node:
    a: float
    b: float
    c: float
    tri0: int
    tri1: int
    less: int
    greater: int

    def side(self, x: float, z: float) -> float:
        """The splitting test the game itself performs: a*x + b*z + c."""
        return self.a * x + self.b * z + self.c


@dataclass
class Bpp:
    root: int = 0
    reserved: tuple[int, int] = (0, 0)             # header +08 and +0c, zero in stock data
    triangles: list[Triangle] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)

    @property
    def size(self) -> int:
        return HEADER + TRIANGLE * len(self.triangles) + NODE * len(self.nodes)


def parse(payload: bytes) -> Bpp:
    """Decode a .bpp payload (the bytes inside the 0SER envelope)."""
    if len(payload) < HEADER:
        raise BppError(f"too short to hold a header: {len(payload)} bytes")
    n_tri, n_node, r0, r1, root = struct.unpack_from("<5I", payload, 0)
    expect = HEADER + TRIANGLE * n_tri + NODE * n_node
    if expect != len(payload):
        raise BppError(
            f"header says {n_tri:,} triangles and {n_node:,} nodes, which needs "
            f"{expect:,} bytes, but the payload is {len(payload):,}")

    tris: list[Triangle] = []
    off = HEADER
    for _ in range(n_tri):
        f = struct.unpack_from("<13f", payload, off)
        flag = struct.unpack_from("<I", payload, off + 52)[0]
        tris.append(Triangle(normal=f[0:3], d=f[3],
                             v=(f[4:7], f[7:10], f[10:13]), flag=flag))
        off += TRIANGLE

    nodes: list[Node] = []
    for _ in range(n_node):
        a, b, c = struct.unpack_from("<3f", payload, off)
        tri0, tri1, less, greater = struct.unpack_from("<4i", payload, off + 12)
        nodes.append(Node(a, b, c, tri0, tri1, less, greater))
        off += NODE

    return Bpp(root=root, reserved=(r0, r1), triangles=tris, nodes=nodes)


def build(b: Bpp) -> bytes:
    """Re-encode. parse -> build reproduces the original payload byte for byte."""
    out = bytearray()
    out += struct.pack("<5I", len(b.triangles), len(b.nodes),
                       b.reserved[0], b.reserved[1], b.root)
    for t in b.triangles:
        if len(t.v) != 3:
            raise BppError(f"a triangle has {len(t.v)} vertices, not 3")
        out += struct.pack("<13f", *t.normal, t.d, *t.v[0], *t.v[1], *t.v[2])
        out += struct.pack("<I", t.flag)
    for n in b.nodes:
        out += struct.pack("<3f", n.a, n.b, n.c)
        out += struct.pack("<4i", n.tri0, n.tri1, n.less, n.greater)
    return bytes(out)


def walk(b: Bpp):
    """Yield node indices reachable from the root, depth first, without revisiting.

    Guards against cycles rather than trusting the data: a malformed tree would
    otherwise hang the caller.
    """
    seen: set[int] = set()
    stack = [b.root]
    while stack:
        i = stack.pop()
        if i < 0 or i >= len(b.nodes) or i in seen:
            continue
        seen.add(i)
        yield i
        n = b.nodes[i]
        stack.append(n.greater)
        stack.append(n.less)


def retag(b: Bpp, mapping: dict[int, int], *,
          region: tuple[float, float, float, float] | None = None) -> int:
    """Rewrite triangle surface codes in place. Returns the number changed.

    `mapping` is {old_code: new_code} -- e.g. {10: 20} turns grass into dirt, or
    {10: 14} floods the grass with water. Codes not in the mapping are left alone.

    `region`, if given, is an axis-aligned XZ box (min_x, min_z, max_x, max_z) in
    world units; only triangles whose centroid falls inside it are retouched. That
    is the difference between "make all grass dirt" and "make the grass in THIS
    corner dirt". Y is ignored, matching the game's own 2D (XZ) surface model.

    The surface code is what the physics reads at a contact point (see the
    reference): it selects drag, dust and float behaviour. This edits only that
    field, so the collision shape is untouched -- the car still hits exactly what
    it hit before, it just behaves differently on contact.
    """
    changed = 0
    for t in b.triangles:
        if t.flag not in mapping:
            continue
        if region is not None:
            cx = (t.v[0][0] + t.v[1][0] + t.v[2][0]) / 3.0
            cz = (t.v[0][2] + t.v[1][2] + t.v[2][2]) / 3.0
            if not (region[0] <= cx <= region[2] and region[1] <= cz <= region[3]):
                continue
        t.flag = mapping[t.flag]
        changed += 1
    return changed


def surface_histogram(b: Bpp) -> dict[int, int]:
    """{surface code: triangle count} -- what to feed a retag decision."""
    out: dict[int, int] = {}
    for t in b.triangles:
        out[t.flag] = out.get(t.flag, 0) + 1
    return dict(sorted(out.items()))


def to_obj(b: Bpp, name: str = "collision") -> str:
    """The collision soup as Wavefront OBJ, for looking at beside the render mesh.

    This is the quickest way to see what a track actually collides with -- and to
    spot geometry that is present here but missing from `.grf`, which is what an
    invisible wall looks like from the outside.
    """
    lines = [f"# {name}: {len(b.triangles):,} collision triangles from .bpp", f"o {name}"]
    for t in b.triangles:
        for vert in t.v:
            lines.append(f"v {vert[0]:.5f} {vert[1]:.5f} {vert[2]:.5f}")
    for i in range(len(b.triangles)):
        a = i * 3 + 1
        lines.append(f"f {a} {a+1} {a+2}")
    return "\n".join(lines) + "\n"
