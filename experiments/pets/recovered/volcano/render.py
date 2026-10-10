"""Offline views of the volcano, with the crater renderer (lava/render_views.render)."""
import io
import contextlib
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "lava"))
import build_volcano as V  # noqa: E402
import render_views as RV  # noqa: E402
import volcano_art as art  # noqa: E402

_orig_sky = RV.art.crater_sky
RV.art.crater_sky = lambda *a, **k: _orig_sky(volcanoes=((300, 80, 0.11), (760, 60, 0.07)))   # the volcano's sky


def load():
    with contextlib.redirect_stdout(io.StringIO()):
        scene, g, line, wanted = V.main(verbose=False)
    tex = {name: np.array(fn()).astype(np.float32) / 255.0 for name, (fn, _m) in art.ALL.items()}
    tris = []
    for name, m in scene.meshes.items():
        if name == "ground.mod" or not m.materials:
            continue
        cols = scene.colours.get(name)
        t = m.materials[0].name
        Vx = m.vertices
        for f in m.faces:
            P = np.array([(Vx[i].x, Vx[i].y, Vx[i].z) for i in f])
            UV = np.array([(Vx[i].u, Vx[i].v) for i in f])
            G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
            tris.append((P, UV, G, t))
    # the rolling boulders, drawn where they start
    mm = V.magma_mesh()
    for x, y in V.MAGMA_AT:
        gx, gh, gz = V.bc.game((x, y, float(V.base_h(np.array(x), np.array(y))) + V.MAGMA_R + 0.4))
        for f in mm.faces:
            P = np.array([(mm.vertices[i].x + gx, mm.vertices[i].y + gh, mm.vertices[i].z + gz) for i in f])
            UV = np.array([(mm.vertices[i].u, mm.vertices[i].v) for i in f])
            tris.append((P, UV, np.array([1.0, 1.0, 1.0]), "magma.tex"))
    # the burning monks, standing where they start
    for x, y, z, look, yaw in V.monk_spots():
        mm = V.ds.monk_mesh(V.ds.MONK_TEX[look], yaw, V.bc.game)
        gx, gh, gz = V.bc.game((x, y, z + V.MONK_H / 2 + 0.05))
        for f in mm.faces:
            P = np.array([(mm.vertices[i].x + gx, mm.vertices[i].y + gh, mm.vertices[i].z + gz) for i in f])
            UV = np.array([(mm.vertices[i].u, mm.vertices[i].v) for i in f])
            tris.append((P, UV, np.array([1.0, 1.0, 1.0]), mm.materials[0].name))
    return tris, tex


def at(x, y, up):
    return (x, y, float(V.base_h(np.array(x), np.array(y))) + up)


VIEWS = {
    "1_climb": (at(-3, -430, 1.4), (0.0, -30.0, V.HR + 2)),
    "2_lip": (at(0, -70, 1.4), (0.0, 70.0, V.HR - 6)),
    "3_over_crater": ((0.0, -8.0, V.HR + 12.0), (0.0, 90.0, V.HR - 22)),
    "4_in_crater": ((-6.0, -2.0, V.LZ + 1.3), (30.0, 50.0, V.LZ + 3.0)),
    "5_descent": (at(4, 170, 1.4), (150.0, 360.0, 20.0)),
    "6_valley": (at(836, 180, 1.6), (0.0, 0.0, 55.0)),
    "7_aerial": ((1150.0, -1250.0, 820.0), (180.0, 0.0, 30.0)),
    "8_boulders": (at(-6, -330, 1.4), (0.0, -120.0, 150.0)),
    "9_jungle": (at(905, -60, 1.6), (760.0, -470.0, 4.0)),
    "10_dragon_climb": (at(0, -62, 1.4), (0.0, 20.0, V.HR + 6)),
    "11_dragon_lip": (at(0, -32, 1.4), (0.0, 20.0, V.HR + 3)),
    "12_fireball": ((0.0, -12.0, V.HR + 3.5), (0.0, 30.0, V.HR + 2)),
    "13_monks": ((V.PAD[0] - 16.0, V.PAD[1] - 20.0, V.HR + 3.0), (V.PAD[0], V.PAD[1], V.HR + 1.2)),
    "16_cottage_pad": ((V.PAD[0] - 26.0, V.PAD[1] - 22.0, V.HR + 5.0), (V.PAD[0], V.PAD[1] + 2.0, V.HR + 2.5)),
    "17_jungle_cottage": (at(864, -205, 1.6), (823.0, -175.0, 3.0)),
    "18_jungle_cottage2": (at(900, 560, 1.6), (872.0, 555.0, 3.0)),
    "19_respawn": ((V.CX - 50.0, V.CY + 2.0, V.HR + 1.5), (V.CX - 44.0, V.CY + 60.0, V.HR - 4.0)),
    "20_terrace_air": ((V.CX + 40.0, V.CY - 90.0, V.HR + 55.0), (V.CX - 38.0, V.CY + 4.0, V.HR - 6.0)),
    "21_from_lava": ((V.CX + 2.0, V.CY - 4.0, V.LZ + 1.4), (V.CX - 50.0, V.CY + 0.0, V.HR + 2.0)),
    "15_ledge_wide": ((V.PAD[0] - 30.0, V.PAD[1] - 55.0, V.HR + 14.0), (V.PAD[0] - 12.0, V.PAD[1] - 2.0, V.HR - 2.0)),
    "14_dragon_close": ((V.CX - 12.0, V.CY - 16.0, V.HR + 12.0), (V.CX - 28.0, V.CY + 12.0, V.HR + 12.0)),
}


if __name__ == "__main__":
    tris, tex = load()
    out = HERE / "shots"
    out.mkdir(exist_ok=True)
    for k in sys.argv[1:] or list(VIEWS):
        e, tg = VIEWS[k]
        print(RV.render(tris, tex, RV.g(e), RV.g(tg), out / f"{k}.png"))
