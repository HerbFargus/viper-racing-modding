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

# The straight-ahead steering sprite for each class. SoSC pre-rendered seven
# angles (-90 to +90 in 30-degree steps) and swaps them as you steer; Viper does
# not need them. Its wheel is `Viperw.mod`, a single flat quad at the origin with
# full-texture UVs that the game places at cockpit.tab's `wheel` point and
# rotates itself -- structurally the same sprite, rotated smoothly instead of in
# steps. So one frame is all that transfers.
#
# With one caveat that the seven frames exist to avoid: these sprites are
# CROPPED wheels, cut off square at the bottom edge of the image. SoSC never
# rotates one, so the crop never shows. Viper rotates the quad rigidly, so at
# large steering angles that straight edge swings into view. Small inputs look
# right; full lock will not. Nothing in the source art fixes this -- all seven
# frames are cropped the same way, and the missing half of the rim was never
# drawn.
WHEELS = {
    "strtrat": "COMP_0~1.BMP", "airhawk": "SED_0~1.BMP", "police": "SED_0~1.BMP",
    "azzaroni": "SPORT_~1.BMP", "j57": "RACE_0~1.BMP", "hunter": "RACE_0~1.BMP",
    "hmxvan": "UTIL_0~1.BMP",
}

PANELS = {
    "strtrat": "COMPF2.BMP", "airhawk": "SEDF2.BMP", "police": "SEDF2.BMP",
    "azzaroni": "SPORTF1.BMP", "j57": "RACEF2.BMP", "hunter": "RACEF2.BMP",
    "hmxvan": "UTILF3.BMP",
}
TILES = 3
TILE_PX = 256

# The panel is COMPUTED from the camera rather than hardcoded, because the first
# hardcoded guess was 95 degrees wide and filled the screen with a magnified
# corner of the dash.
#
# The anchor is the stock cockpit. Viperc.mod spans x -0.96..0.52 -- 1.48 units
# -- but sits further forward than the guess did, out to z +0.38, so at its own
# depth it subtends about 77 degrees. That is the game's cockpit field of view,
# near enough to work from; the same 1.48 at the guess's distance was 95.
#
# Everything else follows from wanting the panel to sit where SoSC puts it: a
# 640x192 image in a 640x480 frame is exactly the bottom 40% of the screen.
CAMERA = (-0.408, 0.906, -0.791)      # cockpit.tab's own camera record
GAUGE_Z = -0.14                       # the plane the needle pivots sit on

# MEASURED from a screenshot rather than estimated. The 77-degree figure guessed
# from the stock dash put the panel's top edge at 65% of the frame when it was
# designed for 60%, and that discrepancy solves the camera exactly: a top edge
# 6.7 degrees below the horizon landing 30% of a half-height down gives a
# vertical half-FOV of 21.3 degrees.
#
# SCREEN_ASPECT was the bigger error. It was set to 4:3 because that is what the
# GAME is, but the frame it renders into is whatever the install is patched to --
# 1920x1080 here, so 16:9. Too small an aspect makes half_h too large, which
# pushed 26% of the panel below the bottom of the screen: PRNDL21 sat on the
# edge with dash still to come underneath.
#
# These two are display-dependent, not game-dependent. A 4:3 install wants
# SCREEN_ASPECT = 4/3, and the horizontal FOV follows from it.
FOV_V = 42.6                          # degrees, measured
SCREEN_ASPECT = 16 / 9                # the frame, not the game
PANEL_SCREEN_FRACTION = 0.40          # bottom 40%, as in SoSC


def panel_box(aspect: float):
    """(x0, x1, top, bottom, z) for a panel of the given height/width ratio.

    Placed at the gauge plane, centred on the camera's own x so it fills the
    frame symmetrically -- the camera sits at x -0.408, not at zero, and a panel
    centred on the car's centreline would hang off to one side.
    """
    import math
    d = GAUGE_Z - CAMERA[2]
    half_h = math.tan(math.radians(FOV_V / 2)) * d
    half_w = half_h * SCREEN_ASPECT
    width = 2 * half_w
    height = width * aspect
    bottom = CAMERA[1] - half_h                      # the bottom of the screen
    top = bottom + height
    return (CAMERA[0] - half_w, CAMERA[0] + half_w, top, bottom, GAUGE_Z)


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


