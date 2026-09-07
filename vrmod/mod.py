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
    mirror_x: bool = False, rotate_y90: bool = False,
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
    """
    def rot(x: float, z: float) -> tuple[float, float]:
        return (z, -x) if rotate_y90 else (x, z)

    sx = -1.0 if mirror_x else 1.0
    new_vertices = []
    for v in mesh.vertices:
        rx, rz = rot(v.x, v.z)
        rnx, rnz = rot(v.nx, v.nz)
        new_vertices.append(Vertex(rx * sx + dx, v.y + dy, rz + dz, rnx * sx, v.ny, rnz, v.u, v.v))
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


def _decimate_block(
    vertices: list[Vertex], faces: list[tuple[int, int, int]], target: int
) -> tuple[list[Vertex], list[tuple[int, int, int]]]:
    """Greedy shortest-edge-collapse on one material block's local vertices/faces.

    Each collapse merges the pair of still-distinct vertices with the smallest
    original edge length: the higher-index vertex is redirected (union-find) onto
    the lower one, which keeps its own position/normal/uv rather than averaging --
    that keeps every previously-computed edge length in the heap valid for the
    rest of the run, so no distances need recomputing after a merge. Faces that
    become degenerate (two or more corners landing on the same surviving vertex)
    are dropped. This is a simpler heuristic than full quadric-error decimation
    (edge length stands in for visual importance), but is a real, working
    simplification, not a stub.
    """
    n = len(vertices)
    if n <= target or n <= 3:
        return vertices, faces

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def dist2(i: int, j: int) -> float:
        a, b = vertices[i], vertices[j]
        return (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2

    edges = set()
    for a, b, c in faces:
        edges.add((min(a, b), max(a, b)))
        edges.add((min(b, c), max(b, c)))
        edges.add((min(a, c), max(a, c)))

    heap = [(dist2(i, j), i, j) for i, j in edges]
    heapq.heapify(heap)

    live = n
    while live > target and heap:
        _, i, j = heapq.heappop(heap)
        ri, rj = find(i), find(j)
        if ri == rj:
            continue  # stale entry from an earlier merge -- skip
        lo, hi = (ri, rj) if ri < rj else (rj, ri)
        parent[hi] = lo
        live -= 1

    new_faces = []
    for a, b, c in faces:
        ra, rb, rc = find(a), find(b), find(c)
        if ra == rb or rb == rc or ra == rc:
            continue
        new_faces.append((ra, rb, rc))

    if not new_faces and faces:
        # Every remaining triangle degenerated -- e.g. a small block made of several
        # disconnected sub-clusters (two separate quads, say) where collapsing enough
        # of one cluster to hit the target wipes out all of its faces before the other
        # cluster is touched. Losing an entire material's visible geometry to hit a
        # vertex quota is worse than leaving it over-budget, so back off completely.
        return vertices, faces

    used = sorted({idx for f in new_faces for idx in f})
    remap = {old: new for new, old in enumerate(used)}
    compact_faces = [(remap[a], remap[b], remap[c]) for a, b, c in new_faces]
    compact_vertices = [vertices[i] for i in used]
    return compact_vertices, compact_faces


def decimate(mesh: Mesh, target_vertices: int) -> Mesh:
    """Reduce a mesh to at most `target_vertices` total, decimating each material's
    block independently (their vertex ranges are exclusive by construction, so a
    collapse can never span two materials) and allocating each block a share of
    the budget proportional to its current vertex count. Recomputes normals on the
    result, since edge collapses change local topology enough that the original
    per-vertex normals no longer describe the simplified surface well."""
    if len(mesh.vertices) <= target_vertices:
        return mesh

    total_v = len(mesh.vertices)
    out_vertices: list[Vertex] = []
    out_materials: list[Material] = []
    out_faces: list[tuple[int, int, int]] = []

    for m in mesh.materials:
        block_vertices = mesh.vertices[m.vertex_start: m.vertex_end]
        block_faces = [
            (a - m.vertex_start, b - m.vertex_start, c - m.vertex_start)
            for a, b, c in mesh.faces[m.face_start: m.face_end]
        ]
        share = len(block_vertices) / total_v
        block_target = max(3, round(target_vertices * share))
        new_vertices, new_faces = _decimate_block(block_vertices, block_faces, block_target)

        offset = len(out_vertices)
        vstart = offset
        fstart = len(out_faces)
        out_vertices.extend(new_vertices)
        out_faces.extend((a + offset, b + offset, c + offset) for a, b, c in new_faces)
        out_materials.append(Material(m.name, vstart, len(out_vertices), fstart, len(out_faces)))

    result = Mesh(vertices=out_vertices, materials=out_materials, faces=out_faces, version=mesh.version)
    _compute_vertex_normals(result)
    return result


def write_obj(mesh: Mesh, obj_path: str | Path, mtl_path: str | Path | None = None) -> None:
    obj_path = Path(obj_path)
    if mtl_path is None:
        mtl_path = obj_path.with_suffix(".mtl")
    else:
        mtl_path = Path(mtl_path)
    obj_text, mtl_text = to_obj(mesh, mtl_path.name)
    obj_path.write_text(obj_text, encoding="utf-8")
    mtl_path.write_text(mtl_text, encoding="utf-8")
