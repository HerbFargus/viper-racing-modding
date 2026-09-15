"""Render a built cockpit from the car archive itself.

    python render_cockpit.py <cars_dir> <out_dir> [width] [height]

Reads <prefix>c.mod and its textures back OUT of the packed .car and projects
them through cockpit.tab's own camera, so what you see is the artefact rather
than a model of it -- the same distinction that made preview_cockpit.py's FOV
estimate wrong twice. Every quad here is axis-aligned and faces the driver, so
its projection is a rectangle and the texture can be pasted rather than
rasterised.

Quads are drawn far-to-near by z, which is how the depth ordering in cockpits.py
(pillars in front of the header in front of the dash in front of the skirt) is
meant to resolve.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vrmod import archive, mod, tex                              # noqa: E402
from cockpits import CAMERA, GAUGE_Z, FOV_V                      # noqa: E402


def decode(raw: bytes):
    import io
    from PIL import Image
    return Image.open(io.BytesIO(tex.tex_to_png_bytes(raw))).convert("RGBA")


def render(car: Path, width: int, height: int):
    from PIL import Image
    ents = {e.name.lower(): e for e in archive.read(car)}
    name = next(n for n in ents if n.endswith("c.mod"))
    m = mod.parse(ents[name].to_standalone_bytes())

    d0 = GAUGE_Z - CAMERA[2]
    half_v = math.tan(math.radians(FOV_V / 2))
    half_h = half_v * (width / height)

    def project(x, y, z):
        dz = z - CAMERA[2]
        return (width * (0.5 + 0.5 * ((x - CAMERA[0]) / dz) / half_h),
                height * (0.5 - 0.5 * ((y - CAMERA[1]) / dz) / half_v))

    frame = Image.new("RGBA", (width, height), (108, 152, 198, 255))
    frame.paste(Image.new("RGBA", (width, height // 2), (92, 96, 102, 255)),
                (0, height // 2))

    quads = []
    for mt in m.materials:
        vs = m.vertices[mt.vertex_start:mt.vertex_end]
        for i in range(0, len(vs) - 3, 4):
            quads.append((mt.name, vs[i:i + 4]))
    # farthest first: bigger z is further from the eye, which sits at -0.791
    quads.sort(key=lambda q: -q[1][0].z)

    cache = {}
    for matname, vs in quads:
        key = matname.lower()
        if key not in cache:
            if key not in ents:
                continue
            cache[key] = decode(ents[key].to_standalone_bytes())
        img = cache[key]
        xs = [v.x for v in vs]; ys = [v.y for v in vs]
        us = [v.u for v in vs]; vv = [v.v for v in vs]
        z = vs[0].z
        px0, py0 = project(min(xs), max(ys), z)
        px1, py1 = project(max(xs), min(ys), z)
        w, h = max(1, round(px1 - px0)), max(1, round(py1 - py0))
        # the sub-rectangle of the page this quad actually addresses
        l, r = round(min(us) * img.width), round(max(us) * img.width)
        t, b = round(min(vv) * img.height), round(max(vv) * img.height)
        if r <= l or b <= t:
            continue
        piece = img.crop((l, t, r, b))
        if us[0] > us[2]:                      # mirrored pillar
            piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
        frame.alpha_composite(piece.resize((w, h), Image.LANCZOS),
                              (round(px0), round(py0)))
    return frame


def main(argv):
    from PIL import ImageDraw
    cars, out = Path(argv[0]), Path(argv[1])
    width = int(argv[2]) if len(argv) > 2 else 960
    height = int(argv[3]) if len(argv) > 3 else 540
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for car in sorted(cars.glob("*.car")):
        im = render(car, width, height)
        ImageDraw.Draw(im).text((8, 8), f"{car.stem}  {width}x{height}",
                                fill=(255, 255, 255, 255))
        im.convert("RGB").save(out / f"{car.stem}.png")
        made.append(car.stem)
        print(f"  {car.stem}")
    return made


if __name__ == "__main__":
    raise SystemExit(0 if main(sys.argv[1:]) else 1)
