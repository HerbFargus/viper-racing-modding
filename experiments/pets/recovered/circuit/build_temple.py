"""Temple Run: an Indiana Jones drag strip with hidden launch traps. Everything generated.

LAYOUT. The community's drag-strip shape, rebuilt: an 800 m strip, a hairpin, a
return road 90 m across, and back (the race counts the whole lap). The start line
is 60 m into the strip; a temple gate stands over it and another over the quarter
mile. Two lanes: the AI's (left, the infield side) and yours (right). A carved
stone wall divides them from 40 m to 660 m past the line.

WHY THE WALL. An AI car that touches a launch pad crashes the game (runtime.md 9),
so the AI must never enter the trapped lane. Its racing line runs down the middle
of its own lane from the grid on, and the wall makes that physical. The wall starts
40 m past the line so that an AI car that happens to be gridded in your lane still
has room to cross to its line first -- which grid record the player gets was not
pinned down from the binary.

TRAPS. Eight pads, all in your lane, fully hidden: the collision is an invisible
quad raised over the road, and the road drawn over the hole is a non-solid copy of
the flagstones. What a pad does depends on how long your wheels stay under it
(runtime.md 9), so the early ones are short and low (you are slow there) and the
late ones are long and tall (you are doing 45 m/s+). "full" tiles cover the lane
and throw you straight up; "outer"/"inner" half-lane tiles lift one side and roll
you.

ALSO: knockable idols (wobbles: golden idols and stone heads) along your verge and
in your lane past the last trap, and a jungle of palms, broadleaf trees and ferns.
"""
import math
import random
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "targets"))
import build_launchlab as L  # noqa: E402  (brings bo/bs/bc, HALF = 10 m, Line.nearest_s)
import build_targets as bt  # noqa: E402
import temple_art as ta  # noqa: E402
from build_sticks import turn  # noqa: E402
from vrmod import archive, camtab, envelope, ili, mod, sky, sol, tex, trackbuild, trackgen  # noqa: E402
from vrmod.trackgen import GRASS  # noqa: E402

bo, bs, bc = L.bo, L.bs, L.bc
OUT = HERE / "temple.trk"
SLOT = "kenyon"
STRAIGHT, RADIUS, RUNUP = 800.0, 45.0, 60.0
AI_OFFSET, AI_EASE = 5.0, 30.0                    # the AI's lane centre, metres left; eased in/out
WALL_FROM, WALL_TO, WALL_H, WALL_HALF = 40.0, 660.0, 1.2, 0.3
QUARTER = 402.3
TRAPS = [  # metres past the start line, length, height, which part of your lane
    (50, 5, 4.0, "full"), (100, 6, 5.0, "outer"), (160, 10, 8.0, "full"), (230, 12, 10.0, "inner"),
    (300, 20, 12.0, "full"), (380, 25, 15.0, "outer"), (470, 35, 15.0, "full"), (560, 40, 15.0, "full")]
LANES = {"full": (0.02, 0.47), "outer": (0.02, 0.245), "inner": (0.245, 0.47)}   # 0 = right edge, 0.5 = wall
VERGE_Z = -0.1                                     # the grass band's height against the road's 0
SURFACE_BUDGET, MAX_VERTS = 650, 1500


def centreline():
    pts = [(i * 10.0, 0.0, 0.0) for i in range(int(STRAIGHT / 10))]
    arc = int(math.pi * RADIUS / 10)
    pts += [(STRAIGHT + RADIUS * math.cos(-math.pi / 2 + math.pi * i / arc),
             RADIUS + RADIUS * math.sin(-math.pi / 2 + math.pi * i / arc), 0.0) for i in range(arc)]
    pts += [(STRAIGHT - i * 10.0, 2 * RADIUS, 0.0) for i in range(int(STRAIGHT / 10))]
    pts += [(RADIUS * math.cos(math.pi / 2 + math.pi * i / arc),
             RADIUS + RADIUS * math.sin(math.pi / 2 + math.pi * i / arc), 0.0) for i in range(arc)]
    k = int(RUNUP / 10)
    pts = pts[k:] + pts[:k]                        # station 0 is the start line
    # half a station off the axis grid, so some racing-line segment claims the
    # world origin at race start (ili.origin_is_claimed)
    return [(x - 5.0, y, z) for x, y, z in pts]


