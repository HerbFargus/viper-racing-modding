"""Texture-limit test: the white ball room with N signboards round the lap, each with its OWN texture.

The stock engine crashes once about 119 textures are in use (the deferred-draw bucket overflow; see
viper-port hook/viperport.cpp, lift_texture_limit). Each board shows its number, so a board drawn
with the wrong texture -- or untextured -- is easy to spot.

    python build_texlimit.py 150  ->  Tex150.tra in the Data folder
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_ballroom as B  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 150
_orig_scene = B.build_scene


def board_tex(k):
    hue = (k * 47) % 360
    import colorsys
    r, g, b = (int(255 * c) for c in colorsys.hsv_to_rgb(hue / 360.0, 0.55, 0.95))
    im = Image.new("RGB", (64, 64), (r, g, b))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, 62, 62], outline=(40, 40, 40), width=2)
    f = ImageFont.truetype("arialbd.ttf", 26)
    t = str(k)
    bb = d.textbbox((0, 0), t, font=f)
    d.text(((64 - (bb[2] - bb[0])) / 2 - bb[0], (64 - (bb[3] - bb[1])) / 2 - bb[1]), t, fill=(30, 30, 30), font=f)
    return im


def build_scene():
    scene, line = _orig_scene()
    for k in range(N):
        s = (k + 0.5) / N * line.L
        (x, y, _z), (tx, ty) = line.at(s)
        nx, ny = -ty, tx                                   # to the left of the line
        cx, cy = x + nx * 9.0, y + ny * 9.0
        name = f"tl{k:03d}.tex"
        B.TEXTURES[name] = (lambda k=k: board_tex(k))
        b = B.Batch(scene, f"tlb{k:03d}_", name, False)
        p = [(cx - tx * 1.5, cy - ty * 1.5, 1.0), (cx + tx * 1.5, cy + ty * 1.5, 1.0),
             (cx + tx * 1.5, cy + ty * 1.5, 4.0), (cx - tx * 1.5, cy - ty * 1.5, 4.0)]
        uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        face = (x, y, 2.5)                                 # facing the line
        b.tri([p[0], p[1], p[2]], [uv[0], uv[1], uv[2]], 1.0, up=face)
        b.tri([p[0], p[2], p[3]], [uv[0], uv[2], uv[3]], 1.0, up=face)
        b.flush()
    return scene, line


B.build_scene = build_scene
B.BASE = HERE / f"Tex{N}_base.trk"
B.make_base()
B.write_count([], [], f"Tex{N}")
