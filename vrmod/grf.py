"""
GRAF -- .grf track scenery mesh (props: trees, signs, crowd billboards, guard
rails, etc. -- the *visual* mesh only; collision/physics lives in .sol/.obt).

READ + IN-PLACE WRITE. parse() loads a real .grf for display; to_bytes()
writes edited mesh values back by PATCHING the original bytes, never by
rebuilding the file. See to_bytes() for the full rationale, but the short
version is that the main header is a scene-graph linked list that is still
only partly mapped, and 10-16% of every real file sits in node records in
the gaps BETWEEN chunks, threaded with pointers. Patching in place copies
all of that through untouched, so none of it has to be understood.

What that buys, and what it costs:
  - Can change any VALUE inside a chunk: vertex positions, UVs, texture
    names, face indices. So: move/rotate/scale an object, retexture it,
    edit its mapping.
  - Cannot change any SIZE: no adding or removing vertices, faces or
    materials, and a face can't be repointed into another chunk (face
    records store chunk-local indices). All of those raise GrfWriteError
    rather than producing a file the game might choke on.
  - Round-tripping an unmodified file is byte-identical -- verified on all
    8 stock tracks, and the whole 3.3 MB bemidji.trk repacks byte-identical
    through archive.replace_entry() too. That property is the safety net:
    any diff in an output file is something the caller actually asked for.

Building a .grf from scratch (Tier 2) additionally requires mapping the
scene graph. Note that assuming "the last 40 bytes of each inter-chunk gap
is a node header" holds for only 30-50% of gaps, so that work is a real
reverse-engineering effort, not a small extension of this module.

Confirmed structure (cross-checked byte-for-byte against real, independently
known ground truth: 3DSimED's per-object .grf->.mod extraction feature, which
dumps each real scenery object as its own standalone .mod file -- comparing
those against the raw track.grf bytes let every field below be verified
against real position/UV data rather than inferred from a synthetic test):

  Envelope: 0SER / FARG / version=3 / !IGM, then a main header (not fully
  mapped -- richer than the single flat corner/object/triangle-count fields
  a simplified/3DSimED-round-tripped .grf has at a fixed offset; real retail
  files need a resync from the start too, not just after each chunk).

  The mesh is a sequence of per-texture "chunks", each:
    - one 16-byte "center" record: the object's own placement/pivot position
      in world space -- (0, 0, 0) for an object modeled directly at its
      final position, non-zero for a template object instanced at many
      different spots (e.g. the many repeated crowd-billboard "heads.tex"
      objects, all sharing one small local shape placed at a different
      center each time):
        +0   center X                  float32
        +4   center Y                  float32
        +8   center Z                  float32
        +12  0                         int32 (constant -- validity check)
    - N x 32-byte "corner" records, one per face-corner (not deduplicated --
      a quad's 2 triangles get 4 corners here, matching the source mesh's
      corner count exactly, confirmed against 3DSimED's own per-object
      vertex counts with zero discrepancies across dozens of objects):
        +0   offset X (position - center X)   float32
        +4   offset Y (position - center Y)   float32
        +8   offset Z (position - center Z)   float32
        +12  0                         int32   (constant -- validity check)
        +16  0xFFFFFFFF                int32   (constant -- validity check)
        +20  0xFF000000                int32   (constant -- validity check)
        +24  UV.u                      float32 (this corner's own, un-shifted)
        +28  UV.v                      float32 (this corner's own, un-shifted
             -- NOT flipped, unlike an earlier version of this module which
             assumed a .mod-style v-flip and a UV "shifted back one corner"
             convention that turned out to be specific to simplified/
             3DSimED-authored exports, not the real retail format)
      Absolute position = center + (offset X, offset Y, offset Z). Verified
      exactly (full float32 precision) against real 3DSimED-extracted .mod
      ground truth for both a flat billboard (heads.tex, center far from
      origin, small offsets) and a fully 3D prop (rt2.tex, center at the
      origin, offsets equal to the real absolute position directly) --
      the same 8-field record shape covers both cases uniformly.
    - M x 32-byte MATERIAL records -- structurally identical to .mod's own
      material records: a null-terminated texture name, then (at a fixed
      offset from the END of the record, regardless of name length) 4 x
      int16 vertex_start, vertex_end, face_start, face_end. These chain
      exactly like .mod's do (material i's *_end == material i+1's
      *_start), and the last one's vertex_end equals the chunk's corner
      count. A chunk routinely carries SEVERAL materials -- an earlier
      version of this module assumed exactly one texture tag per chunk and
      silently dropped every secondary material's geometry, which is what
      made whole categories of real objects (e.g. Rock Island's 78
      Rky11.tex objects, Castlegreen's 37 b&w.tex objects) invisible.
    - F x 8-byte FACE records -- again identical to .mod's: 3 x int16
      corner indices (LOCAL to this chunk, SAME winding as .mod, no
      reversal) plus an int16 zero pad.

  So a .grf chunk is, structurally, a .mod mesh: vertices, then materials
  with corner/face sub-ranges, then faces. The material chain's two
  self-consistency properties (perfect chaining, last vertex_end == the
  corner count actually read) make it a strong validity test AND let each
  chunk's true end be computed exactly, rather than resynced for.

Resync is still used to find the FIRST chunk (real retail files have a
richer main header than the fixed-offset one a simplified/3DSimED-exported
.grf has), and as a fallback if a chunk ever fails to present a clean
material chain: scan forward for the next byte offset that looks like a
fresh center+corner0 pair, verified to actually parse through. Chunks that
resolve only through that fallback are marked exact=False and are excluded
from patching, since their record offsets were searched for rather than
computed. No stock track needs the fallback.
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass

from . import envelope
from .mod import Material, Mesh, Vertex, _compute_vertex_normals

TAG = b"FARG"

CENTER_SIZE = 16
CORNER_SIZE = 32
# 80 bytes from the start of the raw file, minus the 20-byte 0SER envelope
# (this module works on envelope.parse()'s payload, not raw file bytes).
MAIN_HEADER_SIZE = 60

CORNER_ZERO_OFFSET = 12
# +16 is real per-corner baked vertex color/shading (RGB varies -- e.g.
# 0xFFFFFFFF white for most small props, 0xFFFDFDFD-style near-white on
# grass/terrain), NOT a constant -- confirmed against real ground truth
# after an earlier version of this module wrongly required it to equal
# exactly -1 (0xFFFFFFFF), which silently rejected every real object with
# non-flat-white shading (grass/terrain in particular) as "invalid". Only
# the alpha byte (bits 24-31) is reliably constant (always opaque, 0xFF).
CORNER_MARKER1_OFFSET = 16
CORNER_MARKER1_ALPHA_MASK = 0xFF000000
CORNER_MARKER2_OFFSET = 20
CORNER_MARKER2_VALUE = -16777216  # 0xFF000000 as a signed int32 -- rock solid

_TAG_RE = re.compile(rb"([A-Za-z0-9_]{1,32}\.tex)\x00")

_RESYNC_WINDOW = 65536
# Byte-by-byte, not 4-byte-aligned: the scan's start position (right after a
# variable-length texture-name string) has no guaranteed alignment relative
# to the record fields' own 4-byte alignment within the file.
_RESYNC_STEP = 1

_POS_LIMIT = 1e6

# See _fan_triangulate_chunks(): real chunks span a wide range of corner
# counts (confirmed against ground truth up into the hundreds for legitimate
# grass/terrain patches), but a resync false-negative that silently merges
# several real chunks into one still shows up as an implausibly huge single
# chunk. Kept as a coarse safety net against that specific failure mode.
_MAX_FAN_CHUNK_SIZE = 400


def _finite_bounded(*values: float) -> bool:
    for f in values:
        if math.isnan(f) or math.isinf(f) or abs(f) > _POS_LIMIT:
            return False
    return True


def _looks_like_corner(data: bytes, off: int) -> bool:
    """Validity check for a single 32-byte corner record -- relies only on
    the three constant fields (rock solid across every real object checked
    against ground truth), not on the offset/UV values."""
    if off + CORNER_SIZE > len(data):
        return False
    zero = struct.unpack_from("<i", data, off + CORNER_ZERO_OFFSET)[0]
    if zero != 0:
        return False
    (m1_raw,) = struct.unpack_from("<I", data, off + CORNER_MARKER1_OFFSET)
    if (m1_raw & CORNER_MARKER1_ALPHA_MASK) != CORNER_MARKER1_ALPHA_MASK:
        return False
    m2 = struct.unpack_from("<i", data, off + CORNER_MARKER2_OFFSET)[0]
    if m2 != CORNER_MARKER2_VALUE:
        return False
    ox, oy, oz = struct.unpack_from("<3f", data, off)
    return _finite_bounded(ox, oy, oz)


def _looks_like_chunk_start(data: bytes, off: int) -> bool:
    """A candidate chunk start: a 16-byte center record whose first three
    fields are plausible world coordinates, immediately followed by a valid
    corner record.

    Deliberately does NOT require the center record's 4th field to be zero.
    It is zero for the vast majority of chunks, but not all -- a real
    track's trailing chunks carry a non-zero value there (e.g. 54), and an
    earlier version of this check rejected them outright, losing every
    object in the file's tail region. The material-chain validation in
    _read_chunk_at() is a far stronger filter than this field ever was, so
    it's safe to be permissive here and let that do the real rejecting."""
    if off + CENTER_SIZE > len(data):
        return False
    cx, cy, cz, _ = struct.unpack_from("<4f", data, off)
    if not _finite_bounded(cx, cy, cz):
        return False
    return _looks_like_corner(data, off + CENTER_SIZE)


