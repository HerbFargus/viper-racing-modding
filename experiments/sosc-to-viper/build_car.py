"""Turn a Streets of SimCity vehicle into a loadable Viper Racing car.

Takes the mesh out of GEO/*.MAX, fits it to Viper's frame, builds the textures
its faces ask for, and swaps the result into a forked donor car so it inherits
a working set of wheels, physics and tables.

WHAT TRANSFERS AND WHAT DOES NOT. The model transfers: vertices, faces, UVs and
the per-face colour/texture assignment. The car does not -- handling, sounds,
gearing and the cockpit all stay the donor's, because none of that exists in a
.MAX. This produces a Viper Racing car that LOOKS like a SoSC one.

FACE TYPES decide where a material's pixels come from (see CahootsMalone's
format notes):

    13   dedicated texture   -> the vehicle skin BMP, already 256x256 8-bit
    15   flat colour         -> a solid .tex built from the colour map
    19   smooth-shaded       -> ditto; Viper has no vertex-colour path, so the
                               gradient collapses to its base colour

This writes LOD 0 only. The donor's LODs 1..7 survive untouched, which means the
car morphs into the donor at distance -- run `vrmod modlod` afterwards, as
build_fleet.py does. See README.md.

    python build_car.py <MAX> <MODEL> <SIM3D.BMP> <donor.car> <out_dir> <prefix>
"""
import math
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                  # the vrmod repo this experiment lives in
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from max2obj import models, read_model            # noqa: E402
from vrmod import archive, envelope, mod          # noqa: E402

USAGE = ("build_car.py <MAX> <MODEL> <SIM3D.BMP> <donor.car> <out_dir> "
         "<prefix> [code]")
# Generated texture names are held to what the retail data actually uses: no
# shipped archive member is longer than 12 characters (`7scraped.tex`) and no
# shipped material name longer than 11 (`effects.tex`). The first name this
# experiment ever pushed past 15 -- `azzaronit089.tex`, at 16 -- is the one car
# of seven that loaded with NO texture at all, flat paint colour, while its
# 15-character siblings were fine. 15 characters plus a terminator is a 16-byte
# buffer, and nothing in 1,770 community cars comes near it either (the longest
# car name in the corpus is 10, so its paint texture is 14). Names are kept
# inside the retail envelope rather than at the edge of the observed cliff.
NAME_LIMIT = 12
PAL_ENTRIES = 256


def palette(blob: bytes) -> list[tuple[int, int, int]]:
    """The colour map: 256 RGB triples, 33 bytes past the CMAP address."""
    # +33 past the CMAP address, per the texture tool's own reader.
    start = struct.unpack_from("<I", blob, 16)[0] + 33
    return [tuple(blob[start + i * 3:start + i * 3 + 3]) for i in range(PAL_ENTRIES)]


def fit(verts, target_len: float, ground: float = 0.0):
    """Scale uniformly to the donor's length and sit the result on the ground.

    Uniform, not per-axis: the two games' proportions already agree to within
    15% (5.7x long against 5.8x wide, 6.5x tall), so stretching each axis to
    match would distort a car that is already the right shape.
    """
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
    scale = target_len / (max(zs) - min(zs))
    cx = (max(xs) + min(xs)) / 2
    cz = (max(zs) + min(zs)) / 2
    ymin = min(ys)
    # Rotate 180 degrees about Y -- negate X and Z. The two games point their
    # cars in opposite directions along Z: rendered at the angle where every
    # stock Viper car shows headlights and a grille, an unrotated SoSC car shows
    # its rear window and number plate. In game that is a car driving backwards.
    #
    # Negating BOTH axes is a rotation, not a mirror: the determinant stays +1,
    # so it does not invert winding. Negating Z alone would, and would undo the
    # backface fix below.
    return [(-(x - cx) * scale, (y - ymin) * scale + ground, -(z - cz) * scale)
            for x, y, z in verts], scale


