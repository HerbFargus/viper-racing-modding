"""Temple escape: a ring-shaped hall floored in 5 m stone tiles, with hidden launch traps
scattered at random across it. Solo -- no AI (an AI car touching a pad crashes the game).

LAYOUT. A 44 m wide corridor loops round a solid inner sanctum: 450 m straights,
60 m-radius ends, lap ~1.28 km. Carved walls 12 m tall line both sides (solid to 8 m),
torches every 30 m, stone pillars down the straights, a great gate over the
start/finish line. The sky is painted as the far walls and vault of the hall.

FLOOR. A world-aligned grid of 5 m tiles covering the whole temple footprint. Every
tile draws from one 2x2 atlas (plain / cracked / glyph / worn), and every vertex is
lit from the torches (track geometry draws pre-lit), so the floor pools with warm
light along the walls and falls dark in the middle.

TRAPS. Twenty single tiles, spread round the lap where people race: at speed each is a
short hop, enough to throw a car off its line. Each is an invisible pad raised 3-6 m over a hole in the floor; the tiles over the hole
are not solid, and each shows a pressure plate set into the slab -- a minor tell,
low contrast, visible if you look. The layout
is random AT BUILD TIME (seed below) -- the engine cannot reshuffle it per race.
Kept clear: the start zone, a margin along each wall, and every pillar.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_temple as BT  # noqa: E402  (brings L, bo, bs, bc and the box/idol helpers)
import hall_art as ha  # noqa: E402
from build_sticks import turn  # noqa: E402
from vrmod import archive, camtab, envelope, ili, mod, sky, sol, tex, trackbuild, trackgen  # noqa: E402
from vrmod.trackgen import GRASS, NO_COLLISION, ROAD  # noqa: E402

L, bc, bs, bt = BT.L, BT.bc, BT.bs, BT.bt
OUT = HERE / "temple_hall.trk"
SLOT = "kenyon"
SEED = 1981                                        # Raiders of the Lost Ark
STRAIGHT, RADIUS, RUNUP = 450.0, 60.0, 60.0
HALFW, WALL_T, WALL_DRAW, WALL_SOLID = 22.0, 2.0, 12.0, 8.0
TILE, BLOCK = 5.0, 16                              # tile size; tiles per mesh block side
TRAP_COUNT = 20                                    # few, spread out, where people race
RACE_BAND = 14.0                                   # traps sit within this of the corridor's middle
START_ZONE = (-45.0, 55.0)                         # metres around the start line kept safe
TORCH_EVERY = 30.0
SURFACE_BUDGET, MAX_VERTS, COLLISION_BUDGET = 650, 1500, 16500


def centreline():
    pts = [(i * 10.0, 0.0, 0.0) for i in range(int(STRAIGHT / 10))]
    arc = int(math.pi * RADIUS / 10)
    pts += [(STRAIGHT + RADIUS * math.cos(-math.pi / 2 + math.pi * i / arc),
             RADIUS + RADIUS * math.sin(-math.pi / 2 + math.pi * i / arc), 0.0) for i in range(arc)]
    pts += [(STRAIGHT - i * 10.0, 2 * RADIUS, 0.0) for i in range(int(STRAIGHT / 10))]
    pts += [(RADIUS * math.cos(math.pi / 2 + math.pi * i / arc),
             RADIUS + RADIUS * math.sin(math.pi / 2 + math.pi * i / arc), 0.0) for i in range(arc)]
    k = int(RUNUP / 10)
    pts = pts[k:] + pts[:k]
    return [(x - 5.0, y, z) for x, y, z in pts]    # off the axis grid: see ili.origin_is_claimed


def d_of(line, s):
    """Arc length -> metres past the start line, negative just before it."""
    return s if s < line.L - 100.0 else s - line.L


# ------------------------------------------------------------------ light
class Light:
    """Torchlight baked into vertex colours: ambient plus warm falloff from each torch."""

    def __init__(self, torches):
        self.t = np.array(torches) if torches else np.zeros((0, 2))

    def at(self, xs, ys, zs=None):
        xs, ys = np.atleast_1d(xs).astype(float), np.atleast_1d(ys).astype(float)
        d2 = (xs[:, None] - self.t[None, :, 0]) ** 2 + (ys[:, None] - self.t[None, :, 1]) ** 2
        v = 0.34 + 0.85 * np.exp(-d2 / (2 * 13.0 ** 2)).sum(axis=1)
        if zs is not None:
            v *= 0.75 + 0.25 * np.exp(-np.maximum(np.atleast_1d(zs) - 3.0, 0) / 5.0)
        return np.clip(v, 0.2, 1.0)


def colours_for(verts, light):
    """verts are game-frame (x, y, z, u, v); the source frame is (-x, -z, y)."""
    g = np.array([v[:3] for v in verts])
    return [bs.grey(c) for c in light.at(-g[:, 0], -g[:, 2], g[:, 1])]


def emit(scene, name, verts, faces, texname, light, solid, code=ROAD):
    scene.meshes[name] = mod.Mesh(
        vertices=[mod.Vertex(x, y, z, 0.0, 1.0, 0.0, u, v) for x, y, z, u, v in verts], faces=faces,
        materials=[mod.Material(name=texname, vertex_start=0, vertex_end=len(verts), face_start=0,
                                face_end=len(faces))])
    scene.colours[name] = colours_for(verts, light)
    if solid:
        scene.driveables.append(trackgen.SceneObject(name, code))
    else:
        scene.scenery.append(trackgen.SceneObject(name, GRASS, NO_COLLISION))


# ------------------------------------------------------------------ walls, pillars, gate, torches
def side_pt(line, s, lat):
    (x, y, _z), (tx, ty) = line.at(s % line.L)
    return (x - ty * lat, y + tx * lat)


def add_walls(scene, line, walls, light):
    """Outer and inner walls: drawn 12 m tall, solid 8 m on the corridor face."""
    n = line.n
    for side, lat_c, lat_face in (("o", -(HALFW + WALL_T / 2), -HALFW), ("i", HALFW + WALL_T / 2, HALFW)):
        chunk_v, chunk_f, chunk_n = [], [], 0
        for k in range(n):
            s0, s1 = line.cum[k], line.cum[k + 1]
            a, b = side_pt(line, s0, lat_c), side_pt(line, s1, lat_c)
            L_ = math.hypot(b[0] - a[0], b[1] - a[1])
            along = ((b[0] - a[0]) / L_, (b[1] - a[1]) / L_)
            v, f = BT.game_box(scene, None, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), along, L_ / 2 + 0.7,
                               WALL_T / 2, -0.3, WALL_DRAW, "carve.tex", tile=4.0)
            chunk_f += [(p + len(chunk_v), q + len(chunk_v), r + len(chunk_v)) for p, q, r in f]
            chunk_v += v
            fa, fb = side_pt(line, s0, lat_face), side_pt(line, s1, lat_face)
            walls.append([(fa[0], fa[1], 0.0), (fb[0], fb[1], 0.0), (fb[0], fb[1], WALL_SOLID), (fa[0], fa[1], WALL_SOLID)])
            if len(chunk_v) >= MAX_VERTS - 40 or k == n - 1:
                emit(scene, f"wall{side}{chunk_n}.mod", chunk_v, chunk_f, "carve.tex", light, False)
                chunk_v, chunk_f, chunk_n = [], [], chunk_n + 1


def solid_box(walls, centre, along, half_len, half_wid):
    tx, ty = along
    nx, ny = -ty, tx
    cx, cy = centre
    c = [(cx + tx * sl * half_len + nx * sw * half_wid, cy + ty * sl * half_len + ny * sw * half_wid)
         for sl, sw in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    for i in range(4):
        (ax, ay), (bx_, by_) = c[i], c[(i + 1) % 4]
        walls.append([(ax, ay, 0.0), (bx_, by_, 0.0), (bx_, by_, WALL_SOLID), (ax, ay, WALL_SOLID)])


def pillar_spots(line):
    ds = [100, 180, 260, 340]
    ret0 = STRAIGHT - RUNUP + math.pi * RADIUS
    ds += [ret0 + 40 + 80 * k for k in range(5)]
    out = []
    for i, d in enumerate(ds):
        for lat in (-11.0, 11.0):
            out.append((d, lat + (3.0 if i % 2 else -3.0) * (1 if lat > 0 else -1) * 0))
    return out


def add_pillars(scene, line, walls, light):
    verts, faces = [], []
    spots = []
    for d, lat in pillar_spots(line):
        (x, y, _z), (tx, ty) = line.at(d % line.L)
        p = (x - ty * lat, y + tx * lat)
        spots.append(p)
        v, f = BT.game_box(scene, None, p, (tx, ty), 1.25, 1.25, -0.3, WALL_DRAW, "carve.tex", tile=4.0)
        faces += [(a + len(verts), b + len(verts), c + len(verts)) for a, b, c in f]
        verts += v
        solid_box(walls, p, (tx, ty), 1.25, 1.25)
    emit(scene, "pillars.mod", verts, faces, "carve.tex", light, False)
    return spots


def add_gate(scene, line, walls, light):
    (x, y, _z), (tx, ty) = line.at(0.0)
    verts, faces = [], []
    for lat in (-(HALFW - 2.0), HALFW - 2.0):
        p = (x - ty * lat, y + tx * lat)
        v, f = BT.game_box(scene, None, p, (tx, ty), 2.0, 2.0, -0.3, 15.0, "carve.tex", tile=4.0)
        faces += [(a + len(verts), b + len(verts), c + len(verts)) for a, b, c in f]
        verts += v
        solid_box(walls, p, (tx, ty), 2.0, 2.0)
    v, f = BT.game_box(scene, None, (x, y), (-ty, tx) if False else (ty, -tx), HALFW + 1.0, 1.6, 12.0, 15.5,
                       "carve.tex", tile=4.0)
    faces += [(a + len(verts), b + len(verts), c + len(verts)) for a, b, c in f]
    verts += v
    emit(scene, "gate.mod", verts, faces, "carve.tex", light, False)


def torch_spots(line):
    out = []
    s = 5.0
    while s < line.L - 1:
        for lat in (-(HALFW - 0.05), HALFW - 0.05):
            out.append((s, lat))
        s += TORCH_EVERY
    return out


def add_torches(scene, line, light):
    verts, faces, n = [], [], 0
    for s, lat in torch_spots(line):
        (x, y, _z), (tx, ty) = line.at(s)
        cx, cy = x - ty * lat, y + tx * lat
        base = len(verts)
        for (dx, dz, u, v) in ((-0.55, 2.6, 0, 1), (0.55, 2.6, 1, 1), (0.55, 4.4, 1, 0), (-0.55, 4.4, 0, 0)):
            g = bc.game((cx + tx * dx, cy + ty * dx, dz))
            verts.append((g[0], g[1], g[2], u, v))
        faces += [(base, base + 1, base + 2), (base, base + 2, base + 3),
                  (base, base + 2, base + 1), (base, base + 3, base + 2)]          # both sides
        if len(verts) >= MAX_VERTS - 8:
            emit(scene, f"torch{n}.mod", verts, faces, "torch.tex", Light([]), False)
            scene.colours[f"torch{n}.mod"] = [bs.grey(1.0)] * len(verts)
            verts, faces, n = [], [], n + 1
    if verts:
        emit(scene, f"torch{n}.mod", verts, faces, "torch.tex", Light([]), False)
        scene.colours[f"torch{n}.mod"] = [bs.grey(1.0)] * len(verts)


# ------------------------------------------------------------------ the floor
def plan_floor(line, pillars):
    xs = [p[0] for p in line.p]; ys = [p[1] for p in line.p]
    pad = HALFW + WALL_T + 12.0
    x0 = math.floor((min(xs) - pad) / TILE) * TILE
    y0 = math.floor((min(ys) - pad) / TILE) * TILE
    nx = int(math.ceil((max(xs) + pad - x0) / TILE))
    ny = int(math.ceil((max(ys) + pad - y0) / TILE))
    corridor, eligible = set(), set()
    for i in range(nx):
        for j in range(ny):
            cx, cy = x0 + (i + 0.5) * TILE, y0 + (j + 0.5) * TILE
            dist = line.nearest(cx, cy)[0]
            if dist > HALFW:
                continue
            corridor.add((i, j))
            if dist > HALFW - 3.6:                        # keep a margin along each wall
                continue
            d = d_of(line, line.nearest_s(cx, cy))
            if START_ZONE[0] <= d <= START_ZONE[1]:
                continue
            if any(math.hypot(cx - px, cy - py) < 5.5 for px, py in pillars):
                continue
            eligible.add((i, j))
    return x0, y0, nx, ny, corridor, eligible


# Single tiles: at racing speed one 5 m tile is a short hop -- enough to throw a car
# off its line, which is the point. (The pad's height only caps the hop; see
# runtime.md 9.)
SHAPES = [((1, 1), 1.0)]
HEIGHTS = {1: (3.0, 6.0)}


def place_traps(line, x0, y0, eligible, rng):
    """TRAP_COUNT traps, spread round the lap at jittered even spacing after the start
    zone, each within RACE_BAND of the middle and stretched along the local heading."""
    first, last = START_ZONE[1] + 60.0, line.L + START_ZONE[0] - 20.0
    step = (last - first) / TRAP_COUNT
    taken, blocked, clusters = set(), set(), []
    for k in range(TRAP_COUNT):
        for _attempt in range(200):
            s = first + step * (k + rng.uniform(0.15, 0.85))
            lat = rng.uniform(-RACE_BAND, RACE_BAND)
            (x, y, _z), (tx, ty) = line.at(s % line.L)
            px, py = x - ty * lat, y + tx * lat
            i, j = int((px - x0) // TILE), int((py - y0) // TILE)
            r, acc = rng.random(), 0.0
            for (ln, wd), p in SHAPES:
                acc += p
                if r <= acc:
                    break
            w, h = (ln, wd) if abs(tx) >= abs(ty) else (wd, ln)     # long side along travel
            cells = [(i + a, j + b) for a in range(w) for b in range(h)]
            if all(c in eligible and c not in blocked for c in cells):
                lo, hi = HEIGHTS[ln]
                clusters.append((i, j, w, h, round(rng.uniform(lo, hi), 1)))
                taken.update(cells)
                for ci, cj in cells:
                    blocked.update((ci + a, cj + b) for a in (-1, 0, 1) for b in (-1, 0, 1))
                break
        else:
            raise SystemExit(f"could not place trap {k + 1}")
    return clusters, taken


def build_floor(scene, x0, y0, nx, ny, clusters, taken, light, rng):
    def corner(i, j, z=0.0):
        g = bc.game((x0 + i * TILE, y0 + j * TILE, z))
        return g

    def tile_quad(i, j, z, uv):
        u0, v0, u1, v1 = uv
        pts = [corner(i, j, z), corner(i + 1, j, z), corner(i + 1, j + 1, z), corner(i, j + 1, z)]
        return [(p[0], p[1], p[2], u, v) for p, (u, v) in zip(pts, ((u0, v1), (u1, v1), (u1, v0), (u0, v0)))]

    look = {(i, j): rng.choice((0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 3)) for i in range(nx) for j in range(ny)}
    blocks = {}
    for i in range(nx):
        for j in range(ny):
            key = (i // BLOCK, j // BLOCK)
            blocks.setdefault(key, {"floor": [], "cover": []})
            blocks[key]["cover" if (i, j) in taken else "floor"].append((i, j))
    counts = {"floor": 0, "cover": 0, "pads": 0}
    for key, parts in sorted(blocks.items()):
        for kind, cells in parts.items():
            if not cells:
                continue
            verts, faces = [], []
            # A trap tile has its own texture: the plain slab with a pressure plate
            # set into it (hall_art.trap_tile) -- a tell for anyone looking closely.
            e = 0.5 / 64
            for i, j in cells:
                base = len(verts)
                uv = ha.atlas_uv(look[(i, j)]) if kind == "floor" else (e, e, 1 - e, 1 - e)
                verts += tile_quad(i, j, 0.0, uv)
                for tri in ((base, base + 1, base + 2), (base, base + 2, base + 3)):
                    faces.append(BT.orient(verts, tri, np.array([0.0, 1.0, 0.0])))
            emit(scene, f"{kind[0]}{key[0]:02d}{key[1]:02d}.mod", verts, faces,
                 "tile.tex" if kind == "floor" else "trap.tex", light, kind == "floor")
            counts[kind] += 1
    # the pads: one invisible quad per cluster, grouped by block
    pads = {}
    for i, j, w, h, hgt in clusters:
        pads.setdefault((i // BLOCK, j // BLOCK), []).append((i, j, w, h, hgt))
    for key, group in sorted(pads.items()):
        verts, faces = [], []
        for i, j, w, h, hgt in group:
            base = len(verts)
            pts = [corner(i, j, hgt), corner(i + w, j, hgt), corner(i + w, j + h, hgt), corner(i, j + h, hgt)]
            verts += [(p[0], p[1], p[2], u, v) for p, (u, v) in zip(pts, ((0, 1), (1, 1), (1, 0), (0, 0)))]
            for tri in ((base, base + 1, base + 2), (base, base + 2, base + 3)):
                faces.append(BT.orient(verts, tri, np.array([0.0, 1.0, 0.0])))
        emit(scene, f"pad{key[0]:02d}{key[1]:02d}.mod", verts, faces, "clear.tex", light, True)
        counts["pads"] += 1
    return counts


# ------------------------------------------------------------------ idols
def add_idols(scene, line, x0, y0, eligible, taken, rng):
    free = sorted(c for c in eligible if c not in taken
                  and not any((c[0] + a, c[1] + b) in taken for a in (-1, 0, 1) for b in (-1, 0, 1)))
    rng.shuffle(free)
    placed = []
    for i, j in free[:10]:
        cx, cy = x0 + (i + 0.5) * TILE, y0 + (j + 0.5) * TILE
        s = line.nearest_s(cx, cy)
        (_x, _y, _z), (tx, ty) = line.at(s)
        yaw = bc.yaw_facing_traffic(tx, ty)
        name = f"idol{len(placed):02d}.mod"
        v, f = BT.lathe(BT.IDOL, 8)
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, "gold.tex")
        scene.wobbles.append(trackgen.Wobble(position=(cx, cy, 0.0), mesh=name, radius=0.42, height=1.6))
        placed.append((cx, cy))
    # the prize: a great golden idol in the sealed sanctum, reachable only by flying in
    cx, cy = STRAIGHT / 2 - 5.0, RADIUS
    big = [(y * 2.2, r * 2.2) for y, r in BT.IDOL]
    v, f = BT.lathe(big, 10)
    scene.meshes["idolbig.mod"] = bt.to_facing(turn(v, 0.0), f, "gold.tex")
    scene.wobbles.append(trackgen.Wobble(position=(cx, cy, 0.0), mesh="idolbig.mod", radius=0.92, height=3.5))
    return placed


# ------------------------------------------------------------------ build
def main():
    rng = random.Random(SEED)
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=HALFW)
    scene.grid = [side_pt(line, -10.0 - 10.0 * (k // 2), 6.0 if k % 2 else -6.0) + (0.0,) for k in range(8)]

    torches = [side_pt(line, s, lat * 0.9) for s, lat in torch_spots(line)]
    light = Light(torches)
    walls = []
    add_walls(scene, line, walls, light)
    pillars = add_pillars(scene, line, walls, light)
    add_gate(scene, line, walls, light)
    add_torches(scene, line, light)
    scene.walls = walls

    x0, y0, nx, ny, corridor, eligible = plan_floor(line, pillars)
    clusters, taken = place_traps(line, x0, y0, eligible, rng)
    counts = build_floor(scene, x0, y0, nx, ny, clusters, taken, light, rng)
    idols = add_idols(scene, line, x0, y0, eligible, taken, rng)

    trackgen.add_ground(scene, texture="vault.tex", margin=400.0, drop=1.0)
    scene.colours["ground.mod"] = [bs.grey(0.5)] * 4

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn) + len(scene.wobbles)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    sizes = {}
    for _i, _j, w, h, _hg in clusters:
        sizes[w * h] = sizes.get(w * h, 0) + 1
    print(f"lap {line.L:.0f} m; corridor {2 * HALFW:.0f} m wide; floor {nx}x{ny} tiles of {TILE:g} m "
          f"({len(corridor)} in the corridor)")
    print(f"traps: {len(clusters)} clusters over {len(taken)} tiles ({100 * len(taken) / len(corridor):.1f}% of the "
          f"corridor) -- " + ", ".join(f"{n} x {k}-tile" for k, n in sorted(sizes.items())) +
          f"; heights {min(c[4] for c in clusters):g}-{max(c[4] for c in clusters):g} m")
    print(f"pillars {len(pillars)}; torches {len(torches)}; idols {len(idols)} + the sanctum idol; "
          f"solid wall faces {len(walls)}; floor meshes {counts}")
    print(f"surfaces {surfaces} (budget {SURFACE_BUDGET}); largest chunk {biggest} verts; collision triangles "
          f"{collide} (budget {COLLISION_BUDGET}); textures {len(wanted)} + 4 sky")
    if surfaces > SURFACE_BUDGET or biggest > MAX_VERTS or collide > COLLISION_BUDGET:
        raise SystemExit("over budget")

    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True,
                              # to the walls and no further: a wider corridor lets a reset leave a
                              # car outside them (seen in the arena)
                              corridor=HALFW + 1.0)
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
    for s in (line.L - 30.0, 150.0, 330.0, 520.0, 760.0, 1000.0):
        (x, y, _z), (tx, ty) = line.at(s % line.L)
        p = (x - ty * -(HALFW - 3), y + tx * -(HALFW - 3), 6.0)
        (ax, ay, _az), _t = line.at((s + 70.0) % line.L)
        gpos, gtgt = bc.game(p), bc.game((ax, ay, 1.5))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)

    by = {e.name.lower(): e for e in archive.read(OUT)}
    for name in sorted(wanted) + list(sky.TILES):
        tex.parse(envelope.build(by[name].tag, by[name].version, by[name].payload))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    ids = sorted(q.id for q in so.primitives if q.id >= 0)
    boxes = sum(1 for q in so.primitives if q.type == sol.BOX)
    if ids != list(range(len(idols) + 1)) or boxes != len(walls):
        raise SystemExit(f"sol wrong: ids {ids[:3]}.. boxes {boxes} vs {len(walls)}")
    print(f"textures all decode; {boxes} wall boxes; wobbles 0..{ids[-1]}; {len(cams)} cameras; "
          f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")
    return line, clusters, x0, y0


if __name__ == "__main__":
    main()