MATERIAL_SIZE = 32
FACE_SIZE = 8
# 4 x int16 (vertex_start, vertex_end, face_start, face_end) sit at a fixed
# offset from the END of each 32-byte material record, regardless of how
# long the name is -- identical to .mod's own material convention.
MATERIAL_RANGE_OFFSET = 24

_MAT_NAME_RE = re.compile(rb"[ -~]{1,23}\Z")


def _read_materials(data: bytes, off: int, corner_count: int):
    """Read the chunk's .mod-style material records: 32 bytes each, a
    null-terminated texture name followed (at a fixed offset from the
    record's end) by 4 x int16 vertex_start/vertex_end/face_start/face_end.

    These chain exactly like .mod's do -- material i's *_end is material
    i+1's *_start -- and the last one's vertex_end must equal the number of
    corner records actually read. Both properties are checked here, which
    together make this a very strong validity test (far stronger than
    pattern-matching a single tag), and they're what lets a chunk's real
    end be computed exactly instead of resynced for.

    Returns (materials, offset_just_past_them) or (None, None) if the
    records don't form a valid chain covering exactly `corner_count`
    corners.
    """
    materials: list[tuple[str, int, int, int, int]] = []
    expect_v = 0
    expect_f = 0
    while off + MATERIAL_SIZE <= len(data):
        rec = data[off:off + MATERIAL_SIZE]
        zero = rec.find(b"\x00")
        # An EMPTY name (leading NUL) is legitimate and must not abort the
        # chain. Real files carry it: dundas's main ground chunk has a
        # middle material reading b"\x00exy.tex" -- the first character of
        # "texy.tex" overwritten with a NUL, the same corruption seen in
        # ground.mod's b"\x00exture.bmp". Its ranges still chain perfectly
        # and still reach the chunk's exact corner count, so bailing on the
        # name threw away a whole valid 131-corner terrain chunk and sent it
        # to fan-triangulation, which is what produced the big wedge
        # artifacts across the ground. The range chain is the real
        # validator; the name is just a label (untextured -> flat colour).
        if zero < 0 or (zero > 0 and not _MAT_NAME_RE.match(rec[:zero])):
            break
        vs, ve, fs, fe = struct.unpack_from("<4h", rec, MATERIAL_RANGE_OFFSET)
        if vs != expect_v or fs != expect_f or ve < vs or fe < fs:
            break
        materials.append((rec[:zero].decode("ascii", errors="replace"), vs, ve, fs, fe))
        expect_v, expect_f = ve, fe
        off += MATERIAL_SIZE
        if expect_v == corner_count:
            # Complete: this chunk's materials cover exactly the corner
            # records we read. Anything past here is face data.
            return materials, off
    return None, None


