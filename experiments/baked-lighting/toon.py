"""Cartoon outline (inverted hull) for a car: python toon.py <in.car> <out.car> [thickness_m]"""
import subprocess, sys, tempfile
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]   # the vrmod repo this experiment lives in
sys.path.insert(0, str(ROOT))
from vrmod import archive, envelope, mod
INK = "wjink.tex"; INK_RGB = (18, 18, 18)   # not 0x0000: that is the transparency key

def hull(m: mod.Mesh, t: float) -> mod.Mesh:
    V = np.array([(v.x, v.y, v.z) for v in m.vertices])
    key = {}; wid = np.array([key.setdefault(tuple(np.round(p, 4)), len(key)) for p in V])
    P = np.zeros((len(key), 3)); P[wid] = V
    N = np.zeros_like(P)
    for a, b, c in m.faces:
        n = np.cross(V[b] - V[a], V[c] - V[a])        # area-weighted, outward (volume > 0)
        for i in (a, b, c): N[wid[i]] += n
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    # Outline closed pieces only. A single open sheet (the windscreen glass) has
    # no inside, so its reversed copy shows as a solid black pane from behind.
    from collections import Counter
    edges = Counter()
    for a, b, c in m.faces:
        for x, y in ((a, b), (b, c), (c, a)):
            x, y = wid[x], wid[y]; edges[(min(x, y), max(x, y))] += 1
    parent = list(range(len(P)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for (x, y) in edges: parent[find(x)] = find(y)
    open_roots = {find(x) for (x, y), n in edges.items() if n == 1}
    # Thin pieces (antenna, mirror stalks) get a line in proportion, not a pole.
    roots = np.array([find(i) for i in range(len(P))])
    tv = np.full(len(P), t)
    for r in set(roots.tolist()):
        sel = roots == r
        ext = np.ptp(P[sel], axis=0).min() if sel.sum() > 1 else 0.0
        tv[sel] = min(t, 0.5 * ext)
    H = P + tv[:, None] * N
    verts = [mod.Vertex(*p, *(-n), 0.5, 0.5) for p, n in zip(H, N)]
    faces = [(int(wid[a]), int(wid[c]), int(wid[b])) for a, b, c in m.faces   # reversed: only the back shows
             if len({wid[a], wid[b], wid[c]}) == 3 and find(int(wid[a])) not in open_roots]
    return mod.Mesh(verts, [mod.Material(INK, 0, len(verts), 0, len(faces))], faces, m.version)

def face_colours(m: mod.Mesh, textures: dict) -> np.ndarray:
    """Each face's colour: its texture sampled at the face's UV centroid."""
    out = np.full((len(m.faces), 3), 128.0)
    for mt in m.materials:
        t = textures.get(mt.name)
        if not t:
            continue
        px, size, ch, _ = t
        for f in range(mt.face_start, mt.face_end):
            a, b, c = m.faces[f]
            u = sum(m.vertices[i].u for i in (a, b, c)) / 3
            v = sum(m.vertices[i].v for i in (a, b, c)) / 3
            k = ((int(v % 1 * size) % size) * size + int(u % 1 * size) % size) * ch
            out[f] = list(px[k:k + 3])
    return out

def lines(m: mod.Mesh, cols: np.ndarray, width: float, lift: float,
          crease_deg: float = 40.0, colour_step: float = 40.0,
          min_fold: float = 0.05) -> mod.Mesh:
    """Black strips along sharp folds and colour boundaries, on each face of the edge."""
    V = np.array([(v.x, v.y, v.z) for v in m.vertices])
    key = {}; wid = np.array([key.setdefault(tuple(np.round(p, 4)), len(key)) for p in V])
    FN = []
    for a, b, c in m.faces:
        n = np.cross(V[b] - V[a], V[c] - V[a]); l = np.linalg.norm(n)
        FN.append(n / l if l > 1e-12 else n)
    edge_faces = {}
    for fi, (a, b, c) in enumerate(m.faces):
        for x, y in ((a, b), (b, c), (c, a)):
            k = (min(wid[x], wid[y]), max(wid[x], wid[y]))
            if k[0] != k[1]: edge_faces.setdefault(k, []).append((fi, x, y))
    cos_lim = np.cos(np.radians(crease_deg))
    verts, faces = [], []
    for k, fl in edge_faces.items():
        if len(fl) != 2: continue
        (f1, _, _), (f2, _, _) = fl
        # folds shorter than min_fold are bolts and grille slats: a cake has no line there
        sharp = FN[f1] @ FN[f2] < cos_lim and np.linalg.norm(V[fl[0][1]] - V[fl[0][2]]) > min_fold
        colour = np.abs(cols[f1] - cols[f2]).max() > colour_step
        if not (sharp or colour): continue
        # One strip per edge, on the larger face: the hull already draws the
        # silhouette side, and a strip on both faces doubled the vertex count.
        def area(fi):
            a, b, c = m.faces[fi]; return np.linalg.norm(np.cross(V[b] - V[a], V[c] - V[a]))
        for fi, x, y in [max(fl, key=lambda t: area(t[0]))]:
            a, b, c = m.faces[fi]; n = FN[fi]
            p0, p1 = V[x], V[y]
            third = V[({a, b, c} - {x, y}).pop()] if len({a, b, c} - {x, y}) == 1 else (V[a] + V[b] + V[c]) / 3
            e = p1 - p0; el = np.linalg.norm(e)
            if el < 1e-6: continue
            d = np.cross(n, e / el)
            if d @ (third - p0) < 0: d = -d
            h = d @ (third - p0)                       # the face's height off this edge
            w = min(width, 0.45 * h)
            if w <= 1e-4: continue
            q = [p0 + lift * n, p1 + lift * n, p1 + d * w + lift * n, p0 + d * w + lift * n]
            base = len(verts)
            verts += [mod.Vertex(*p, *n, 0.5, 0.5) for p in q]
            # wind like the face it lies on: (p0, p1, third) has the face's own order if x->y is in it
            if np.cross(q[1] - q[0], q[2] - q[0]) @ n > 0:
                faces += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
            else:
                faces += [(base, base + 2, base + 1), (base, base + 3, base + 2)]
    return mod.Mesh(verts, [mod.Material(INK, 0, len(verts), 0, len(faces))], faces, m.version)

def ink_tex() -> bytes:
    with tempfile.TemporaryDirectory() as d:
        tga = Path(d, "ink.tga"); out = Path(d, INK)
        tga.write_bytes(bytes([0, 0, 2]) + bytes(9) + (8).to_bytes(2, "little") * 2 + bytes([24, 0])
                        + bytes([INK_RGB[2], INK_RGB[1], INK_RGB[0]]) * 64)
        subprocess.run([sys.executable, "-m", "vrmod.cli", "tga2tex", str(tga), str(out)], cwd=ROOT, check=True, capture_output=True)
        return out.read_bytes()

def main(src, dst, t=0.02, width=0.015, lift=0.004):
    from vrmod import carshot
    entries = archive.read(src); stem = Path(src).stem.lower()
    def get(name):
        e = next(e for e in entries if e.name.lower() == name.lower())
        return e, mod.parse(envelope.build(e.tag, e.version, e.payload))
    e0, body = get(stem + "0.mod")
    cols = face_colours(body, carshot.material_textures(src, body))
    ln = lines(body, cols, width, lift)
    print(f"  inner lines: {len(ln.faces) // 2} strips, {len(ln.vertices)} verts")
    outlined = mod.merge([body, hull(body, t)])
    inked = mod.build(mod.merge([outlined, ln]), e0.version)
    far = mod.build(outlined, e0.version)
    # inner lines only where they can be seen: LODs 0-1; outline alone from LOD 2 out
    for n in range(8):
        entries = archive.upsert_entry(entries, f"{e0.name[:-5]}{n}.mod", inked if n < 2 else far)
    for e in [e for e in entries if e.name.lower().startswith(("wheel_", "fwheel_")) and e.name.lower().endswith(".mod")]:
        _, w = get(e.name)
        wc = face_colours(w, carshot.material_textures(src, w))
        entries = archive.upsert_entry(entries, e.name, mod.build(mod.merge([w, hull(w, t * 0.8), lines(w, wc, width, lift)]), e.version))
    entries = archive.upsert_entry(entries, INK, ink_tex())
    archive.write(entries, dst)
    m = mod.parse(envelope.build(*(lambda e: (e.tag, e.version, e.payload))(next(e for e in archive.read(dst) if e.name.lower() == stem + "0.mod"))))
    print(f"{Path(dst).name}: body {len(m.vertices)} verts, {len(m.faces)} faces")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.02)
