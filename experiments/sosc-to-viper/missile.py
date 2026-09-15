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

# ---------------------------------------------------------------------------
# THE PROPS. Everything the disc throws at you is a model in the same file, and
# converting one is the same job each time: fit it to the ball, drop the shadow
# faces, give each surface a flat texture. So the per-object parts live in a
# table and the pipeline below reads from it.
#
# scale is a multiple of the stock ball's own length (0.644). It is not one
# number for everything: a compact object reads at its own size, while a long
# thin one reads as a dart unless it is much bigger (see LENGTH_VS_BALL).
#
# recolour is {index in the model: index to draw instead}, always staying inside
# SoSC's own 256 rather than inventing colours -- these objects are being seen in
# a different game, under a different sky, against different ground.
PROPS = {
    "missile": dict(
        model="MISSILE", code="mis", scale=7.5,
        recolour={43: 226, 61: 63}, body_index=61),
    "mine": dict(
        model="MINE", code="min", scale=2.0,
        # No recolour. An earlier version mapped 15 -> 12 on the belief that 15
        # was the body's palette colour; 15 is the mine's CELL on the pickup
        # sheet, and its colours come from the image there.
        recolour={}, body_index=15),
}


MODEL = "MISSILE"          # rebound by main() from PROPS; see select()
LENGTH_VS_BALL = 7.5
RECOLOUR = {43: 226, 61: 63}
BODY_INDEX = 61
CODE = "mis"

BALL = "ball.mod"


def select(prop: str) -> dict:
    """Point the module's constants at one prop. The pipeline reads globals --
    they were written for a single object -- so this rebinds them rather than
    threading a parameter through every function that wants one."""
    spec = PROPS.get(prop)
    if spec is None:
        raise SystemExit(f"unknown prop {prop!r}; have {', '.join(sorted(PROPS))}")
    global MODEL, LENGTH_VS_BALL, RECOLOUR, BODY_INDEX, CODE
    MODEL = spec["model"]
    LENGTH_VS_BALL = spec["scale"]
    RECOLOUR = dict(spec["recolour"])
    BODY_INDEX = spec["body_index"]
    CODE = spec["code"]
    return spec

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


def lift_marker(im):
    """Nudge pure black off the transparency marker, before it is encoded.

    A .tex stores RGB565 and raw 0x0000 means TRANSPARENT. Some drivers honour
    that in plain opaque textures too, so a black texel renders as a hole -- and
    the missile's banded surface is 312 texels of exactly that. Confirmed in
    game: the black read through.

    The same sweep build_car.sanitise_textures does for a car's own skins. The
    missile never went through it, because it builds its textures itself.
    """
    px = list(im.getdata())
    out = [(r, 8 if (r < 8 and g < 8 and b < 8) else g, b) for r, g, b in px]
    lifted = sum(1 for a, b in zip(px, out) if a != b)
    if lifted:
        im.putdata(out)
    return lifted


# TWO KINDS OF TEXTURED FACE, and they name their image differently. Measured
# across every model in SIM3D2.MAX:
#
#   type 13   4,825 faces (car bodies, the missile's band). atlas is ALWAYS 0;
#             tex names a whole page of the atlas.
#   type 18   2,752 faces (the pickups, debris, boats). atlas is NEVER 0; it
#             names a 256x256 page, and tex names a 32x32 CELL on it, eight to
#             a row from the top left. Page 84 is the pickup sheet: the mine is
#             cell 15, repair 14, armour 16, oil 3-4, bullets 9-10.
#
# The car pipeline only ever met type 13, and this script inherited its test,
# so every type-18 face fell through to the flat path with tex read as a palette
# index. That is how the mine -- grey, with a red light on top -- came out as one
# flat blue-grey disc.
CELL_PX = 32


def textured(f) -> bool:
    return f["type"] in (13, 18)


def surface_key(f) -> tuple:
    """What makes two faces the same surface. A type-18 cell is only unique with
    its page: cell 15 on page 84 is not cell 15 on page 39."""
    if f["type"] == 18:
        return (18, f["atlas"], f["tex"])
    return (f["type"], f["tex"])


