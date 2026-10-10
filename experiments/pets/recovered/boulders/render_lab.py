import sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "lava"))
import build_boulderlab as L  # noqa: E402
import render_views as RV  # noqa: E402
from vrmod import trackgen  # noqa: E402
RV.art.crater_sky = lambda *a, **k: L.BP.sunny_sky()
pts = L.centreline(); line = L.bc.Line(pts)
scene = trackgen.TrackScene(centreline=pts)
L.build_floor(scene)
walls, drawn = [], L.B.Batch(scene, "wall", "labwall.tex", False)
for a, b in (((L.X_END_TOP, L.Y_OUT_DOWN), (L.X_END_BOT, L.Y_OUT_DOWN)), ((L.X_END_TOP, L.Y_OUT_RET), (L.X_END_BOT, L.Y_OUT_RET)),
             ((L.X_TOP_TURN, L.Y_MED), (L.X_BOT_TURN, L.Y_MED))):
    L.wall_line(scene, walls, drawn, a, b)
drawn.flush()
for d in L.DISTS:
    x = L.x_at_dist(d)
    L.board(scene, f"d{d:04d}.tex", x + 7, x - 7, L.Y_OUT_DOWN + 0.15, L.Y_OUT_DOWN + 5, stem=f"bo{d:04d}")
    if x + 7 < L.X_BOT_TURN:
        L.board(scene, f"d{d:04d}.tex", x - 7, x + 7, L.Y_MED - 0.15, L.Y_MED - 5, stem=f"bm{d:04d}")
L.board(scene, "legend.tex", 230.0, 215.0, L.Y_MED - 0.15, L.Y_MED - 5, lift=1.0, tall=15.0, stem="legend")
tex = {k: np.array(f().convert("RGB")).astype(np.float32) / 255.0 for k, f in L.TEXTURES.items()}
tris = []
for name, m in scene.meshes.items():
    cols = scene.colours.get(name)
    for f in m.faces:
        P = np.array([(m.vertices[i].x, m.vertices[i].y, m.vertices[i].z) for i in f])
        UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
        G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
        tris.append((P, UV, G, m.materials[0].name))
specs = [(c, r, m, L.BOULDER_X, y) for c, r, m, y in L.BOULDERS] + [L.COUNTDOWN]
for k, (_c, r, _m, x, y) in enumerate(specs):
    L.B.BALL_R = r
    mm = L.B.ball_mesh(k, rings=10, segs=14, texture=f"bld{k}.tex")
    g = L.bc.game((x, y, L.z_of(x) + r))
    for f in mm.faces:
        P = np.array([(mm.vertices[i].x + g[0], mm.vertices[i].y + g[1], mm.vertices[i].z + g[2]) for i in f])
        UV = np.array([(mm.vertices[i].u, mm.vertices[i].v) for i in f])
        tris.append((P, UV, np.array([1.0, 1.0, 1.0]), mm.materials[0].name))
views = {"grid_uphill": ((262.0, L.Y_DOWN, L.z_of(262.0) + 2.0), (40.0, L.Y_DOWN, L.z_of(40.0) + 6.0)),
         "downhill": ((20.0, L.Y_DOWN - 8, L.z_of(20.0) + 12.0), (700.0, L.Y_DOWN, L.z_of(700.0))),
         "side": ((600.0, L.Y_OUT_RET - 5, L.z_of(600.0) + 60.0), (600.0, L.Y_DOWN, L.z_of(600.0)))}
for k, (e, t) in views.items():
    print(RV.render(tris, tex, RV.g(e), RV.g(t), HERE / f"lab_{k}.png"))
