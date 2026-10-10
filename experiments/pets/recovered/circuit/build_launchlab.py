"""Launch Lab: a flat stadium with seven hidden launch pads, for finding out how
the game treats ground that is suddenly ABOVE the car.

A pad is ten metres of road, full width, whose COLLISION is raised by `h` while
what is drawn stays at road level:

  * the asphalt's faces over the pad are cut out on station lines (as the
    bridge's verges were), so nothing else claims those points;
  * a collision quad spans exactly the same plan -- the asphalt's own vertices at
    the two station lines, lifted by h -- and is drawn with a fully keyed
    texture, so it is solid and invisible;
  * a painted hazard square at road level marks the pad, with its height on it.

One surface per point throughout, so .bpp builds it strictly. The hypothesis
under test, from the bridge (9 m up: a launch) and Ridge Valley's deck (50 m
up: a wall): a small step is resolved by pushing the car onto it, a big one is
a wall.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "targets"))
import build_offroad as bo  # noqa: E402  (also widens bc.HALF to 10 m)
import build_scenic as bs  # noqa: E402
import build_circuit as bc  # noqa: E402
import build_river  # noqa: E402,F401  (adds Line.nearest_s)
from vrmod import archive, camtab, envelope, ili, mod, sky, tex, trackbuild, trackgen  # noqa: E402
from vrmod.trackgen import GRASS  # noqa: E402

OUT = HERE / "launchlab.trk"
SLOT = "bemidji"
STRAIGHT, RADIUS = 1100.0, 120.0
PAD_HEIGHT = 20.0                                       # set 3: every pad this tall...
PADS = [2.5, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0]       # ...and this LONG (metres along the road)
PAD_LEAD, PAD_GAP = 70.0, 100.0                        # first pad after the curve; gap between pads   # set 2: past the 8 m top of set 1 (build_launchlab_v3_lanes_low.py), toward Ridge Valley's ~50 m wall           # metres the collision is raised
PAD_FIRST, PAD_EVERY = 100.0, 150.0                    # along the far straight
MARGIN, LATTICE = 260.0, 20.0
AI_OFFSET, AI_RAMP = 5.0, 50.0                          # the AI's lane: 5 m inside, eased over 50 m


def stadium():
    """Anticlockwise: near straight +x, far straight -x, 10 m stations, flat."""
    pts = []
    n = int(STRAIGHT / 10)
    for i in range(n):
        pts.append((i * 10.0, 0.0, 0.0))
    arc = int(math.pi * RADIUS / 10)
    for i in range(arc):
        a = -math.pi / 2 + math.pi * i / arc
        pts.append((STRAIGHT + RADIUS * math.cos(a), RADIUS + RADIUS * math.sin(a), 0.0))
    for i in range(n):
        pts.append((STRAIGHT - i * 10.0, 2 * RADIUS, 0.0))
    for i in range(arc):
        a = math.pi / 2 + math.pi * i / arc
        pts.append((RADIUS * math.cos(a), RADIUS + RADIUS * math.sin(a), 0.0))
    # Slide the whole loop half a station along x. At race start the game looks up
    # the racing-line segment containing the world ORIGIN (RaceDeity::register_car ->
    # CenterLine::reset -> get_nearest_pair, with the car's point still (0, 0)). The
    # test is strict on both ends of a segment, so with nodes every 10 m on axis-
    # aligned straights and one at x = 0, the origin sits exactly on a boundary of
    # every straight's band, no segment claims it, the pointer stays null and the
    # next CenterLine::update faults reading it.
    return [(x - 5.0, y, z) for x, y, z in pts]


def pad_texture(h):
    """Yellow and grey hazard stripes, and the height in big type."""
    size = 128
    img = Image.new("RGB", (size, size), (232, 196, 40))
    d = ImageDraw.Draw(img)
    for k in range(-size, size * 2, 32):
        d.polygon([(k, 0), (k + 16, 0), (k + 16 - size, size), (k - size, size)], fill=(70, 70, 76))
    d.rectangle([22, 36, size - 22, size - 36], fill=(245, 245, 240))
    try:
        font = ImageFont.truetype("segoeuib.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    label = (f"{h:g} m").replace("0.", ".")
    d.text((size / 2, size / 2), label, fill=(190, 30, 30), font=font, anchor="mm")
    return img.transpose(Image.FLIP_LEFT_RIGHT)       # the game draws left-handed


def stripes_texture():
    """Hazard stripes alone, tiled every 5 m along a pad."""
    size = 128
    img = Image.new("RGB", (size, size), (232, 196, 40))
    d = ImageDraw.Draw(img)
    for k in range(-size, size * 2, 32):
        d.polygon([(k, 0), (k + 16, 0), (k + 16 - size, size), (k - size, size)], fill=(70, 70, 76))
    return img


def clear_texture():
    """Every texel pure black: keyed out entirely, so the mesh is invisible."""
    return Image.new("RGB", (32, 32), (0, 0, 0))


def cut_asphalt(scene, line, t0, t1):
    """Drop the asphalt faces between two station lines; return the pad's corners.

    The corners are the asphalt's own vertices on those lines, so the raised pad
    and the remaining road share their boundary exactly.
    """
    corners = {}
    for name in [n for n in scene.meshes if n.startswith("asphalt")]:
        m = scene.meshes[name]
        for v in m.vertices:
            st = line.nearest_s(-v.x, -v.z)
            for t in (t0, t1):
                if abs(st - t) < 0.5:
                    corners[(t, round(v.u))] = v
        faces = []
        for f in m.faces:
            st = line.nearest_s(-sum(m.vertices[i].x for i in f) / 3, -sum(m.vertices[i].z for i in f) / 3)
            if not t0 < st < t1:
                faces.append(f)
        if len(faces) != len(m.faces):
            used = sorted({i for f in faces for i in f})
            remap = {o: k for k, o in enumerate(used)}
            m.vertices = [m.vertices[i] for i in used]
            m.faces = [tuple(remap[i] for i in f) for f in faces]
            m.materials[0].vertex_end = len(m.vertices)
            m.materials[0].face_end = len(m.faces)
    need = [(t0, 0), (t1, 0), (t1, 1), (t0, 1)]
    missing = [k for k in need if k not in corners]
    if missing:
        raise SystemExit(f"no asphalt vertex at {missing}")
    return [corners[k] for k in need], m.materials[0].name


PAD_SHARE = 0.25          # the pad takes the outer quarter of the road: 5 m of 20


def part(a, b, f=PAD_SHARE):
    """The road-surface point a fraction f of the way from edge vertex a to b."""
    return mod.Vertex(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, a.z + (b.z - a.z) * f,
                      0.0, 1.0, 0.0, a.u + (b.u - a.u) * f, a.v + (b.v - a.v) * f)


def quad_mesh(name, corners, lift, texname, uvs, solid, scene):
    verts = [mod.Vertex(c.x, c.y + lift, c.z, 0.0, 1.0, 0.0, u, v) for c, (u, v) in zip(corners, uvs)]
    faces = [(0, 1, 2), (0, 2, 3)]
    a, b, c = verts[0], verts[1], verts[2]
    if (b.z - a.z) * (c.x - a.x) - (b.x - a.x) * (c.z - a.z) < 0:
        faces = [(0, 2, 1), (0, 3, 2)]
    scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
        mod.Material(name=texname, vertex_start=0, vertex_end=4, face_start=0, face_end=2)])
    if solid:
        scene.driveables.append(trackgen.SceneObject(name, trackgen.ROAD))  # pads and the road beside them
    else:
        scene.scenery.append(trackgen.SceneObject(name, GRASS, trackgen.NO_COLLISION))


def flat_terrain(scene, line):
    """Drivable flat grass to land on, meeting the verge watertight (build_offroad's seam)."""
    loops = bo.verge_loops(scene)
    seam = []
    runs = []
    for side in ("l", "r"):
        ring = bo.densify(loops[side], bo.SEAM_STEP)
        runs.append((len(seam), len(ring)))
        seam += ring
    level = float(np.median([p[2] for p in seam]))
    xs = [p[0] for p in line.p]; ys = [p[1] for p in line.p]
    x0, x1, y0, y1 = min(xs) - MARGIN, max(xs) + MARGIN, min(ys) - MARGIN, max(ys) + MARGIN
    seam_xy = np.array([[p[0], p[1]] for p in seam])
    land = []
    jit = random.Random(11)                 # a perfect grid is cocircular/collinear: Delaunay's worst case
    y = y0
    while y <= y1 + 1e-6:
        x = x0
        while x <= x1 + 1e-6:
            jx, jy = x + jit.uniform(-2.0, 2.0), y + jit.uniform(-2.0, 2.0)
            if (line.nearest(jx, jy)[0] > bc.GRASS_EDGE + bo.CLEAR
                    and np.min((seam_xy[:, 0] - jx) ** 2 + (seam_xy[:, 1] - jy) ** 2) > bo.CLEAR ** 2):
                land.append((jx, jy, level))
            x += LATTICE
        y += LATTICE
    pts = seam + land
    P = [p[:2] for p in pts]
    tris = bo.delaunay(P)
    edges = {tuple(sorted(e)) for a, b, c in tris for e in ((a, b), (b, c), (c, a))}
    missing = sum(1 for start, m in runs for i in range(m)
                  if tuple(sorted((start + i, start + (i + 1) % m))) not in edges)
    cx = np.array([(P[a][0] + P[b][0] + P[c][0]) / 3 for a, b, c in tris])
    cy = np.array([(P[a][1] + P[b][1] + P[c][1]) / 3 for a, b, c in tris])
    inside = bo.point_in_poly(cx, cy, [p[:2] for p in loops["l"]]) ^ bo.point_in_poly(cx, cy, [p[:2] for p in loops["r"]])
    kept = [t for t, bad in zip(tris, inside) if not bad]
    groups = {}
    for a, b, c in kept:
        mx = (P[a][0] + P[b][0] + P[c][0]) / 3; my = (P[a][1] + P[b][1] + P[c][1]) / 3
        groups.setdefault((int((mx - x0) // 240), int((my - y0) // 240)), []).append((a, b, c))
    n = 0
    for key, tl in sorted(groups.items()):
        idx, verts, faces = {}, [], []
        for tri in tl:
            f = []
            for i in tri:
                if i not in idx:
                    idx[i] = len(verts)
                    g = bc.game((P[i][0], P[i][1], pts[i][2]))
                    verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, P[i][0] / 12, P[i][1] / 12))
                f.append(idx[i])
            a_, b_, c_ = (verts[k] for k in f)
            ny_ = (b_.z - a_.z) * (c_.x - a_.x) - (b_.x - a_.x) * (c_.z - a_.z)
            faces.append(tuple(f) if ny_ > 0 else (f[0], f[2], f[1]))
        name = f"g{n:03d}.mod"
        scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
            mod.Material(name="grass.tex", vertex_start=0, vertex_end=len(verts), face_start=0, face_end=len(faces))])
        scene.driveables.append(trackgen.SceneObject(name, GRASS))
        n += 1
    return n, len(kept), missing


