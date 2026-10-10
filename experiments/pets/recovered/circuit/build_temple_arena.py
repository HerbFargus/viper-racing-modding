"""Temple arena: the temple hall's floor, light and sky as one open 380 x 240 m arena.

Walls only round the edge (drawn 12 m, solid 8 m) with torches along them; ten massive
carved columns (8 m square, 30 m tall, solid) to hide behind, each with torches; eight
giant stone-head totems -- the four on the long walls knockable, the four at the
ends solid; golden idols to knock over, the great idol on
a plinth in the middle; and the same twenty hidden single-tile traps with their
pressure-plate tell. The racing loop is invisible -- it exists because the engine
needs a lap -- and the corridor is wide enough that the whole floor counts as track.
Solo: an AI car touching a trap crashes the game.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_temple_hall as H  # noqa: E402
import temple_art as ta  # noqa: E402
from build_sticks import turn  # noqa: E402
from vrmod import archive, camtab, envelope, ili, sky, sol, tex, trackbuild, trackgen  # noqa: E402

BT, L, bc, bs, bt, ha = H.BT, H.L, H.bc, H.bs, H.bt, H.ha
OUT = HERE / "temple_arena.trk"
KNOCKABLE = {4, 5, 6, 7}                           # the four on the long walls; the ends stay solid
SLOT = "dundas"
SEED = 1984                                        # Temple of Doom
AX, AY = 188.0, 118.0                              # arena half-extents: the 2 m walls' outer faces
                                                   # land on a tile edge, so no floor lies outside them
CORNER = 12.0                                      # solid corner towers, where the corridor can't reach
LOOP_STRAIGHT, LOOP_R = 140.0, 60.0                # the invisible racing loop: every wall at least
                                                   # as far from it as the arena's middle is (see fit_corridor)
COLUMNS = [(-120, -95), (-40, -95), (40, -95), (120, -95), (-120, 95), (-40, 95), (40, 95), (120, 95),
           (-40, 0), (40, 0)]
COLUMN_HALF, COLUMN_H = 4.0, 30.0
TOTEMS = [(-170, -60, 0), (-170, 60, 0), (170, -60, 180), (170, 60, 180),
          (-80, -110, 90), (80, -110, 90), (-80, 110, -90), (80, 110, -90)]   # x, y, facing (deg): into the arena
TOTEM_SCALE = 4.0                                  # 5.6 m wide, 8.8 m tall
TRAP_COUNT, TORCH_EVERY = 20, 25.0


def centreline():
    """A stadium loop 40 m inside the walls, started off the axis grid (origin claim)."""
    pts = [(-LOOP_STRAIGHT / 2 + 3.0 + i * 10.0, -LOOP_R, 0.0) for i in range(int(LOOP_STRAIGHT / 10))]
    arc = int(math.pi * LOOP_R / 10)
    pts += [(LOOP_STRAIGHT / 2 + 3.0 + LOOP_R * math.cos(-math.pi / 2 + math.pi * i / arc),
             LOOP_R * math.sin(-math.pi / 2 + math.pi * i / arc), 0.0) for i in range(arc)]
    pts += [(LOOP_STRAIGHT / 2 + 3.0 - i * 10.0, LOOP_R, 0.0) for i in range(int(LOOP_STRAIGHT / 10))]
    pts += [(-LOOP_STRAIGHT / 2 + 3.0 + LOOP_R * math.cos(math.pi / 2 + math.pi * i / arc),
             LOOP_R * math.sin(math.pi / 2 + math.pi * i / arc), 0.0) for i in range(arc)]
    k = 9                                          # the start line mid-way along the south straight
    return pts[k:] + pts[:k]


def perimeter_walls(scene, walls, light, torches):
    corners = [(-AX, -AY), (AX, -AY), (AX, AY), (-AX, AY)]
    verts, faces, n = [], [], 0
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        length = math.hypot(bx - ax, by - ay)
        tx, ty = (bx - ax) / length, (by - ay) / length
        nx, ny = -ty, tx                           # inward, for an anticlockwise corner list
        steps = int(length // 10)
        for k in range(steps):
            s0, s1 = k * length / steps, (k + 1) * length / steps
            cx, cy = ax + tx * (s0 + s1) / 2 - nx * 1.0, ay + ty * (s0 + s1) / 2 - ny * 1.0
            v, f = BT.game_box(scene, None, (cx, cy), (tx, ty), (s1 - s0) / 2 + 1.0, 1.0, -0.3, H.WALL_DRAW,
                               "carve.tex", tile=4.0)
            faces += [(p + len(verts), q + len(verts), r + len(verts)) for p, q, r in f]
            verts += v
            pa, pb = (ax + tx * s0, ay + ty * s0), (ax + tx * s1, ay + ty * s1)
            walls.append([(pa[0], pa[1], 0.0), (pb[0], pb[1], 0.0), (pb[0], pb[1], H.WALL_SOLID),
                          (pa[0], pa[1], H.WALL_SOLID)])
            if len(verts) >= H.MAX_VERTS - 40:
                H.emit(scene, f"wallp{n}.mod", verts, faces, "carve.tex", light, False)
                verts, faces, n = [], [], n + 1
        s = TORCH_EVERY / 2
        while s < length:
            torches.append(((ax + tx * s + nx * 0.05, ay + ty * s + ny * 0.05), (tx, ty)))
            s += TORCH_EVERY
    if verts:
        H.emit(scene, f"wallp{n}.mod", verts, faces, "carve.tex", light, False)


def add_columns(scene, walls, light, torches):
    """Massive columns: a stepped plinth, the shaft, a capital. Solid, torch on each face."""
    verts, faces = [], []
    for cx, cy in COLUMNS:
        for half, z0, z1 in ((COLUMN_HALF + 1.5, -0.3, 1.5), (COLUMN_HALF, 1.5, COLUMN_H - 2.0),
                             (COLUMN_HALF + 1.2, COLUMN_H - 2.0, COLUMN_H)):
            v, f = BT.game_box(scene, None, (cx, cy), (1.0, 0.0), half, half, z0, z1, "carve.tex", tile=8.0)
            faces += [(p + len(verts), q + len(verts), r + len(verts)) for p, q, r in f]
            verts += v
        H.solid_box(walls, (cx, cy), (1.0, 0.0), COLUMN_HALF + 1.5, COLUMN_HALF + 1.5)
        for fx, fy, tx, ty in ((1, 0, 0, 1), (-1, 0, 0, -1), (0, 1, -1, 0), (0, -1, 1, 0)):
            torches.append(((cx + fx * (COLUMN_HALF + 0.05), cy + fy * (COLUMN_HALF + 0.05)), (tx, ty)))
    H.emit(scene, "columns.mod", verts, faces, "carve.tex", light, False)


def add_torch_meshes(scene, torches):
    verts, faces = [], []
    for (cx, cy), (tx, ty) in torches:
        base = len(verts)
        for dx, dz, u, v in ((-0.55, 2.6, 0, 1), (0.55, 2.6, 1, 1), (0.55, 4.4, 1, 0), (-0.55, 4.4, 0, 0)):
            g = bc.game((cx + tx * dx, cy + ty * dx, dz))
            verts.append((g[0], g[1], g[2], u, v))
        faces += [(base, base + 1, base + 2), (base, base + 2, base + 3),
                  (base, base + 2, base + 1), (base, base + 3, base + 2)]
    for n, k in enumerate(range(0, len(verts), 1480)):
        vv = verts[k:k + 1480]
        ff = [(a - k, b - k, c - k) for a, b, c in faces if k <= a < k + 1480]
        H.emit(scene, f"torch{n}.mod", vv, ff, "torch.tex", H.Light([]), False)
        scene.colours[f"torch{n}.mod"] = [bs.grey(1.0)] * len(vv)


def add_totems(scene, walls, light):
    """Giant stone heads (the drag strip's knock-overs, scaled up) as solid scenery."""
    verts, faces = [], []
    w, d, h = 1.4 * TOTEM_SCALE, 1.1 * TOTEM_SCALE, 2.2 * TOTEM_SCALE
    for n, (cx, cy, face_deg) in enumerate(TOTEMS):
        hv, hf = BT.stone_head_mesh(w, d, h)
        a = math.radians(face_deg)
        fx, fy = math.cos(a), math.sin(a)          # where the face looks, source frame
        if n in KNOCKABLE:
            # A wobble: a facing model on a capsule pivoted at its foot. yaw_facing_traffic
            # turns a face toward traffic travelling along (tx, ty), i.e. to look along
            # -(tx, ty); so pass the reverse of where this one should look.
            name = f"totem{n}.mod"
            yaw = bc.yaw_facing_traffic(-fx, -fy)
            scene.meshes[name] = bt.to_facing(turn(hv, yaw), hf, "head.tex")
            scene.wobbles.append(trackgen.Wobble(position=(cx, cy, 0.0), mesh=name, radius=w / 2, height=h))
            continue
        rx, ry = fy, -fx                           # its local +x
        base = len(verts)
        for x, y, z, u, v in hv:                   # authoring: y up, face along +z
            g = bc.game((cx + rx * x + fx * z, cy + ry * x + fy * z, y))
            verts.append((g[0], g[1], g[2], u, v))
        mid = np.array(bc.game((cx, cy, h / 2)))
        for tri in hf:
            t = tuple(i + base for i in tri)
            cen = np.mean([verts[i][:3] for i in t], axis=0)
            faces.append(BT.orient(verts, t, cen - mid))
        H.solid_box(walls, (cx, cy), (fx, fy), d / 2, w / 2)
    H.emit(scene, "totems.mod", verts, faces, "head.tex", light, False)


def plan_arena_floor():
    """The floor stops at the walls' outer faces: nothing to land on outside them."""
    x0, y0 = -(AX + 2.0), -(AY + 2.0)
    nx, ny = int(round(2 * (AX + 2.0) / H.TILE)), int(round(2 * (AY + 2.0) / H.TILE))
    assert abs(nx * H.TILE - 2 * (AX + 2.0)) < 1e-6 and abs(ny * H.TILE - 2 * (AY + 2.0)) < 1e-6
    return x0, y0, nx, ny


def add_corners(scene, walls, light):
    """Carved towers filling the four inside corners, solid, a little taller than the walls."""
    verts, faces = [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            c = (sx * (AX - CORNER / 2), sy * (AY - CORNER / 2))
            v, f = BT.game_box(scene, None, c, (1.0, 0.0), CORNER / 2, CORNER / 2, -0.3, H.WALL_DRAW + 4.0,
                               "carve.tex", tile=8.0)
            faces += [(a + len(verts), b + len(verts), cc + len(verts)) for a, b, cc in f]
            verts += v
            H.solid_box(walls, c, (1.0, 0.0), CORNER / 2, CORNER / 2)
    H.emit(scene, "corners.mod", verts, faces, "carve.tex", light, False)


def place_traps(line, x0, y0, nx, ny, rng):
    keep_clear = [(x, y, COLUMN_HALF + 6.0) for x, y in COLUMNS] + [(x, y, 7.0) for x, y, _f in TOTEMS] + [(3.0, 0.0, 8.0)]
    spawn = line.p[0]
    eligible = set()
    for i in range(nx):
        for j in range(ny):
            cx, cy = x0 + (i + 0.5) * H.TILE, y0 + (j + 0.5) * H.TILE
            if abs(cx) > AX - 6 or abs(cy) > AY - 6:
                continue
            if abs(cx) > AX - CORNER - 4 and abs(cy) > AY - CORNER - 4:
                continue
            if any(math.hypot(cx - px, cy - py) < r for px, py, r in keep_clear):
                continue
            if math.hypot(cx - spawn[0], cy - spawn[1]) < 60.0:
                continue
            eligible.add((i, j))
    taken, blocked, clusters = set(), set(), []
    order = sorted(eligible)
    rng.shuffle(order)
    for i, j in order:
        if len(clusters) >= TRAP_COUNT:
            break
        if (i, j) in blocked:
            continue
        clusters.append((i, j, 1, 1, round(rng.uniform(3.0, 6.0), 1)))
        taken.add((i, j))
        blocked.update((i + a, j + b) for a in range(-4, 5) for b in range(-4, 5))    # spread them
    return clusters, taken, eligible


def fit_corridor(path):
    """Set track.ild's corridor, per waypoint, to the distance to the arena wall.

    The corridor is how far from the line still counts as track, and a reset only
    moves a car that is outside it -- so a corridor wider than the arena let a car
    that flew over the wall reset onto the strip outside it (seen in game). It is
    per record (stock heaven and kenyon vary it), and symmetric, so each waypoint
    takes the nearer of the two walls its sideways ray meets, out to the wall's outer
    face (2 m thick): the floor ends there, so everything past it -- the pit -- is off.
    """
    ents = archive.read(path)
    by = {e.name.lower(): e for e in ents}
    e = by["track.ild"]
    line = ili.parse_line(envelope.build(e.tag, e.version, e.payload))
    vals = []
    for r in line.records:
        px, py = -r[ili.FIELD_X], -r[ili.FIELD_Z]            # game frame -> source frame
        tx, ty = -r[ili.FIELD_DIR_X], -r[ili.FIELD_DIR_Z]
        n = math.hypot(tx, ty); tx, ty = tx / n, ty / n
        hits = []
        for nx, ny in ((-ty, tx), (ty, -tx)):
            t = min([(AX * sx - px) / nx for sx in (-1, 1) if nx and (AX * sx - px) / nx > 0] +
                    [(AY * sy - py) / ny for sy in (-1, 1) if ny and (AY * sy - py) / ny > 0])
            hits.append(t)
        vals.append(min(hits) + 2.0)                    # to the walls' OUTER faces: the floor ends
                                                        # there, and past them is the pit
    line.set_field(ili.FIELD_CORRIDOR, vals)
    e.payload = envelope.parse(ili.build(line)).payload
    archive.write(ents, path)
    return min(vals), max(vals)


def main():
    rng = random.Random(SEED)
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=40.0)
    scene.grid = [H.side_pt(line, -10.0 - 10.0 * (k // 2), 6.0 if k % 2 else -6.0) + (0.0,) for k in range(8)]

    walls, torches = [], []
    # torches first: their positions light everything else
    corners_probe = []
    perimeter_walls(trackgen.TrackScene(centreline=[]), corners_probe, H.Light([]), torches)
    add_columns(trackgen.TrackScene(centreline=[]), [], H.Light([]), torches)
    light = H.Light([(x - 0.0, y) for (x, y), _t in torches])
    torches = []
    perimeter_walls(scene, walls, light, torches)
    add_columns(scene, walls, light, torches)
    add_torch_meshes(scene, torches)
    add_totems(scene, walls, light)
    add_corners(scene, walls, light)
    scene.walls = walls

    x0, y0, nx, ny = plan_arena_floor()
    clusters, taken, eligible = place_traps(line, x0, y0, nx, ny, rng)
    counts = H.build_floor(scene, x0, y0, nx, ny, clusters, taken, light, rng)

    # idols: ten scattered on safe tiles, and the great one on a plinth in the middle
    free = sorted(c for c in eligible if c not in taken
                  and not any((c[0] + a, c[1] + b) in taken for a in (-1, 0, 1) for b in (-1, 0, 1)))
    rng.shuffle(free)
    for n, (i, j) in enumerate(free[:10]):
        cx, cy = x0 + (i + 0.5) * H.TILE, y0 + (j + 0.5) * H.TILE
        v, f = BT.lathe(BT.IDOL, 8)
        scene.meshes[f"idol{n:02d}.mod"] = bt.to_facing(turn(v, rng.uniform(0, 360)), f, "gold.tex")
        scene.wobbles.append(trackgen.Wobble(position=(cx, cy, 0.0), mesh=f"idol{n:02d}.mod", radius=0.42, height=1.6))
    pv, pf = BT.game_box(scene, None, (3.0, 0.0), (1.0, 0.0), 3.0, 3.0, -0.3, 1.2, "carve.tex", tile=2.0)
    H.emit(scene, "plinth.mod", pv, pf, "carve.tex", light, False)
    H.solid_box(walls, (3.0, 0.0), (1.0, 0.0), 3.0, 3.0)
    big = [(y * 2.2, r * 2.2) for y, r in BT.IDOL]
    v, f = BT.lathe(big, 10)
    scene.meshes["idolbig.mod"] = bt.to_facing(turn(v, 0.0), f, "gold.tex")
    scene.wobbles.append(trackgen.Wobble(position=(3.0, 0.0, 1.2), mesh="idolbig.mod", radius=0.92, height=3.5))

    trackgen.add_ground(scene, texture="vault.tex", margin=400.0, drop=40.0)   # a pit beyond the walls
    scene.colours["ground.mod"] = [bs.grey(0.5)] * 4

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn) + len(scene.wobbles)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    print(f"arena {2 * AX:.0f} x {2 * AY:.0f} m; floor {nx} x {ny} tiles; loop {line.L:.0f} m")
    print(f"columns {len(COLUMNS)}; totems {len(TOTEMS)} ({len(KNOCKABLE)} knockable); torches {len(torches)}; traps {len(clusters)} "
          f"(heights {min(c[4] for c in clusters)}-{max(c[4] for c in clusters)} m); idols 10 + the great idol; "
          f"solid faces {len(walls)}; floor meshes {counts}")
    print(f"surfaces {surfaces} (budget {H.SURFACE_BUDGET}); largest chunk {biggest} verts; collision triangles "
          f"{collide} (budget {H.COLLISION_BUDGET}); textures {len(wanted)} + 4 sky")
    if surfaces > H.SURFACE_BUDGET or biggest > H.MAX_VERTS or collide > H.COLLISION_BUDGET:
        raise SystemExit("over budget")

    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True,
                              corridor=ili.corridor_for(2 * AX))
    print(f"assembled: {res.summary()}")
    gen = dict(ha.ALL)
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
    s_img = ha.temple_sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for (px, py), (tx_, ty_) in (((-AX + 8, -AY + 8), (1, 1)), ((AX - 8, -AY + 8), (-1, 1)),
                                  ((AX - 8, AY - 8), (-1, -1)), ((-AX + 8, AY - 8), (1, -1))):
        gpos, gtgt = bc.game((px, py, 10.0)), bc.game((px + tx_ * 80, py + ty_ * 60, 1.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)
    lo, hi = fit_corridor(OUT)
    print(f"corridor fitted to the walls: {lo:.0f}-{hi:.0f} m either side of the line")

    by = {e.name.lower(): e for e in archive.read(OUT)}
    for name in sorted(wanted) + list(sky.TILES):
        tex.parse(envelope.build(by[name].tag, by[name].version, by[name].payload))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    ids = sorted(q.id for q in so.primitives if q.id >= 0)
    boxes = sum(1 for q in so.primitives if q.type == sol.BOX)
    if ids != list(range(len(scene.wobbles))) or boxes != len(walls):
        raise SystemExit(f"sol wrong: ids {ids[:3]}.. boxes {boxes} vs {len(walls)}")
    print(f"textures all decode; {boxes} solid boxes; wobbles 0..{ids[-1]}; {OUT.name} "
          f"{OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
