"""Put a Streets of SimCity dashboard into a Viper Racing cockpit.

The two games disagree about what a cockpit IS. SoSC draws a flat 640x190
bitmap across the bottom of the screen. Viper renders 3D geometry in car space
-- `Viperc.mod`, 45 faces -- and drives a separate needle from `cockpit.tab`.

So the SoSC look is rebuilt as a flat billboard sitting in front of the cockpit
camera. Not a compromise: a flat panel filling the lower view is exactly what
the original is, and Viper has no objection to a cockpit mesh being flat.

WHAT THE DISC PROVIDES. Five panels, by car CLASS rather than by car, which
covers all seven conversions:

    COMPF2  640x180  compact   -> strtrat   (confirmed from a screenshot)
    SEDF2   640x192  sedan     -> airhawk, police   (airhawk confirmed)
    SPORTF1 640x200  sport     -> azzaroni
    RACEF2  640x198  race      -> j57, hunter       (j57 confirmed)
    UTILF3  640x185  utility   -> hmxvan

THREE TILES, not one. Viper's textures cap at 256 pixels square, so a 640-wide
panel cannot be one texture. Scaling it down to 256 would throw away 60% of the
horizontal detail, which is precisely where the gauge markings are -- so the
panel is cut into three tiles across three quads instead, each keeping its
pixels at 1:1.

CYAN IS THE TRANSPARENCY KEY. Between 10% and 26% of each panel is cyan: the
mirror inset, and the whole region above the dash that has to show the road.
Viper stores a per-texture colorkey value in the .tex header, so cyan maps
straight onto it -- no repainting needed.

THE MECHANISM IS PROVEN, which is the part that could have sunk this: 4x4cos.car
ships with its own `4x4cosc.mod` and `cockpit.tab`, so a car carrying a cockpit
of its own is something the game already does. (MGI copied the Viper's mesh and
textures wholesale, so there is no precedent for one that LOOKS different --
only for one existing.)

POSITIONING IS A GUESS on the first pass and will need correcting from the
game, the same way the brake lights did. Nothing here can render a cockpit:
carshot draws the body and wheels, so the panel's placement is invisible until
somebody sits in it.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from vrmod import archive, cockpit_tab, envelope, mod, tex  # noqa: E402

PANELS = {
    "strtrat": "COMPF2.BMP", "airhawk": "SEDF2.BMP", "police": "SEDF2.BMP",
    "azzaroni": "SPORTF1.BMP", "j57": "RACEF2.BMP", "hunter": "RACEF2.BMP",
    "hmxvan": "UTILF3.BMP",
}
TILES = 3
TILE_PX = 256

# Where the panel sits in car space. The cockpit camera is at
# (-0.408, 0.906, -0.791) and the instrument faces are at z -0.14, y ~0.70, so
# the panel goes just forward of the needles and below the eye line. The width
# matches the stock dash mesh's own span (x -0.96..0.54), and the height follows
# from the panel's aspect ratio rather than being chosen -- a 640x192 image in a
# 1.50-wide quad is 0.45 tall, and squashing it would be visible on every dial.
PANEL_X = (-0.96, 0.54)
PANEL_Z = -0.10
PANEL_TOP = 0.82


def load_panel(path: Path):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    return im


def tile_textures(im, prefix: str) -> list[tuple[str, bytes]]:
    """Cut the panel into TILES columns, each its own colorkey .tex."""
    from PIL import Image
    out = []
    edges = [round(im.width * i / TILES) for i in range(TILES + 1)]
    for i in range(TILES):
        crop = im.crop((edges[i], 0, edges[i + 1], im.height))
        # Pad into a square power-of-two page: the .tex format is square and
        # power-of-two only, and padding beats scaling because the UVs can
        # simply address the used corner.
        page = Image.new("RGB", (TILE_PX, TILE_PX), (0, 255, 255))
        page.paste(crop, (0, 0))
        rgba = bytearray()
        for (r, g, b) in page.getdata():
            # cyan -> transparent; everything else opaque
            a = 0 if (r < 60 and g > 200 and b > 200) else 255
            rgba += bytes((r, g, b, a))
        raw = tex.encode_to_tex(bytes(rgba), TILE_PX, mode="colorkey", wrap=1)
        out.append((f"{prefix}p{i}.tex", raw, crop.width, crop.height))
    return out


def build_panel_mesh(tiles, version: int = 1) -> mod.Mesh:
    """One quad per tile, side by side, facing the driver."""
    verts, faces, mats = [], [], []
    x0, x1 = PANEL_X
    total = sum(t[2] for t in tiles)
    aspect = tiles[0][3] / total          # height / full width, in pixels
    height = (x1 - x0) * aspect
    y1, y0 = PANEL_TOP, PANEL_TOP - height
    cut = x0
    for name, _raw, w, h in tiles:
        span = (x1 - x0) * (w / total)
        # the tile occupies the top-left w x h of a TILE_PX page
        u1, v1 = w / TILE_PX, h / TILE_PX
        base = len(verts)
        for (x, y, u, v) in ((cut, y1, 0.0, 0.0), (cut, y0, 0.0, v1),
                             (cut + span, y1, u1, 0.0), (cut + span, y0, u1, v1)):
            verts.append(mod.Vertex(x=x, y=y, z=PANEL_Z, nx=0.0, ny=0.0, nz=-1.0,
                                    u=u, v=1.0 - v))
        fstart = len(faces)
        faces += [(base + 2, base + 1, base), (base + 1, base + 2, base + 3)]
        mats.append(mod.Material(name, base, len(verts), fstart, len(faces)))
        cut += span
    return mod.Mesh(vertices=verts, materials=mats, faces=faces, version=version)


def fit(car: Path, prefix: str, panels_dir: Path, base_car: Path) -> str:
    im = load_panel(panels_dir / PANELS[prefix])
    tiles = tile_textures(im, prefix[:3])
    mesh = build_panel_mesh(tiles)

    entries = archive.read(car)
    # the cockpit table: copied from a car that has one, since its camera and
    # needle calibration are the only reference points that exist
    base = {e.name.lower(): e for e in archive.read(base_car)}
    tab = base["cockpit.tab"]
    entries = archive.upsert_entry(
        entries, "cockpit.tab",
        envelope.build(tab.tag, tab.version, tab.payload))
    entries = archive.upsert_entry(entries, f"{prefix}c.mod", mod.build(mesh))
    for name, raw, _w, _h in tiles:
        entries = archive.upsert_entry(entries, name, raw)
    archive.write(entries, car)
    return (f"{PANELS[prefix]} -> {TILES} tiles ({im.width}x{im.height}), "
            f"panel at z {PANEL_Z}, y {PANEL_TOP:.2f} down")


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("cockpits.py <panels_dir> <viper_install> <car_or_fleet>")
    panels, install, target = (Path(a) for a in sys.argv[1:4])
    base_car = install / "viper.car"
    cars = sorted(target.rglob("*.car")) if target.is_dir() else [target]
    for car in cars:
        if car.stem not in PANELS:
            print(f"  {car.stem:10s} no panel assigned")
            continue
        print(f"  {car.stem:10s} {fit(car, car.stem, panels, base_car)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
