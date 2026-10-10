"""Offline perspective renders of the crater, for when no browser can draw.

Renders the builder's own scene -- every drawn mesh, its texture and its baked grey
light -- with a z-buffer and the game's one-sided faces (a triangle shows when its
winding faces the eye), at the game's measured 16:9 / ~54 degree view, with the sky
strip behind. An approximation of the game's look, not a capture of it.
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_crater as C  # noqa: E402
import lava_art as art  # noqa: E402

W, H, VFOV = 960, 540, 54.0


def load_scene():
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        scene, st = C.main()
    tex = {name: np.array(fn()).astype(np.float32) / 255.0 for name, (fn, _m) in art.ALL.items()}
    tris = []                                   # (P 3x3 game, UV 3x2, grey 3, texture)
    for name, m in scene.meshes.items():
        if name == "ground.mod" or not m.materials:
            continue
        cols = scene.colours.get(name)
        t = m.materials[0].name
        V = m.vertices
        for f in m.faces:
            P = np.array([(V[i].x, V[i].y, V[i].z) for i in f])
            UV = np.array([(V[i].u, V[i].v) for i in f])
            G = np.array([cols[i][0] / 255.0 if cols else 1.0 for i in f])
            tris.append((P, UV, G, t))
    return tris, tex


def look(eye, target):
    f = np.array(target, float) - np.array(eye, float); f /= np.linalg.norm(f)
    up = np.array([0.0, 1.0, 0.0])
    r = np.cross(up, f); r /= np.linalg.norm(r)            # game frame is left-handed: x right when looking +z
    u = np.cross(f, r)
    return r, u, f


def sky_background(r, u, f, sky):
    ys, xs = np.mgrid[0:H, 0:W]
    t = math.tan(math.radians(VFOV) / 2)
    dx = (xs + 0.5 - W / 2) / (H / 2) * t
    dy = -(ys + 0.5 - H / 2) / (H / 2) * t
    d = f[None, None, :] + dx[..., None] * r[None, None, :] + dy[..., None] * u[None, None, :]
    d /= np.linalg.norm(d, axis=2, keepdims=True)
    az = np.arctan2(d[..., 0], d[..., 2])
    el = np.arcsin(np.clip(d[..., 1], -1, 1))
    sh, sw = sky.shape[:2]
    su = ((az / (2 * math.pi) * 4) % 1.0 * sw).astype(int) % sw
    sv = np.clip((1 - el / math.radians(40)) * sh, 0, sh - 1).astype(int)
    img = sky[sv, su].copy()
    img[el < 0] = np.array([30, 22, 20]) / 255.0
    return img


def clip_near(cam, uv, g, near=0.3):
    """Clip a camera-space triangle against z = near; returns 0-2 triangles."""
    pts = list(zip(cam, uv, g))
    out = []
    for i in range(3):
        a, b = pts[i], pts[(i + 1) % 3]
        ina, inb = a[0][2] >= near, b[0][2] >= near
        if ina:
            out.append(a)
        if ina != inb:
            t = (near - a[0][2]) / (b[0][2] - a[0][2])
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2])))
    if len(out) < 3:
        return []
    return [(out[0], out[k], out[k + 1]) for k in range(1, len(out) - 1)]


def render(tris, tex, eye, target, out_path):
    eye = np.array(eye, float)
    r, u, f = look(eye, target)
    sky = np.array(art.crater_sky()).astype(np.float32) / 255.0
    img = sky_background(r, u, f, sky)
    zbuf = np.full((H, W), np.inf)
    t = math.tan(math.radians(VFOV) / 2)
    Mrot = np.stack([r, u, f])
    for P, UV, G, tname in tris:
        a, b, c = P
        if np.dot(np.cross(b - a, c - a), eye - a) <= 0:          # the game draws one side only
            continue
        cam = (P - eye) @ Mrot.T
        if (cam[:, 2] < 0.3).all():
            continue
        for tri in clip_near(cam, UV, G):
            cp = np.array([q[0] for q in tri]); tuv = np.array([q[1] for q in tri]); tg = np.array([q[2] for q in tri])
            sx = W / 2 + cp[:, 0] / cp[:, 2] / t * (H / 2)
            sy = H / 2 - cp[:, 1] / cp[:, 2] / t * (H / 2)
            x0, x1 = max(int(sx.min()), 0), min(int(sx.max()) + 1, W)
            y0, y1 = max(int(sy.min()), 0), min(int(sy.max()) + 1, H)
            if x0 >= x1 or y0 >= y1:
                continue
            ys, xs = np.mgrid[y0:y1, x0:x1]
            px, py = xs + 0.5, ys + 0.5
            den = (sy[1] - sy[2]) * (sx[0] - sx[2]) + (sx[2] - sx[1]) * (sy[0] - sy[2])
            if abs(den) < 1e-9:
                continue
            w0 = ((sy[1] - sy[2]) * (px - sx[2]) + (sx[2] - sx[1]) * (py - sy[2])) / den
            w1 = ((sy[2] - sy[0]) * (px - sx[2]) + (sx[0] - sx[2]) * (py - sy[2])) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            iz = w0 / cp[0, 2] + w1 / cp[1, 2] + w2 / cp[2, 2]
            z = 1 / iz
            win = inside & (z < zbuf[y0:y1, x0:x1])
            if not win.any():
                continue
            uu = (w0 * tuv[0, 0] / cp[0, 2] + w1 * tuv[1, 0] / cp[1, 2] + w2 * tuv[2, 0] / cp[2, 2]) * z
            vv = (w0 * tuv[0, 1] / cp[0, 2] + w1 * tuv[1, 1] / cp[1, 2] + w2 * tuv[2, 1] / cp[2, 2]) * z
            gg = (w0 * tg[0] / cp[0, 2] + w1 * tg[1] / cp[1, 2] + w2 * tg[2] / cp[2, 2]) * z
            T = tex[tname]
            th, tw = T.shape[:2]
            ti = ((vv % 1.0) * th).astype(int) % th
            tj = ((uu % 1.0) * tw).astype(int) % tw
            texel = T[ti, tj]
            if T.shape[2] == 4:                                   # colorkey: keyed texels are holes
                win &= texel[..., 3] > 0.5
                texel = texel[..., :3]
            col = texel * np.clip(gg, 0, 1)[..., None]
            sub = img[y0:y1, x0:x1]
            sub[win] = col[win]
            zbuf[y0:y1, x0:x1][win] = z[win]
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(out_path)
    return out_path


def g(p):
    return C.bc.game(p)


VIEWS = {
    "1_runway": ((300.0, -4.0, 1.4), (440.0, 0.0, 4.0)),
    "2_lip": ((417.0, 0.0, C.LIP_H + 1.4), (540.0, 0.0, -2.0)),
    "3_flight": ((470.0, 0.0, 15.0), (600.0, 0.0, 0.0)),
    "4_side": ((445.0, -34.0, 20.0), (445.0, 20.0, -2.0)),
    "5_overview": ((330.0, -170.0, 430.0), (330.0, 70.0, 0.0)),
    "6_in_lava": ((440.0, 8.0, C.LAVA + 1.3), (480.0, -2.0, 1.0)),
    "7_return": ((60.0, 136.0, 1.4), (320.0, 70.0, 16.0)),
}


if __name__ == "__main__":
    tris, tex = load_scene()
    out = HERE / "shots"
    out.mkdir(exist_ok=True)
    which = sys.argv[1:] or list(VIEWS)
    for k in which:
        e, tg = VIEWS[k]
        print(render(tris, tex, g(e), g(tg), out / f"{k}.png"))
