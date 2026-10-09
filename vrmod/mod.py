"""
MINF -- .mod 3D mesh (car parts, track props).

    0x00  vertex count (V)                       int32
    0x04  (stale in-memory pointer -- ignore)     int32
    0x08  material count (M)                      int32
    0x0C  (stale pointer -- ignore)                int32
    0x10  face count (F)                          int32
    0x14  (stale pointers/reserved x4 -- ignore)  int32 x4
    0x28  V x 32-byte vertex records: float32 x,y,z, nx,ny,nz, u,v
          M x 32-byte material records: null-terminated texture filename,
              then (at a fixed offset from the END of the 32-byte record,
              regardless of name length) 4 x int16: vertex_start, vertex_end,
              face_start, face_end -- the half-open [start,end) range of
              vertices/faces that use this material. These chain: material i's
              *_end equals material i+1's *_start, and the last material's
              vertex_end/face_end equal V/F exactly. Verified against every
              face's actual vertex indices across three real multi-material
              files (0 violations) -- this was previously undocumented as
              "no per-face material index exists anywhere in the file"; it
              does, it's just stored as contiguous ranges rather than a
              per-face index.
          F x 8-byte face records: int16 a,b,c (CCW winding) + int16 pad(=0)

All offsets above are payload-relative (i.e. relative to the byte right after
the 20-byte 0SER envelope) -- the doc's raw-file offsets (0x3C for the vertex
block) are 0x14 higher, matching the envelope size.

Coordinate convention: Viper stores meshes in a LEFT-handed space (it is a
DirectX-era engine), while OBJ consumers and three.js are right-handed. So
to_obj() negates Z and swaps two face indices to keep winding correct, and
from_obj() undoes both. That is the standard left-to-right handedness
conversion, not a mirror.

This is worth recording carefully, because it was removed once on the belief
that it was a spurious mirror, and that removal silently reflected every
rendered scene -- cars and tracks alike. The reasoning behind the removal was
that negating a single axis IS a reflection; what it missed is that the source
data is left-handed, so the reflection is exactly what makes it come out
right. Two pieces of evidence settle it, both reproducible:

  * bemidji's pit wall carries a "VIPER" texture. With the conversion it reads
    "VIPER"; without it, reversed.
  * viper.car's Viperd1.tex is a gauge cluster with the tachometer on the LEFT
    and its redline at the top RIGHT. With the conversion the render matches
    the texture; without it, the cluster is mirrored and the digits reverse.

Anything drawn alongside this output (driving lines, camera positions,
collision geometry) is still in the native left-handed space and therefore
needs the SAME Z negation applied before it will line up.
"""
from __future__ import annotations

import heapq
import struct
from dataclasses import dataclass
from pathlib import Path

from . import envelope

TAG = b"FNIM"

VERTEX_SIZE = 32
MATERIAL_SIZE = 32
FACE_SIZE = 8
VERTEX_BLOCK_START = 0x3C - 0x14  # 0x14 = envelope size; matches the doc's file-relative 0x3C

# Per-.mod vertex ceilings before the game crashes (EXCEPTION_ACCESS_VIOLATION), per the
# community car-creation tutorial's tested figures for each patch level.
VERTEX_BUDGETS = {"original": 1200, "1.23": 5000, "hd": 20000}


@dataclass
class Vertex:
    x: float
    y: float
    z: float
    nx: float
    ny: float
    nz: float
    u: float
    v: float


@dataclass
class Material:
    name: str
    vertex_start: int
    vertex_end: int
    face_start: int
    face_end: int


@dataclass
class Mesh:
    vertices: list[Vertex]
    materials: list[Material]
    faces: list[tuple[int, int, int]]
    version: int = 1


