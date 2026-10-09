"""Bake ambient occlusion into a car's wheels: wheel_1-3.mod and fwheel_1-3.mod.

python bake_wheels.py <in.car> <out.car> [px_per_m]

The six are one identical mesh, so it's baked once onto its own page(s)
(wjwh0.tex ...) and written to all six. Occlusion only, no key light: the wheel
spins, and a baked highlight would spin with it. The flat light level is the
body's key light averaged over all directions, so the wheels match the body.
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
import bake_light as B
from vrmod import archive, envelope, mod, carshot
import toon

NAMES = [f"{p}wheel_{i}.mod" for p in ("", "f") for i in (1, 2, 3)]


def main(src, dst, ppm=120.0):
    entries = archive.read(src)
    by = {e.name.lower(): e for e in entries}
    e1 = by[NAMES[0]]
    assert all(by[n].payload == e1.payload for n in NAMES), "the wheel meshes differ; bake each"
    wheel = mod.parse(envelope.build(e1.tag, e1.version, e1.payload))
    # Mean of KEY_FLOOR + KEY_GAIN * max(0, n.key) over all directions n: the positive
    # half of a cosine averages 1/4 over the sphere.
    B.KEY_FLOOR, B.KEY_GAIN = B.KEY_FLOOR + B.KEY_GAIN / 4, 0.0
    B.STEM = "wjwh"
    cols = toon.face_colours(wheel, carshot.material_textures(src, wheel))
    baked, pages, nch, mean_ao = B.bake(wheel, cols, ppm)
    data = mod.build(baked, e1.version)
    for n in NAMES:
        entries = archive.upsert_entry(entries, by[n].name, data)
    for i, img in enumerate(pages):
        entries = archive.upsert_entry(entries, f"wjwh{i}.tex", B.tex_bytes(img))
        img.save(Path(dst).with_name(f"wjwh{i}.png"))
    archive.write(entries, dst)
    print(f"wheels: {nch} charts on {len(pages)} page(s), mean openness {mean_ao:.2f}, "
          f"{len(baked.vertices)} verts (was {len(wheel.vertices)}), materials {[m.name for m in baked.materials]}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], *(float(x) for x in a[2:]))