def wind_outward(verts, faces, double=False):
    """Make the winding consistent across the mesh, then point it outward.

    Streets of SimCity renders two-sided, so its winding is arbitrary -- 101 of
    the Airhawk's 520 faces wind the other way from their neighbours, and every
    face carries the same flags (0x2002), so nothing in the file says which.
    Viper culls backfaces, so a wrongly wound face is simply not drawn: in game
    that is a hole you can see the track through.

    Deciding each face independently against the mesh centroid gets most of them
    and fails exactly where a car is concave -- sills, wheel arches, the
    underbody. That was the first attempt, and on most of these meshes it was
    worse than doing nothing: with propagation in place FIVE of the seven cars
    need zero flips and a sixth needs one, so nearly every flip the centroid
    pass made on those bodies was opening a hole rather than closing one. Only
    the Airhawk genuinely needs reorienting, and it needs it wholesale (807
    flips across 5 shells). check_mesh.py is the measurement that settled it.

    So orientation is PROPAGATED instead. Two triangles sharing an edge agree
    only if they traverse that edge in opposite directions; a breadth-first walk
    over shared edges makes every connected shell self-consistent, and the
    volume test is then applied once per shell rather than once per face, which
    is a question about a whole closed surface and not about one triangle in a
    dent.
    """
    edge_faces = {}
    for fi, f in enumerate(faces):
        if f["n"] < 3:
            continue
        idx = f["idx"]
        for k in range(len(idx)):
            a, b = idx[k], idx[(k + 1) % len(idx)]
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(fi)

    def traverses(fi, a, b):
        """True if face fi walks edge a->b in that direction."""
        idx = faces[fi]["idx"]
        for k in range(len(idx)):
            if idx[k] == a and idx[(k + 1) % len(idx)] == b:
                return True
        return False

    def flip(fi):
        faces[fi]["idx"] = list(reversed(faces[fi]["idx"]))
        faces[fi]["uv"] = list(reversed(faces[fi]["uv"]))

    seen = set()
    flipped = 0
    shells = 0
    for seed in range(len(faces)):
        if seed in seen or faces[seed]["n"] < 3:
            continue
        shells += 1
        shell = [seed]
        seen.add(seed)
        queue = [seed]
        while queue:
            fi = queue.pop()
            idx = faces[fi]["idx"]
            for k in range(len(idx)):
                a, b = idx[k], idx[(k + 1) % len(idx)]
                for nb in edge_faces.get((min(a, b), max(a, b)), ()):
                    if nb in seen or faces[nb]["n"] < 3:
                        continue
                    # Agreeing neighbours traverse the shared edge the other way.
                    if traverses(nb, a, b):
                        flip(nb)
                        flipped += 1
                    seen.add(nb)
                    shell.append(nb)
                    queue.append(nb)

        # The shell is now self-consistent; decide its global sign by signed
        # volume, which is positive for an outward-facing closed surface.
        vol = 0.0
        for fi in shell:
            a, b, c = (verts[i] for i in faces[fi]["idx"][:3])
            vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                    - a[1] * (b[0] * c[2] - b[2] * c[0])
                    + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        if vol < 0:
            for fi in shell:
                flip(fi)
            flipped += len(shell)

    # Propagation makes a mesh consistent only where it CAN be: an edge shared
    # by three faces, or a shell that is not cleanly orientable, leaves
    # conflicts behind -- 26 faces on the Airhawk, 4 on the van, 2 on the
    # Ferrari, none on the other four.
    #
    # `double` emits those twice, once each way, so neither winding can be
    # culled. It is OFF by default because it appears to trade one artifact for
    # a worse one: two coplanar triangles fight for the depth buffer, and the
    # speckled band reported along the Airhawk's flank showed up on the ONE car
    # with a meaningful number of twins, after they were introduced. A face
    # left single can at worst vanish; a doubled pair shimmers across the whole
    # surface it covers.
    seen_edge = {}
    conflicted = set()
    for fi, f in enumerate(faces):
        if f["n"] < 3:
            continue
        idx = f["idx"]
        for k in range(len(idx)):
            a, b = idx[k], idx[(k + 1) % len(idx)]
            key = (min(a, b), max(a, b))
            d = 1 if a < b else -1
            if key in seen_edge:
                if seen_edge[key][0] == d:
                    conflicted.add(fi)
                    conflicted.add(seen_edge[key][1])
            else:
                seen_edge[key] = (d, fi)
    for fi in (sorted(conflicted) if double else ()):
        twin = dict(faces[fi])
        twin["idx"] = list(reversed(twin["idx"]))
        twin["uv"] = list(reversed(twin["uv"]))
        faces.append(twin)
    return flipped, shells, len(conflicted)