def transform(
    mesh: Mesh, dx: float = 0, dy: float = 0, dz: float = 0,
    mirror_x: bool = False, rotate_y90: bool = False, rotate_z: float = 0.0,
) -> Mesh:
    """Return a repositioned copy of a mesh -- used to place multiple instances of the
    same part .mod (most notably a wheel) at different spots in a combined scene.

    rotate_y90: rotate 90 degrees about the vertical axis before translating (x,z) ->
    (z,-x), applied to normals too. Needed for Viperw.mod specifically: its own local
    geometry is a flat quad lying in the XY plane (Z constant across every vertex --
    confirmed directly from the file), i.e. it faces front/back, not sideways -- the
    wrong orientation for a wheel meant to be seen from the side of the car. A pure
    rotation doesn't flip handedness, so it needs no winding fix (unlike mirroring).

    mirror_x: flip left/right for the opposite-side copy of a part. Flips winding
    (swaps two face indices) to keep the mesh correctly wound after the handedness flip.

    rotate_z: degrees about the depth axis, applied before translating. This is the
    dash-gauge case: Needle.mod is a single triangle standing on its pivot and
    pointing straight up, and cockpit.tab's "rpm dat"/"mph dat" records give the
    angle it should stand at for a given reading. Like rotate_y90 it is a pure
    rotation, so winding is untouched.
    """
    import math

    def rot(x: float, z: float) -> tuple[float, float]:
        return (z, -x) if rotate_y90 else (x, z)

    t = math.radians(rotate_z)
    cz, sz = math.cos(t), math.sin(t)

    def spin(x: float, y: float) -> tuple[float, float]:
        return (x * cz - y * sz, x * sz + y * cz) if rotate_z else (x, y)

    sx = -1.0 if mirror_x else 1.0
    new_vertices = []
    for v in mesh.vertices:
        rx, rz = rot(v.x, v.z)
        rnx, rnz = rot(v.nx, v.nz)
        rx, ry = spin(rx, v.y)
        rnx, rny = spin(rnx, v.ny)
        new_vertices.append(Vertex(rx * sx + dx, ry + dy, rz + dz, rnx * sx, rny, rnz, v.u, v.v))
    new_faces = [(a, c, b) if mirror_x else (a, b, c) for a, b, c in mesh.faces]
    return Mesh(vertices=new_vertices, materials=list(mesh.materials), faces=new_faces, version=mesh.version)


def merge(parts: list[Mesh]) -> Mesh:
    """Concatenate several meshes (already positioned via transform()) into one, with
    vertex/face indices and material ranges offset to keep everything valid."""
    out_vertices: list[Vertex] = []
    out_materials: list[Material] = []
    out_faces: list[tuple[int, int, int]] = []
    for part in parts:
        voffset = len(out_vertices)
        foffset = len(out_faces)
        out_vertices.extend(part.vertices)
        out_faces.extend((a + voffset, b + voffset, c + voffset) for a, b, c in part.faces)
        for m in part.materials:
            out_materials.append(
                Material(m.name, m.vertex_start + voffset, m.vertex_end + voffset,
                          m.face_start + foffset, m.face_end + foffset)
            )
    return Mesh(vertices=out_vertices, materials=out_materials, faces=out_faces)


def parse(data: bytes) -> Mesh:
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .mod file: tag {env.tag!r}, expected {TAG!r}")
    payload = env.payload

    V = struct.unpack_from("<i", payload, 0x00)[0]
    M = struct.unpack_from("<i", payload, 0x08)[0]
    F = struct.unpack_from("<i", payload, 0x10)[0]

    vstart = VERTEX_BLOCK_START
    mstart = vstart + V * VERTEX_SIZE
    fstart = mstart + M * MATERIAL_SIZE

    vertices = []
    for i in range(V):
        rec = payload[vstart + i * VERTEX_SIZE: vstart + (i + 1) * VERTEX_SIZE]
        x, y, z, nx, ny, nz, u, v = struct.unpack("<8f", rec)
        vertices.append(Vertex(x, y, z, nx, ny, nz, u, v))

    materials = []
    for i in range(M):
        rec = payload[mstart + i * MATERIAL_SIZE: mstart + (i + 1) * MATERIAL_SIZE]
        name = rec.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        vs, ve, fs, fe = struct.unpack("<4h", rec[24:32])
        materials.append(Material(name, vs, ve, fs, fe))

    faces = []
    for i in range(F):
        rec = payload[fstart + i * FACE_SIZE: fstart + (i + 1) * FACE_SIZE]
        a, b, c, pad = struct.unpack("<4h", rec)
        faces.append((a, b, c))

    return Mesh(vertices=vertices, materials=materials, faces=faces, version=env.version)


def parse_file(path: str | Path) -> Mesh:
    return parse(Path(path).read_bytes())


def set_material_texture(data: bytes, index: int, new_name: str) -> bytes:
    """Return a copy of a real .mod file's bytes with material `index`'s texture
    filename replaced. Only the filename bytes (and its new null terminator) are
    touched -- the material's vertex/face range, its padding bytes, every other
    material, and all geometry are carried over from `data` unmodified. This is
    pure retexturing: it doesn't touch UVs, so it only makes sense for a texture
    that shares the same UV layout as the one it replaces.
    """
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .mod file: tag {env.tag!r}, expected {TAG!r}")

    name_bytes = new_name.encode("ascii")
    max_len = MATERIAL_SIZE - 8 - 1  # last 8 bytes are the vertex/face range; 1 for the null terminator
    if len(name_bytes) > max_len:
        raise ValueError(
            f"texture filename too long: {new_name!r} ({len(name_bytes)} bytes, max {max_len})"
        )

    payload = bytearray(env.payload)
    V = struct.unpack_from("<i", payload, 0x00)[0]
    M = struct.unpack_from("<i", payload, 0x08)[0]
    if not (0 <= index < M):
        raise IndexError(f"material index {index} out of range (0..{M - 1})")

    mstart = VERTEX_BLOCK_START + V * VERTEX_SIZE
    rec_start = mstart + index * MATERIAL_SIZE
    payload[rec_start: rec_start + len(name_bytes)] = name_bytes
    payload[rec_start + len(name_bytes)] = 0  # null terminator

    return envelope.build(env.tag, env.version, bytes(payload))


