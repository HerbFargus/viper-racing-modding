"""Bake lighting (ambient occlusion + a key light) into a texture atlas for a car body.

python bake_light.py <in.car> <out.car> [px_per_m]

No added geometry: the body keeps its own vertices and faces; only the UVs and
the texture change. Faces are grouped into charts (edge-connected, one colour,
normals within CHART_DEG of the seed), each chart is projected flat and packed
onto PAGE x PAGE pages, and every face is painted as
    colour * (AO_FLOOR + (1 - AO_FLOOR) * ao) * (KEY_FLOOR + KEY_GAIN * key)
with ao interpolated across the face from per-vertex ray-cast occlusion.
"""
import subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                  # the vrmod repo this experiment lives in
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from vrmod import archive, envelope, mod, carshot, tex   # noqa: E402
import toon                                              # noqa: E402

PAGE, PAD = 256, 2
CHART_DEG = 35.0
RAYS, RAY_LEN = 32, 0.6          # occlusion: rays per vertex, and how far a hit still counts (m)
AO_FLOOR = 0.35                  # a fully enclosed spot keeps this much light
KEY = np.array([-0.45, 0.75, 0.5]); KEY /= np.linalg.norm(KEY)
KEY_FLOOR, KEY_GAIN = 0.78, 0.32
STEM = "wjlt"                    # wjlt0.tex, wjlt1.tex ... (8.3)


def occlusion(V, F, P, wid, FN):
    """Per welded vertex: the fraction of a cosine-weighted hemisphere that is open."""
    N = np.zeros_like(P)
    for fi, (a, b, c) in enumerate(F):
        for i in (a, b, c):
            N[wid[i]] += FN[fi]
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    rng = np.random.default_rng(1)
    r1, r2 = rng.random(RAYS), rng.random(RAYS)
    local = np.stack([np.cos(2 * np.pi * r1) * np.sqrt(r2), np.sin(2 * np.pi * r1) * np.sqrt(r2), np.sqrt(1 - r2)], 1)
    T0, E1, E2 = V[F[:, 0]], V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]
    ao = np.ones(len(P))
    for start in range(0, len(P), 16):
        idx = np.arange(start, min(start + 16, len(P)))
        n = N[idx]
        t1 = np.where(np.abs(n[:, :1]) < 0.9, np.cross(n, [1, 0, 0]), np.cross(n, [0, 1, 0]))
        t1 /= np.linalg.norm(t1, axis=1, keepdims=True); t2 = np.cross(n, t1)
        dirs = (local[None, :, 0:1] * t1[:, None] + local[None, :, 1:2] * t2[:, None] + local[None, :, 2:3] * n[:, None])
        orig = (P[idx] + n * 1e-3)[:, None, None, :]                # (v,1,1,3)
        d = dirs[:, :, None, :]                                     # (v,r,1,3)
        p = np.cross(d, E2[None, None])                             # (v,r,t,3)
        det = np.einsum("vrtk,tk->vrt", p, E1)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
        s = orig - T0[None, None]
        u = (s * p).sum(-1) * inv
        q = np.cross(s, E1[None, None])
        v = (d * q).sum(-1) * inv
        t = (q * E2[None, None]).sum(-1) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-3) & (t < RAY_LEN)
        ao[idx] = 1 - hit.any(axis=2).mean(axis=1)
    return ao