_FOOTER_HEADER_SEARCH = 256


def _find_triangle_footer(data: bytes, start: int, corner_count: int):
    """Search forward from `start` (right after the texture tag) for the
    footer's [0, cornerCount, 0, triCount] header (int16 x4) -- confirmed
    exact against real ground truth (3DSimED's per-object .mod extraction):
    cornerCount is already known from the just-parsed corner records, which
    pins this down precisely rather than assuming a fixed byte offset (the
    amount of leading padding/metadata before this header varies per
    chunk). Once found, reads triCount x [c0, c1, c2, 0] (local corner
    indices, SAME winding as .mod, trailing zero pad) right after it.
    Returns (triangles, end_pos) or (None, None) if no such header shows up
    within the search window."""
    end = min(len(data), start + _FOOTER_HEADER_SEARCH)
    # Step 1 byte, not 2: the texture-name string's length varies and is
    # often ODD (e.g. b"rail.tex\0" is 9 bytes), which puts the footer on
    # odd alignment relative to this scan's start. An earlier 2-byte step
    # silently missed every such chunk -- that alone was the difference
    # between a 62% and a 6% real-triangle hit rate across different
    # tracks, purely depending on whether their texture names happened to
    # have even-length names.
    for off in range(start, end - 8):
        a, b, c, tri_count = struct.unpack_from("<4h", data, off)
        if a == 0 and b == corner_count and c == 0 and 1 <= tri_count <= corner_count * 2:
            tri_start = off + 8
            if tri_start + tri_count * 8 > len(data):
                continue
            triangles = []
            ok = True
            for t in range(tri_count):
                c0, c1, c2, pad = struct.unpack_from("<4h", data, tri_start + t * 8)
                if pad != 0 or not (0 <= c0 < corner_count and 0 <= c1 < corner_count and 0 <= c2 < corner_count):
                    ok = False
                    break
                triangles.append((c0, c1, c2))
            if ok:
                return triangles, tri_start + tri_count * 8
    return None, None


