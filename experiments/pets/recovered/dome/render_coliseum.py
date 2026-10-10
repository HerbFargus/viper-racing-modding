"""Offline views of the Coliseum, balls where they spawn (4 m up)."""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "lava"))
import build_coliseum as C  # noqa: E402
import render_views as RV  # noqa: E402
from vrmod import archive, envelope, obt as obt_mod, trackgen  # noqa: E402
B, bc = C.B, C.bc

RV.art.crater_sky = lambda *a, **k: C.night_sky()
rng = random.Random(C.SEED)
n_line = int(C.L_LAP // 8)
centre = [(*C.point_at(C.START_X + C.SL + k * C.L_LAP / n_line)[:2], 0.0) for k in range(n_line)]
scene = trackgen.TrackScene(centreline=centre)
C.build_floor(scene, rng)
C.add_start_line(scene)
C.add_dome(scene)
tex = {n: np.array(C.TEXTURES[n]()).astype(np.float32) / 255.0 for n in C.TEXTURES}
tris = []
for name, m in scene.meshes.items():
    cols = scene.colours.get(name)
    for f in m.faces:
        P = np.array([(m.vertices[i].x, m.vertices[i].y, m.vertices[i].z) for i in f])
        UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
        G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
        tris.append((P, UV, G, m.materials[0].name))
by = {e.name.lower(): e for e in archive.read(C.OUT)}
balls = {k: B.ball_mesh(k, rings=C.BALL_RINGS, segs=C.BALL_SEGS, texture=f"{C.ball_name(k)}.tex")
         for k in range(len(C.BALL_COLOURS))}
t = by["track.obt"]
for r in obt_mod.parse(envelope.build(t.tag, t.version, t.payload)).records:
    if r.startswith("obj obstacle"):
        _o, _b, _kind, meshname, pos, _mass = r.split()
        m = balls[int(meshname[4:6])]
        gx, rest = pos.split(","); gz = float(rest.split(":")[0])
        ground = C.height(-float(gx), -gz)
        for f in m.faces:
            P = np.array([(m.vertices[i].x + float(gx), m.vertices[i].y + ground + B.BALL_R + 4.0, m.vertices[i].z + gz) for i in f])
            UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
            tris.append((P, UV, np.array([1.0, 1.0, 1.0]), m.materials[0].name))
gx, gy, (tx, ty) = C.point_at(C.START_X + C.SL - 30)
tx_, ty_, (a, b) = C.point_at(2 * C.SL + 20)
r0 = C.RAMPS[0]
views = {
    "grid": ((gx - 4 * ty, gy + 4 * tx, 1.6), (gx + 80 * tx, gy + 80 * ty, 3.0)),
    "turn": ((C.SL + C.SHIFT - 60, -C.R + 2, 1.6), (C.SL + C.SHIFT + 180, -60.0, 10.0)),
    "ramp": ((C.SHIFT - 220.0, 1.5, 1.6), (C.SHIFT, 0.0, 8.0)),
    "ramp_side": ((C.SHIFT, -150.0, 14.0), (C.SHIFT, 0.0, 6.0)),
    "apron": ((C.SL + C.SHIFT + 60.0, -C.R - 30.0, 10.0), (C.SL + C.SHIFT + 200.0, 40.0, 6.0)),
    "infield": ((-150.0, -60.0, 2.0), (120.0, 60.0, 45.0)),
    "sky": ((-40.0, -120.0, 2.0), (40.0, 60.0, 160.0)),
    "menu": ((C.SHIFT - 150.0, -95.0, 16.0), (C.SHIFT + 40.0, 20.0, 18.0)),
    "across": ((C.SHIFT, -40.0, 3.0), (C.SHIFT + 60.0, -270.0, 10.0)),
    "corner": ((C.SL + C.SHIFT - 120.0, -C.R + 4.0, 1.6), (C.SL + C.SHIFT + 60.0, -C.R - 20.0, 5.0)),
    "balls": ((C.SHIFT + 180.0, -95.0, 6.0), (C.SHIFT + 260.0, -30.0, 10.0)),
    "overhead": ((0.0, -520.0, 330.0), (0.0, 0.0, 0.0)),
}
for k in sys.argv[1:] or list(views):
    e, tg = views[k]
    print(RV.render(tris, tex, RV.g(e), RV.g(tg), HERE / f"view_{k}.png"))