def main():
    pts = stadium()
    line = bc.Line(pts)
    scene = trackgen.sweep(pts, bands=bs.BANDS, road_half_width=bc.HALF, closed=True, segment_length=150.0)
    trackgen.add_checkpoints(scene, 4, half_width=bc.HALF)
    trackgen.add_grid(scene, 8)

    far_start = STRAIGHT + math.pi * RADIUS                  # the far straight begins here
    rows = []
    at = far_start + PAD_LEAD
    for k, length in enumerate(PADS):
        i = min(range(line.n), key=lambda j: abs(line.cum[j] - at))
        n_st = math.ceil(length / 10.0 - 1e-9)
        t0, t1 = line.cum[i], line.cum[i + n_st]
        (r0, r1, l1, l0), road_tex = cut_asphalt(scene, line, t0, t1)
        # AI cars wander, dodge and get shunted: an AI car that touched a 10 m+ pad
        # crashed the game twice. Outer quarter only, 10 m clear of the AI's line.
        m0, m1 = part(r0, l0), part(r1, l1)
        # The pad runs `length` metres from t0; the rest of the cut section's outer
        # quarter goes back as road. u = 0 is the right-hand edge: the OUTSIDE.
        f = length / (t1 - t0)
        rL, mL = part(r0, r1, f), part(m0, m1, f)
        pad = [r0, rL, mL, m0]
        inside = [m0, m1, l1, l0]
        quad_mesh(f"pad{k}.mod", pad, PAD_HEIGHT, "clear.tex",
                  [(0, 1), (1, 1), (1, 0), (0, 0)], True, scene)             # solid, invisible
        quad_mesh(f"padmk{k}.mod", pad, 0.02, "padstr.tex",
                  [(0, 1), (length / 5.0, 1), (length / 5.0, 0), (0, 0)], False, scene)  # stripes, 5 m tiles
        quad_mesh(f"padrd{k}.mod", inside, 0.0, road_tex, [(c.u, c.v) for c in inside], True, scene)
        if f < 1.0 - 1e-9:
            rest = [rL, r1, m1, mL]
            quad_mesh(f"padrs{k}.mod", rest, 0.0, road_tex, [(c.u, c.v) for c in rest], True, scene)
        # the length, painted on the road in the pad's lane just before it
        back = -5.0 / (t1 - t0)
        label = [part(r0, r1, back), r0, m0, part(m0, m1, back)]
        quad_mesh(f"padlb{k}.mod", label, 0.02, f"pad{k}.tex",
                  [(0, 1), (1, 1), (1, 0), (0, 0)], False, scene)
        rows.append((k, length, t0, t0 + length))
        at = t1 + PAD_GAP
    if at - PAD_GAP > far_start + STRAIGHT - AI_RAMP:
        raise SystemExit(f"pads run to {at - PAD_GAP:.0f} m, past the AI lane's end")
    # Steer the racing line (which trackbuild builds all three .ili lines from)
    # into the inside lane along the far straight, eased in and out.
    far_end = far_start + STRAIGHT
    shifted = []
    for (x, y, z), st in zip(scene.centreline, line.cum):
        if far_start <= st <= far_end:
            ease = min(1.0, (st - far_start) / AI_RAMP, (far_end - st) / AI_RAMP)
            ease = 0.5 - 0.5 * math.cos(math.pi * max(0.0, ease))
            (_x, _y, _z), (tx, ty) = line.at(st)
            x, y = x - ty * AI_OFFSET * ease, y + tx * AI_OFFSET * ease      # left = inside
        shifted.append((x, y, z))
    scene.centreline = shifted
    chunks, ntri, missing = flat_terrain(scene, line)
    if missing:
        raise SystemExit(f"{missing} seam segments missing")
    trackgen.add_ground(scene, margin=MARGIN + 1500.0, drop=0.6)

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[n].materials) for n in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    print(f"lap {line.L:.0f} m; far straight from {far_start:.0f} m; terrain {ntri} triangles in {chunks} chunks")
    for k, h, t0, t1 in rows:
        print(f"   pad {k + 1}: {h:g} m long, {PAD_HEIGHT:g} m tall, {t0:.1f}-{t1:.1f} m, outer quarter")
    print(f"surfaces {surfaces}; collision triangles {collide}")

    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True,
                              corridor=ili.corridor_for(bc.HALF * 2.0))
    print(f"assembled: {res.summary()}")

    gen = dict(bs.GENERATED)
    gen["clear.tex"] = (clear_texture, "colorkey")
    gen["padstr.tex"] = (stripes_texture, "opaque")
    for k, h in enumerate(PADS):
        gen[f"pad{k}.tex"] = ((lambda hh=h: pad_texture(hh)), "opaque")
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        fn, mode = gen[name]
        im = fn(); a = np.array(im)
        if mode == "opaque":
            if int((a.sum(axis=2) == 0).sum()):
                raise SystemExit(f"{name} has black texels")
            data = im.tobytes()
        else:
            data = np.dstack([a, np.where(a.sum(axis=2) > 0, 255, 0).astype(np.uint8)]).tobytes()
        enc = envelope.parse(tex.encode_to_tex(data, im.width, mode=mode, wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = bs.art.sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for k, h, t0, t1 in rows[::2] + [rows[-1]]:
        (x, y, z), (tx, ty) = line.at((t0 + t1) / 2)
        pos = bc.game((x - ty * 40.0 - tx * 30.0, y + tx * 40.0 - ty * 30.0, 5.0))
        tgt = bc.game((x, y, 2.0))
        cams.append(camtab.Camera("fixed", *pos, *camtab.aim(pos, tgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes, {len(cams)} cameras on the pads  VERIFIED")


if __name__ == "__main__":
    main()
