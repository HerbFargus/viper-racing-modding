"""Extract a model from a Maxis .MAX (SimCopter / Streets of SimCity) to OBJ.

Written against CahootsMalone's format notes rather than guessed:
https://github.com/CahootsMalone/maxis-mesh-stuff

    DIRC header      12 bytes, then fixed CMAP/GEOM address pointers at 12 and 20
    GEOM table       53-byte entries: name[17], addr, count, ..., faces, verts
    OBJX object      124-byte header, then verts (3 x int32), then FACE records
    FACE             tag, size, n_verts, flags, light, unknown, type,
                     colour/texture index, atlas index, then per vertex:
                     index (u16) + U,V (int32 each, / 65536)

    python max2obj.py <file.MAX> <MODEL_NAME> <out.obj>
"""
import struct
import sys
from pathlib import Path

OBJX_HEADER = 124
# Streets of SimCity measures V from the opposite end of the texture to Viper
# Racing. Confirmed against the Airhawk's rear: unflipped, its yellow roof
# surround renders along the bottom bumper and the tail lights sit mid-panel;
# negated, the roof, window, lights and bumper all land where the game puts
# them. Nothing in either format declares this -- only the picture tells you.
FLIP_V = True


def models(blob: bytes):
    """{name: (addr, n_faces, n_verts)} from the geometry table."""
    geom = struct.unpack_from("<I", blob, 24)[0]
    if blob[geom:geom + 4] != b"GEOM":
        raise SystemExit(f"no GEOM at {geom}")
    n_gte, _obj, table = struct.unpack_from("<III", blob, geom + 8)
    out = {}
    for i in range(n_gte):
        o = table + i * 53
        name = blob[o:o + 17].split(b"\0")[0].decode("latin-1", "replace")
        addr, _count = struct.unpack_from("<II", blob, o + 17)
        faces, verts = struct.unpack_from("<II", blob, o + 41)
        out[name] = (addr, faces, verts)
    return out


def read_model(blob: bytes, addr: int, n_faces: int, n_verts: int):
    if blob[addr:addr + 4] != b"OBJX":
        raise SystemExit(f"no OBJX at {addr}")
    voff = addr + OBJX_HEADER
    verts = [struct.unpack_from("<iii", blob, voff + i * 12) for i in range(n_verts)]

    faces = []
    o = voff + n_verts * 12
    for _ in range(n_faces):
        if blob[o:o + 4] != b"FACE":
            break
        size = struct.unpack_from("<I", blob, o + 4)[0]
        nfv, flags = struct.unpack_from("<HH", blob, o + 8)
        ftype = blob[o + 18]
        tex = blob[o + 19]
        atlas = blob[o + 20]
        # Indices first as a contiguous block, THEN the UVs -- not interleaved.
        # Both readings give 51 bytes for a triangle, so the record size does
        # not disambiguate them; reading them interleaved yields indices like
        # 49438 for a 285-vertex mesh, which is a V coordinate being read as an
        # index.
        p = o + 21
        idx = [struct.unpack_from("<H", blob, p + i * 2)[0] for i in range(nfv)]
        q = p + nfv * 2
        uvs = []
        for v_i in range(nfv):
            u, v = struct.unpack_from("<ii", blob, q + v_i * 8)
            # FLIP_V negates V. The two games disagree about which end of a
            # texture v=0 means; the tell is the Airhawk's rear, where the
            # yellow roof surround lands on the bumper instead.
            uvs.append((u / 65536.0,
                        -v / 65536.0 if FLIP_V else v / 65536.0))
        faces.append(dict(n=nfv, flags=flags, type=ftype, tex=tex,
                          atlas=atlas, idx=idx, uv=uvs))
        # `size` covers the WHOLE record, tag and size field included --
        # 21-byte header + 10 per vertex = 51 for a triangle, which is
        # exactly what the field says. Treating it as a payload length
        # oversteps by 8 and the walk stops after one face.
        o += size
    return verts, faces


def to_obj(verts, faces, name: str, scale: float = 1 / 65536.0) -> str:
    """OBJ text. Coordinates are divided down from the game's fixed-point ints;
    vrmod's obj2mod does not care about absolute scale, but a sane magnitude
    makes the result inspectable in any viewer."""
    L = [f"# {name}: {len(verts)} verts, {len(faces)} faces",
         f"o {name}"]
    for x, y, z in verts:
        L.append(f"v {x * scale:.6f} {y * scale:.6f} {z * scale:.6f}")
    uv_index = {}
    for f in faces:
        for uv in f["uv"]:
            if uv not in uv_index:
                uv_index[uv] = len(uv_index) + 1
                L.append(f"vt {uv[0]:.6f} {uv[1]:.6f}")
    current = None
    for f in faces:
        if f["n"] < 3:
            continue                      # points and lines are not geometry
        mat = f"tex{f['tex']:02d}"
        if mat != current:
            L.append(f"usemtl {mat}")
            current = mat
        parts = [f"{i + 1}/{uv_index[uv]}" for i, uv in zip(f["idx"], f["uv"])]
        L.append("f " + " ".join(parts))
    return "\n".join(L) + "\n"


def main() -> int:
    src, want, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    blob = src.read_bytes()
    table = models(blob)
    if want not in table:
        raise SystemExit(f"no model {want!r}; have {len(table)}: "
                         f"{sorted(table)[:8]} ...")
    addr, nf, nv = table[want]
    verts, faces = read_model(blob, addr, nf, nv)
    polys = [f for f in faces if f["n"] >= 3]
    tris = sum(f["n"] - 2 for f in polys)
    out.write_text(to_obj(verts, faces, want), encoding="utf-8")
    print(f"  {want}: {len(verts)} verts, {len(faces)}/{nf} face records read")
    print(f"    {len(polys)} polygons -> {tris} triangles, "
          f"{len(faces) - len(polys)} points/lines skipped")
    print(f"    texture indices used: {sorted({f['tex'] for f in polys})}")
    print(f"    face types: {sorted({f['type'] for f in polys})}")
    print(f"    wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
