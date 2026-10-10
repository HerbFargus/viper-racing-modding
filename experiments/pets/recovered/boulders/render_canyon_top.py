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
C.build_floor(scene)
tex = {k: np.array(f().convert("RGB")).astype(np.float32) / 255.0 for k, f in C.TEXTURES.items()}
tris = []
for name, m in scene.meshes.items():
    for f in m.faces:
        P = np.array([(m.vertices[i].x, m.vertices[i].y, m.vertices[i].z) for i in f])
        UV = np.array([(m.vertices[i].u, m.vertices[i].v) for i in f])
        tris.append((P, UV, np.ones(3), m.materials[0].name))
rock = C.make_boulder.boulder_mesh(C.BOULDER_R, seed=11)
for x, y in C.boulders():
    g = C.bc.game((x, y, C.height(x, y) + C.BOULDER_R))
    for f in rock.faces:
        P = np.array([(rock.vertices[i].x + g[0], rock.vertices[i].y + g[1], rock.vertices[i].z + g[2]) for i in f])
        UV = np.array([(rock.vertices[i].u, rock.vertices[i].v) for i in f])
        tris.append((P, UV, np.ones(3), "boulder.tex"))
h = C.height
views = {"top": ((250.0, -60.0, 1100.0), (250.0, -59.0, 0.0))}
for k, (e, t) in views.items():
    print(RV.render(tris, tex, RV.g(e), RV.g(t), HERE / f"canyon_{k}.png"))