def unit_uvs(faces):
    """Shift every face's UVs back into the unit square.

    Streets of SimCity puts them wherever the repeat lands: the Airhawk's v
    runs 1.0..2.0 and the police car's 1.0..3.0, which is the same texel as
    0.0..1.0 for any sampler that wraps. Viper's does not agree -- surveyed
    across the shipped cars, NOT ONE leaves the unit square (exotic 1 vertex of
    181, sedan 2 of 142, viper 1 of 325, all by a hundredth from rounding),
    where the raw conversion puts 100% of the Airhawk's outside it. In game
    that is the see-through patch along the flank, and no renderer that wraps
    unconditionally -- including this project's own -- can show it to you.

    The shift is per FACE, not per vertex: a face spanning v 1.2..1.8 has to
    move as a unit, and moving its vertices independently would tear a seam
    across it. A face that genuinely spans more than one repeat cannot be
    fixed this way and is counted instead.
    """
    moved = spanning = 0
    for f in faces:
        if f["n"] < 3:
            continue
        us = [u for u, _ in f["uv"]]
        vs = [v for _, v in f["uv"]]
        du, span_u = _fit_axis(us)
        dv, span_v = _fit_axis(vs)
        su, sv = max(span_u, 1.0), max(span_v, 1.0)
        span = max(span_u, span_v)
        if du or dv or span > 1.0:
            f["uv"] = [((u + du) / su, (v + dv) / sv) for u, v in f["uv"]]
            moved += 1
        # A face WIDER than one repeat cannot be moved inside the square, only
        # squeezed into it. On the van and the police car 96 faces each span
        # 1.01 -- one full repeat plus fixed-point rounding -- so the squeeze is
        # 1% and invisible. A face that genuinely tiled its texture several
        # times would lose the repeat, so the worst factor is returned and
        # printed rather than quietly absorbed.
        spanning = max(spanning, span)
    return moved, spanning


def _fit_axis(vals):
    """Offset (and, if it is wider than one repeat, the span) for one UV axis."""
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span > 1.0:
        return -lo, span                   # slide to zero; the caller divides
    off = -math.floor(lo)
    if hi + off > 1.0:
        off = 1.0 - hi                     # slide it down until it just fits
    return off, span


def tga_solid(rgb, size: int = 8) -> bytes:
    """A tiny uncompressed 24-bit TGA of one colour.

    Viper materials are textures, not colours, so a flat-shaded SoSC face needs
    something to sample. Eight pixels square is the smallest that still survives
    mipmapping without drawing attention to itself.
    """
    r, g, b = rgb
    header = bytes([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0]) + \
        struct.pack("<HHBB", size, size, 24, 0)
    return header + bytes([b, g, r]) * (size * size)


def atlas(bmp: Path):
    """Walk SIM3D.BMP and return {index: (w, h, pixel bytes)}.

    Each texture carries its OWN header -- width, height, a third word, then a
    per-row offset table of `height` u32s -- before its pixels. That per-image
    header is the 68,736 bytes that a naive sum of width*height cannot account
    for, and ignoring it drifts the read further off with every entry: index 83
    landed in the middle of a building. Walking it properly ends exactly on the
    file size, which is the check that the rule is right, and the one
    check_formats.py makes.

    The dimensions come from each image's own header, not from the resolution
    table at offset 16.
    """
    b = bmp.read_bytes()
    count = struct.unpack_from("<I", b, 8)[0]
    rescount = struct.unpack_from("<I", b, 12)[0]
    cur = 16 + rescount * 3 * 4
    out = {}
    for i in range(count):
        w = struct.unpack_from("<I", b, cur)[0]
        h = struct.unpack_from("<I", b, cur + 4)[0]
        data = cur + 12 + h * 4
        out[i] = (w, h, b[data:data + w * h])
        cur = data + w * h
    if cur != len(b):
        raise SystemExit(f"atlas walk ended at {cur}, file is {len(b)}")
    return out


def tga_from_indexed(w: int, h: int, px: bytes, pal) -> bytes:
    """Indexed pixels + palette -> 24-bit TGA, bottom-up as TGA expects."""
    rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            r, g, bl = pal[px[y * w + x]]
            row += bytes((bl, g, r))
        rows.append(bytes(row))
    header = bytes([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0]) + \
        struct.pack("<HHBB", w, h, 24, 0)
    return header + b"".join(rows)


