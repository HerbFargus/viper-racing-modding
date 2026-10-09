"""Bake the same lighting into a car's cockpit (<prefix>c.mod): palette faces only.

python bake_cockpit.py <in.car> <out.car> [px_per_m]

Faces on the palette texture are charted, lit and packed onto their own pages
(wjck0.tex ...), exactly as bake_light.py does the body; faces on any other
texture (the dash, with its gauges) are kept as they are. Occlusion rays hit the
body's LOD 0 as well as the cockpit, so the body shades the interior.
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
import bake_light as B
from vrmod import archive, envelope, mod, carshot   # vrmod-experiments, via bake_light's path
import toon

PALETTE = "wjpal.tex"


def main(src, dst, ppm=80.0):
    entries = archive.read(src); stem = Path(src).stem.lower()
    by = {e.name.lower(): e for e in entries}
    ec, e0 = by[stem + "c.mod"], by[stem + "0.mod"]
    cock = mod.parse(envelope.build(ec.tag, ec.version, ec.payload))
    body = mod.parse(envelope.build(e0.tag, e0.version, e0.payload))

    # The palette part of the cockpit, as its own mesh.
    pal = [m for m in cock.materials if m.name.lower() == PALETTE]
    keep = [m for m in cock.materials if m.name.lower() != PALETTE]
    faces = [cock.faces[fi] for m in pal for fi in range(m.face_start, m.face_end)]
    used = sorted({i for f in faces for i in f}); remap = {o: n for n, o in enumerate(used)}
    sub = mod.Mesh([cock.vertices[i] for i in used],
                   [mod.Material(PALETTE, 0, len(used), 0, len(faces))],
                   [tuple(remap[i] for i in f) for f in faces], cock.version)

    # Occluders: the whole cockpit plus the body.
    occ_v = np.array([(v.x, v.y, v.z) for v in cock.vertices] + [(v.x, v.y, v.z) for v in body.vertices])
    occ_f = np.array(list(cock.faces) + [(a + len(cock.vertices), b + len(cock.vertices), c + len(cock.vertices))
                                         for a, b, c in body.faces])
    orig_occ = B.occlusion

    def occlusion(V, F, P, wid, FN):
        # Same rays as bake_light.occlusion, cast against occ_v/occ_f instead of V/F alone.
        N = np.zeros_like(P)
        for fi, (a, b, c) in enumerate(F):
            for i in (a, b, c):
                N[wid[i]] += FN[fi]
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        rng = np.random.default_rng(1)
        r1, r2 = rng.random(B.RAYS), rng.random(B.RAYS)
        local = np.stack([np.cos(2 * np.pi * r1) * np.sqrt(r2), np.sin(2 * np.pi * r1) * np.sqrt(r2), np.sqrt(1 - r2)], 1)
        T0, E1, E2 = occ_v[occ_f[:, 0]], occ_v[occ_f[:, 1]] - occ_v[occ_f[:, 0]], occ_v[occ_f[:, 2]] - occ_v[occ_f[:, 0]]
        ao = np.ones(len(P))
        for start in range(0, len(P), 8):
            idx = np.arange(start, min(start + 8, len(P)))
            n = N[idx]
            t1 = np.where(np.abs(n[:, :1]) < 0.9, np.cross(n, [1, 0, 0]), np.cross(n, [0, 1, 0]))
            t1 /= np.linalg.norm(t1, axis=1, keepdims=True); t2 = np.cross(n, t1)
            dirs = (local[None, :, 0:1] * t1[:, None] + local[None, :, 1:2] * t2[:, None] + local[None, :, 2:3] * n[:, None])
            orig = (P[idx] + n * 1e-3)[:, None, None, :]
            d = dirs[:, :, None, :]
            p = np.cross(d, E2[None, None])
            det = np.einsum("vrtk,tk->vrt", p, E1)
            ok = np.abs(det) > 1e-9
            inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
            s = orig - T0[None, None]
            u = (s * p).sum(-1) * inv
            q = np.cross(s, E1[None, None])
            v = (d * q).sum(-1) * inv
            t = (q * E2[None, None]).sum(-1) * inv
            hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-3) & (t < B.RAY_LEN)
            ao[idx] = 1 - hit.any(axis=2).mean(axis=1)
        return ao

    B.occlusion = occlusion
    B.STEM = "wjck"
    cols = toon.face_colours(sub, carshot.material_textures(src, sub))
    baked, pages, nch, mean_ao = B.bake(sub, cols, ppm)
    B.occlusion = orig_occ

    # Baked palette part + the untouched other materials (the dash).
    verts, out_faces, mats = list(baked.vertices), list(baked.faces), list(baked.materials)
    for m in keep:
        vs, fs = len(verts), len(out_faces)
        verts += cock.vertices[m.vertex_start:m.vertex_end]
        out_faces += [(a - m.vertex_start + vs, b - m.vertex_start + vs, c - m.vertex_start + vs)
                      for a, b, c in cock.faces[m.face_start:m.face_end]]
        mats.append(mod.Material(m.name, vs, len(verts), fs, len(out_faces)))
    new = mod.Mesh(verts, mats, out_faces, cock.version)
    entries = archive.upsert_entry(entries, ec.name, mod.build(new, ec.version))
    for i, img in enumerate(pages):
        entries = archive.upsert_entry(entries, f"wjck{i}.tex", B.tex_bytes(img))
        img.save(Path(dst).with_name(f"wjck{i}.png"))
    archive.write(entries, dst)
    print(f"{ec.name}: {nch} charts on {len(pages)} page(s), mean openness {mean_ao:.2f}, "
          f"{len(new.vertices)} verts (was {len(cock.vertices)}), materials {[m.name for m in new.materials]}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], *(float(x) for x in a[2:]))