def to_obj(mesh: Mesh, mtl_filename: str) -> tuple[str, str]:
    """Return (obj_text, mtl_text). Materials map to contiguous face runs already
    present in the data, so this just needs to emit a `usemtl` at each material's
    face-block start -- no grouping/reconstruction required.

    Z is negated and face winding swapped: Viper's mesh space is left-handed
    and OBJ/three.js are right-handed, so this is the handedness conversion.
    See the module docstring for the two texture tests that pin it down, and
    for why removing it (on the theory that it was a spurious mirror) reflected
    every rendered scene instead of fixing anything.

    Anything drawn alongside this output -- racing lines, camera positions,
    collision geometry -- is still in native left-handed coordinates and needs
    the same Z negation to line up.
    """
    obj_lines = [f"mtllib {mtl_filename}"]
    for vtx in mesh.vertices:
        obj_lines.append(f"v {vtx.x:.6f} {vtx.y:.6f} {-vtx.z:.6f}")
    for vtx in mesh.vertices:
        obj_lines.append(f"vt {vtx.u:.6f} {1.0 - vtx.v:.6f}")
    for vtx in mesh.vertices:
        obj_lines.append(f"vn {vtx.nx:.6f} {vtx.ny:.6f} {-vtx.nz:.6f}")

    face_to_material = {}
    for m in mesh.materials:
        for fi in range(m.face_start, m.face_end):
            face_to_material[fi] = m.name

    current_mat = None
    for i, (a, b, c) in enumerate(mesh.faces):
        mat = face_to_material.get(i)
        if mat != current_mat:
            obj_lines.append(f"usemtl {mat}")
            current_mat = mat
        # OBJ is 1-indexed. b and c are swapped because negating Z reverses
        # winding; swapping two indices puts it back so faces stay front-facing.
        ia, ib, ic = a + 1, c + 1, b + 1
        obj_lines.append(f"f {ia}/{ia}/{ia} {ib}/{ib}/{ib} {ic}/{ic}/{ic}")

    mtl_lines = []
    seen = set()
    for m in mesh.materials:
        if m.name in seen:
            continue
        seen.add(m.name)
        tga_name = Path(m.name).stem + ".tga"
        mtl_lines.append(f"newmtl {m.name}")
        mtl_lines.append("Kd 1.000 1.000 1.000")
        mtl_lines.append(f"map_Kd {tga_name}")
        mtl_lines.append("")

    return "\n".join(obj_lines) + "\n", "\n".join(mtl_lines)


def _parse_obj_text(text: str):
    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []
    blocks: list[dict] = []  # {"material": str, "faces": [((pi,ui,ni), ...) x3, ...]}
    current = None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v":
            positions.append(tuple(float(x) for x in parts[1:4]))
        elif tag == "vt":
            uvs.append(tuple(float(x) for x in parts[1:3]))
        elif tag == "vn":
            normals.append(tuple(float(x) for x in parts[1:4]))
        elif tag == "usemtl":
            current = {"material": parts[1], "faces": []}
            blocks.append(current)
        elif tag == "f":
            if current is None:
                raise ValueError("face defined before any usemtl -- every face must belong to a material")
            verts = parts[1:]
            if len(verts) < 3:
                raise ValueError(f"a face needs at least 3 vertices, got a {len(verts)}-gon")
            poly = []
            for token in verts:
                comps = token.split("/")
                pi = int(comps[0])
                ui = int(comps[1]) if len(comps) > 1 and comps[1] else None
                ni = int(comps[2]) if len(comps) > 2 and comps[2] else None
                poly.append((pi, ui, ni))
            # Fan-triangulate n-gons -- real models (Blender exports especially)
            # ship quads and larger polys, but Viper .mod is triangles only. A
            # convex fan (v0,v1,v2),(v0,v2,v3),... is correct for the near-convex
            # faces these exporters produce.
            for k in range(1, len(poly) - 1):
                current["faces"].append((poly[0], poly[k], poly[k + 1]))

    return positions, uvs, normals, blocks


def _compute_vertex_normals(mesh: Mesh) -> None:
    accum = [[0.0, 0.0, 0.0] for _ in mesh.vertices]
    for a, b, c in mesh.faces:
        va, vb, vc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        ux, uy, uz = vb.x - va.x, vb.y - va.y, vb.z - va.z
        wx, wy, wz = vc.x - va.x, vc.y - va.y, vc.z - va.z
        nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
        for idx in (a, b, c):
            accum[idx][0] += nx
            accum[idx][1] += ny
            accum[idx][2] += nz
    for vtx, (nx, ny, nz) in zip(mesh.vertices, accum):
        length = (nx * nx + ny * ny + nz * nz) ** 0.5
        if length > 1e-12:
            vtx.nx, vtx.ny, vtx.nz = nx / length, ny / length, nz / length
        else:
            vtx.nx, vtx.ny, vtx.nz = 0.0, 1.0, 0.0


