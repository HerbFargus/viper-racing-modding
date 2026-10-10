"""A rolling-boulder horn ball: a lumpy sandstone rock as the car's ball.mod.

The horn ball's COLLISION is set in the engine (vrmod hornball --size); what is
drawn is the car's own ball.mod. This writes a rock sized to a given collision
radius, and puts it (plus its texture, boulder.tex) into a car archive, keeping
a backup of the car.

Car textures added by a mod need wrap 1 or 2 -- wrap 0 on a car is "unknown
texture format" (see the OBJ/texture pipeline notes).
"""
import math
import random
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
import art  # noqa: E402
from vrmod import archive, envelope, mod, tex  # noqa: E402

STOCK_R = 18.0 * 0.0254             # the engine's stock collision radius, metres
TEXNAME = "boulder.tex"


def icosphere(subdiv=1):
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    v = [np.array(p) / np.linalg.norm(p) for p in v]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
         (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
         (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    for _ in range(subdiv):
        cache, nf = {}, []

        def mid(a, b):
            k = (min(a, b), max(a, b))
            if k not in cache:
                m = v[a] + v[b]
                v.append(m / np.linalg.norm(m))
                cache[k] = len(v) - 1
            return cache[k]
        for a, b, c in f:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    return v, f


def boulder_mesh(radius, seed=7):
    """Flat-shaded lumpy rock of about `radius`, centred on the origin, faces out."""
    rng = random.Random(seed)
    v, f = icosphere(1)
    bump = [radius * rng.uniform(0.86, 1.10) for _ in v]
    P = [p * b for p, b in zip(v, bump)]
    verts, faces = [], []
    for a, b, c in f:
        pa, pb, pc = P[a], P[b], P[c]
        n = np.cross(pb - pa, pc - pa)
        cen = (pa + pb + pc) / 3
        if np.dot(n, cen) < 0:                      # right-hand normal out = the side that draws
            pb, pc = pc, pb
            n = -n
        n = n / np.linalg.norm(n)
        base = len(verts)
        for p in (pa, pb, pc):
            u = 0.5 + math.atan2(p[2], p[0]) / (2 * math.pi)
            w = 0.5 - math.asin(max(-1.0, min(1.0, p[1] / np.linalg.norm(p)))) / math.pi
            verts.append(mod.Vertex(float(p[0]), float(p[1]), float(p[2]),
                                    float(n[0]), float(n[1]), float(n[2]), u * 2, w))
        faces.append((base, base + 1, base + 2))
    m = mod.Mesh(vertices=verts, faces=faces, materials=[])
    m.materials = [mod.Material(name=TEXNAME, vertex_start=0, vertex_end=len(verts),
                                face_start=0, face_end=len(faces))]
    return m


def boulder_texture(size=128, seed=501):
    n = art.tile_noise(size, 4, 6, 0.6, seed)
    pits = (art.tile_noise(size, 20, 2, 0.5, seed + 3) > 0.74).astype(float)
    img = art.colourise(n, (116, 94, 66), (182, 156, 116))
    img *= (1 - 0.3 * pits)[..., None]
    img += art.speckle(size, 0.06, seed + 1)[..., None] * np.array([-24, -22, -18])
    return art.to_img(img)


def install(car_path, size_mult, backup_dir):
    car_path = Path(car_path)
    backup_dir = Path(backup_dir)
    backup = backup_dir / (car_path.name + ".boulder-backup")
    if not backup.exists():
        shutil.copy2(car_path, backup)
    data = backup.read_bytes()                        # always rebuild from the original
    layout = archive.read_layout(data)
    entries = archive.read_bytes(data)
    names = {e.name.lower(): e for e in entries}
    old = names["ball.mod"]
    m = boulder_mesh(STOCK_R * size_mult)
    ball = envelope.parse(mod.build(m, old.version))
    old.payload = ball.payload
    im = boulder_texture()
    t = envelope.parse(tex.encode_to_tex(im.tobytes(), im.width, mode="opaque", wrap=1))
    if TEXNAME in names:
        names[TEXNAME].tag, names[TEXNAME].version, names[TEXNAME].payload = t.tag, t.version, t.payload
    else:
        entries.append(archive.ArchiveEntry(name=TEXNAME, tag=t.tag, version=t.version, payload=t.payload))
    car_path.write_bytes(archive.to_bytes(entries, partitioned=layout.partitioned))
    back = {e.name.lower(): e for e in archive.read(car_path)}
    chk = mod.parse(envelope.build(back["ball.mod"].tag, back["ball.mod"].version, back["ball.mod"].payload))
    tex.parse(envelope.build(back[TEXNAME].tag, back[TEXNAME].version, back[TEXNAME].payload))
    r = max(math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2) for v in chk.vertices)
    return len(chk.vertices), len(chk.faces), r, backup


if __name__ == "__main__":
    car, size = sys.argv[1], float(sys.argv[2])
    nv, nf, r, backup = install(car, size, Path(car).parent / "Backups")
    print(f"{Path(car).name}: ball.mod is now a {nv}-vertex, {nf}-face boulder, radius up to {r:.2f} m "
          f"(collision {STOCK_R * size:.2f} m); {TEXNAME} added; original kept as {backup.name}")