@dataclass
class _RawChunk:
    """One parsed chunk, plus the exact payload byte offset of every record
    it owns -- that offset bookkeeping is what makes the in-place write path
    (to_bytes()) possible without understanding the scene-graph header."""
    center: tuple[float, float, float]
    center_offset: int
    corners: list[tuple[float, float, float, float, float]]
    corner_offsets: list[int]
    materials: list[tuple[str, int, int, int, int]]
    material_offsets: list[int]
    triangles: list[tuple[int, int, int]] | None
    face_offsets: list[int]
    next_pos: int
    # True when the chunk resolved through the material chain, meaning every
    # record's position is known exactly and the chunk is safe to patch.
    # False for the legacy single-tag fallback, whose footer layout is only
    # located by search -- those chunks still render but are not writable.
    exact: bool


def _read_chunk_at(data: bytes, pos: int):
    """Tentatively parse one chunk (center + corner records + texture tag +
    triangle-index footer) starting exactly at `pos`. Returns None if this
    position doesn't actually lead to a texture tag right where one should
    be -- used both for the real parse and to verify resync candidates, so
    a position that merely *looks* like a valid center+corner0 pair (a
    false positive somewhere inside an unknown-length footer) doesn't get
    accepted just because its first bytes happen to pass the generic
    validity check.

    Returns a _RawChunk, or None. Its `triangles` is None when the footer's
    triangle-index header couldn't be found within the search window (some
    chunks, e.g. batched same-texture groups, don't have one right after
    their own tag) -- the caller falls back to fan-triangulation for those,
    and next_pos is just past the tag in that case since the real footer
    length is then unknown."""
    if not _looks_like_chunk_start(data, pos):
        return None
    cx, cy, cz, _ = struct.unpack_from("<4f", data, pos)
    p = pos + CENTER_SIZE
    corners: list[tuple[float, float, float, float, float]] = []
    corner_offsets: list[int] = []
    while _looks_like_corner(data, p):
        ox, oy, oz = struct.unpack_from("<3f", data, p)
        u, v = struct.unpack_from("<2f", data, p + 24)
        corners.append((cx + ox, cy + oy, cz + oz, u, v))
        corner_offsets.append(p)
        p += CORNER_SIZE
    if not corners:
        return None

    mat_start = p
    materials, mat_end = _read_materials(data, p, len(corners))
    if materials is not None:
        # Real, fully-resolved chunk: materials chained cleanly and cover
        # exactly the corners read, so the face records start right after
        # them and the chunk's true end is computable exactly (no resync
        # guessing needed to find the next chunk).
        face_count = materials[-1][4]
        faces_end = mat_end + face_count * FACE_SIZE
        if faces_end <= len(data):
            triangles = []
            face_offsets = []
            ok = True
            for f in range(face_count):
                fo = mat_end + f * FACE_SIZE
                c0, c1, c2, pad = struct.unpack_from("<4h", data, fo)
                if not (0 <= c0 < len(corners) and 0 <= c1 < len(corners) and 0 <= c2 < len(corners)):
                    ok = False
                    break
                triangles.append((c0, c1, c2))
                face_offsets.append(fo)
            if ok:
                # Records are contiguous fixed-size runs, so every offset
                # here is exact rather than searched-for.
                return _RawChunk(
                    center=(cx, cy, cz),
                    center_offset=pos,
                    corners=corners,
                    corner_offsets=corner_offsets,
                    materials=materials,
                    material_offsets=[mat_start + i * MATERIAL_SIZE for i in range(len(materials))],
                    triangles=triangles,
                    face_offsets=face_offsets,
                    next_pos=faces_end,
                    exact=True,
                )

    # Fall back to the older single-tag path for anything that doesn't
    # present a clean material chain (kept so a chunk shaped unlike
    # anything seen so far still contributes its geometry rather than
    # stopping the walk outright). Not writable: the footer is located by
    # search, so its records' offsets aren't trustworthy enough to patch.
    m = _TAG_RE.match(data, p)
    if not m:
        return None
    texture_name = m.group(1).decode("ascii", errors="replace")
    triangles, tri_end = _find_triangle_footer(data, m.end(), len(corners))
    single = [(texture_name, 0, len(corners), 0, len(triangles) if triangles else 0)]
    next_pos = tri_end if triangles is not None else m.end()
    return _RawChunk(
        center=(cx, cy, cz),
        center_offset=pos,
        corners=corners,
        corner_offsets=corner_offsets,
        materials=single,
        material_offsets=[],
        triangles=triangles,
        face_offsets=[],
        next_pos=next_pos,
        exact=False,
    )