def from_obj(text: str) -> Mesh:
    """Parse an OBJ (triangulated, with usemtl groups) into a Mesh ready for build().

    Each contiguous usemtl run becomes one material record with its own exclusive
    vertex/face range, matching Viper's requirement that no vertex is shared across
    materials -- a (position, uv, normal) index-tuple used by two different runs is
    duplicated into each, even if they're numerically identical. Positions and face
    winding pass straight through, matching to_obj(): neither direction mirrors Z any
    more (see the module docstring for why that mirror existed and why it was wrong).
    Missing `vn` data is filled in with computed face-averaged normals.
    """
    positions, uvs, normals, blocks = _parse_obj_text(text)
    if not blocks:
        raise ValueError("no usemtl/f data found -- OBJ must have triangulated faces under at least one usemtl")
    have_normals = bool(normals)

    out_vertices: list[Vertex] = []
    out_materials: list[Material] = []
    out_faces: list[tuple[int, int, int]] = []

    for block in blocks:
        vstart = len(out_vertices)
        fstart = len(out_faces)
        cache: dict[tuple, int] = {}
        for tri in block["faces"]:
            face_idx = []
            for pi, ui, ni in tri:
                key = (pi, ui, ni)
                if key not in cache:
                    x, y, z = positions[pi - 1]
                    u, v = uvs[ui - 1] if ui else (0.0, 0.0)
                    if have_normals and ni:
                        nx, ny, nz = normals[ni - 1]
                    else:
                        nx, ny, nz = 0.0, 0.0, 0.0
                    cache[key] = len(out_vertices)
                    # undo to_obj's v-flip and its Z negation (see its docstring)
                    out_vertices.append(Vertex(x, y, -z, nx, ny, -nz, u, 1.0 - v))
                face_idx.append(cache[key])
            a, b, c = face_idx
            # undo to_obj's winding swap
            out_faces.append((a, c, b))
        vend = len(out_vertices)
        fend = len(out_faces)
        out_materials.append(Material(block["material"], vstart, vend, fstart, fend))

    mesh = Mesh(vertices=out_vertices, materials=out_materials, faces=out_faces)
    if not have_normals:
        _compute_vertex_normals(mesh)
    return mesh


def read_obj(obj_path: str | Path) -> Mesh:
    return from_obj(Path(obj_path).read_text(encoding="utf-8"))


def build(mesh: Mesh, version: int = 1) -> bytes:
    """Serialize a Mesh into a .mod file. This is a fresh construction, not an
    in-place edit like set_material_texture() -- the header's unused/"stale
    pointer" fields and each material record's padding bytes are zero-filled
    rather than preserved, since a freshly built mesh has no original bytes to
    carry them over from."""
    V, M, F = len(mesh.vertices), len(mesh.materials), len(mesh.faces)

    header = bytearray(VERTEX_BLOCK_START)
    struct.pack_into("<i", header, 0x00, V)
    struct.pack_into("<i", header, 0x08, M)
    struct.pack_into("<i", header, 0x10, F)

    vertex_bytes = bytearray()
    for vtx in mesh.vertices:
        vertex_bytes += struct.pack("<8f", vtx.x, vtx.y, vtx.z, vtx.nx, vtx.ny, vtx.nz, vtx.u, vtx.v)

    material_bytes = bytearray()
    max_name_len = MATERIAL_SIZE - 8 - 1
    for m in mesh.materials:
        name_bytes = m.name.encode("ascii")
        if len(name_bytes) > max_name_len:
            raise ValueError(f"material name too long: {m.name!r} (max {max_name_len} bytes)")
        rec = bytearray(MATERIAL_SIZE)
        rec[: len(name_bytes)] = name_bytes
        struct.pack_into("<4h", rec, 24, m.vertex_start, m.vertex_end, m.face_start, m.face_end)
        material_bytes += rec

    face_bytes = bytearray()
    for a, b, c in mesh.faces:
        face_bytes += struct.pack("<4h", a, b, c, 0)

    payload = bytes(header) + bytes(vertex_bytes) + bytes(material_bytes) + bytes(face_bytes)
    return envelope.build(TAG, version, payload)


# Positions are welded at this many decimals (0.1 mm in game units) when deciding which
# vertex records are "the same point" -- the same rounding the seam checks use.
_WELD_DECIMALS = 4

