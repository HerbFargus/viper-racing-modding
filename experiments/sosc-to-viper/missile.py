"""Replace the horn ball with Streets of SimCity's missile.

Viper Racing's HACKS tab has a Horn Ball toy: honk and the car throws a ball out
of the front. SoSC has a missile, which is a better thing to throw.

    python missile.py <SIM3D2.MAX> <SIM3D.BMP> <install> <cars_dir> [scale]

WHICH MISSILE. SIM3D2.MAX carries four weapon models and only one is the rocket:

    MISSILE           101 verts, 163 faces, 3.4 x 5.3 x 14.3  <- this one
    STREETS_MISSILE    30 verts,  30 faces, 4.5 x 6.9 x  4.5     cubic: the pickup
    BULLET              5 verts,   4 faces, 0.2 x 0.3 x 15.6     a tracer streak
    STREETS_BULLETS     9 verts,   6 faces, 4.2 x 4.2 x  4.2     also a pickup

The STREETS_ prefix is the fleet naming convention, so STREETS_MISSILE looks like
the right answer and is not: it is as wide as it is long. The projectile is the
one that is four times longer than it is wide.

PER-CAR OR GLOBAL. This writes ball.mod into each car archive, not into race.res.
The format reference claims the horn ball is the one asset NOT resolved per-car
-- that the engine hardcodes the bare name and loads it once globally -- but that
note argues from the name being hardcoded, which does not actually rule out the
usual own-archive-first lookup. Writing it per-car settles the question in one
run: if the SoSC cars throw missiles and a stock car still throws a ball, the
lookup is per-car and the reference needs correcting. If every car throws a ball,
it is global and this has to go into race.res instead.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vrmod import archive, envelope, mod                      # noqa: E402
from build_car import (atlas, models, palette, read_model,    # noqa: E402
                       reserved_indices, shade_of, tga_from_indexed,
                       tga_solid, unit_uvs, wind_outward, NAME_LIMIT)

MODEL = "MISSILE"
# Length as a multiple of the stock ball's own length (0.644). 1.5x -- a missile
# the size of the thing it replaces -- read as comically small in game: the ball
# is a ball and reads at its own size, whereas a rocket the same length reads as
# a dart. 7.5x is five times that, which is what it took to look like a weapon.
# Override from the command line to try another.
LENGTH_VS_BALL = 7.5

# Palette substitutions, {index in the model: index to draw instead}. Both stay
# inside SoSC's own 256 rather than inventing colours, and both exist because
# this object is being seen in a different game than it was drawn for.
#
#   43 -> 226   the exhaust flame. Index 43 is the 24-face group that sits
#               entirely BEYOND the fins on the tail side (z -10.99..-6.94
#               against the fins' -7.85..-4.23), so it is the plume and not a
#               nose cone, which its shape resembles. SoSC draws it
#               RGB(137,149,238), a pale blue-white that works as a
#               half-transparent flame over that game's sky. Viper has no
#               transparency here and throws it at ground level, where pale blue
#               just reads as more missile. 226 is SoSC's own bright orange.
#
#   61 -> 63    the body. 61 is RGB(213,213,213), which disappears against
#               Viper's grey asphalt and its overcast sky. 63 is RGB(255,255,255)
#               and is the TOP OF THE SAME RAMP -- 48..63 runs black to white --
#               so this is the brightest the body can be without leaving the
#               shade family the model already chose.
RECOLOUR = {43: 226, 61: 63}
BODY_INDEX = 61      # what the uncoloured tail cap is painted as
CODE = "mis"                       # -> mist061.tex, 11 chars, inside NAME_LIMIT
BALL = "ball.mod"


def stock_ball(install: Path):
    """(length, size) of the ball we are replacing, from race.res."""
    ents = {e.name.lower(): e for e in archive.read(install / "race.res")}
    m = mod.parse(ents[BALL].to_standalone_bytes())
    zs = [v.z for v in m.vertices]
    xs = [v.x for v in m.vertices]
    ys = [v.y for v in m.vertices]
    return (max(zs) - min(zs),
            (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))


def fit_to(verts, target_len: float):
    """Scale about the centroid so the LONG axis is `target_len`, centred on 0.

    Centred, not grounded: the ball is a free projectile with no contact patch,
    and the engine spins it about its own origin.
    """
    zs = [v[2] for v in verts]
    span = max(zs) - min(zs)
    scale = target_len / span
    mids = [(max(a[i] for a in verts) + min(a[i] for a in verts)) / 2
            for i in range(3)]
    out = [tuple((v[i] - mids[i]) * scale for i in range(3)) for v in verts]
    # A half turn about Y, so it leaves the car nose-first: SoSC draws the missile
    # nose-at-minus-z and Viper's cars run nose-at-plus-z (cockpit.tab puts the
    # eye at z -0.791 with the gauges ahead of it at -0.14, so +z is forward).
    #
    # This only sets which way it STARTS. The horn ball is a rolling physics
    # object and tumbles once thrown, so the launch orientation does not survive
    # the first bounce and no amount of getting it right would make it point
    # anywhere in particular. Kept because leaving it backwards would be wrong
    # for free, not because it is load-bearing.
    #
    # A rotation rather than negating z on its own: mirroring a single axis flips
    # handedness and every face would then be wound inside out.
    return [(-x, y, -z) for (x, y, z) in out], scale


def double_side(verts, faces, model_size: float):
    """Give every face a back, so the missile survives being seen from behind.

    SoSC's MISSILE is not a solid. Measured around its long axis it fills 15 of
    36 angular bins -- 42% -- and STREETS_MISSILE is worse at 28%.

    That is not sloppiness, it is the firing geometry: in SoSC you shoot the
    missile out of your own car and watch it fly away, so the only surfaces that
    ever face the camera are the ones you can see from behind. Everything else
    was never modelled because it could never be seen. The 40-140 degree arc the
    plume covers is exactly the cone a chase view spans.

    Viper throws the horn ball forward out of the car, so the viewing geometry is
    the same one SoSC built for -- which is why the orientation flip above points
    the nose away from the driver. The difference is that Viper's horn ball is a
    rolling physics object. It tumbles, the unmodelled side comes round, and you
    see straight through it: the "gap" down the middle, and the plume vanishing
    whenever its arc rotates away.

    No winding fixes that -- there is nothing on the other side to turn round.
    An earlier radial pass here assumed a tube and was reasoning about geometry
    that does not exist.

    Each new face sits a hair BEHIND its original along the face normal rather
    than exactly on it. Coincident coplanar faces z-fight, which is the artefact
    that made build_car's own `double` option not worth using.
    """
    eps = model_size * 0.002
    added = 0
    for f in list(faces):
        if f["n"] < 3:
            continue
        a, b, c = (verts[i] for i in f["idx"][:3])
        u = tuple(b[i] - a[i] for i in range(3))
        w = tuple(c[i] - a[i] for i in range(3))
        n = (u[1]*w[2] - u[2]*w[1], u[2]*w[0] - u[0]*w[2], u[0]*w[1] - u[1]*w[0])
        mag = sum(q*q for q in n) ** 0.5
        if mag == 0:
            continue
        n = tuple(q / mag for q in n)
        base = len(verts)
        for i in f["idx"]:
            verts.append(tuple(verts[i][k] - n[k] * eps for k in range(3)))
        back = dict(f)
        back["idx"] = list(reversed(range(base, base + len(f["idx"]))))
        back["uv"] = list(reversed(f["uv"]))
        faces.append(back)
        added += 1
    return added


ATLAS_NAME = "misall.tex"    # 10 chars, inside the 12 a .tex name may use
CELL = 32                   # each surface gets a CELL x CELL square


def tga_from_image(im) -> bytes:
    """Uncompressed 24-bit TGA, bottom-up, which is what tga2tex reads."""
    import struct
    W, H = im.size
    px = im.convert("RGB").load()
    body = bytearray()
    for y in range(H - 1, -1, -1):
        for x in range(W):
            r, g, b = px[x, y]
            body += bytes((b, g, r))
    return (struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, W, H, 24, 0)
            + bytes(body))


def consolidate(faces, pal, atl):
    """Fold every surface into ONE texture and rewrite the UVs to suit.

    Viper does not require this -- only 36% of stock meshes use a single
    texture, and a car body uses four. But a stock body's other three are
    UCAR/WHEELS/EFFECTS, which already ship in race.res, so they cost the author
    nothing. Everything a horn ball names is new and has to travel with it, so
    the number that matters for a shareable bundle is new FILES, not textures
    per mesh.

    This missile is the easy case: three of its four surfaces are flat colours
    sitting alone on a 32x32 page to say one thing. Only the checker band holds
    real image data. So they pack into one grid, and the remap divides into two
    kinds:

      flat colour   every vertex points at the middle of its own cell. A single
                    point cannot be filtered across a cell boundary, so no
                    inset, no gutter, no bleed.
      real image    the existing 0..1 UVs scale into its cell, inset half a
                    texel so filtering cannot reach the neighbouring cell.

    Returns (image, {(type, index): None}) -- the mesh ends up with one material.
    """
    from PIL import Image
    surfaces = []
    for f in faces:
        key = (f["type"], f["tex"])
        if key not in [s[0] for s in surfaces]:
            surfaces.append((key, f["type"] == 13))
    cols = 2 if len(surfaces) <= 4 else 3
    rows = (len(surfaces) + cols - 1) // cols
    page = Image.new("RGB", (cols * CELL, rows * CELL), (0, 0, 0))
    where = {}
    for i, (key, is_image) in enumerate(surfaces):
        ox, oy = (i % cols) * CELL, (i // cols) * CELL
        if is_image:
            w, h, px = atl[key[1]]
            cell = Image.new("RGB", (w, h))
            cell.putdata([pal[b] for b in px])
            page.paste(cell.resize((CELL, CELL), Image.LANCZOS), (ox, oy))
        else:
            idx = RECOLOUR.get(key[1], key[1])
            page.paste(Image.new("RGB", (CELL, CELL), shade_of(pal, idx, key[0])),
                       (ox, oy))
        where[key] = (ox, oy, is_image)
    W, H = page.size
    half = 0.5
    for f in faces:
        ox, oy, is_image = where[(f["type"], f["tex"])]
        if is_image:
            f["uv"] = [(((ox + half) + u * (CELL - 1)) / W,
                        ((oy + half) + v * (CELL - 1)) / H) for u, v in f["uv"]]
        else:
            c = ((ox + CELL / 2) / W, (oy + CELL / 2) / H)
            f["uv"] = [c for _ in f["uv"]]
    return page, where


def build(max_path: Path, skin: Path, install: Path, length: float):
    blob = max_path.read_bytes()
    table = models(blob)
    if MODEL not in table:
        raise SystemExit(f"no {MODEL} in {max_path.name}")
    verts, faces = read_model(blob, *table[MODEL])
    pal, atl = palette(blob), atlas(skin)

    # Faces pointing at reserved palette slots carry no colour of their own, and
    # they are NOT all the same thing. Two groups qualify and only one is a
    # shadow:
    #
    #   idx 6   9 faces at y -3.36 exactly -- constant, so a flat horizontal
    #           plane slung under the missile, wider (radius 3.39) than the fins.
    #           The ground shadow. Drop it; keeping it opens 27 edges.
    #   idx 1   6 faces spanning y -1.01..+1.94 at the tail. Keeping these takes
    #           the model from 12 open edges to ZERO -- it is the cap that seals
    #           the body. Dropping it with the shadow left a hole you could see
    #           straight through from underneath.
    #
    # So the test is flatness, not colour: a shadow is planar in y, a cap is not.
    # The cap has no colour stored, so it takes the body's.
    reserved = reserved_indices(pal)
    groups = {}
    for f in faces:
        if f["type"] != 13 and f["tex"] in reserved:
            groups.setdefault(f["tex"], []).append(f)
    # Flat RELATIVE to the model, not to an absolute figure. The shadow is 79
    # fixed-point units thick against the missile's own 347,340 -- 0.02% -- but
    # it is not literally zero, and a "< 1" test in raw units matched neither
    # group and silently kept the lot.
    span = (max(v[1] for v in verts) - min(v[1] for v in verts)) or 1
    shadows = set()
    for idx, fs in groups.items():
        ys = [verts[i][1] for f in fs for i in f["idx"]]
        if (max(ys) - min(ys)) / span < 0.02:
            shadows.add(idx)
    before = len(faces)
    faces = [f for f in faces if f["type"] == 13 or f["tex"] not in shadows]
    for f in faces:
        if f["type"] != 13 and f["tex"] in reserved:
            f["tex"] = BODY_INDEX           # the cap, painted as bodywork
    if before != len(faces):
        print(f"  dropped {before - len(faces)} flat shadow face(s); "
              f"kept {sum(len(v) for k, v in groups.items() if k not in shadows)} "
              f"structural face(s) and painted them as bodywork")

    fitted, scale = fit_to(verts, length)
    print(f"  {MODEL}: {len(verts)} verts, {len(faces)} faces "
          f"-> {length:.2f} long (scale {scale:.6f})")
    flipped, shells, doubled = wind_outward(fitted, faces)
    print(f"  winding: {shells} shell(s), flipped {flipped}, {doubled} conflicted")
    backs = double_side(fitted, faces, length)
    print(f"  double-sided: added {backs} back face(s) so it reads from any angle")
    moved, widest = unit_uvs(faces)
    print(f"  uvs: normalised {moved} face(s), widest span {widest:.2f}")
    live = {f["tex"] for f in faces if f["type"] != 13}
    missing = sorted(set(RECOLOUR) - live)
    if missing:
        raise SystemExit(
            f"no faces use palette index/indices {missing} -- a recolour is aimed "
            f"at a group this model does not have; re-identify it before trusting "
            f"the colours")
    for src, dst in sorted(RECOLOUR.items()):
        print(f"  recolour: {src} RGB{pal[src]} -> {dst} RGB{pal[dst]}")

    page, where = consolidate(faces, pal, atl)
    if len(ATLAS_NAME) > NAME_LIMIT:
        raise SystemExit(f"{ATLAS_NAME} is over {NAME_LIMIT} characters")
    mats = {k: ATLAS_NAME for k in where}
    print(f"  consolidated {len(where)} surface(s) into one "
          f"{page.width}x{page.height} texture, {ATLAS_NAME}")

    obj = [f"# {MODEL} as the horn ball"]
    for x, y, z in fitted:
        obj.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    uv_i, current = {}, None
    for f in faces:
        for uv in f["uv"]:
            if uv not in uv_i:
                uv_i[uv] = len(uv_i) + 1
                obj.append(f"vt {uv[0]:.6f} {uv[1]:.6f}")
    for f in faces:
        if f["n"] < 3:
            continue
        m = mats[(f["type"], f["tex"])]
        if m != current:
            obj.append(f"usemtl {m}")
            current = m
        obj.append("f " + " ".join(f"{i + 1}/{uv_i[uv]}"
                                   for i, uv in zip(f["idx"], f["uv"])))

    work = Path(tempfile.mkdtemp(prefix="missile_"))
    obj_path = work / "missile.obj"
    obj_path.write_text("\n".join(obj) + "\n", encoding="utf-8")
    run = [sys.executable, "-m", "vrmod.cli"]
    out_mod = work / BALL
    r = subprocess.run(run + ["obj2mod", str(obj_path), str(out_mod)],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"obj2mod failed: {r.stderr[-400:]}")

    png = work / "atlas.png"
    page.save(png)
    dest = work / ATLAS_NAME
    subprocess.run(run + ["img2tex", str(png), str(dest), "--wrap", "1"],
                   cwd=str(ROOT), capture_output=True)
    if not dest.is_file():                       # no img2tex: go via TGA
        tga = work / "atlas.tga"
        tga.write_bytes(tga_from_image(page))
        subprocess.run(run + ["tga2tex", str(tga), str(dest), "--wrap", "1"],
                       cwd=str(ROOT), check=True, capture_output=True)
    return out_mod.read_bytes(), {ATLAS_NAME: dest.read_bytes()}


def install_into(car: Path, ball_bytes: bytes, textures: dict) -> str:
    entries = archive.read(car)
    entries = archive.upsert_entry(entries, BALL, ball_bytes)
    for name, raw in textures.items():
        entries = archive.upsert_entry(entries, name, raw)
    archive.write(entries, car)
    return f"{BALL} + {len(textures)} texture(s)"


def main(argv):
    if len(argv) not in (4, 5):
        raise SystemExit(__doc__.strip().splitlines()[2])
    max_path, skin, install, cars = (Path(a) for a in argv[:4])
    scale = float(argv[4]) if len(argv) > 4 else LENGTH_VS_BALL
    length, size = stock_ball(install)
    print(f"  stock {BALL}: {size[0]:.3f} x {size[1]:.3f} x {size[2]:.3f}")
    target = length * scale
    print(f"  scale {scale}x the ball -> {target:.2f} long")
    ball_bytes, textures = build(max_path, skin, install, target)
    for car in sorted(cars.glob("*.car")):
        print(f"  {car.stem:10s} {install_into(car, ball_bytes, textures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