def _find_next_chunk(data: bytes, pos: int):
    """Scan forward (byte-by-byte, bounded window) for the next position
    that both looks like a fresh chunk start AND actually parses through to
    a real texture tag -- rejects false-positive center/corner-shaped
    garbage inside an unknown-length footer that doesn't lead anywhere
    real."""
    end = min(len(data), pos + _RESYNC_WINDOW)
    for off in range(pos, end, _RESYNC_STEP):
        if not _looks_like_chunk_start(data, off):
            continue
        result = _read_chunk_at(data, off)
        if result is not None:
            return off, result
    return None, None


@dataclass
class Chunk:
    texture: str
    corner_start: int
    corner_end: int


@dataclass
class ChunkLayout:
    """Where one chunk's records physically live in the payload, so their
    values can be rewritten in place. `center` is needed to patch a vertex:
    corner records store position MINUS center, so writing an absolute
    position back means re-deriving the offset against this same center."""
    center: tuple[float, float, float]
    center_offset: int
    corner_offsets: list[int]
    material_offsets: list[int]
    face_offsets: list[int]
    # Global (whole-mesh) index of this chunk's first corner and first face,
    # for translating between mesh-level and chunk-local indices.
    vertex_base: int
    face_base: int
    exact: bool


@dataclass
class GrfMesh:
    mesh: Mesh
    chunks: list[Chunk]
    # Everything below supports the in-place write path (to_bytes()).
    layout: list[ChunkLayout] = None  # type: ignore[assignment]
    payload: bytes = b""
    version: int = 3
    # Parallel to mesh.vertices / mesh.faces / mesh.materials: which chunk
    # each one came from, or -1 for entries with no writable backing record
    # (fan-triangulated faces, fallback-path chunks).
    vertex_chunk: list[int] = None  # type: ignore[assignment]
    face_chunk: list[int] = None  # type: ignore[assignment]
    # Payload byte offset of each material's own 32-byte record, or -1 when
    # it has none (fallback-path chunks). Stored directly rather than as a
    # chunk index plus a local slot, since materials are the one array whose
    # per-chunk slot isn't derivable from a simple base offset.
    material_offset: list[int] = None  # type: ignore[assignment]

    @property
    def writable(self) -> bool:
        return bool(self.layout) and all(c.exact for c in self.layout)


