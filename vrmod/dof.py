"""Racer `.dof` — the format Bob's Track Builder exports that carries everything.

BTB will not export a centreline curve, and its OBJ option does not exist, so the
established route into Viper Racing has been `.dof` → Zmodeler (to map textures)
→ `.mod`, plus a separate `.3ds` → 3DS Max pass to draw a centreline spline by
hand. Neither detour is necessary: `.dof` already holds the UVs, and a
centreline can be recovered from the road surface itself (see
`trackgen.centreline_from_meshes`).

The format is chunked, `4-char tag` + `int32 length`, nested — the same shape as
Viper's own resources:

```
DOF1
  MATS   int32 count, then one MAT0 per material
    MAT0
      MHDR   u16 name length, then the name
      MTEX   int32, u16 length, then the texture filename
      MEND
  GEOB   int32 count, then one GOB1 per object
    GOB1
      GHDR   three int32; the THIRD is the material index
      INDI   int32 count, then u16 triangle indices
      VERT   int32 count, then float3 positions
      TVER   int32 count, then float2 texture coordinates
      NORM   int32 count, then float3 normals
```

Sizes cross-check exactly on a real export: 2,480 vertices give a 19,844-byte
TVER (2480x8+4) and a 29,764-byte NORM (2480x12+4).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import mod

MAGIC = b"DOF1"


class DofError(ValueError):
    pass


@dataclass
class Material:
    name: str
    texture: str = ""

    @property
    def tex_name(self) -> str:
        """The material name Viper wants: the texture's stem plus `.tex`.

        Texture resolution in Viper is by NAME, and a material without the `.tex`
        suffix does not resolve -- confirmed in game while getting custom car
        models to load. BTB names its textures `road_tarmac001.tga`, so the stem
        is what carries over.
        """
        stem = Path(self.texture).stem if self.texture else self.name
        return f"{stem}.tex"


@dataclass
class Object:
    material: int = 0
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)

    @property
    def faces(self) -> list[tuple[int, int, int]]:
        it = iter(self.indices)
        return [(a, b, c) for a, b, c in zip(it, it, it)]


@dataclass
class Dof:
    materials: list[Material] = field(default_factory=list)
    objects: list[Object] = field(default_factory=list)


def _chunks(data: bytes, pos: int, end: int):
    """Walk sibling chunks between `pos` and `end`."""
    while pos + 8 <= end:
        tag = data[pos:pos + 4]
        size = struct.unpack_from("<i", data, pos + 4)[0]
        if size < 0:
            return
        if pos + 8 + size > end:
            size = end - pos - 8          # clamp an over-long child, do not drop it
            if size <= 0:
                return
        yield tag, pos + 8, size
        pos += 8 + size


def _counted(data: bytes, off: int, fmt: str, width: int):
    n = struct.unpack_from("<i", data, off)[0]
    at = off + 4
    return [struct.unpack_from(fmt, data, at + i * width) for i in range(n)]


def parse(data: bytes) -> Dof:
    if data[:4] != MAGIC:
        raise DofError(f"not a .dof: magic {data[:4]!r}, expected {MAGIC!r}")
    # DOF1's declared length is not always consistent with its children: a real
    # BTB export has GEOB running 8 bytes past what DOF1 claims. The file itself
    # is the authority, so the declared total is used only as a sanity hint.
    total = struct.unpack_from("<i", data, 4)[0]
    if not 0 < total <= len(data):
        total = len(data) - 8
    end = len(data)

    out = Dof()
    for tag, off, size in _chunks(data, 8, end):
        if tag == b"MATS":
            for mtag, moff, msize in _chunks(data, off + 4, off + size):
                if mtag != b"MAT0":
                    continue
                m = Material(name="")
                for stag, soff, ssize in _chunks(data, moff, moff + msize):
                    if stag == b"MHDR":
                        ln = struct.unpack_from("<H", data, soff)[0]
                        m.name = data[soff + 2:soff + 2 + ln].decode("latin-1").rstrip("\x00")
                    elif stag == b"MTEX":
                        # int32, then a u16 length, then the name: 4 + 2 + 18 = 24
                        ln = struct.unpack_from("<H", data, soff + 4)[0]
                        m.texture = data[soff + 6:soff + 6 + ln].decode("latin-1").rstrip(chr(0))
                out.materials.append(m)
        elif tag == b"GEOB":
            # GOB1's declared size cannot be trusted -- in a real export it is 8
            # bytes short of its own children, so following it lands in the
            # middle of the next object rather than at its header. (It also has a
            # BRST chunk after NORM that the size does not cover.) Walking the
            # region as a flat stream sidesteps the question: GOB1 is treated as
            # a marker that starts a new object, and its children follow as
            # siblings until the next one.
            pos, end_geob = off + 4, min(off + size, len(data))
            current: Object | None = None
            while pos + 8 <= end_geob:
                stag = data[pos:pos + 4]
                ssize = struct.unpack_from("<i", data, pos + 4)[0]
                soff = pos + 8
                # isalpha() is wrong here: GOB1 and MAT0 both carry a digit
                if not stag.isalnum() or ssize < 0 or soff + ssize > len(data):
                    break
                if stag == b"GOB1":
                    current = Object()
                    out.objects.append(current)
                    pos = soff                      # descend, do not skip the body
                    continue
                if current is not None:
                    if stag == b"GHDR":
                        # three int32; the material index is the THIRD, not the
                        # first -- both are zero on the first object, which makes
                        # the wrong one look right until a second object appears
                        current.material = struct.unpack_from("<i", data, soff + 8)[0]
                    elif stag == b"INDI":
                        current.indices = [v[0] for v in _counted(data, soff, "<H", 2)]
                    elif stag == b"VERT":
                        current.positions = _counted(data, soff, "<3f", 12)
                    elif stag == b"TVER":
                        current.uvs = _counted(data, soff, "<2f", 8)
                    elif stag == b"NORM":
                        current.normals = _counted(data, soff, "<3f", 12)
                pos = soff + ssize
    if not out.objects:
        raise DofError("no GOB1 geometry found")
    return out


def parse_file(path: str | Path) -> Dof:
    return parse(Path(path).read_bytes())


def to_meshes(scene: Dof, *, flip_v: bool = True,
              scale: float = 1.0) -> dict[str, mod.Mesh]:
    """Convert to Viper meshes, keyed by a `<material><n>.mod` name.

    Frames: BTB writes Y-up with the ground in X/Z, which is already Viper's
    layout, so positions carry over directly. `flip_v` mirrors the V coordinate,
    since OBJ-style exporters put the texture origin at the bottom left while a
    decoded image starts at the top -- the same correction `carshot` needed.
    """
    out: dict[str, mod.Mesh] = {}
    for i, o in enumerate(scene.objects):
        material = (scene.materials[o.material] if 0 <= o.material < len(scene.materials)
                    else Material(name=f"object{i}"))
        verts = []
        for k, (x, y, z) in enumerate(o.positions):
            u, v = o.uvs[k] if k < len(o.uvs) else (0.0, 0.0)
            nx, ny, nz = o.normals[k] if k < len(o.normals) else (0.0, 1.0, 0.0)
            verts.append(mod.Vertex(x * scale, y * scale, z * scale,
                                    nx, ny, nz, u, (1.0 - v) if flip_v else v))
        faces = o.faces
        name = f"{material.name}{i}.mod" if len(scene.objects) > 1 else f"{material.name}.mod"
        out[name] = mod.Mesh(
            vertices=verts,
            materials=[mod.Material(material.tex_name, 0, len(verts), 0, len(faces))],
            faces=faces,
        )
    return out