def at(line, d, lat=0.0, z=0.0):
    """Source-frame point `d` metres past the start line, `lat` metres left of the centreline."""
    (x, y, _z), (tx, ty) = line.at(d % line.L)
    return (x - ty * lat, y + tx * lat, z), (tx, ty)


# ------------------------------------------------------------------ meshes
def orient(verts, tri, outward):
    """Wind `tri` so its right-hand normal points along `outward` (that side draws)."""
    a, b, c = (np.array(verts[i][:3]) for i in tri)
    n = np.cross(b - a, c - a)
    return tri if np.dot(n, outward) >= 0 else (tri[0], tri[2], tri[1])


def game_box(scene, name, centre, along, half_len, half_wid, z0, z1, texname, tile=4.0,
             top=True, solid_walls=None):
    """A drawn stone block in the source frame (a wall run, a pillar, a lintel), faces out."""
    tx, ty = along
    nx, ny = -ty, tx
    cx, cy = centre
    corners = [(cx + tx * sl * half_len + nx * sw * half_wid, cy + ty * sl * half_len + ny * sw * half_wid)
               for sl, sw in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    verts, faces = [], []
    mid = np.array(bc.game((cx, cy, (z0 + z1) / 2)))
    sides = [(0, 1), (1, 2), (2, 3), (3, 0)]
    for i, j in sides:
        (ax, ay), (bx_, by_) = corners[i], corners[j]
        w = math.hypot(bx_ - ax, by_ - ay)
        base = len(verts)
        for (px, py), z, u, v in (((ax, ay), z0, 0, (z1 - z0) / tile), ((bx_, by_), z0, w / tile, (z1 - z0) / tile),
                                  ((bx_, by_), z1, w / tile, 0), ((ax, ay), z1, 0, 0)):
            g = bc.game((px, py, z))
            verts.append((g[0], g[1], g[2], u, v))
        centre_face = np.mean([verts[base + k][:3] for k in range(4)], axis=0)
        for tri in ((base, base + 1, base + 2), (base, base + 2, base + 3)):
            faces.append(orient(verts, tri, centre_face - mid))
        if solid_walls is not None:
            solid_walls.append([(ax, ay, z0), (bx_, by_, z0), (bx_, by_, z0 + WALL_H), (ax, ay, z0 + WALL_H)])
    if top:
        base = len(verts)
        for (px, py), (u, v) in zip(corners, ((0, 0), (2 * half_len / tile, 0), (2 * half_len / tile, 2 * half_wid / tile),
                                               (0, 2 * half_wid / tile))):
            g = bc.game((px, py, z1))
            verts.append((g[0], g[1], g[2], u, v))
        for tri in ((base, base + 1, base + 2), (base, base + 2, base + 3)):
            faces.append(orient(verts, tri, np.array([0.0, 1.0, 0.0])))
    return verts, faces


def emit(scene, name, verts, faces, texname, colour=0.92):
    scene.meshes[name] = mod.Mesh(
        vertices=[mod.Vertex(x, y, z, 0.0, 1.0, 0.0, u, v) for x, y, z, u, v in verts], faces=faces,
        materials=[mod.Material(name=texname, vertex_start=0, vertex_end=len(verts), face_start=0,
                                face_end=len(faces))])
    scene.colours[name] = [bs.grey(colour)] * len(verts)
    scene.scenery.append(trackgen.SceneObject(name, GRASS, trackgen.NO_COLLISION))


# ------------------------------------------------------------------ the strip
def add_wall(scene, line, walls):
    """The lane divider: carved stone, 0.6 m thick, solid on both faces."""
    verts, faces = [], []
    d = WALL_FROM
    while d < WALL_TO - 1e-6:
        e = min(d + 20.0, WALL_TO)
        (a, t), (b, _t) = at(line, d), at(line, e)
        v, f = game_box(scene, None, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), t, (e - d) / 2, WALL_HALF,
                        -0.2, WALL_H - 0.2, "carve.tex", tile=2.0)
        faces += [(p + len(verts), q + len(verts), r + len(verts)) for p, q, r in f]
        verts += v
        for side in (-1.0, 1.0):                       # a collision face on each side
            (pa, _), (pb, _) = at(line, d, side * WALL_HALF), at(line, e, side * WALL_HALF)
            walls.append([pa, pb, (pb[0], pb[1], WALL_H), (pa[0], pa[1], WALL_H)])
        d = e
    emit(scene, "cwall.mod", verts, faces, "carve.tex", 0.95)


