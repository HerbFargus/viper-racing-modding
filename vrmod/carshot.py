"""Generate a small thumbnail of a car, straight from its mesh.

A .car has no equivalent of a track's .stp menu screenshot, so unlike tracks
there is no stored picture to show in a library listing. Rather than leave car
entries as text, this renders one -- the same move trackmap.py makes for
tracks, which draw their own outline from track.ild.

Pure Python, no GL. That is viable because these meshes are tiny by modern
standards: with wheels the stock cars are 250-620 triangles and the most
elaborate add-ons about 2800. Measured, the cost is ALL in the per-pixel loop
-- reading the archive, decoding textures and assembling the wheels each come
in at 0.01s or less. So more data is free; only more pixels and more triangles
cost anything.

Two styles:

  "wire"    (default) hidden-line wireframe. Two passes: fill every triangle
            into the DEPTH buffer only, then draw each edge, plotting it only
            where it is at or in front of the stored depth. Structure on the
            far side is hidden by the near side, which is what makes this
            readable rather than a ball of string. It is also CHEAPER than
            shading, since the fill pass writes no colour and does no lighting.

  "shaded"  flat-shaded solid, tinted per material by the average colour of
            that material's texture (see material_colours). Kept because it is
            occasionally useful, but wireframe is the default: at icon size the
            averaged colours come out muddy and the shaded wheels read as grey
            blobs, so the wireframe is both clearer and faster.

Wheels come from car.assemble_car(), which positions them from tyre data and
applies the ground offset so the car sits on them. Worth their ~60% extra
triangles -- a kart without wheels reads as a lump.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import archive, car as car_mod, envelope, mod, tex

WIDTH = 200
HEIGHT = 120
MARGIN = 8

# A three-quarter view reads as "a car" far better than a flat side-on
# silhouette, and it separates the add-ons from each other at icon size.
YAW = 35.0
PITCH = 18.0

BACKGROUND = (25, 28, 34)      # sits just under the UI's panel colour
WIRE = (150, 200, 235)         # cool blueprint blue against the dark ground
BASE = (150, 160, 178)         # "shaded" fallback when a material has no texture

# Depth slack when testing an edge against the surface it belongs to, so a
# triangle's own outline is not z-fought away by its own fill.
EDGE_BIAS = 0.012
# Near edges are drawn brighter than far ones, which is most of what gives a
# flat wireframe its sense of depth.
WIRE_FADE = 0.45

AMBIENT = 0.30                 # "shaded": floor brightness for faces facing away
LIGHT = (-0.35, 0.72, 0.60)
SAMPLE_STRIDE = 7              # texture-averaging stride; coprime with typical widths


class CarShotError(RuntimeError):
    """The car has no drawable mesh."""


def body_mesh(car_path: str | Path) -> mod.Mesh:
    """The car's main body part. Named <prefix>0.mod in every stock and add-on
    car seen so far (Viper0.mod, mario0.mod, plane0.mod)."""
    entries = archive.read(Path(car_path))
    entry = next((e for e in entries if e.name.lower().endswith("0.mod")), None)
    if entry is None:
        raise CarShotError(f"no body mesh (<prefix>0.mod) in {Path(car_path).name}")
    return mod.parse(envelope.build(entry.tag, entry.version, entry.payload))


def car_mesh(car_path: str | Path, wheels: bool = True) -> mod.Mesh:
    """Body plus positioned wheels, falling back to the bare body if assembly
    fails -- a mod car with missing or odd wheel parts still gets an icon."""
    car_path = Path(car_path)
    if wheels:
        try:
            return car_mod.assemble_car(car_path).mesh
        except Exception:
            pass
    return body_mesh(car_path)


def material_colours(car_path: str | Path, mesh: mod.Mesh,
                     paint_texture: str | Path | None = None) -> dict[str, tuple[int, int, int]]:
    """Average colour of each material's texture, keyed by material name.
    Only used by the "shaded" style.

    Resolves names the way the game does -- the car's own archive, then the
    shared .res bundles beside it, then the runtime paint slot (see
    car.resolve_textures). Looking only inside the .car, as this used to, missed
    every shared material (wheels, glass, effects come from race.res) and missed
    the body paint entirely on the many community cars whose own textures are
    just white shading overlays: their colour lives in the paint the player
    supplies, so without one they really are grey shells.

    Transparent pixels are skipped: a colorkeyed texture is mostly hole for
    things like grilles and wings, and averaging the key colour in drags every
    result toward it.
    """
    from . import car as car_mod        # local: car imports this module's siblings
    names = {(m.name or "") for m in mesh.materials if m.name}
    try:
        raw_by_name = car_mod.resolve_textures(car_path, names, paint_texture=paint_texture)
    except Exception:
        raw_by_name = {}
    out: dict[str, tuple[int, int, int]] = {}
    for m in mesh.materials:
        raw = raw_by_name.get(m.name)
        if raw is None:
            continue
        try:
            info = tex.parse(raw)
            px = tex.decode_base_level(info)
        except Exception:
            continue
        step = 4 if (info.has_alpha or info.has_colorkey) else 3
        r = g = b = n = 0
        for i in range(0, len(px) - step + 1, step * SAMPLE_STRIDE):
            if step == 4 and px[i + 3] < 128:
                continue
            r += px[i]; g += px[i + 1]; b += px[i + 2]; n += 1
        if n:
            out[m.name] = (r // n, g // n, b // n)
    return out


def _viewer(yaw: float, pitch: float):
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))

    def view(x: float, y: float, z: float) -> tuple[float, float, float]:
        """Yaw about Y, then pitch about X. Returns (screen u, screen v, depth)."""
        x2, z2 = x * cy + z * sy, -x * sy + z * cy
        return x2, y * cp - z2 * sp, y * sp + z2 * cp

    return view


def _project(mesh: mod.Mesh, width: int, height: int, yaw: float, pitch: float):
    view = _viewer(yaw, pitch)
    pts = [view(v.x, v.y, v.z) for v in mesh.vertices]
    if not pts:
        raise CarShotError("mesh has no vertices")
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    du = (max(us) - min(us)) or 1.0
    dv = (max(vs) - min(vs)) or 1.0
    scale = min((width - 2 * MARGIN) / du, (height - 2 * MARGIN) / dv)
    ox = (width - du * scale) / 2 - min(us) * scale
    oy = (height - dv * scale) / 2 + max(vs) * scale      # screen Y grows downward
    return view, [(u * scale + ox, oy - v * scale, d) for u, v, d in pts]


def render(
    mesh: mod.Mesh, style: str = "wire",
    width: int = WIDTH, height: int = HEIGHT,
    yaw: float = YAW, pitch: float = PITCH,
    background: tuple[int, int, int] = BACKGROUND,
    wire: tuple[int, int, int] = WIRE,
    base: tuple[int, int, int] = BASE,
    colours: dict[str, tuple[int, int, int]] | None = None,
) -> tuple[bytes, int, int]:
    """Render the mesh to raw RGB bytes. Returns (pixels, width, height)."""
    if style not in ("wire", "shaded"):
        raise ValueError(f"unknown style {style!r} (expected 'wire' or 'shaded')")
    view, screen = _project(mesh, width, height, yaw, pitch)

    buf = [list(background) * width for _ in range(height)]
    zbuf = [[-1e30] * width for _ in range(height)]

    shading = style == "shaded"
    if shading:
        ln = math.sqrt(sum(c * c for c in LIGHT)) or 1.0
        light = tuple(c / ln for c in LIGHT)
        # Material ranges are contiguous face runs, so this is just a lookup table.
        face_colour = [base] * len(mesh.faces)
        if colours:
            for m in mesh.materials:
                col = colours.get(m.name)
                if col is None:
                    continue
                for fi in range(max(0, m.face_start), min(len(mesh.faces), m.face_end)):
                    face_colour[fi] = col

    # ---- pass 1: rasterise. Depth always; colour only when shading. --------
    for fi, (ia, ib, ic) in enumerate(mesh.faces):
        a, b, c = screen[ia], screen[ib], screen[ic]
        area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(area) < 1e-9:
            continue
        if shading:
            # Shade from the stored vertex normal, rotated into view space so
            # the lighting follows the rendered orientation, not model space.
            nx, ny, nz = view(mesh.vertices[ia].nx, mesh.vertices[ia].ny, mesh.vertices[ia].nz)
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            lam = max(0.0, (nx * light[0] + ny * light[1] + nz * light[2]) / nl)
            shade = AMBIENT + (1.0 - AMBIENT) * lam
            col = [min(255, int(ch * shade)) for ch in face_colour[fi]]

        minx = max(0, int(min(a[0], b[0], c[0])))
        maxx = min(width - 1, int(max(a[0], b[0], c[0])) + 1)
        miny = max(0, int(min(a[1], b[1], c[1])))
        maxy = min(height - 1, int(max(a[1], b[1], c[1])) + 1)
        for py in range(miny, maxy + 1):
            row, zrow = buf[py], zbuf[py]
            fy = py + 0.5
            for px in range(minx, maxx + 1):
                fx = px + 0.5
                w0 = ((b[0] - a[0]) * (fy - a[1]) - (fx - a[0]) * (b[1] - a[1])) / area
                w1 = ((fx - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (fy - a[1])) / area
                w2 = 1.0 - w0 - w1
                if w0 < 0.0 or w1 < 0.0 or w2 < 0.0:
                    continue
                # Depth uses the same weights; no winding assumption is made,
                # so faces wound either way still resolve correctly.
                d = a[2] * w2 + b[2] * w1 + c[2] * w0
                if d > zrow[px]:
                    zrow[px] = d
                    if shading:
                        row[px * 3:px * 3 + 3] = col

    # ---- pass 2 (wire only): edges, depth-tested against the filled solid --
    if not shading:
        depths = [p[2] for p in screen]
        dmin, drange = min(depths), (max(depths) - min(depths)) or 1.0

        def edge(p0, p1):
            x0, y0, d0 = p0
            x1, y1, d1 = p1
            steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
            for i in range(steps + 1):
                t = i / steps
                px, py = int(x0 + (x1 - x0) * t), int(y0 + (y1 - y0) * t)
                if not (0 <= px < width and 0 <= py < height):
                    continue
                d = d0 + (d1 - d0) * t
                if d + EDGE_BIAS < zbuf[py][px]:
                    continue                      # hidden behind nearer geometry
                k = WIRE_FADE + (1.0 - WIRE_FADE) * ((d - dmin) / drange)
                buf[py][px * 3:px * 3 + 3] = [min(255, int(ch * k)) for ch in wire]

        for ia, ib, ic in mesh.faces:
            a, b, c = screen[ia], screen[ib], screen[ic]
            edge(a, b)
            edge(b, c)
            edge(c, a)

    return b"".join(bytes(row) for row in buf), width, height


def to_png(car_path: str | Path, style: str = "wire", wheels: bool = True,
           paint_texture: str | Path | None = None, **kw) -> bytes:
    """Render a car straight to PNG bytes.

    paint_texture supplies the runtime paint (a Config/paint*.tex), which is
    where most community cars actually keep their colour -- without it they
    render as the grey shells they literally are.
    """
    from . import viewer          # local import: viewer imports plenty, this module is small
    car_path = Path(car_path)
    mesh = car_mesh(car_path, wheels=wheels)
    if style == "shaded":
        kw.setdefault("colours", material_colours(car_path, mesh, paint_texture=paint_texture))
    pixels, w, h = render(mesh, style=style, **kw)
    rows = [bytearray(pixels[y * w * 3:(y + 1) * w * 3]) for y in range(h)]
    return viewer._rgb_png(w, h, rows)


# Tracks are wide, near-flat layouts, so a steeper look-down than the car's 18
# degrees reads far better -- you see the circuit shape, not an edge-on smear.
# Wireframe (like the cars), not shaded: hidden-line removal keeps a track's
# few-thousand-face scenery readable rather than a ball of string, and unlike
# the flat-grey shaded form it shows the circuit winding through the terrain --
# the track's identifying feature. Same cheap software path as the car shot
# (~0.15s), since track meshes are only 4-8k faces.
TRACK_YAW = 30.0
TRACK_PITCH = 38.0
TRACK_WIDTH = 260
TRACK_HEIGHT = 150


def track_to_png(trk_path: str | Path, style: str = "wire", **kw) -> bytes:
    """Render a track's 3D scenery mesh straight to PNG bytes -- the track
    counterpart to to_png, drawn from the very same geometry the 3D viewer shows
    (viewer._track_render_mesh) and in the same blueprint-wire style, for one
    consistent gallery look. Pass style="shaded" for a solid form instead;
    trackmap.render is the cheaper top-down-outline alternative."""
    from . import viewer
    mesh = viewer._track_render_mesh(Path(trk_path))
    kw.setdefault("yaw", TRACK_YAW)
    kw.setdefault("pitch", TRACK_PITCH)
    kw.setdefault("width", TRACK_WIDTH)
    kw.setdefault("height", TRACK_HEIGHT)
    pixels, w, h = render(mesh, style=style, **kw)
    rows = [bytearray(pixels[y * w * 3:(y + 1) * w * 3]) for y in range(h)]
    return viewer._rgb_png(w, h, rows)
