"""BigBalls at the instant they spawn: 16 m balls hanging 30 m up, before the drop."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "lava"))
import build_bigballs as BB  # noqa: E402
B = BB.B
import render_views as RV  # noqa: E402
from vrmod import archive, envelope, obt as obt_mod  # noqa: E402

RV.art.crater_sky = lambda *a, **k: Image.new("RGB", (1024, 512), (255, 255, 255))
ents = {e.name.lower(): e for e in archive.read(HERE / "BigBalls.trk")}
tex = {name: np.array(fn()).astype(np.float32) / 255.0 for name, fn in B.TEXTURES.items()}
scene, line = B.build_scene()
tris = []
for name, m in scene.meshes.items():
    cols = scene.colours.get(name)
    for f in m.faces:
        P = np.array([(m.vertices[i].x, m.vertices[i].y, m.vertices[i].z) for i in f])
        UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
        G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
        tris.append((P, UV, G, m.materials[0].name))
balls = {k: B.ball_mesh(k) for k in range(len(B.PALETTES))}
t = ents["track.obt"]
for r in obt_mod.parse(envelope.build(t.tag, t.version, t.payload)).records:
    if r.startswith("obj obstacle"):
        _o, _b, _kind, meshname, pos, _mass = r.split()
        m = balls[int(meshname[5])]
        gx, rest = pos.split(","); gz = float(rest.split(":")[0])
        for f in m.faces:
            P = np.array([(m.vertices[i].x + float(gx), m.vertices[i].y + B.BALL_R + BB.DROP, m.vertices[i].z + gz) for i in f])
            UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
            tris.append((P, UV, np.array([1.0, 1.0, 1.0]), m.materials[0].name))
(gx, gy, _), (tx, ty) = line.at(line.L - 40.0)
for name, (e, tg) in {"grid": ((gx - tx * 6, gy - ty * 6, 1.6), (gx + tx * 60, gy + ty * 60, 22.0)),
                      "high": ((-B.ROOM_X + 20, -B.ROOM_Y + 20, 70.0), (20.0, 10.0, 10.0))}.items():
    print(RV.render(tris, tex, RV.g(e), RV.g(tg), HERE / f"view_big_{name}.png"))