# A collapse may turn a surviving triangle by at most 45 degrees, and may not leave one
# thinner than _MIN_QUALITY (see _quality) unless it was already that thin. Looser limits
# (60 degrees, no sliver check) let LODs grow long shards out of the body: points locked
# on seams and open edges stay put while their neighbours collapse onto them from far
# away. These stop a mesh from shrinking past the point where it would start to look
# wrong; the car's own parts are what LODs should shed next (drop_parts).
_MAX_TURN_COS = 0.7071
_MIN_QUALITY = 0.15

# Weight of the planes that pin seam lines and open edges in the error metric, relative
# to the surface's own planes: high enough that a seam is straightened only where it
# was nearly straight already.
_SEAM_WEIGHT = 10.0


def _weld_key(v: Vertex) -> tuple[float, float, float]:
    return (round(v.x, _WELD_DECIMALS), round(v.y, _WELD_DECIMALS), round(v.z, _WELD_DECIMALS))


def _uv_key(v: Vertex) -> tuple[float, float]:
    return (round(v.u, _WELD_DECIMALS), round(v.v, _WELD_DECIMALS))


def _face_normal(p, q, r) -> tuple[float, float, float]:
    ux, uy, uz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
    wx, wy, wz = r[0] - p[0], r[1] - p[1], r[2] - p[2]
    return (uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx)


def _quality(pts, cross_len: float) -> float:
    """Triangle shape, 1 for equilateral down to 0 for a sliver: 4*sqrt(3)*area / sum of
    squared edge lengths (cross_len is |cross product| = 2 * area)."""
    e2 = sum((pts[a][k] - pts[b][k]) ** 2 for a, b in ((0, 1), (1, 2), (2, 0)) for k in range(3))
    return 2 * 3 ** 0.5 * cross_len / e2 if e2 > 0 else 0.0


def _point_triangle_distance(p, tri) -> float:
    """Distance from point p to the triangle tri (three points), edges and corners included."""
    a, b, c = tri
    ab = [b[k] - a[k] for k in range(3)]
    ac = [c[k] - a[k] for k in range(3)]
    ap = [p[k] - a[k] for k in range(3)]

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return dot(ap, ap) ** 0.5
    bp = [p[k] - b[k] for k in range(3)]
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return dot(bp, bp) ** 0.5
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        t = d1 / (d1 - d3)
        return sum((ap[k] - t * ab[k]) ** 2 for k in range(3)) ** 0.5
    cp = [p[k] - c[k] for k in range(3)]
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return dot(cp, cp) ** 0.5
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        t = d2 / (d2 - d6)
        return sum((ap[k] - t * ac[k]) ** 2 for k in range(3)) ** 0.5
    va = d3 * d6 - d5 * d4
    if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return sum((bp[k] - t * (c[k] - b[k])) ** 2 for k in range(3)) ** 0.5
    denom = va + vb + vc
    v, w = vb / denom, vc / denom
    return sum((ap[k] - ab[k] * v - ac[k] * w) ** 2 for k in range(3)) ** 0.5


def _plane_quadric(n, p, weight: float) -> list[float]:
    """Error quadric (upper triangle of the 4x4) of the plane through p with unit normal n."""
    a, b, c = n
    d = -(a * p[0] + b * p[1] + c * p[2])
    return [weight * x for x in (a * a, a * b, a * c, a * d, b * b, b * c, b * d, c * c, c * d, d * d)]


def _quadric_error(qd: list[float], p) -> float:
    x, y, z = p
    return (qd[0] * x * x + 2 * qd[1] * x * y + 2 * qd[2] * x * z + 2 * qd[3] * x
            + qd[4] * y * y + 2 * qd[5] * y * z + 2 * qd[6] * y
            + qd[7] * z * z + 2 * qd[8] * z + qd[9])


