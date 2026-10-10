"""Offline views of the ball pit, balls where they spawn (overlapping; they burst apart in game)."""
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "lava"))
import build_ballpit as BP  # noqa: E402
import render_views as RV  # noqa: E402
from vrmod import archive, envelope, obt as obt_mod, trackgen  # noqa: E402

RV.art.crater_sky = lambda *a, **k: BP.sunny_sky()
n = int(round(2 * math.pi * BP.R_LINE / 10.0))
pts = [BP.P(BP.R_LINE, 360.0 * k / n) for k in range(n)]
line = BP.bc.Line(pts)
scene = trackgen.TrackScene(centreline=pts)
BP.build_floor(scene); BP.add_rings(scene); BP.add_start_line(scene, line)
tex = {k: np.array(f()).astype(np.float32) / 255.0 for k, f in BP.TEXTURES.items()}
tris = []
for name, m in scene.meshes.items():
    cols = scene.colours.get(name)
    for f in m.faces:
        P = np.array([(m.vertices[i].x, m.vertices[i].y, m.vertices[i].z) for i in f])
        UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
        G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
        tris.append((P, UV, G, m.materials[0].name))
by = {e.name.lower(): e for e in archive.read(BP.OUT)}
balls = {k: BP.B.ball_mesh(k, rings=BP.BALL_RINGS, segs=BP.BALL_SEGS, texture=f"{BP.CO.ball_name(k)}.tex")
         for k in range(len(BP.CO.BALL_COLOURS))}
t = by["track.obt"]
for r in obt_mod.parse(envelope.build(t.tag, t.version, t.payload)).records:
    if r.startswith("obj obstacle"):
        _o, _b, _kind, meshname, pos, _mass = r.split()
        m = balls[int(meshname[4:6])]
        gx, rest = pos.split(","); gz = float(rest.split(":")[0])
        ground = BP.floor_z(math.hypot(-float(gx) - BP.CX, -gz - BP.CY))
        for f in m.faces:
            P = np.array([(m.vertices[i].x + float(gx), m.vertices[i].y + ground + BP.BALL_R + 4.0, m.vertices[i].z + gz) for i in f])
            UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
            tris.append((P, UV, np.array([1.0, 1.0, 1.0]), m.materials[0].name))
(gx, gy, _), (tx, ty) = line.at(line.L - 30.0)
views = {
    "grid": ((gx - tx * 10, gy - ty * 10, 1.6), (gx + tx * 60, gy + ty * 60, 8.0)),
    "rim": (BP.P(BP.R_RIM - 20, 200.0, 8.0), BP.P(BP.R_RIM - 5, 250.0, 30.0)),
    "high": (BP.P(BP.R_RIM + 40, 225.0, 140.0), BP.P(0.0, 0.0, 10.0)),
    "menu": (BP.P(BP.R_RIM - 25, 225.0, 38.0), BP.P(40.0, 45.0, 4.0)),
}
for k in sys.argv[1:] or list(views):
    e, tg = views[k]
    print(RV.render(tris, tex, RV.g(e), RV.g(tg), HERE / f"view_{k}.png"))