def wheel_texture(im, prefix: str):
    """The steering sprite as a colorkey .tex, cyan keyed out.

    Colorkey rather than the flags=0x03 alpha the stock wheel uses: 0x03 is a
    four-byte-per-pixel format, and writing ARGB4444 under it hands the game
    half the data it expects and panics the loader. Hard-edged transparency is
    what the source has anyway -- it is a colour key in SoSC too.
    """
    from PIL import Image
    page = Image.new("RGB", (TILE_PX, TILE_PX), (0, 255, 255))
    fitted = im.resize((TILE_PX, TILE_PX), Image.NEAREST)
    page.paste(fitted, (0, 0))
    rgba = bytearray()
    for (r, g, b) in page.getdata():
        a = 0 if (r < 60 and g > 200 and b > 200) else 255
        rgba += bytes((r, g, b, a))
    return f"{prefix}w.tex", tex.encode_to_tex(bytes(rgba), TILE_PX,
                                               mode="colorkey", wrap=1)


def build_wheel_mesh(name: str, src_w: int, src_h: int, version: int = 1) -> mod.Mesh:
    """A quad at the ORIGIN, like the stock wheel -- the game moves and turns it.

    Sized from the sprite's own proportions against the dash panel, so the wheel
    keeps the size relationship it has in the original: a SED wheel is 392 of the
    panel's 640 pixels wide, and the panel spans 1.50 units here, so the wheel is
    0.92 units across. Guessing a size would be guessing the one thing the source
    art actually tells us.
    """
    x0, x1, _t, _b, _z = panel_box(1.0)
    span = x1 - x0
    w = span * (src_w / 640.0)
    h = span * (src_h / 640.0)
    hw, hh = w / 2, h / 2
    verts = [mod.Vertex(x=hw, y=hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=1.0, v=0.0),
             mod.Vertex(x=-hw, y=hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=0.0, v=0.0),
             mod.Vertex(x=-hw, y=-hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=0.0, v=1.0),
             mod.Vertex(x=hw, y=-hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=1.0, v=1.0)]
    faces = [(0, 1, 2), (0, 2, 3)]
    return mod.Mesh(vertices=verts,
                    materials=[mod.Material(name, 0, 4, 0, 2)],
                    faces=faces, version=version)


def build_panel_mesh(tiles, version: int = 1) -> mod.Mesh:
    """One quad per tile, side by side, facing the driver."""
    verts, faces, mats = [], [], []
    total = sum(t[2] for t in tiles)
    aspect = tiles[0][3] / total          # height / full width, in pixels
    x0, x1, y1, y0, panel_z = panel_box(aspect)
    cut = x0
    for name, _raw, w, h in tiles:
        span = (x1 - x0) * (w / total)
        # the tile occupies the top-left w x h of a TILE_PX page
        u1, v1 = w / TILE_PX, h / TILE_PX
        base = len(verts)
        for (x, y, u, v) in ((cut, y1, 0.0, 0.0), (cut, y0, 0.0, v1),
                             (cut + span, y1, u1, 0.0), (cut + span, y0, u1, v1)):
            # V grows DOWNWARD -- v=0 is the TOP of the texture. Checked
            # against the stock brake lamp quad, whose top vertex (y 0.815)
            # carries v 0.383 and whose bottom (y 0.442) carries v 0.480.
            # Storing 1.0 - v instead, which is what this did first, turns every
            # panel upside down: the black lower dash renders across the top of
            # the quad and PRNDL21 reads mirrored along the bottom edge.
            verts.append(mod.Vertex(x=x, y=y, z=panel_z, nx=0.0, ny=0.0, nz=-1.0,
                                    u=u, v=v))
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

    # the steering wheel, if this class has one
    wheel_note = ""
    src = panels_dir.parent / "steer" / WHEELS.get(prefix, "")
    if src.is_file():
        wim = load_panel(src)
        wname, wraw = wheel_texture(wim, prefix[:3])
        wmesh = build_wheel_mesh(wname, wim.width, wim.height)
        entries = archive.upsert_entry(entries, f"{prefix}w.mod", mod.build(wmesh))
        entries = archive.upsert_entry(entries, wname, wraw)
        bx0, bx1, _t, _b, _z = panel_box(1.0)
        span = bx1 - bx0
        wheel_note = (f", wheel {WHEELS[prefix]} "
                      f"({wim.width}x{wim.height} -> {span*wim.width/640:.2f} wide)")

    archive.write(entries, car)
    bx0, bx1, btop, bbot, bz = panel_box(im.height / im.width)
    return (f"{PANELS[prefix]} -> {TILES} tiles ({im.width}x{im.height}), "
            f"panel x {bx0:.2f}..{bx1:.2f} y {bbot:.2f}..{btop:.2f} z {bz:.2f}"
            f"{wheel_note}")


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