def decimate(mesh: Mesh, target_vertices: int, max_move: float | None = None) -> Mesh:
    """Reduce a mesh towards `target_vertices` vertex records without tearing it.

    Works on the mesh as one welded surface: vertex records at the same (rounded)
    position are one point, whatever material or UV they carry. Each step is a
    half-edge collapse -- a point is removed by moving its triangles onto a
    neighbouring point, which stays exactly where it is -- cheapest first by
    quadric error (how far the surface moves), with seam lines and open edges
    weighted in so they hold their shape. Positions are never averaged, so every
    surviving vertex is an original record, untouched.

    Material boundaries and UV seams are where the old per-material decimator tore
    the mesh: it collapsed each block on its own, so the two sides of a boundary
    moved apart. Here a point carrying records of more than one material or UV (a
    seam point) can only be removed along its own seam line: it must sit on exactly
    two seam edges, it collapses onto the neighbour at the end of one of them, and
    each of its records goes to that neighbour's record on the same side. Both sides
    move together, so no crack opens, and no triangle ever picks up a UV from another
    atlas chart. Points where three or more charts meet, and points on open,
    non-manifold or inconsistently wound edges in the input, never move.

    A collapse is also refused when it would make the surface non-manifold (the link
    condition), duplicate a triangle, fold a triangle over (_MAX_TURN_COS) or delete a
    material's last triangle. Together these mean decimation adds no open edge and no
    winding error that the input didn't already have.

    `max_move` caps how far the surface may move (in the mesh's units): a removed point's
    distance to the nearest of the triangles that now cover its neighbourhood, added up
    over the collapses that carried it. Sliding a point along a flat panel moves nothing.
    Each collapse is checked on its own, so without a cap many small steps can add up to
    a spike; with one, a mesh stops shrinking once going further would visibly change
    its shape. LOD building passes a cap that grows with the distance the level is seen
    from.

    The points that never move put a floor under how far a mesh can shrink, so the
    result may stay above `target_vertices`; callers with a hard ceiling must check.
    Normals are recomputed, as the triangle fans around surviving points have changed.
    """
    if len(mesh.vertices) <= target_vertices:
        return mesh

    verts = mesh.vertices
    nv = len(verts)
    vmat = [0] * nv
    for mi, m in enumerate(mesh.materials):
        for i in range(m.vertex_start, m.vertex_end):
            vmat[i] = mi
    vcls = [(vmat[i], _uv_key(v)) for i, v in enumerate(verts)]   # a record's "side"

    # Weld: a node per distinct rounded position.
    node_of: list[int] = []
    ids: dict[tuple[float, float, float], int] = {}
    for v in verts:
        node_of.append(ids.setdefault(_weld_key(v), len(ids)))
    nn = len(ids)
    pos = [(0.0, 0.0, 0.0)] * nn
    for v, n in zip(verts, node_of):
        pos[n] = (v.x, v.y, v.z)

    faces = [list(f) for f in mesh.faces]
    fmat = [0] * len(faces)
    for mi, m in enumerate(mesh.materials):
        for fi in range(m.face_start, m.face_end):
            fmat[fi] = mi
    alive = [True] * len(faces)
    node_faces: list[set[int]] = [set() for _ in range(nn)]
    refs = [0] * nv
    for fi, f in enumerate(faces):
        for i in f:
            node_faces[node_of[i]].add(fi)
            refs[i] += 1
    mat_faces = [m.face_end - m.face_start for m in mesh.materials]

    def rec_in(fi: int, n: int) -> int:
        return next(i for i in faces[fi] if node_of[i] == n)

    # Topology of the input, and the error quadrics.
    locked = [False] * nn
    quad = [[0.0] * 10 for _ in range(nn)]
    directed: dict[tuple[int, int], int] = {}
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for fi, f in enumerate(faces):
        a, b, c = (node_of[i] for i in f)
        if a == b or b == c or a == c:
            locked[a] = locked[b] = locked[c] = True   # already degenerate: leave it be
            continue
        n = _face_normal(pos[a], pos[b], pos[c])
        ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
        if ln > 1e-12:
            fq = _plane_quadric((n[0] / ln, n[1] / ln, n[2] / ln), pos[a], ln / 2)
            for x in (a, b, c):
                quad[x] = [s + t for s, t in zip(quad[x], fq)]
        for e in ((a, b), (b, c), (c, a)):
            directed[e] = directed.get(e, 0) + 1
            edge_faces.setdefault((min(e), max(e)), []).append(fi)
    for (a, b), k in directed.items():
        if k != 1 or directed.get((b, a), 0) != 1:
            locked[a] = locked[b] = True               # open, non-manifold or mis-wound
    for (a, b), fl in edge_faces.items():
        pinned = len(fl) != 2 or any(
            vcls[rec_in(fl[0], x)] != vcls[rec_in(fl[1], x)] for x in (a, b))
        if not pinned:
            continue
        # A seam or open edge: add planes through it, perpendicular to its triangles.
        ex, ey, ez = (pos[b][k] - pos[a][k] for k in range(3))
        for fi in fl:
            n = _face_normal(*(pos[node_of[i]] for i in faces[fi]))
            px, py, pz = ey * n[2] - ez * n[1], ez * n[0] - ex * n[2], ex * n[1] - ey * n[0]
            lp = (px * px + py * py + pz * pz) ** 0.5
            if lp > 1e-12:
                eq = _plane_quadric((px / lp, py / lp, pz / lp), pos[a],
                                    _SEAM_WEIGHT * (ex * ex + ey * ey + ez * ez))
                for x in (a, b):
                    quad[x] = [s + t for s, t in zip(quad[x], eq)]

    def neighbours(n: int) -> set[int]:
        out = {node_of[i] for fi in node_faces[n] for i in faces[fi]}
        out.discard(n)
        return out

    version = [0] * nn
    reach = [0.0] * nn     # how far the surface has moved, at most, at the points merged into each node

    def cost(p: int, q: int) -> float:
        merged = [s + t for s, t in zip(quad[p], quad[q])]
        d2 = sum((pos[p][k] - pos[q][k]) ** 2 for k in range(3))
        return _quadric_error(merged, pos[q]) + 1e-6 * d2   # length breaks ties on flat areas

    heap: list[tuple[float, int, int, int, int]] = []

    def push(p: int, q: int) -> None:
        if not locked[p]:
            heapq.heappush(heap, (cost(p, q), p, q, version[p], version[q]))

    for n in range(nn):
        for m in neighbours(n):
            push(n, m)

    live = sum(1 for r in refs if r)

    def ref(i: int, delta: int) -> None:
        nonlocal live
        before = refs[i]
        refs[i] += delta
        live += (refs[i] > 0) - (before > 0)

    def try_collapse(p: int, q: int) -> bool:
        fp = node_faces[p]
        if not fp or not node_faces[q]:
            return False
        shared = [fi for fi in fp if any(node_of[i] == q for i in faces[fi])]
        if len(shared) != 2:
            return False
        # Link condition: p and q may share only the two points opposite their edge.
        opposite = {node_of[i] for fi in shared for i in faces[fi]} - {p, q}
        if neighbours(p) & neighbours(q) != opposite:
            return False
        # Which record of q each record of p becomes: q's record on the same side.
        prec = {fi: rec_in(fi, p) for fi in fp}
        sides = {vcls[i] for i in prec.values()}
        (s0, s1), (q0, q1) = shared, (rec_in(shared[0], q), rec_in(shared[1], q))
        if len(sides) == 1:                            # p is inside one chart
            if vcls[q0] != vcls[q1]:
                return False
            mapping = {vcls[prec[s0]]: q0}
        elif len(sides) == 2:                          # p is on a seam: only along it
            if vcls[prec[s0]] == vcls[prec[s1]] or vcls[q0] == vcls[q1]:
                return False
            changes = 0
            for x in neighbours(p):
                fx = [fi for fi in fp if any(node_of[i] == x for i in faces[fi])]
                if len(fx) != 2:
                    return False
                changes += vcls[prec[fx[0]]] != vcls[prec[fx[1]]]
            if changes != 2:                           # a seam corner, not a seam line
                return False
            mapping = {vcls[prec[s0]]: q0, vcls[prec[s1]]: q1}
        else:
            return False
        if any(vmat[r] != side[0] for side, r in mapping.items()):
            return False
        for fi in shared:
            if mat_faces[fmat[fi]] <= sum(1 for f2 in shared if fmat[f2] == fmat[fi]):
                return False
        q_tris = {frozenset(node_of[i] for i in faces[fi]) for fi in node_faces[q]}
        moved = float("inf")
        for fi in fp:
            if fi in shared:
                continue
            f = faces[fi]
            n0 = _face_normal(*(pos[node_of[i]] for i in f))
            n1 = _face_normal(*(pos[q] if node_of[i] == p else pos[node_of[i]] for i in f))
            l0 = (n0[0] ** 2 + n0[1] ** 2 + n0[2] ** 2) ** 0.5
            l1 = (n1[0] ** 2 + n1[1] ** 2 + n1[2] ** 2) ** 0.5
            if l0 <= 1e-12 or l1 <= 1e-12:
                return False
            if n0[0] * n1[0] + n0[1] * n1[1] + n0[2] * n1[2] < _MAX_TURN_COS * l0 * l1:
                return False
            new_quality = _quality([pos[q] if node_of[i] == p else pos[node_of[i]] for i in f], l1)
            if new_quality < _MIN_QUALITY and new_quality < _quality([pos[node_of[i]] for i in f], l0):
                return False
            if frozenset(q if node_of[i] == p else node_of[i] for i in f) in q_tris:
                return False
            # How far the surface moved at p: its distance to the nearest new triangle.
            moved = min(moved, _point_triangle_distance(
                pos[p], [pos[q] if node_of[i] == p else pos[node_of[i]] for i in f]))
        new_reach = max(reach[q], reach[p] + (moved if moved != float("inf") else 0.0))
        if max_move is not None and new_reach > max_move:
            return False
        for fi in shared:
            alive[fi] = False
            mat_faces[fmat[fi]] -= 1
            for i in faces[fi]:
                node_faces[node_of[i]].discard(fi)
                ref(i, -1)
        for fi in fp:
            f = faces[fi]
            for k, i in enumerate(f):
                if node_of[i] == p:
                    f[k] = mapping[vcls[i]]
                    ref(i, -1)
                    ref(f[k], +1)
            node_faces[q].add(fi)
        fp.clear()
        quad[q] = [s + t for s, t in zip(quad[q], quad[p])]
        reach[q] = new_reach
        return True

    while live > target_vertices and heap:
        _, p, q, vp, vq = heapq.heappop(heap)
        if vp != version[p] or vq != version[q]:
            continue                                   # superseded by a fresher entry
        if try_collapse(p, q):
            version[p] += 1
            version[q] += 1
            for m in neighbours(q):
                push(q, m)
                push(m, q)

    # Rebuild. Records keep their original order, so each material's stay contiguous.
    used = sorted({i for fi, f in enumerate(faces) if alive[fi] for i in f})
    remap = {old: new for new, old in enumerate(used)}
    out_vertices = [Vertex(**vars(verts[i])) for i in used]
    out_faces: list[tuple[int, int, int]] = []
    out_materials: list[Material] = []
    vcursor = 0
    for mi, m in enumerate(mesh.materials):
        fstart = len(out_faces)
        for fi in range(m.face_start, m.face_end):
            if alive[fi]:
                a, b, c = faces[fi]
                out_faces.append((remap[a], remap[b], remap[c]))
        vstart = vcursor
        while vcursor < len(used) and vmat[used[vcursor]] == mi:
            vcursor += 1
        out_materials.append(Material(m.name, vstart, vcursor, fstart, len(out_faces)))

    result = Mesh(vertices=out_vertices, materials=out_materials, faces=out_faces, version=mesh.version)
    _compute_vertex_normals(result)
    return result