def add_gate(scene, line, d, name, walls):
    """Two carved pillars on the verges and a lintel over both lanes."""
    (c, t) = at(line, d)
    verts, faces = [], []
    for lat in (-14.0, 14.0):
        p, _ = at(line, d, lat)
        v, f = game_box(scene, None, p[:2], t, 1.2, 1.2, VERGE_Z - 0.3, 9.0, "carve.tex", solid_walls=walls)
        faces += [(a + len(verts), b + len(verts), cc + len(verts)) for a, b, cc in f]
        verts += v
    v, f = game_box(scene, None, c[:2], (t[1], -t[0]), 16.5, 1.4, 9.0, 11.6, "carve.tex")
    faces += [(a + len(verts), b + len(verts), cc + len(verts)) for a, b, cc in f]
    verts += v
    emit(scene, name, verts, faces, "carve.tex", 0.9)


def add_traps(scene, line):
    rows = []
    for k, (d, length, h, lane) in enumerate(TRAPS):
        t0 = float(d)
        t1 = t0 + 10.0 * math.ceil(length / 10.0 - 1e-9)
        (r0, r1, l1, l0), road_tex = L.cut_asphalt(scene, line, t0, t1)

        def bil(s, f):
            return L.part(L.part(r0, r1, s), L.part(l0, l1, s), f)

        def rect(s0, s1, f0, f1):
            return [bil(s0, f0), bil(s1, f0), bil(s1, f1), bil(s0, f1)]

        sL = length / (t1 - t0)
        fa, fb = LANES[lane]
        pieces = [rect(0, 1, 0, fa), rect(0, 1, fb, 1)] + ([rect(sL, 1, fa, fb)] if sL < 1 - 1e-9 else [])
        for j, q in enumerate(pieces):                              # the road around the pad, solid
            L.quad_mesh(f"trd{k}{j}.mod", q, 0.0, road_tex, [(c.u, c.v) for c in q], True, scene)
        pad = rect(0, sL, fa, fb)
        L.quad_mesh(f"trap{k}.mod", pad, h, "clear.tex", [(0, 1), (1, 1), (1, 0), (0, 0)], True, scene)
        L.quad_mesh(f"tcv{k}.mod", pad, 0.0, road_tex, [(c.u, c.v) for c in pad], False, scene)
        rows.append((k, d, length, h, lane, fa, fb))
    return rows


# ------------------------------------------------------------------ idols (wobbles)
def lathe(profile, seg):
    """A turned solid, y-up, faces out: (verts as x,y,z,u,v), faces."""
    verts, faces = [], []
    rings = []
    for j, (y, r) in enumerate(profile):
        ring = []
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            verts.append((r * math.cos(a), y, r * math.sin(a), i / seg, j / (len(profile) - 1)))
            ring.append(len(verts) - 1)
        rings.append(ring)
    for j in range(len(profile) - 1):
        ymid = (profile[j][0] + profile[j + 1][0]) / 2
        for i in range(seg):
            a, b, c, d = rings[j][i], rings[j][i + 1], rings[j + 1][i + 1], rings[j + 1][i]
            for tri in ((a, b, c), (a, c, d)):
                cen = np.mean([verts[q][:3] for q in tri], axis=0)
                faces.append(orient(verts, tri, cen - np.array([0.0, ymid, 0.0])))
    for j, up in ((0, -1.0), (len(profile) - 1, 1.0)):              # caps
        y, r = profile[j]
        if r <= 1e-6:
            continue
        verts.append((0.0, y, 0.0, 0.5, 0.5))
        cen = len(verts) - 1
        for i in range(seg):
            faces.append(orient(verts, (cen, rings[j][i], rings[j][i + 1]), np.array([0.0, up, 0.0])))
    return verts, faces


IDOL = [(0.0, 0.42), (0.16, 0.42), (0.2, 0.30), (0.9, 0.24), (0.95, 0.32), (1.06, 0.32),
        (1.1, 0.19), (1.16, 0.27), (1.44, 0.25), (1.6, 0.0)]