def build(max_path: Path, model: str, skin: Path, donor: Path,
          out_dir: Path, prefix: str, code: str | None = None,
          double: bool = False) -> Path:
    """Convert one vehicle. Returns the path to the finished .car.

    `code` is the short stem the generated textures are named from, and it
    matters more than it looks: see NAME_LIMIT.
    """
    code = (code or prefix[:3]).lower()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir(exist_ok=True)

    blob = max_path.read_bytes()
    table = models(blob)
    if model not in table:
        raise SystemExit(f"no model {model!r} in {max_path.name}; "
                         f"have {len(table)}: {sorted(table)[:6]} ...")
    addr, nf, nv = table[model]
    verts, faces = read_model(blob, addr, nf, nv)
    pal = palette(blob)
    atl = atlas(skin)

    # --- the donor sets the frame -----------------------------------------
    body_name = None
    for e in archive.read(donor):
        if e.name.lower().endswith("0.mod"):
            body_name = e.name
            donor_body = mod.parse(envelope.build(e.tag, e.version, e.payload))
            break
    if body_name is None:
        raise SystemExit(f"{donor.name}: no LOD-0 body to measure against")
    dz = [v.z for v in donor_body.vertices]
    target_len = max(dz) - min(dz)
    print(f"  donor {donor.name}: body {body_name}, {target_len:.2f} long")

    fitted, scale = fit(verts, target_len)
    print(f"  fitted to {target_len:.2f} long (scale {scale:.6f})")
    before = len(faces)
    flipped, shells, doubled = wind_outward(fitted, faces, double=double)
    print(f"  winding: {before} faces in {shells} shell(s), flipped {flipped}, "
          f"{doubled} still conflicted{' (doubled)' if double else ''}")
    moved, widest = unit_uvs(faces)
    print(f"  uvs: normalised {moved} face(s) into the unit square; "
          f"widest face spanned {widest:.2f} of a repeat"
          f"{' (squeezed)' if widest > 1.0 else ''}")

    # --- one material per (type, index), named for what it is --------------
    mats, tex_files = {}, {}
    for f in faces:
        key = (f["type"], f["tex"])
        if key in mats:
            continue
        if f["type"] == 13:                       # dedicated texture, by index
            name = f"{code}t{f['tex']:03d}.tex"
            w, h, px = atl[f["tex"]]
            tex_files[name] = tga_from_indexed(w, h, px, pal)
        else:                                     # colour map
            name = f"{code}c{f['tex']:03d}.tex"
            tex_files[name] = tga_solid(pal[f["tex"]])
        mats[key] = name
    over = [n for n in set(mats.values()) if len(n) > NAME_LIMIT]
    if over:
        raise SystemExit(f"texture name(s) over {NAME_LIMIT} characters: {over} "
                         f"-- pass a shorter `code` (see NAME_LIMIT)")
    print(f"  materials: {len(mats)} -> {sorted(set(mats.values()))}")

    # --- OBJ, then vrmod does the rest -------------------------------------
    obj = [f"# {model} fitted to {donor.name}"]
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
    obj_path = work / f"{prefix}.obj"
    obj_path.write_text("\n".join(obj) + "\n", encoding="utf-8")

    # --- fork the donor, then replace what we have ------------------------
    forked = out / f"{prefix}.car"
    run = [sys.executable, "-m", "vrmod.cli"]
    cwd = str(ROOT)
    subprocess.run(run + ["carfork", str(donor), prefix, "--out", str(forked)],
                   cwd=cwd, check=True, capture_output=True)
    unpacked = work / "car"
    subprocess.run(run + ["unpack", str(forked), str(unpacked)],
                   cwd=cwd, check=True, capture_output=True)

    # the forked body, at whatever name carfork gave it
    body = next(p for p in unpacked.iterdir() if p.name.lower().endswith("0.mod"))
    r = subprocess.run(run + ["obj2mod", str(obj_path), str(body)],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"obj2mod failed: {r.stderr[-400:]}")
    print(f"  body -> {body.name}")

    for name, tga in tex_files.items():
        t = work / (name[:-4] + ".tga")
        t.write_bytes(tga)
        # wrap=1 (tileable). The UVs are not confined to 0..1 -- this car's v
        # reaches 2.0 -- so a decal-clamped texture smears at the seams instead
        # of repeating.
        subprocess.run(run + ["tga2tex", str(t), str(unpacked / name), "--wrap", "1"],
                       cwd=cwd, check=True, capture_output=True)
    # pack builds the archive from _manifest.txt, not from what is on disk, so
    # a new file that is not listed there is silently left out. The first run
    # produced a car with five textures written into the staging directory and
    # one texture in the archive.
    man = unpacked / "_manifest.txt"
    lines = man.read_text(encoding="utf-8").splitlines()
    added = [n for n in tex_files if n not in lines]
    man.write_text("\n".join(lines + added) + "\n", encoding="utf-8")
    print(f"  wrote {len(tex_files)} texture(s); added {len(added)} to the manifest")

    subprocess.run(run + ["pack", str(unpacked), str(forked)],
                   cwd=cwd, check=True, capture_output=True)
    print(f"  {forked.name}  ({forked.stat().st_size:,} bytes)")
    return forked


def main() -> int:
    if len(sys.argv) not in (7, 8):
        raise SystemExit(USAGE)
    max_path, model, skin, donor, out_dir, prefix = sys.argv[1:7]
    code = sys.argv[7] if len(sys.argv) > 7 else None
    build(Path(max_path), model, Path(skin), Path(donor), Path(out_dir),
          prefix, code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