def parts(mesh: Mesh) -> list[tuple[float, list[int]]]:
    """The mesh's separate pieces, as (size, face indices): triangles joined through shared
    positions (welded, so a piece split over materials or UV seams is still one piece).
    Size is sqrt(longest x middle extent of its bounding box) -- roughly how big it looks
    side-on, so a 1.3 m bumper 9 cm thick counts as 0.35 m and an antenna 3 cm thick as
    0.23 m, where its thickness alone would call both tiny."""
    ids: dict[tuple[float, float, float], int] = {}
    node_of = [ids.setdefault(_weld_key(v), len(ids)) for v in mesh.vertices]
    parent = list(range(len(ids)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in mesh.faces:
        parent[find(node_of[a])] = find(node_of[b])
        parent[find(node_of[b])] = find(node_of[c])
    groups: dict[int, list[int]] = {}
    for fi, (a, b, c) in enumerate(mesh.faces):
        groups.setdefault(find(node_of[a]), []).append(fi)
    out = []
    for fl in groups.values():
        vs = [mesh.vertices[i] for i in {i for fi in fl for i in mesh.faces[fi]}]
        ext = sorted(max(getattr(v, k) for v in vs) - min(getattr(v, k) for v in vs) for k in "xyz")
        out.append(((ext[2] * ext[1]) ** 0.5, fl))
    return out


def drop_parts(mesh: Mesh, min_size: float) -> Mesh:
    """The mesh without the pieces smaller than `min_size` (parts()' size). The biggest
    piece always stays, so there is always something to draw. Whole pieces go, so nothing
    is torn: a far LOD sheds the mirrors and door handles rather than crushing them. A
    material whose pieces all went is left out, which is what the stock viper's own LODs
    do (its wheel and effects materials are gone from LOD 2 on)."""
    ps = parts(mesh)
    if not ps:
        return mesh
    biggest = max(ps, key=lambda t: t[0])
    keep = {fi for size, fl in ps if size >= min_size or fl is biggest[1] for fi in fl}
    if len(keep) == len(mesh.faces):
        return mesh
    vmat = [0] * len(mesh.vertices)
    for mi, m in enumerate(mesh.materials):
        for i in range(m.vertex_start, m.vertex_end):
            vmat[i] = mi
    used = sorted({i for fi in keep for i in mesh.faces[fi]})
    remap = {old: new for new, old in enumerate(used)}
    out_faces: list[tuple[int, int, int]] = []
    out_materials: list[Material] = []
    vcursor = 0
    for mi, m in enumerate(mesh.materials):
        fstart = len(out_faces)
        for fi in range(m.face_start, m.face_end):
            if fi in keep:
                a, b, c = mesh.faces[fi]
                out_faces.append((remap[a], remap[b], remap[c]))
        vstart = vcursor
        while vcursor < len(used) and vmat[used[vcursor]] == mi:
            vcursor += 1
        if len(out_faces) > fstart:     # a material left with nothing goes, as the stock LODs do
            out_materials.append(Material(m.name, vstart, vcursor, fstart, len(out_faces)))
    return Mesh(vertices=[Vertex(**vars(mesh.vertices[i])) for i in used],
                materials=out_materials, faces=out_faces, version=mesh.version)


def write_obj(mesh: Mesh, obj_path: str | Path, mtl_path: str | Path | None = None) -> None:
    obj_path = Path(obj_path)
    if mtl_path is None:
        mtl_path = obj_path.with_suffix(".mtl")
    else:
        mtl_path = Path(mtl_path)
    obj_text, mtl_text = to_obj(mesh, mtl_path.name)
    obj_path.write_text(obj_text, encoding="utf-8")
    mtl_path.write_text(mtl_text, encoding="utf-8")
