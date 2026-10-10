import sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "lava"))
import build_boulderlab2 as L  # noqa: E402
import render_views as RV  # noqa: E402
from vrmod import trackgen  # noqa: E402
RV.art.crater_sky = lambda *a, **k: L.L1.BP.sunny_sky()
pts = L.centreline()
scene = trackgen.TrackScene(centreline=pts)
L.build_floor(scene); L.draw_walls(scene); L.add_boards(scene)
tex = {k: np.array(f().convert("RGB")).astype(np.float32) / 255.0 for k, f in L.TEXTURES.items()}
tex["bld0.tex"] = tex["bld3.tex"]
tris = []
for name, m in scene.meshes.items():
    cols = scene.colours.get(name)
    for f in m.faces:
        P = np.array([(m.vertices[i].x, m.vertices[i].y, m.vertices[i].z) for i in f])
        UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
        G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
        tris.append((P, UV, G, m.materials[0].name))
L.B.BALL_R = L.BOULDER_R
mm = L.B.ball_mesh(3, rings=10, segs=14, texture="bld3.tex")
for _l, lo, hi, _d, ch in L.LANES:
    x = L.CHUTE_BOULDER_X if ch else L.BOULDER_X
    y = (lo + hi) / 2
    g = L.bc.game((x, y, L.height(x, y) + L.BOULDER_R))
    for f in mm.faces:
        P = np.array([(mm.vertices[i].x + g[0], mm.vertices[i].y + g[1], mm.vertices[i].z + g[2]) for i in f])
        UV = np.array([(mm.vertices[i].u, mm.vertices[i].v) for i in f])
        tris.append((P, UV, np.array([1.0, 1.0, 1.0]), "bld3.tex"))
h = L.height
views = {"plateau": ((-120.0, -45.0, 132.0), (40.0, -75.0, 112.0)),
         "overview": ((-60.0, 120.0, 260.0), (500.0, -75.0, 40.0)),
         "chute_side": ((60.0, -100.0, 190.0), (-40.0, -135.0, 135.0)),
         "downhill_B": ((20.0, -45.0, h(20.0, -45.0) + 12.0), (600.0, -45.0, h(600.0, -45.0)))}
for k, (e, t) in views.items():
    print(RV.render(tris, tex, RV.g(e), RV.g(t), HERE / f"lab2_{k}.png"))