def cell_image(atl, pal, page: int, cell: int):
    """One 32x32 cell off an atlas page, as a PIL image."""
    from PIL import Image
    w, h, px = atl[page]
    per = w // CELL_PX
    if per == 0 or cell >= per * (h // CELL_PX):
        # Page 20 is a 1x256 strip and fails this. It is not a cell sheet, and
        # guessing what its index means would be worse than stopping.
        raise SystemExit(f"page {page} is {w}x{h}; it has no cell {cell} on a "
                         f"{CELL_PX}px grid -- not a sheet this script understands")
    r, c = divmod(cell, per)
    im = Image.new("RGB", (CELL_PX, CELL_PX))
    im.putdata([pal[px[(r * CELL_PX + y) * w + c * CELL_PX + x]]
                for y in range(CELL_PX) for x in range(CELL_PX)])
    return im


def per_surface(faces, pal, atl):
    """One texture per surface, and the UVs left pointing at a whole page.

    This is the format the bundle standard argues for and the one the missile
    should have shipped in. A flat colour alone on its own page makes the FILE
    the part -- mis061.tex IS the body -- so recolouring the missile is swapping
    one small image, which is the mapping a colour picker in the editor would
    drive. An atlas throws that away: every surface becomes a rectangle inside
    one image that only the UVs can explain.

    It also deletes a class of bug outright. A 2x2 atlas has a row order, and
    getting it upside down sampled red where white was meant -- which is exactly
    what happened. A single-colour page reads the same either way up.

    The cost is four files instead of one, about 4KB on 77.

    Returns ({name: PIL image}, {(type, index): name}).
    """
    from PIL import Image
    FLAT = 16                       # smallest sane square for one colour
    surfaces = []
    for f in faces:
        key = surface_key(f)
        if key not in [s[0] for s in surfaces]:
            surfaces.append((key, textured(f)))

    pages, mats, used = {}, {}, set()
    for key, is_image in surfaces:
        # Recolour is a PALETTE substitution, so it only means anything on a
        # flat face. A cell's tex is a position on a sheet, not a colour.
        idx = key[1] if is_image else RECOLOUR.get(key[1], key[1])
        # CODE, not a hardcoded "mis": two props in one race share a texture
        # namespace, and a mine whose texture is called mis012.tex both lies
        # about what it is and collides with any missile that happens to use
        # index 12 (see bundle.py's KNOWN, NOT GUARDED note).
        stem = ("{}c{:03d}".format(CODE, key[2]) if key[0] == 18
                else "{}{:03d}".format(CODE, idx))
        while stem + ".tex" in used:            # two surfaces, one palette slot
            stem = stem + "b"
        name = stem + ".tex"
        if len(name) > NAME_LIMIT:
            raise SystemExit(name + " is over " + str(NAME_LIMIT) + " characters")
        used.add(name)
        if key[0] == 18:
            pages[name] = cell_image(atl, pal, key[1], key[2])
        elif is_image:
            w, h, px = atl[key[1]]
            cell = Image.new("RGB", (w, h))
            cell.putdata([pal[b] for b in px])
            side = 1
            while side < max(w, h):
                side *= 2
            pages[name] = cell.resize((side, side), Image.LANCZOS)
        else:
            pages[name] = Image.new("RGB", (FLAT, FLAT),
                                    shade_of(pal, idx, key[0]))
        mats[key] = name

    # V IS MEASURED FROM THE OTHER END -- see the atlas note in the history.
    # A flat page does not care, but the banded one does, so every surface is
    # treated the same way rather than only the one that shows it.
    for f in faces:
        if f["type"] == 13:
            f["uv"] = [(u, 1.0 - v) for u, v in f["uv"]]
        elif f["type"] == 18:
            # NOT flipped. A cell's UVs come out of read_model already the right
            # way up for the cell once unit_uvs has shifted them into 0..1 --
            # flipping them as well put the mine's red light off the model
            # entirely: 0 red samples flipped, 84 unflipped. Type 13 and type 18
            # disagree here, and each was settled by sampling the exported mesh
            # against its exported texture, the check that has predicted the
            # game correctly both times it mattered.
            pass
        else:
            f["uv"] = [(0.5, 0.5) for _ in f["uv"]]
    return pages, mats


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
        if not textured(f) and f["tex"] in reserved:
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
    faces = [f for f in faces if textured(f) or f["tex"] not in shadows]
    for f in faces:
        if not textured(f) and f["tex"] in reserved:
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
    live = {f["tex"] for f in faces if not textured(f)}
    missing = sorted(set(RECOLOUR) - live)
    if missing:
        raise SystemExit(
            f"no faces use palette index/indices {missing} -- a recolour is aimed "
            f"at a group this model does not have; re-identify it before trusting "
            f"the colours")
    for src, dst in sorted(RECOLOUR.items()):
        print(f"  recolour: {src} RGB{pal[src]} -> {dst} RGB{pal[dst]}")

    pages, mats = per_surface(faces, pal, atl)
    print(f"  {len(pages)} surface(s), one texture each: "
          + ", ".join(f"{n} {im.width}x{im.height}" for n, im in sorted(pages.items())))

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
        m = mats[surface_key(f)]
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

    out_tex = {}
    lifted_total = 0
    for name, im in sorted(pages.items()):
        lifted_total += lift_marker(im)
        png = work / (name[:-4] + ".png")
        im.save(png)
        dest = work / name
        subprocess.run(run + ["img2tex", str(png), str(dest), "--wrap", "1"],
                       cwd=str(ROOT), capture_output=True)
        if not dest.is_file():                   # no img2tex: go via TGA
            tga = work / (name[:-4] + ".tga")
            tga.write_bytes(tga_from_image(im))
            subprocess.run(run + ["tga2tex", str(tga), str(dest), "--wrap", "1"],
                           cwd=str(ROOT), check=True, capture_output=True)
        out_tex[name] = dest.read_bytes()
    if lifted_total:
        print(f"  lifted {lifted_total} texel(s) off the transparency marker")
    return out_mod.read_bytes(), out_tex


def install_into(car: Path, ball_bytes: bytes, textures: dict) -> str:
    entries = archive.read(car)
    entries = archive.upsert_entry(entries, BALL, ball_bytes)
    for name, raw in textures.items():
        entries = archive.upsert_entry(entries, name, raw)
    archive.write(entries, car)
    return f"{BALL} + {len(textures)} texture(s)"


def main(argv):
    prop = "missile"
    for a in list(argv):
        if a.startswith("--prop="):
            prop = a.split("=", 1)[1].lower()
            argv.remove(a)
    select(prop)
    if len(argv) not in (4, 5):
        raise SystemExit(__doc__.strip().splitlines()[2])
    max_path, skin, install, cars = (Path(a) for a in argv[:4])
    scale = float(argv[4]) if len(argv) > 4 else LENGTH_VS_BALL
    print(f"  prop: {prop} ({MODEL})")
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
