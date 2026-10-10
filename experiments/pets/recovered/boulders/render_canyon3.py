import sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "lava"))
import build_canyon as C  # noqa: E402
import render_views as RV  # noqa: E402
from vrmod import trackgen  # noqa: E402
RV.art.crater_sky = lambda *a, **k: C.L1.BP.sunny_sky()
scene = trackgen.TrackScene(centreline=C.centreline())
C.build_floor(scene); C.build_roof(scene)
tex = {k: np.array(f().convert("RGB")).astype(np.float32) / 255.0 for k, f in C.TEXTURES.items()}
tris = []
for name, m in scene.meshes.items():
    cols = scene.colours.get(name)
    for f in m.faces:
        P = np.array([(m.vertices[i].x, m.vertices[i].y, m.vertices[i].z) for i in f])
        UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
        G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
        tris.append((P, UV, G, m.materials[0].name))
for (x, y), r in zip(C.boulders(), C.boulder_radii()):
    rock = C.make_boulder.boulder_mesh(r, seed=11)
    g = C.bc.game((x, y, C.height(x, y) + r))
    for f in rock.faces:
        P = np.array([(rock.vertices[i].x + g[0], rock.vertices[i].y + g[1], rock.vertices[i].z + g[2]) for i in f])
        UV = np.array([(rock.vertices[i].u, rock.vertices[i].v) for i in f])
        tris.append((P, UV, np.ones(3) * 0.8, "boulder.tex"))
# a stand-in for the chaser mid-run, just out of its mouth, and cars on the grid
rock = C.make_boulder.boulder_mesh(C.CHASER_R, seed=23)
for cx in (-248.0,):
    g = C.bc.game((cx, 0.0, C.height(cx, 0.0) + C.CHASER_R))
    for f in rock.faces:
        P = np.array([(rock.vertices[i].x + g[0], rock.vertices[i].y + g[1], rock.vertices[i].z + g[2]) for i in f])
        UV = np.array([(rock.vertices[i].u, rock.vertices[i].v) for i in f])
        tris.append((P, UV, np.ones(3) * 0.8, "boulder.tex"))
h = lambda x, y=0.0: C.height(x, y)
views = {k: v for k, v in {
    "grid_back": ((-70.0, 3.0, h(-70) + 3.0), (-260.0, 0.0, h(-260) + 7.0)),
    "tunnel_fwd": ((-150.0, -3.0, h(-150) + 3.0), (0.0, 0.0, h(0) + 4.0)),
    "courtyard": ((-212.0, 30.0, h(-212, 30) + 12.0), (-256.0, 0.0, h(-256) + 8.0)),
    "exit_portal": ((70.0, 5.0, h(70) + 5.0), (-5.0, 0.0, h(-5) + 9.0)),
    "halfpipe_ambush": ((110.0, 6.0, h(110) + 3.0), (165.0, -16.0, h(165) + 8.0)),
    "halfpipe_down": ((30.0, 2.0, h(30) + 4.0), (320.0, 0.0, h(320))),
}.items() if k in ("tunnel_entry",)}
for k, (e, t) in views.items():
    print(RV.render(tris, tex, RV.g(e), RV.g(t), HERE / f"cave_{k}.png"))