def parse(data: bytes) -> GrfMesh:
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .grf file: tag {env.tag!r}, expected {TAG!r}")
    payload = env.payload

    corners: list[list[float]] = []  # [x, y, z, u, v]
    chunks: list[Chunk] = []
    materials: list[Material] = []
    faces: list[tuple[int, int, int]] = []
    layout: list[ChunkLayout] = []
    vertex_chunk: list[int] = []
    face_chunk: list[int] = []
    material_offset: list[int] = []
    pos = MAIN_HEADER_SIZE

    result = _read_chunk_at(payload, pos)
    if result is None:
        # First chunk doesn't start exactly at MAIN_HEADER_SIZE for every
        # file -- real retail files have a richer main header (a scene-graph
        # node structure, not fully mapped) and push it later, while some
        # files start EARLIER than MAIN_HEADER_SIZE (a real fan-made track
        # starts its first chunk at 52). So rescan from the very beginning
        # rather than from MAIN_HEADER_SIZE, which would skip straight past
        # any chunk sitting before that offset.
        found_pos, result = _find_next_chunk(payload, 0)
        if found_pos is not None:
            pos = found_pos

    while result is not None:
        chunk_corners = result.corners
        chunk_materials = result.materials
        triangles = result.triangles
        next_pos = result.next_pos
        chunk_index = len(layout)
        chunk_start_corner = len(corners)
        corners.extend([list(c) for c in chunk_corners])
        chunk_end_corner = len(corners)
        n = chunk_end_corner - chunk_start_corner
        chunk_face_start = len(faces)
        vertex_chunk.extend([chunk_index] * n)
        layout.append(ChunkLayout(
            center=result.center,
            center_offset=result.center_offset,
            corner_offsets=result.corner_offsets,
            material_offsets=result.material_offsets,
            face_offsets=result.face_offsets,
            vertex_base=chunk_start_corner,
            face_base=chunk_face_start,
            exact=result.exact,
        ))

        if triangles is not None:
            # Real face data straight out of the chunk's own face records --
            # local indices, same winding as .mod, confirmed byte-exact
            # against real ground truth.
            faces.extend(
                (chunk_start_corner + c0, chunk_start_corner + c1, chunk_start_corner + c2)
                for c0, c1, c2 in triangles
            )
        elif n <= _MAX_FAN_CHUNK_SIZE:
            # Couldn't resolve this chunk's real faces -- fan-triangulate
            # the corner run instead (correct for a triangle or a quad,
            # a reasonable convex approximation otherwise).
            for i in range(1, n - 1):
                faces.append((chunk_start_corner, chunk_start_corner + i, chunk_start_corner + i + 1))

        # One Material per REAL material, using its own corner/face
        # sub-ranges -- a single chunk routinely carries several (that's
        # the multi-material case an earlier version of this module missed
        # entirely, silently dropping every secondary material's geometry).
        # Faces added above are backed by real records only on the exact
        # path; fan-triangulated ones have no record to write back to.
        backed = result.exact and triangles is not None
        face_chunk.extend([chunk_index if backed else -1] * (len(faces) - chunk_face_start))

        if triangles is not None:
            for mi, (name, vs, ve, fs, fe) in enumerate(chunk_materials):
                chunks.append(Chunk(texture=name, corner_start=chunk_start_corner + vs, corner_end=chunk_start_corner + ve))
                materials.append(Material(
                    name,
                    chunk_start_corner + vs, chunk_start_corner + ve,
                    chunk_face_start + fs, chunk_face_start + fe,
                ))
                material_offset.append(result.material_offsets[mi] if result.exact else -1)
        else:
            name = chunk_materials[0][0]
            chunks.append(Chunk(texture=name, corner_start=chunk_start_corner, corner_end=chunk_end_corner))
            materials.append(Material(name, chunk_start_corner, chunk_end_corner, chunk_face_start, len(faces)))
            material_offset.append(-1)

        pos = next_pos
        found_pos, result = _find_next_chunk(payload, pos)
        if found_pos is not None:
            pos = found_pos

    vertices = [Vertex(c[0], c[1], c[2], 0.0, 0.0, 0.0, c[3], c[4]) for c in corners]
    mesh = Mesh(vertices=vertices, materials=materials, faces=faces)
    if faces:
        _compute_vertex_normals(mesh)
    return GrfMesh(
        mesh=mesh,
        chunks=chunks,
        layout=layout,
        payload=payload,
        version=env.version,
        vertex_chunk=vertex_chunk,
        face_chunk=face_chunk,
        material_offset=material_offset,
    )


def parse_file(path) -> GrfMesh:
    from pathlib import Path
    return parse(Path(path).read_bytes())


# Name field of a material record: bytes 0..MATERIAL_RANGE_OFFSET, so the
# longest storable name is one less than that (a NUL terminator must fit).
MAX_MATERIAL_NAME = MATERIAL_RANGE_OFFSET - 1


class GrfWriteError(ValueError):
    """A requested edit can't be expressed as an in-place patch."""


def _patch_f32(buf: bytearray, off: int, value: float) -> None:
    """Write a float32 only if it actually differs from what's already
    there, comparing by VALUE rather than by bytes.

    The distinction matters for negative zero. Real files carry -0.0 corner
    offsets, and parsing computes position = center + offset, so a -0.0
    offset comes back as position == center; writing it out again as
    (position - center) yields +0.0, a different bit pattern for an
    identical number. Byte-comparing would rewrite those and leave a diff
    in a file the caller never edited -- 13 such bytes in uptown, 409 in
    heaven. Comparing by value leaves the original bits untouched, which is
    what makes an unmodified round-trip byte-exact."""
    (cur,) = struct.unpack_from("<f", buf, off)
    if cur == value or (math.isnan(cur) and math.isnan(value)):
        return
    struct.pack_into("<f", buf, off, value)


