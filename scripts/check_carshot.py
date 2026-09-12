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
            try:
                png = carshot.track_to_png(trks[0])
                check("track_to_png returns a PNG",
                      png[:8] == b"\x89PNG\r\n\x1a\n", f"{trks[0].name}, {len(png)} bytes")
            except Exception as e:                              # noqa: BLE001
                check("track_to_png returns a PNG", False, f"{type(e).__name__}: {e}")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