def bake(m, cols, ppm):
    V = np.array([(v.x, v.y, v.z) for v in m.vertices])
    key = {}; wid = np.array([key.setdefault(tuple(np.round(p, 4)), len(key)) for p in V])
    P = np.zeros((len(key), 3)); P[wid] = V
    F = np.array(m.faces)
    FN = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    FA = np.linalg.norm(FN, axis=1); FN = FN / np.maximum(FA[:, None], 1e-12)
    ao = occlusion(V, F, P, wid, FN)
    ckey = [tuple(int(x) for x in c) for c in cols]

    edge_faces = {}
    for fi, (a, b, c) in enumerate(m.faces):
        for x, y in ((a, b), (b, c), (c, a)):
            k = (min(wid[x], wid[y]), max(wid[x], wid[y]))
            if k[0] != k[1]:
                edge_faces.setdefault(k, []).append(fi)
    nbrs = [[] for _ in range(len(F))]
    for fl in edge_faces.values():
        if len(fl) == 2:
            nbrs[fl[0]].append(fl[1]); nbrs[fl[1]].append(fl[0])
    chart = np.full(len(F), -1); charts = []
    cos_c = np.cos(np.radians(CHART_DEG))
    for seed in np.argsort(-FA):
        if chart[seed] >= 0:
            continue
        cid = len(charts); chart[seed] = cid; members = [seed]; q = [seed]
        while q:
            f = q.pop()
            for g in nbrs[f]:
                if chart[g] < 0 and ckey[g] == ckey[seed] and FN[g] @ FN[seed] > cos_c:
                    chart[g] = cid; members.append(g); q.append(g)
        charts.append(members)

    rects = []
    for cid, members in enumerate(charts):
        n = FN[members[0]]
        u = np.cross(n, [0, 1, 0]) if abs(n[1]) < 0.9 else np.cross(n, [1, 0, 0])
        u /= np.linalg.norm(u); v = np.cross(n, u)
        pts = V[F[members].ravel()]
        uv = np.stack([pts @ u, pts @ v], 1) * ppm
        lo = uv.min(0); ext = uv.max(0) - lo
        s = min(1.0, (PAGE - 2 * PAD - 1) / max(ext.max(), 1e-9))
        w, h = (np.ceil(ext * s).astype(int) + 1)
        rects.append((cid, int(w), int(h), lo, u, v, s))
    rects.sort(key=lambda r: -r[2])
    pages = [[]]; x = y = shelf = 0; placed = {}
    for r in rects:
        cid, w, h = r[:3]
        if x + w + 2 * PAD > PAGE:
            x = 0; y += shelf + 2 * PAD; shelf = 0
        if y + h + 2 * PAD > PAGE:
            pages.append([]); x = y = shelf = 0
        placed[cid] = (len(pages) - 1, x + PAD, y + PAD)
        x += w + 2 * PAD; shelf = max(shelf, h)

    imgs = [np.zeros((PAGE, PAGE, 3), float) for _ in pages]
    face_uv = {}
    for cid, w, h, lo, u, v, s in rects:
        pg, ox, oy = placed[cid]
        members = charts[cid]; img = imgs[pg]
        base = np.array(ckey[members[0]], float)
        img[oy - PAD:oy + h + PAD, ox - PAD:ox + w + PAD] = base * np.mean(
            [(AO_FLOOR + (1 - AO_FLOOR) * ao[wid[F[f]]].mean()) for f in members])
        for f in members:
            tri = np.array([(((V[i] @ u) * ppm - lo[0]) * s + ox, ((V[i] @ v) * ppm - lo[1]) * s + oy) for i in F[f]])
            face_uv[f] = (pg, [tuple(p / PAGE) for p in tri])
            light = KEY_FLOOR + KEY_GAIN * max(0.0, FN[f] @ KEY)
            a_c = ao[wid[F[f]]]
            x0, y0 = np.floor(tri.min(0) - 1).astype(int); x1, y1 = np.ceil(tri.max(0) + 1).astype(int)
            x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, PAGE - 1), min(y1, PAGE - 1)
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            A, B, C = tri
            den = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1])
            if abs(den) < 1e-12:
                continue
            l0 = ((B[1] - C[1]) * (xs - C[0]) + (C[0] - B[0]) * (ys - C[1])) / den
            l1 = ((C[1] - A[1]) * (xs - C[0]) + (A[0] - C[0]) * (ys - C[1])) / den
            l2 = 1 - l0 - l1
            inside = (l0 >= -0.15) & (l1 >= -0.15) & (l2 >= -0.15)      # a little past the edge, against seams
            occ = np.clip(l0, 0, 1) * a_c[0] + np.clip(l1, 0, 1) * a_c[1] + np.clip(l2, 0, 1) * a_c[2]
            occ /= np.maximum(np.clip(l0, 0, 1) + np.clip(l1, 0, 1) + np.clip(l2, 0, 1), 1e-9)
            shade = (AO_FLOOR + (1 - AO_FLOOR) * occ) * light
            region = img[y0:y1 + 1, x0:x1 + 1]
            region[inside] = base * shade[inside, None]
    pages_px = [Image.fromarray(np.clip(i, 1, 255).astype(np.uint8)) for i in imgs]

    by_page = {}
    for f in range(len(F)):
        pg, uvs = face_uv[f]
        by_page.setdefault(pg, []).append((f, uvs))
    verts, faces, mats = [], [], []
    for pg in sorted(by_page):
        vs, fs = len(verts), len(faces); index = {}
        for f, uvs in by_page[pg]:
            tri = []
            for vi, (uu, vv) in zip(F[f], uvs):
                k = (int(vi), round(uu, 5), round(vv, 5))
                if k not in index:
                    o = m.vertices[vi]; index[k] = len(verts)
                    verts.append(mod.Vertex(o.x, o.y, o.z, o.nx, o.ny, o.nz, uu, vv))
                tri.append(index[k])
            faces.append(tuple(tri))
        mats.append(mod.Material(f"{STEM}{pg}.tex", vs, len(verts), fs, len(faces)))
    return mod.Mesh(verts, mats, faces, m.version), pages_px, len(charts), float(ao.mean())


def tex_bytes(img):
    with tempfile.TemporaryDirectory() as d:
        tga = Path(d, "p.tga"); out = Path(d, "p.tex")
        tex.write_tga(img.tobytes(), img.width, img.height, tga)
        subprocess.run([sys.executable, "-m", "vrmod.cli", "tga2tex", str(tga), str(out)],
                       cwd=ROOT, check=True, capture_output=True)
        return out.read_bytes()


def main(src, dst, ppm=40.0):
    entries = archive.read(src); stem = Path(src).stem.lower()
    e0 = next(e for e in entries if e.name.lower() == stem + "0.mod")
    body = mod.parse(envelope.build(e0.tag, e0.version, e0.payload))
    cols = toon.face_colours(body, carshot.material_textures(src, body))
    baked, pages, nch, mean_ao = bake(body, cols, ppm)
    data = mod.build(baked, e0.version)
    for n in range(8):
        entries = archive.upsert_entry(entries, f"{e0.name[:-5]}{n}.mod", data)
    for i, img in enumerate(pages):
        entries = archive.upsert_entry(entries, f"{STEM}{i}.tex", tex_bytes(img))
        img.save(Path(dst).with_name(f"{STEM}{i}.png"))
    archive.write(entries, dst)
    print(f"{Path(dst).name}: {nch} charts on {len(pages)} page(s), mean openness {mean_ao:.2f}, "
          f"body {len(baked.vertices)} verts (was {len(body.vertices)}), {Path(dst).stat().st_size:,} bytes")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], *(float(x) for x in a[2:]))
