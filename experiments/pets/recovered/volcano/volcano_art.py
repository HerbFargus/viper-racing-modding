"""Volcano art. New here: the dirt road and the ash ground; basalt, hot rock, lava and
the erupting-volcano sky come from the crater set (lava_art).

  dirtrd.tex  a dirt road: packed brown-grey earth, two darker tyre ruts, gravel,
              edges crumbling into ash (u across the road, v along 16 m)
  ash.tex     volcanic ash ground: dark grey-brown, pumice flecks (tiles on the world)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lava"))
sys.path.insert(0, str(HERE.parent / "circuit"))
import lava_art as la  # noqa: E402
from art import colourise, speckle, tile_noise, to_img  # noqa: E402


def ash(size=256, seed=61):
    n = tile_noise(size, 8, 5, 0.6, seed)
    img = colourise(n, (40, 36, 36), (70, 62, 58))
    fine = tile_noise(size, 48, 2, 0.5, seed + 1)
    img *= (0.88 + 0.24 * fine)[..., None]
    img += speckle(size, 0.02, seed + 2)[..., None] * np.array([48, 42, 36])      # pumice
    img -= speckle(size, 0.03, seed + 3)[..., None] * np.array([20, 18, 16])      # cinders
    return to_img(img)


def dirt_road(size=256, seed=67):
    n = tile_noise(size, 6, 5, 0.55, seed)
    img = colourise(n, (128, 104, 80), (168, 140, 110))
    x = np.arange(size)[None, :] / size
    y = np.arange(size)[:, None] / size
    wob = 0.012 * np.sin(2 * np.pi * (y * 2 + 0.3)) + 0.006 * np.sin(2 * np.pi * y * 5)
    ruts = np.exp(-((x - 0.3 - wob) / 0.05) ** 2) + np.exp(-((x - 0.7 + wob) / 0.05) ** 2)
    img *= (1 - 0.28 * ruts)[..., None]
    crown = np.exp(-((x - 0.5) / 0.08) ** 2)
    img = img + np.array([10, 8, 6]) * crown[..., None]                          # the packed crown
    img += speckle(size, 0.05, seed + 1)[..., None] * np.array([34, 30, 26])       # gravel
    img -= speckle(size, 0.03, seed + 2)[..., None] * np.array([24, 22, 20])
    edge = np.clip((np.abs(x - 0.5) - 0.40) / 0.10, 0, 1)                          # crumbles into ash
    edge = np.clip(edge + 0.35 * (tile_noise(size, 16, 3, 0.5, seed + 3) - 0.5), 0, 1)
    ashc = np.array(ash(size)).astype(float)
    img = img * (1 - edge[..., None]) + ashc * edge[..., None]
    return to_img(img)


ALL = {"dirtrd.tex": (dirt_road, "opaque"), "ash.tex": (ash, "opaque"),
       "basalt.tex": la.ALL["basalt.tex"], "hot.tex": la.ALL["hot.tex"], "lava.tex": la.ALL["lava.tex"]}
import jungle_art as ja  # noqa: E402
ALL.update(ja.ALL)


def sky():
    """The crater sky with its volcanoes pushed far off: this volcano must dominate."""
    return la.crater_sky(volcanoes=((300, 80, 0.11), (760, 60, 0.07)))


if __name__ == "__main__":
    sheet = Image.new("RGB", (5 * 140 + 10, 150), (20, 16, 16))
    for i, (name, (fn, _)) in enumerate(ALL.items()):
        sheet.paste(fn().resize((128, 128), Image.NEAREST), (10 + i * 140, 10))
    sheet.save(HERE / "volcano_art.png")
    print(HERE / "volcano_art.png")