def stone_head_mesh(w=1.4, d=1.1, h=2.2):
    """A block head: the carved face on its front (+z), plain stone elsewhere -- a closed box,
    underside included, since a knocked-over head lies showing it."""
    hw, hd = w / 2, d / 2
    P = ta.PLAIN_UV
    quads = [  # corners, uvs, outward
        ([(-hw, 0, hd), (hw, 0, hd), (hw, h, hd), (-hw, h, hd)], [(1, 1), (0, 1), (0, 0), (1, 0)], (0, 0, 1)),  # u flipped: left-handed draw
        ([(hw, 0, -hd), (-hw, 0, -hd), (-hw, h, -hd), (hw, h, -hd)], [P] * 4, (0, 0, -1)),
        ([(hw, 0, hd), (hw, 0, -hd), (hw, h, -hd), (hw, h, hd)], [P] * 4, (1, 0, 0)),
        ([(-hw, 0, -hd), (-hw, 0, hd), (-hw, h, hd), (-hw, h, -hd)], [P] * 4, (-1, 0, 0)),
        ([(-hw, h, hd), (hw, h, hd), (hw, h, -hd), (-hw, h, -hd)], [P] * 4, (0, 1, 0)),
        # the underside: never seen standing, but a knocked-over head shows it
        ([(-hw, 0, -hd), (hw, 0, -hd), (hw, 0, hd), (-hw, 0, hd)], [P] * 4, (0, -1, 0)),
    ]
    verts, faces = [], []
    for corners, uvs, out in quads:
        base = len(verts)
        verts += [(x, y, z, u, v) for (x, y, z), (u, v) in zip(corners, uvs)]
        for tri in ((base, base + 1, base + 2), (base, base + 2, base + 3)):
            faces.append(orient(verts, tri, np.array(out, float)))
    return verts, faces


def add_idols(scene, line):
    placed = []
    spots = [(70 + 70 * k, -(bc.HALF + 4.0 + 3.0 * (k % 2)), VERGE_Z, "head" if k % 2 else "idol") for k in range(10)]
    spots += [(612, -3.0, 0.0, "idol"), (622, -6.5, 0.0, "idol"), (634, -4.5, 0.0, "head"), (646, -7.5, 0.0, "idol")]
    for n, (d, lat, z, kind) in enumerate(spots):
        (x, y, _z), (tx, ty) = line.at(d)
        foot = (x - ty * lat, y + tx * lat, z)
        yaw = bc.yaw_facing_traffic(tx, ty)
        name = f"idol{n:02d}.mod"
        if kind == "idol":
            v, f = lathe(IDOL, 8)
            scene.meshes[name] = bt.to_facing(turn(v, yaw), f, "gold.tex")
            scene.wobbles.append(trackgen.Wobble(position=foot, mesh=name, radius=0.42, height=1.6))
        else:
            v, f = stone_head_mesh()
            scene.meshes[name] = bt.to_facing(turn(v, yaw), f, "head.tex")
            scene.wobbles.append(trackgen.Wobble(position=foot, mesh=name, radius=0.75, height=2.2))
        placed.append((d, lat, kind))
    return placed


# ------------------------------------------------------------------ jungle
KINDS = {"palm.tex": (8.0, 14.0, 0.8), "broad.tex": (7.0, 12.0, 0.9), "fern.tex": (1.2, 2.2, 1.4)}


def add_jungle(scene, line, level):
    xs = [p[0] for p in line.p]; ys = [p[1] for p in line.p]
    x0, x1, y0, y1 = min(xs) - L.MARGIN + 30, max(xs) + L.MARGIN - 30, min(ys) - L.MARGIN + 30, max(ys) + L.MARGIN - 30
    rng = random.Random(41)
    trees = []
    for _ in range(40000):
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        dist = line.nearest(x, y)[0]
        if dist < bc.GRASS_EDGE + 4:
            continue
        dense = bs.vnoise(x, y, 120.0, 17)
        near = dist < 90
        if rng.random() > (0.06 + 0.5 * dense) * (1.0 if near else 0.45):
            continue
        r = rng.random()
        kind = "palm.tex" if r < 0.45 else ("broad.tex" if r < 0.75 else "fern.tex")
        lo, hi, aspect = KINDS[kind]
        trees.append((kind, x, y, level - 0.15, rng.uniform(lo, hi), aspect, rng.uniform(0, 180), rng.uniform(0.8, 1.0)))
        if len(trees) >= 2600:
            break
    return bs.add_vegetation(scene, trees), len(trees)