def to_bytes(grf_mesh: GrfMesh) -> bytes:
    """Rewrite `grf_mesh`'s current mesh values back into the original
    payload IN PLACE and return complete file bytes (envelope included).

    This is deliberately a patcher, not a builder. Every byte outside the
    corner/material/face records -- the scene-graph main header, the node
    records in the gaps between chunks, and all the pointers threaded
    through them -- is copied through untouched, which is what makes the
    write safe without those structures being understood. The direct
    consequence is that nothing may change SIZE: vertex, face and material
    counts are fixed, and a face may not move to a different chunk (its
    record stores an index local to its own chunk).

    Round-tripping an unmodified GrfMesh reproduces the input byte for byte
    -- corner offsets are recovered as (position - center), which is exact
    in float32, and records whose values are unchanged are not rewritten at
    all. Verified against all 8 stock tracks.

    Raises GrfWriteError if an edit can't be represented.
    """
    m = grf_mesh.mesh
    if not grf_mesh.layout:
        raise GrfWriteError("this GrfMesh carries no layout (parsed by an older version?)")
    if len(grf_mesh.vertex_chunk) != len(m.vertices):
        raise GrfWriteError(
            f"vertex count changed ({len(grf_mesh.vertex_chunk)} -> {len(m.vertices)}); "
            "in-place patching cannot add or remove geometry"
        )
    if len(grf_mesh.face_chunk) != len(m.faces):
        raise GrfWriteError(
            f"face count changed ({len(grf_mesh.face_chunk)} -> {len(m.faces)}); "
            "in-place patching cannot add or remove faces"
        )
    if len(grf_mesh.material_offset) != len(m.materials):
        raise GrfWriteError(
            f"material count changed ({len(grf_mesh.material_offset)} -> {len(m.materials)})"
        )

    buf = bytearray(grf_mesh.payload)

    # --- corners: position (stored relative to the chunk center) and UV ---
    for i, v in enumerate(m.vertices):
        ci = grf_mesh.vertex_chunk[i]
        if ci < 0:
            continue
        lay = grf_mesh.layout[ci]
        off = lay.corner_offsets[i - lay.vertex_base]
        cx, cy, cz = lay.center
        try:
            _patch_f32(buf, off, v.x - cx)
            _patch_f32(buf, off + 4, v.y - cy)
            _patch_f32(buf, off + 8, v.z - cz)
            _patch_f32(buf, off + 24, v.u)
            _patch_f32(buf, off + 28, v.v)
        except (OverflowError, struct.error) as exc:
            raise GrfWriteError(f"vertex {i} not representable as float32: {exc}") from exc

    # --- materials: texture name only; the range fields are structural and
    # are recomputed from the (fixed) counts, never taken from the caller ---
    for i, mat in enumerate(m.materials):
        off = grf_mesh.material_offset[i]
        if off < 0:
            continue
        name = mat.name
        encoded = name.encode("ascii", errors="strict") if name else b""
        if len(encoded) > MAX_MATERIAL_NAME:
            raise GrfWriteError(
                f"texture name {name!r} is {len(encoded)} bytes; the material record "
                f"holds at most {MAX_MATERIAL_NAME}"
            )
        cur_end = buf.find(b"\x00", off, off + MATERIAL_RANGE_OFFSET)
        cur = bytes(buf[off:cur_end]) if cur_end >= 0 else b""
        if cur != encoded:
            # Only touched when the name actually changed, so trailing bytes
            # after the original terminator stay byte-identical otherwise.
            buf[off:off + MATERIAL_RANGE_OFFSET] = encoded.ljust(MATERIAL_RANGE_OFFSET, b"\x00")

    # --- faces: 3 local corner indices (the 4th int16 pad is left alone) ---
    for i, face in enumerate(m.faces):
        ci = grf_mesh.face_chunk[i]
        if ci < 0:
            continue
        lay = grf_mesh.layout[ci]
        off = lay.face_offsets[i - lay.face_base]
        local = []
        for gi in face:
            if not (0 <= gi < len(m.vertices)) or grf_mesh.vertex_chunk[gi] != ci:
                raise GrfWriteError(
                    f"face {i} references vertex {gi}, which is outside its own chunk; "
                    "face records store chunk-local indices, so a face cannot be "
                    "repointed at another chunk's geometry"
                )
            local.append(gi - lay.vertex_base)
        new = struct.pack("<3h", *local)
        if buf[off:off + 6] != new:
            buf[off:off + 6] = new

    return envelope.build(TAG, grf_mesh.version, bytes(buf))


def write_file(path, grf_mesh: GrfMesh) -> None:
    from pathlib import Path
    Path(path).write_bytes(to_bytes(grf_mesh))


