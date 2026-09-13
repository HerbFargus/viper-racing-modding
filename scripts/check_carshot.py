"""Checks for the thumbnail renderer.

Runs against a synthetic mesh, so it needs no game files and no network. Point it
at a real .car or Data folder as an optional argument to additionally render one.

    python scripts/check_carshot.py [path/to/car.car | path/to/Data]

WHY THIS EXISTS. `render()` shipped raising `UnboundLocalError` on its very first
pixel in the **default** `wire` style: the texture lookup was nested inside the
`if shading:` branch, which `wire` never enters. Every car and track thumbnail in
the mod manager 404'd, because the route turns any exception into "no body mesh".
Nothing here exercised carshot at all, so nothing caught it.

The lesson these checks encode: render EVERY style, and assert something about
the pixels rather than that a call returned bytes.
"""
from __future__ import annotations

import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import carshot, mod  # noqa: E402

PASS = FAIL = 0
STYLES = ("wire", "shaded", "textured")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def cube() -> mod.Mesh:
    """A unit cube with normals and UVs -- enough to exercise every path."""
    pts = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
           (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    verts = []
    for i, (x, y, z) in enumerate(pts):
        n = (x / 1.732, y / 1.732, z / 1.732)
        verts.append(mod.Vertex(x=float(x), y=float(y), z=float(z),
                                nx=n[0], ny=n[1], nz=n[2],
                                u=(i % 2) * 1.0, v=(i // 4) * 1.0))
    faces = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 4, 5), (0, 5, 1),
             (3, 2, 6), (3, 6, 7), (0, 3, 7), (0, 7, 4), (1, 5, 6), (1, 6, 2)]
    m = mod.Material(name="body.tex", vertex_start=0, vertex_end=len(verts),
                     face_start=0, face_end=len(faces))
    return mod.Mesh(vertices=verts, materials=[m], faces=faces)


def cube_on_a_plain(span: float = 400.0) -> mod.Mesh:
    """The cube again, this time with a vast flat quad under it.

    The shape a track actually has: a small subject standing on a ground plane
    sized to hide the horizon rather than to frame the subject. Fitting to the
    whole bounding box renders the cube at a fraction of its size, which is
    what track thumbnails did until render() learned to take a fit box.
    """
    m = cube()
    verts = list(m.vertices)
    base = len(verts)
    for x, z in ((-span, -span), (span, -span), (span, span), (-span, span)):
        verts.append(mod.Vertex(x=x, y=-1.0, z=z, nx=0.0, ny=1.0, nz=0.0,
                                u=0.0, v=0.0))
    faces = list(m.faces) + [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    mats = list(m.materials) + [
        mod.Material(name="ground.tex", vertex_start=base, vertex_end=len(verts),
                     face_start=len(m.faces), face_end=len(faces))]
    return mod.Mesh(vertices=verts, materials=mats, faces=faces)


def texture_stub(size: int = 4):
    """What render() expects in `textures`: (pixels, size, channels, has_key)."""
    px = bytearray()
    for i in range(size * size):
        px += bytes((255, (i * 37) % 256, 0, 255))
    return (bytes(px), size, 4, True)


def non_background(pixels: bytes, w: int, h: int, bg) -> int:
    n = 0
    for i in range(0, len(pixels), 3):
        if tuple(pixels[i:i + 3]) != tuple(bg):
            n += 1
    return n


def main() -> int:
    mesh = cube()
    print("thumbnail renderer -- every style")

    rendered = {}
    for style in STYLES:
        kw = {}
        if style == "textured":
            kw["textures"] = {"body.tex": texture_stub()}
            kw["colours"] = {"body.tex": (200, 40, 40)}
        elif style == "shaded":
            kw["colours"] = {"body.tex": (200, 40, 40)}
        try:
            pixels, w, h = carshot.render(mesh, style=style, **kw)
            rendered[style] = (pixels, w, h)
            check(f"{style} renders without raising", True, f"{w}x{h}")
        except Exception as e:                                  # noqa: BLE001
            check(f"{style} renders without raising", False, f"{type(e).__name__}: {e}")

    # A render that returns the right number of untouched background bytes is
    # still a broken render, so check that something was actually drawn.
    for style, (pixels, w, h) in rendered.items():
        check(f"{style} has the right buffer size", len(pixels) == w * h * 3,
              f"{len(pixels)} bytes")
        drawn = non_background(pixels, w, h, carshot.BACKGROUND)
        check(f"{style} actually draws pixels", drawn > 50, f"{drawn} non-background")

    # The wire style is the default and the one that regressed -- state it plainly.
    check("the default style is wire",
          carshot.render.__defaults__[0] == "wire" if carshot.render.__defaults__
          else False, "so it is the path thumbnails take")

    if "wire" in rendered and "shaded" in rendered:
        check("wire and shaded differ",
              rendered["wire"][0] != rendered["shaded"][0], "not the same image")

    try:
        carshot.render(mesh, style="nonsense")
        check("an unknown style is rejected", False, "no error raised")
    except ValueError as e:
        check("an unknown style is rejected", True, str(e)[:48])
    except Exception as e:                                      # noqa: BLE001
        check("an unknown style is rejected", False, f"{type(e).__name__}")

    # --- shared_dir: resolving textures from a Data folder elsewhere ---------
    # A lone .car -- a gallery build, an extracted pack -- has no Data folder
    # beside it, so every shared material resolves to nothing and the car
    # renders without them. shared_dir points the resolver at a real install
    # without copying 1.8 MB of .res next to every asset.
    from vrmod import car as car_mod
    import inspect
    for fn in (car_mod.resolve_textures, carshot.to_png,
               carshot.material_colours, carshot.material_textures):
        check(f"{fn.__name__} accepts shared_dir",
              "shared_dir" in inspect.signature(fn).parameters)

    # The stock Viper's own textures behave as shared ones -- confirmed in game.
    for n in ("VIPERW.tex", "VIPERD1.tex", "viperd.tex"):
        check(f"  {n} counts as a stock-car texture",
              n.lower() in car_mod.STOCK_CAR_TEX)
    check("  and viper.car is searched, since they are in no .res",
          "viper.car" in car_mod.DEFAULT_SHARED_ARCHIVES)
    check("  the stock paint name is treated as the paint slot, not as missing",
          "viper.tex" in car_mod.STOCK_PAINT_TEX)

    data = Path.home() / "Desktop" / "claude-code" / "game-files" / "installs" / "v1.0-RC"
    stock_car = data / "viper.car"
    if stock_car.is_file():
        with tempfile.TemporaryDirectory() as t:
            lone = Path(t) / "viper.car"
            lone.write_bytes(stock_car.read_bytes())
            names = {"effects.tex", "ucar.tex"}
            bare = car_mod.resolve_textures(lone, names)
            with_dir = car_mod.resolve_textures(lone, names, shared_dir=data)
            check("a lone car resolves no shared texture on its own",
                  not any(bare.values()), f"{sum(1 for v in bare.values() if v)} resolved")
            check("  ...and does once pointed at a Data folder",
                  any(with_dir.values()),
                  f"{sum(1 for v in with_dir.values() if v)}/{len(names)} resolved")
            a = carshot.to_png(lone, style="shaded")
            b = carshot.to_png(lone, style="shaded", shared_dir=data)
            check("  ...and the shaded render actually changes because of it", a != b)
            # wire ignores textures entirely, which is why a wireframe thumbnail
            # is unaffected by any of this.
            w1 = carshot.to_png(lone, style="wire")
            w2 = carshot.to_png(lone, style="wire", shared_dir=data)
            check("a WIRE render is unaffected -- it uses no textures", w1 == w2)
    else:
        print("  (no pristine install -- skipping the shared_dir render checks)")

    # --- junk UVs must not sink the render -----------------------------------
    # daytonarc's track.grf carries 20 vertices (of 93,930) whose v is NaN.
    # Wire and shaded never read UVs, so only the textured style ever met it:
    # "cannot convert float NaN to integer", and two tracks dropped out of the
    # catalogue the first time it was built textured.
    junk = cube()
    junk.vertices[0] = junk.vertices[0].__class__(
        **{**junk.vertices[0].__dict__, "v": float("nan")})
    junk.vertices[1] = junk.vertices[1].__class__(
        **{**junk.vertices[1].__dict__, "u": float("inf")})
    try:
        px, w, h = carshot.render(junk, style="textured",
                                  textures={"body.tex": texture_stub()},
                                  colours={"body.tex": (200, 40, 40)})
        check("a NaN or inf UV does not sink the render", True,
              f"{non_background(px, w, h, carshot.BACKGROUND)} px still drawn")
    except Exception as e:                                      # noqa: BLE001
        check("a NaN or inf UV does not sink the render", False,
              f"{type(e).__name__}: {e}")

    # --- the fit box: framing on the subject, not on the backdrop ------------
    # Encodes the bug this was written for. A first version of track_fit made
    # the box `pad` units TALL as well as wide; the view looks down at an
    # angle, so that height went straight into the vertical extent being
    # fitted and every track came out SMALLER than with no crop at all. So it
    # is not enough to check that fit changes the image -- check which way.
    plain = cube_on_a_plain()
    subject = [(x, y, z) for x in (-2.0, 2.0) for z in (-2.0, 2.0)
               for y in (-1.0, 1.0)]
    cols = {"body.tex": (200, 40, 40), "ground.tex": (40, 90, 40)}
    try:
        wide, w, h = carshot.render(plain, style="shaded", colours=cols)
        near, _, _ = carshot.render(plain, style="shaded", fit=subject, colours=cols)
    except Exception as e:                                      # noqa: BLE001
        check("fit box renders", False, f"{type(e).__name__}: {e}")
    else:
        check("fit box renders", True, f"{w}x{h}")
        check("fit changes the framing", wide != near, "not the same image")
        def reds(px):
            return sum(1 for i in range(0, len(px), 3)
                       if px[i] > 60 and px[i] > px[i + 1] * 2)
        red_wide, red_near = reds(wide), reds(near)
        check("fit makes the subject BIGGER, not smaller", red_near > red_wide * 4,
              f"{red_wide} px unfitted -> {red_near} px fitted")
        check("the backdrop still fills the frame behind it",
              non_background(near, w, h, carshot.BACKGROUND) > w * h * 0.8,
              "cropping in should not leave holes")

    # --- optional: a real car, end to end through to_png ---------------------
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        cars = sorted(target.glob("*.car")) if target.is_dir() else [target]
        if cars:
            print(f"\nagainst {cars[0].name}")
            for style in STYLES:
                try:
                    png = carshot.to_png(cars[0], style=style)
                    ok = png[:8] == b"\x89PNG\r\n\x1a\n"
                    check(f"to_png({style}) returns a PNG", ok, f"{len(png)} bytes")
                except Exception as e:                          # noqa: BLE001
                    check(f"to_png({style}) returns a PNG", False,
                          f"{type(e).__name__}: {e}")
        trks = sorted(target.glob("*.trk")) if target.is_dir() else []
        if trks:
            trk = trks[0]
            pngs = {}
            for style in STYLES:
                try:
                    png = carshot.track_to_png(trk, style=style)
                    pngs[style] = png
                    check(f"track_to_png({style}) returns a PNG",
                          png[:8] == PNG_MAGIC, f"{trk.name}, {len(png)} bytes")
                except Exception as e:                          # noqa: BLE001
                    check(f"track_to_png({style}) returns a PNG", False,
                          f"{type(e).__name__}: {e}")
            if "wire" in pngs and "textured" in pngs:
                check("a textured track is not the wireframe",
                      pngs["wire"] != pngs["textured"])
            from vrmod import viewer                            # noqa: PLC0415
            tmesh = viewer._track_render_mesh(trk)
            texs = carshot.track_material_textures(trk, tmesh)
            names = {(m.name or "") for m in tmesh.materials if m.name}
            check("track textures resolve from the track's own archive",
                  len(texs) > 0, f"{len(texs)}/{len(names)} materials")
            box = carshot.track_fit(trk, tmesh)
            if box is None:
                check("track_fit found the racing line", False, "no default.ili?")
            else:
                check("track_fit found the racing line", True, f"{len(box)} corners")
                mx = [v.x for v in tmesh.vertices]
                mz = [v.z for v in tmesh.vertices]
                fx = [c[0] for c in box]
                fz = [c[2] for c in box]
                # The claim track_fit's docstring makes: it only ever crops IN.
                # A box wider than the mesh just adds back the empty margin it
                # exists to remove.
                check("the fit box only ever crops in",
                      min(fx) >= min(mx) - 1e-6 and max(fx) <= max(mx) + 1e-6
                      and min(fz) >= min(mz) - 1e-6 and max(fz) <= max(mz) + 1e-6,
                      f"x {max(fx) - min(fx):,.0f} of {max(mx) - min(mx):,.0f}")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
