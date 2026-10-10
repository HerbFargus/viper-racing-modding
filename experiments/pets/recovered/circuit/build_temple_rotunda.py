"""Temple rotunda: the arena as a circle, 360 m across, its outer 30 m banked up to the wall.

FLOOR. Concentric rings of 5 m-deep stone tiles around a carved sun medallion, like a
calendar stone. A ring's tile count doubles as the radius grows (16 -> 256) so tiles
stay near 5 m across; where it doubles, the tiles just inside the join carry an extra
corner at each new division, so both sides of the join share exactly the same vertices
-- a crack there would be a hole in the collision. From r = 150 m the rings rise to
12 m at r = 180 m (steepening to ~33 degrees), and the wall stands on top of the bank.

CORRIDOR. The racing loop is a circle at half the wall's radius, so one corridor
width -- the loop's radius plus the wall -- covers everything from the centre out to
the wall's outer face and nothing past it. The floor ends at that face; beyond it is a
pit, off track, so a reset brings the car back in.

ORIGIN. The rotunda is centred off the world origin: a circular line centred ON it
leaves the origin on every segment's boundary, and the engine's race-start lookup
comes back empty (ili.origin_is_claimed; trackbuild refuses such a line).

Everything else is the arena's: massive columns, stone-head totems (all of them
knockable), golden idols and the great idol on the medallion, twenty hidden
traps on the flat floor with their pressure-plate tell, torchlight baked in, the
painted temple sky. Solo only.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_temple_hall as H  # noqa: E402
import temple_art as ta  # noqa: E402
from build_sticks import turn  # noqa: E402
from vrmod import archive, camtab, envelope, sky, sol, tex, trackbuild, trackgen  # noqa: E402
from vrmod.trackgen import GRASS, NO_COLLISION, ROAD  # noqa: E402

BT, L, bc, bs, bt, ha = H.BT, H.L, H.bc, H.bs, H.bt, H.ha
OUT = HERE / "temple_rotunda.trk"
SLOT = "dundas"
SEED = 1989                                        # The Last Crusade
CX, CY = 13.7, 7.3                                 # centre, off the world origin
R_MED, R_BANK, R_WALL, WALL_T = 10.0, 150.0, 180.0, 2.0
BANK_H = 12.0
RING = 5.0
R_LINE = (R_WALL + WALL_T) / 2                     # 91 m: its corridor spans centre to outer face
CORRIDOR = R_WALL + WALL_T - R_LINE                # 91 m
COLUMN_HALF, COLUMN_H = 4.0, 30.0
COLUMNS = [(60.0, a) for a in range(0, 360, 45)] + [(120.0, a + 22.5) for a in range(0, 360, 45)]
TOTEM_SCALE = 4.0
TOTEMS = [(138.0, a) for a in range(0, 360, 45)]   # at the foot of the bank, facing the middle
KNOCKABLE = set(range(len(TOTEMS)))               # every totem (was the four nearest the start)
TRAP_COUNT, TORCH_EVERY = 20, 25.0


def P(r, a_deg, z=0.0):
    a = math.radians(a_deg)
    return (CX + r * math.cos(a), CY + r * math.sin(a), z)


def floor_z(r):
    if r <= R_BANK:
        return 0.0
    if r >= R_WALL:
        return BANK_H
    return BANK_H * ((r - R_BANK) / (R_WALL - R_BANK)) ** 1.6


def ring_edges():
    edges = [R_MED]
    while edges[-1] < R_WALL - 1e-6:
        edges.append(edges[-1] + RING)
    return edges + [R_WALL + WALL_T]               # the last ring runs under the wall, flat on top


def ring_count(r_inner):
    n = 16
    while 2 * math.pi * r_inner / n > 7.5:
        n *= 2
    return n


def medallion():
    """A sun carved into the middle of the floor: rings, rays and a face."""
    s = 256
    n = ta.tile_noise(s, 8, 4, 0.55, 701)
    base = ta.colourise(n, (132, 110, 78), (176, 150, 108))
    img = Image.fromarray(np.clip(base, 20, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    c, dark = s / 2, (88, 72, 50)
    for r, w in ((0.47, 4), (0.40, 3), (0.22, 3)):
        d.ellipse([c - r * s, c - r * s, c + r * s, c + r * s], outline=dark, width=w)
    for k in range(16):
        a = 2 * math.pi * k / 16
        r0, r1 = 0.24 * s, (0.38 if k % 2 else 0.33) * s
        d.polygon([(c + math.cos(a - 0.08) * r0, c + math.sin(a - 0.08) * r0), (c + math.cos(a) * r1, c + math.sin(a) * r1),
                   (c + math.cos(a + 0.08) * r0, c + math.sin(a + 0.08) * r0)], fill=dark)
    for k in range(32):                                   # glyph band between the outer rings
        a = 2 * math.pi * k / 32
        x, y = c + math.cos(a) * 0.435 * s, c + math.sin(a) * 0.435 * s
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=dark)
    for ex in (-0.07, 0.07):
        d.ellipse([c + ex * s - 6, c - 0.06 * s - 5, c + ex * s + 6, c - 0.06 * s + 5], fill=dark)
    d.arc([c - 0.09 * s, c - 0.02 * s, c + 0.09 * s, c + 0.12 * s], 20, 160, fill=dark, width=3)
    return ta.to_img(np.array(img).astype(float))


# ------------------------------------------------------------------ floor
def plan_tiles():
    """Every floor tile as (key, polygon in (r, angle) corners). Keys (ring, index)."""
    edges = ring_edges()
    tiles = []
    for k, (r0, r1) in enumerate(zip(edges, edges[1:])):
        n = ring_count(r0)
        n_out = ring_count(r1) if k + 2 < len(edges) else n
        split = n_out // n                                  # 1, or 2 where the next ring doubles
        for i in range(n):
            a0, a1 = 360.0 * i / n, 360.0 * (i + 1) / n
            outer = [(r1, a0 + (a1 - a0) * j / split) for j in range(split + 1)]
            poly = [(r0, a0), (r0, a1)] + list(reversed(outer))    # inner edge, then outer back
            tiles.append(((k, i), poly, split == 1))
    return tiles


def ring_of(key):
    return key[0]


def tile_centre(poly):
    r = sum(p[0] for p in poly) / len(poly)
    a0, a1 = poly[0][1], poly[1][1]
    return r, (a0 + a1) / 2


def place_traps(tiles, rng):
    spawn_a = 0.0
    col_xy = [P(r, a)[:2] for r, a in COLUMNS]
    tot_xy = [P(r, a)[:2] for r, a in TOTEMS]
    cand = []
    for key, poly, simple in tiles:
        if not simple:
            continue
        r, a = tile_centre(poly)
        if r < 20 or r > R_BANK - 6:
            continue
        x, y, _ = P(r, a)
        if any(math.hypot(x - cx, y - cy) < COLUMN_HALF + 7 for cx, cy in col_xy):
            continue
        if any(math.hypot(x - cx, y - cy) < 8 for cx, cy in tot_xy):
            continue
        sx, sy, _ = P(R_LINE, spawn_a)
        if math.hypot(x - sx, y - sy) < 60:
            continue
        cand.append((key, poly))
    rng.shuffle(cand)
    chosen, used = [], []
    for key, poly in cand:
        x, y, _ = P(*tile_centre(poly))
        if any(math.hypot(x - ux, y - uy) < 30 for ux, uy in used):
            continue
        chosen.append((key, poly, round(rng.uniform(3.0, 6.0), 1)))
        used.append((x, y))
        if len(chosen) >= TRAP_COUNT:
            break
    return chosen


def build_floor(scene, tiles, traps, light, rng):
    trap_keys = {k for k, _p, _h in traps}
    look = {key: rng.choice((0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 3)) for key, _p, _s in tiles}
    buckets = {}
    for key, poly, simple in tiles:
        r, a = tile_centre(poly)
        band = 0 if r < 40 else 1 if r < 80 else 2 if r < 120 else 3 if r < R_BANK else 4
        sector = int(a // 22.5)
        kind = "cover" if key in trap_keys else "floor"
        buckets.setdefault((kind, band, sector), []).append((key, poly))
    counts = {"floor": 0, "cover": 0}
    for (kind, band, sector), group in sorted(buckets.items()):
        verts, faces = [], []
        for key, poly in group:
            if kind == "floor":
                u0, v0, u1, v1 = ha.atlas_uv(look[key])
            else:
                e = 0.5 / 64
                u0, v0, u1, v1 = e, e, 1 - e, 1 - e
            n_out = len(poly) - 2
            uvs = [(u0, v1), (u1, v1)] + [(u1 - (u1 - u0) * j / (n_out - 1), v0) for j in range(n_out)]
            base = len(verts)
            for (r, a), (u, v) in zip(poly, uvs):
                g = bc.game(P(r, a, floor_z(r)))
                verts.append((g[0], g[1], g[2], u, v))
            for j in range(1, len(poly) - 1):              # fan from the first inner corner
                faces.append(BT.orient(verts, (base, base + j, base + j + 1), np.array([0.0, 1.0, 0.0])))
        name = f"{kind[0]}{band}{sector:02d}.mod"
        H.emit(scene, name, verts, faces, "tile.tex" if kind == "floor" else "trap.tex", light, kind == "floor")
        counts[kind] += 1
    # the medallion: a fan of 16 wedges, planar-mapped
    verts, faces = [], []
    gc = bc.game(P(0, 0, 0.0))
    verts.append((gc[0], gc[1], gc[2], 0.5, 0.5))
    n = ring_count(R_MED)
    for i in range(n):
        a = 360.0 * i / n
        g = bc.game(P(R_MED, a, 0.0))
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
        verts.append((g[0], g[1], g[2], 0.5 - 0.5 * ca, 0.5 - 0.5 * sa))       # u flipped: left-handed draw
    for i in range(n):
        faces.append(BT.orient(verts, (0, 1 + i, 1 + (i + 1) % n), np.array([0.0, 1.0, 0.0])))
    H.emit(scene, "medal.mod", verts, faces, "medal.tex", light, True)
    # the pads, one invisible quad per trap
    verts, faces = [], []
    for key, poly, hgt in traps:
        base = len(verts)
        for (r, a), (u, v) in zip(poly, ((0, 1), (1, 1), (1, 0), (0, 0))):
            g = bc.game(P(r, a, hgt))
            verts.append((g[0], g[1], g[2], u, v))
        for tri in ((base, base + 1, base + 2), (base, base + 2, base + 3)):
            faces.append(BT.orient(verts, tri, np.array([0.0, 1.0, 0.0])))
    H.emit(scene, "pads.mod", verts, faces, "clear.tex", light, True)
    return counts


# ------------------------------------------------------------------ walls, columns, totems, torches
def add_wall(scene, walls, light, torches):
    n = ring_count(R_WALL)
    verts, faces, m = [], [], 0
    for i in range(n):
        a0, a1 = 360.0 * i / n, 360.0 * (i + 1) / n
        pa, pb = P(R_WALL + WALL_T / 2, a0), P(R_WALL + WALL_T / 2, a1)
        L_ = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
        along = ((pb[0] - pa[0]) / L_, (pb[1] - pa[1]) / L_)
        v, f = BT.game_box(scene, None, ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2), along, L_ / 2 + 0.3,
                           WALL_T / 2, BANK_H - 0.3, BANK_H + H.WALL_DRAW, "carve.tex", tile=4.0)
        faces += [(p + len(verts), q + len(verts), r + len(verts)) for p, q, r in f]
        verts += v
        fa, fb = P(R_WALL, a0), P(R_WALL, a1)
        walls.append([(fa[0], fa[1], BANK_H), (fb[0], fb[1], BANK_H), (fb[0], fb[1], BANK_H + H.WALL_SOLID),
                      (fa[0], fa[1], BANK_H + H.WALL_SOLID)])
        if len(verts) >= H.MAX_VERTS - 40:
            H.emit(scene, f"wall{m}.mod", verts, faces, "carve.tex", light, False)
            verts, faces, m = [], [], m + 1
    if verts:
        H.emit(scene, f"wall{m}.mod", verts, faces, "carve.tex", light, False)
    step = TORCH_EVERY / (2 * math.pi * R_WALL) * 360.0
    a = 0.0
    while a < 360.0 - 1e-6:
        p = P(R_WALL - 0.05, a, BANK_H)
        ta_ = (-math.sin(math.radians(a)), math.cos(math.radians(a)))
        torches.append(((p[0], p[1]), ta_, BANK_H))
        a += step


def add_columns(scene, walls, light, torches):
    verts, faces = [], []
    for r, a in COLUMNS:
        cx, cy, _ = P(r, a)
        for half, z0, z1 in ((COLUMN_HALF + 1.5, -0.3, 1.5), (COLUMN_HALF, 1.5, COLUMN_H - 2.0),
                             (COLUMN_HALF + 1.2, COLUMN_H - 2.0, COLUMN_H)):
            v, f = BT.game_box(scene, None, (cx, cy), (1.0, 0.0), half, half, z0, z1, "carve.tex", tile=8.0)
            faces += [(p + len(verts), q + len(verts), s + len(verts)) for p, q, s in f]
            verts += v
        H.solid_box(walls, (cx, cy), (1.0, 0.0), COLUMN_HALF + 1.5, COLUMN_HALF + 1.5)
        for fx, fy, tx, ty in ((1, 0, 0, 1), (-1, 0, 0, -1), (0, 1, -1, 0), (0, -1, 1, 0)):
            torches.append(((cx + fx * (COLUMN_HALF + 0.05), cy + fy * (COLUMN_HALF + 0.05)), (tx, ty), 0.0))
    H.emit(scene, "columns.mod", verts, faces, "carve.tex", light, False)


def add_torch_meshes(scene, torches):
    verts, faces = [], []
    for (cx, cy), (tx, ty), z0 in torches:
        base = len(verts)
        for dx, dz, u, v in ((-0.55, 2.6, 0, 1), (0.55, 2.6, 1, 1), (0.55, 4.4, 1, 0), (-0.55, 4.4, 0, 0)):
            g = bc.game((cx + tx * dx, cy + ty * dx, z0 + dz))
            verts.append((g[0], g[1], g[2], u, v))
        faces += [(base, base + 1, base + 2), (base, base + 2, base + 3),
                  (base, base + 2, base + 1), (base, base + 3, base + 2)]
    k, n = 0, 0
    while k < len(verts):
        vv = verts[k:k + 1480]
        ff = [(a - k, b - k, c - k) for a, b, c in faces if k <= a < k + 1480]
        H.emit(scene, f"torch{n}.mod", vv, ff, "torch.tex", H.Light([]), False)
        scene.colours[f"torch{n}.mod"] = [bs.grey(1.0)] * len(vv)
        k, n = k + 1480, n + 1


def add_totems(scene, walls, light):
    verts, faces = [], []
    w, d, h = 1.4 * TOTEM_SCALE, 1.1 * TOTEM_SCALE, 2.2 * TOTEM_SCALE
    for n, (r, a) in enumerate(TOTEMS):
        cx, cy, _ = P(r, a)
        fx, fy = -math.cos(math.radians(a)), -math.sin(math.radians(a))      # facing the middle
        hv, hf = BT.stone_head_mesh(w, d, h)
        if n in KNOCKABLE:
            name = f"totem{n}.mod"
            scene.meshes[name] = bt.to_facing(turn(hv, bc.yaw_facing_traffic(-fx, -fy)), hf, "head.tex")
            scene.wobbles.append(trackgen.Wobble(position=(cx, cy, 0.0), mesh=name, radius=w / 2, height=h))
            continue
        rx, ry = fy, -fx
        base = len(verts)
        for x, y, z, u, v in hv:
            g = bc.game((cx + rx * x + fx * z, cy + ry * x + fy * z, y))
            verts.append((g[0], g[1], g[2], u, v))
        mid = np.array(bc.game((cx, cy, h / 2)))
        for tri in hf:
            t = tuple(i + base for i in tri)
            cen = np.mean([verts[i][:3] for i in t], axis=0)
            faces.append(BT.orient(verts, t, cen - mid))
        H.solid_box(walls, (cx, cy), (fx, fy), d / 2, w / 2)
    if verts:                                          # none left once every totem is a wobble
        H.emit(scene, "totems.mod", verts, faces, "head.tex", light, False)


# ------------------------------------------------------------------ build
def centreline():
    n = int(round(2 * math.pi * R_LINE / 10.0))
    return [P(R_LINE, 360.0 * k / n) for k in range(n)]      # anticlockwise


def main():
    rng = random.Random(SEED)
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=R_LINE / 2.5 + 1.0)
    scene.grid = [H.side_pt(line, -10.0 - 10.0 * (k // 2), 6.0 if k % 2 else -6.0) + (0.0,) for k in range(8)]

    torches, walls = [], []
    probe = trackgen.TrackScene(centreline=[])
    add_wall(probe, [], H.Light([]), torches)
    add_columns(probe, [], H.Light([]), torches)
    light = H.Light([(x, y) for (x, y), _t, _z in torches])
    torches = []
    add_wall(scene, walls, light, torches)
    add_columns(scene, walls, light, torches)
    add_torch_meshes(scene, torches)
    add_totems(scene, walls, light)
    scene.walls = walls

    tiles = plan_tiles()
    traps = place_traps(tiles, rng)
    counts = build_floor(scene, tiles, traps, light, rng)

    trap_keys = {k for k, _p, _h in traps}
    free = [(key, poly) for key, poly, simple in tiles
            if simple and key not in trap_keys and 30 < tile_centre(poly)[0] < R_BANK - 10]
    rng.shuffle(free)
    col_xy = [P(r, a)[:2] for r, a in COLUMNS] + [P(r, a)[:2] for r, a in TOTEMS]
    idols = 0
    for key, poly in free:
        x, y, _ = P(*tile_centre(poly))
        if any(math.hypot(x - cx, y - cy) < 9 for cx, cy in col_xy):
            continue
        v, f = BT.lathe(BT.IDOL, 8)
        scene.meshes[f"idol{idols:02d}.mod"] = bt.to_facing(turn(v, rng.uniform(0, 360)), f, "gold.tex")
        scene.wobbles.append(trackgen.Wobble(position=(x, y, 0.0), mesh=f"idol{idols:02d}.mod", radius=0.42, height=1.6))
        idols += 1
        if idols == 10:
            break
    big = [(y * 2.2, r * 2.2) for y, r in BT.IDOL]
    v, f = BT.lathe(big, 10)
    scene.meshes["idolbig.mod"] = bt.to_facing(turn(v, 0.0), f, "gold.tex")
    scene.wobbles.append(trackgen.Wobble(position=(CX, CY, 0.0), mesh="idolbig.mod", radius=0.92, height=3.5))

    trackgen.add_ground(scene, texture="vault.tex", margin=400.0, drop=40.0)
    scene.colours["ground.mod"] = [bs.grey(0.5)] * 4

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn) + len(scene.wobbles)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables if o.name in scene.meshes)
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    print(f"rotunda {2 * R_WALL:.0f} m across, bank {R_BANK:.0f}-{R_WALL:.0f} m up to {BANK_H:g} m; {len(tiles)} floor "
          f"tiles in rings of {ring_count(R_MED)}-{ring_count(R_WALL)}; loop r {R_LINE:.0f} m ({line.L:.0f} m), "
          f"corridor {CORRIDOR:.0f} m")
    print(f"columns {len(COLUMNS)}; totems {len(TOTEMS)} ({len(KNOCKABLE)} knockable); torches {len(torches)}; "
          f"traps {len(traps)}; idols {idols} + the great idol; solid faces {len(walls)}; floor meshes {counts}")
    print(f"surfaces {surfaces} (budget {H.SURFACE_BUDGET}); largest chunk {biggest} verts; collision triangles "
          f"{collide} (budget {H.COLLISION_BUDGET}); textures {len(wanted)} + 4 sky")
    if surfaces > H.SURFACE_BUDGET or biggest > H.MAX_VERTS or collide > H.COLLISION_BUDGET:
        raise SystemExit("over budget")

    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True, corridor=CORRIDOR)
    print(f"assembled: {res.summary()}")
    gen = dict(ha.ALL)
    gen["clear.tex"] = (L.clear_texture, "colorkey")
    gen["medal.tex"] = (medallion, "opaque")
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
    for a in (20.0, 110.0, 200.0, 290.0):
        gpos = bc.game(P(R_WALL - 8.0, a, BANK_H + 6.0))
        gtgt = bc.game(P(R_LINE, a + 50.0, 1.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)

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