# ------------------------------------------------------------------ build
def main():
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.sweep(pts, bands=bs.BANDS, road_half_width=bc.HALF, closed=True, segment_length=150.0)
    trackgen.add_checkpoints(scene, 4, half_width=bc.HALF)
    # Grid: record 0 (the player, as far as the car list order goes) in the trapped
    # right lane, everyone else in the AI lane -- see the module note on the wall.
    scene.grid = [at(line, -8.0, -AI_OFFSET)[0], at(line, -8.0, AI_OFFSET)[0]]
    scene.grid += [at(line, -20.0 - 12.0 * k, AI_OFFSET)[0] for k in range(6)]

    rows = add_traps(scene, line)
    walls = []
    add_wall(scene, line, walls)
    add_gate(scene, line, 0.0, "gate0.mod", walls)
    add_gate(scene, line, QUARTER, "gate1.mod", walls)
    scene.walls = walls
    idols = add_idols(scene, line)

    # The AI's line: its lane's centre along the whole strip, eased in over the
    # first 30 m out of the hairpin and out over the last 30 m before the next.
    strip = (-RUNUP, STRAIGHT - RUNUP)
    shifted = []
    for (x, y, z), cum in zip(scene.centreline, line.cum):
        d = cum if cum < line.L - RUNUP - 1e-6 else cum - line.L
        if strip[0] <= d <= strip[1]:
            ease = min(1.0, (d - strip[0]) / AI_EASE, (strip[1] - d) / AI_EASE)
            ease = 0.5 - 0.5 * math.cos(math.pi * max(0.0, ease))
            (_p, (tx, ty)) = at(line, d)
            x, y = x - ty * AI_OFFSET * ease, y + tx * AI_OFFSET * ease
        shifted.append((x, y, z))
    scene.centreline = shifted

    chunks, ntri, missing = L.flat_terrain(scene, line)
    if missing:
        raise SystemExit(f"{missing} seam segments missing")
    trackgen.add_ground(scene, margin=L.MARGIN + 1500.0, drop=0.6)
    scene.colours["ground.mod"] = [bs.grey(0.8)] * 4
    veg, plants = add_jungle(scene, line, -0.1)

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn) + len(scene.wobbles)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    print(f"lap {line.L:.0f} m; strip {STRAIGHT:.0f} m, start line {RUNUP:.0f} m in, quarter mile at {QUARTER} m")
    for k, d, length, h, lane, fa, fb in rows:
        print(f"   trap {k + 1}: {d}-{d + length} m past the line, {length} m long, {h:g} m tall, {lane} "
              f"({(0.5 - fb) * 20:.1f}-{(0.5 - fa) * 20:.1f} m right of the wall)")
    print(f"centre wall {WALL_FROM:.0f}-{WALL_TO:.0f} m; {len(walls)} solid wall faces; idols {len(idols)}; "
          f"jungle {plants} plants in {veg} chunks; terrain {ntri} triangles")
    print(f"surfaces {surfaces} (budget {SURFACE_BUDGET}); largest chunk {biggest} verts; collision triangles "
          f"{collide}; textures {len(wanted)} + 4 sky")
    if surfaces > SURFACE_BUDGET or biggest > MAX_VERTS:
        raise SystemExit("over budget")

    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True,
                              corridor=ili.corridor_for(bc.HALF * 2.0))
    print(f"assembled: {res.summary()}")

    gen = dict(ta.ALL)
    gen["clear.tex"] = (L.clear_texture, "colorkey")
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
    s_img = ta.jungle_sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for d in (-30.0, 120.0, 260.0, 400.0, 540.0, 680.0):
        p, (tx, ty) = at(line, d, -32.0, 4.5)
        tgt, _ = at(line, d + 60.0, -3.0, 1.5)
        gpos, gtgt = bc.game(p), bc.game(tgt)
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)

    by = {e.name.lower(): e for e in archive.read(OUT)}
    for name in sorted(wanted) + list(sky.TILES):
        tex.parse(envelope.build(by[name].tag, by[name].version, by[name].payload))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    ids = sorted(q.id for q in so.primitives if q.id >= 0)
    boxes = sum(1 for q in so.primitives if q.type == sol.BOX)
    if ids != list(range(len(idols))) or boxes != len(walls):
        raise SystemExit(f"sol wrong: ids {ids[:3]}.. boxes {boxes}")
    print(f"textures all decode; {boxes} wall boxes, wobbles 0..{ids[-1]}; {len(cams)} cameras; "
          f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