# ---------------------------------------------------------------------------
# Building a .grf from nothing
#
# to_bytes() above is a patcher: it rewrites values inside a payload it parsed
# and forbids anything that changes size. What follows builds the payload
# outright, which is what a generated track needs.
#
# The layout, measured against a freshly compiled track (553 chunks) and checked
# against the shipped ones:
#
#   payload
#     +00  i32 0, i32 0, i32 12          file header; 12 is the first chunk
#     then a chain of chunks, each:
#       +00  i32   3                     chunk type
#       +04  i32   offset of the NEXT chunk header, 0 at the end
#       +08  i32   0
#       +0c  i32   -1
#       +10  i32   corner count
#       +14  i32   0
#       +18  i32   1
#       +1c  i32   0
#       +20  i32   face count
#       +24  3f    chunk centre; corner positions are stored relative to it
#       +30  zero
#       +38  corners   count x 32
#            material  32
#            faces     count x 8
#
# A corner is position(3f) relative to the centre, a zero u32, a BGRA vertex
# colour, a constant 00 00 00 ff, then UV(2f). A face is three u16 indices local
# to its chunk plus a zero. A material is a NUL-padded texture name with the
# corner and face counts repeated at +26 and +30.
#
# One caveat worth stating plainly: the chain built here is FLAT -- every chunk
# points at the next. That is exactly what nhmkworld emits for a track made of
# many small uniform meshes, and such a track renders correctly in game. The
# shipped tracks are not flat: bemidji has 446 chunks but only 2 in its chain,
# so there is a nesting this does not reproduce and does not need to.

FILE_HEADER = 12
CHUNK_HEADER = 56
CORNER = 32
FACE = 8
MATERIAL = 32
CHUNK_TYPE = 3
NAME_FIELD = 26

# The two constants inside every corner record, established by surveying every
# corner of every track on hand.
CORNER_PAD = b"\x00\x00\x00\x00"
CORNER_TAIL = b"\x00\x00\x00\xff"
WHITE = b"\xff\xff\xff\xff"


def _corner(x: float, y: float, z: float, u: float, v: float,
            colour: bytes = WHITE) -> bytes:
    return (struct.pack("<3f", x, y, z) + CORNER_PAD + colour + CORNER_TAIL
            + struct.pack("<2f", u, v))


def _material(texture: str, corners: int, faces: int) -> bytes:
    name = texture.encode("latin-1")[:NAME_FIELD - 1]
    rec = bytearray(MATERIAL)
    rec[0:len(name)] = name
    struct.pack_into("<H", rec, 26, corners)
    struct.pack_into("<H", rec, 30, faces)
    return bytes(rec)


def build_chunk(mesh, texture: str, *, centre=(0.0, 0.0, 0.0),
                next_offset: int = 0, colours=None) -> bytes:
    """One chunk: header, corners, material, faces.

    `next_offset` is patched by build() once every chunk's size is known, so
    callers normally leave it at 0.
    """
    n, f = len(mesh.vertices), len(mesh.faces)
    if n > 0xFFFF:
        raise GrfWriteError(f"chunk has {n:,} corners; face indices are u16")
    head = bytearray(CHUNK_HEADER)
    struct.pack_into("<i", head, 0, CHUNK_TYPE)
    struct.pack_into("<i", head, 4, next_offset)
    struct.pack_into("<i", head, 12, -1)
    struct.pack_into("<i", head, 16, n)
    struct.pack_into("<i", head, 24, 1)
    struct.pack_into("<i", head, 32, f)
    struct.pack_into("<3f", head, 36, *centre)

    body = bytearray(head)
    cx, cy, cz = centre
    for i, vert in enumerate(mesh.vertices):
        colour = colours[i] if colours else WHITE
        body += _corner(vert.x - cx, vert.y - cy, vert.z - cz, vert.u, vert.v, colour)
    body += _material(texture, n, f)
    for a, b, c in mesh.faces:
        body += struct.pack("<4H", a, b, c, 0)
    return bytes(body)


def build(chunks: list[tuple], version: int = 3) -> bytes:
    """Build a complete `.grf` from (mesh, texture) pairs, envelope included.

    Each pair becomes one chunk. Sizes are computed first so each chunk header
    can name the offset of the next, and the last is terminated with 0.
    """
    if not chunks:
        raise GrfWriteError("a .grf needs at least one chunk")

    blobs = [build_chunk(m, t) for m, t in chunks]
    offsets = []
    at = FILE_HEADER
    for b in blobs:
        offsets.append(at)
        at += len(b)

    out = bytearray(struct.pack("<3i", 0, 0, FILE_HEADER))
    for i, b in enumerate(blobs):
        nxt = offsets[i + 1] if i + 1 < len(blobs) else 0
        patched = bytearray(b)
        struct.pack_into("<i", patched, 4, nxt)
        out += patched
    return envelope.build(TAG, version, bytes(out))
