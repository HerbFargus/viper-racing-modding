"""The Ballroom: how many objects can a track spawn before the game falls over?

A white room -- white floor, white walls, white sky -- with a stadium-loop race and a
field of multicoloured beach balls (`obj obstacle ball`, mass 4, so cars knock them
flying). The game drops every obstacle 4 m at race start, so it rains beach balls.

THE LIMIT IT PROBES, read from race.exe: PhysTaskBegin (0x426850) gives the physics
objects room for exactly 512 pointers (MemAlloc(0x800)) and fills it in a loop with no
bounds check -- every car, checkpoint and obstacle goes in it. The world and graphics
lists allow 1,024 each and ASSERT past that ("Too many (w)objects allocated"). So with
8 cars and 4 checkpoints the physics list should overflow somewhere past ~500 balls,
silently corrupting the heap rather than failing cleanly. One .tra per count brackets it.

Writes Balls<N>.tra into the test install's Data folder for each count on the ladder.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "circuit"))
sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
import build_circuit as bc  # noqa: E402
from vrmod import archive, camtab, envelope, mod, obt as obt_mod, sky, tex, track, trackbuild, trackgen, trackmap  # noqa: E402
from vrmod.trackgen import GRASS, NO_COLLISION, ROAD  # noqa: E402

DATA = Path(r"C:\Users\seamus\Desktop\claude-code\game-files\installs\v1.0-RC")
BASE = HERE / "ballroom_base.trk"
SLOT = "heaven"
SEED = 512
LADDER = [100, 250, 400, 480, 490, 500, 510, 520, 600, 1000]

# the loop: a stadium, straights along x. Slid 3.7 m along x so no waypoint sits at x = 0
# (a waypoint there puts the world origin on a segment boundary and the race crashes).
SL, RAD, SHIFT = 110.0, 55.0, 3.7
HALF = 9.0                                   # the painted road's half-width
CORRIDOR = 30.0                              # track.ild field 5: off the path beyond 15 m
ROOM_X, ROOM_Y = SL + RAD + 45.0, RAD + 45.0  # the room's half-extents: 420 x 200 m
WALL_H, WALL_SOLID = 12.0, 6.0
MAX_VERTS = 990
BALL_R, BALL_MASS = 0.8, 4.0                 # 1.6 m beach balls; mass 4 floats and bounces
PALETTES = [[(230, 40, 40), (250, 150, 20), (250, 220, 40), (60, 180, 70), (40, 110, 230), (150, 60, 200)],
            [(240, 60, 150), (40, 200, 220), (250, 220, 40), (240, 90, 30), (90, 200, 60), (70, 70, 220)],
            [(250, 250, 250), (230, 40, 40), (250, 250, 250), (40, 110, 230), (250, 250, 250), (250, 200, 30)],
            [(120, 220, 60), (250, 120, 180), (60, 160, 240), (250, 170, 40), (170, 90, 220), (40, 200, 160)]]


# ------------------------------------------------------------------ geometry helpers
class Batch:
    """Triangles for one texture, chunked under MAX_VERTS; grey baked into vertex colours."""

    def __init__(self, scene, stem, texture, solid, code=ROAD):
        self.scene, self.stem, self.texture, self.solid, self.code = scene, stem, texture, solid, code
        self.v, self.f, self.c, self.n = [], [], [], 0

    def tri(self, P, uv, grey, up=True):
        g = [bc.game(tuple(p)) for p in P]
        a, b, c = (np.array(q) for q in g)
        want = np.array([0.0, 1.0, 0.0]) if up is True else np.array(bc.game(tuple(up))) - (a + b + c) / 3
        order = [0, 1, 2] if np.dot(np.cross(b - a, c - a), want) >= 0 else [0, 2, 1]
        if len(self.v) + 3 > MAX_VERTS:
            self.flush()
        base = len(self.v)
        for k in order:
            self.v.append(mod.Vertex(*g[k], 0.0, 1.0, 0.0, *uv[k]))
            gv = int(max(40, min(255, grey * 255)))
            self.c.append(bytes([gv, gv, gv, 0xFF]))
        self.f.append((base, base + 1, base + 2))

    def quad(self, P, grey, up=True):
        uv = [(0.02, 0.02), (0.98, 0.02), (0.98, 0.98), (0.02, 0.98)]
        self.tri([P[0], P[1], P[2]], [uv[0], uv[1], uv[2]], grey, up)
        self.tri([P[0], P[2], P[3]], [uv[0], uv[2], uv[3]], grey, up)

    def flush(self):
        if not self.f:
            return
        name = f"{self.stem}{self.n}.mod"
        self.scene.meshes[name] = mod.Mesh(vertices=self.v, faces=self.f, materials=[mod.Material(
            name=self.texture, vertex_start=0, vertex_end=len(self.v), face_start=0, face_end=len(self.f))])
        self.scene.colours[name] = self.c
        if self.solid:
            self.scene.driveables.append(trackgen.SceneObject(name, self.code))
        else:
            self.scene.scenery.append(trackgen.SceneObject(name, GRASS, NO_COLLISION))
        self.v, self.f, self.c, self.n = [], [], [], self.n + 1


def centreline(step=10.0):
    """Anticlockwise stadium: bottom straight east, right bend, top straight west, left bend."""
    pts = []
    n_s = int(round(2 * SL / step))
    n_b = int(round(math.pi * RAD / step))
    for k in range(n_s):
        pts.append((-SL + 2 * SL * k / n_s + SHIFT, -RAD, 0.0))
    for k in range(n_b):
        a = -math.pi / 2 + math.pi * k / n_b
        pts.append((SL + RAD * math.cos(a) + SHIFT, RAD * math.sin(a), 0.0))
    for k in range(n_s):
        pts.append((SL - 2 * SL * k / n_s + SHIFT, RAD, 0.0))
    for k in range(n_b):
        a = math.pi / 2 + math.pi * k / n_b
        pts.append((-SL + RAD * math.cos(a) + SHIFT, RAD * math.sin(a), 0.0))
    return pts


# ------------------------------------------------------------------ art
def white(size=32):
    return Image.new("RGB", (size, size), (255, 255, 255))


def grey(size=32):
    return Image.new("RGB", (size, size), (175, 178, 184))


def beach_ball(palette, size=128):
    """Six vertical gores round the ball (u), white caps at the poles (v)."""
    a = np.zeros((size, size, 3), np.uint8)
    for j in range(size):
        a[:, j] = palette[(j * 6) // size]
    cap = int(size * 0.13)
    a[:cap], a[-cap:] = 250, 250
    return Image.fromarray(a)


TEXTURES = {"white.tex": white, "grey.tex": grey}
TEXTURES.update({f"bball{k}.tex": (lambda p=p: beach_ball(p)) for k, p in enumerate(PALETTES)})


def ball_mesh(k, rings=8, segs=12, drop=0.0, texture=None):
    """A UV sphere at its own origin, in the game frame (y up), wound outward, wearing
    `texture` (bball<k>.tex by default). v runs 0 at the top pole to 1 at the bottom.

    drop > 0 adds one vertex no face uses, straight below the ball. parse_obstacle places
    an obstacle at ground - (the mesh's lowest y) + 4 m, and mrModelGetExtents reads every
    vertex, used or not -- so that vertex lifts the spawn by (drop - 4) m. The collision
    sphere's radius is half the Z extent, which it leaves alone."""
    verts, faces = [], []
    grid = {}
    for i in range(rings + 1):
        th = math.pi * i / rings
        for j in range(segs + 1):
            ph = 2 * math.pi * j / segs
            n = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
            grid[i, j] = len(verts)
            verts.append(mod.Vertex(BALL_R * n[0], BALL_R * n[1], BALL_R * n[2], *n,
                                    min(0.98, max(0.02, j / segs)), min(0.98, max(0.02, i / rings))))
    for i in range(rings):
        for j in range(segs):
            q = [grid[i, j], grid[i, j + 1], grid[i + 1, j + 1], grid[i + 1, j]]
            for tri in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
                P = [np.array((verts[t].x, verts[t].y, verts[t].z)) for t in tri]
                cr = np.cross(P[1] - P[0], P[2] - P[0])
                if np.linalg.norm(cr) < 1e-9:
                    continue                                          # degenerate at the poles
                faces.append(tri if np.dot(cr, sum(P)) > 0 else (tri[0], tri[2], tri[1]))
    if drop > 4.0:
        verts.append(mod.Vertex(0.0, -(BALL_R + drop - 4.0), 0.0, 0.0, -1.0, 0.0, 0.5, 0.5))
    return mod.Mesh(vertices=verts, faces=faces, materials=[mod.Material(
        name=texture or f"bball{k}.tex", vertex_start=0, vertex_end=len(verts), face_start=0,
        face_end=len(faces))])


# ------------------------------------------------------------------ the room
def build_scene():
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=HALF + 2.0)
    grid = []
    for k in range(8):
        (gx, gy, _gz), (tx, ty) = line.at(line.L - 16.0 - 10.0 * (k // 2))
        lat = 4.0 if k % 2 else -4.0
        grid.append((gx - ty * lat, gy + tx * lat, 0.0))
    scene.grid = grid

    floor = Batch(scene, "floor", "white.tex", solid=True)
    cell = 20.0
    xs = np.arange(-ROOM_X, ROOM_X + 0.1, cell)
    ys = np.arange(-ROOM_Y, ROOM_Y + 0.1, cell)
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            floor.quad([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)], 1.0)
    floor.flush()

    lines = Batch(scene, "rdline", "grey.tex", solid=False)       # painted edges, drawn only
    L = line.L
    for side in (-1, 1):
        s = 0.0
        while s < L:
            s1 = min(L, s + 5.0)
            (ax, ay, _), (atx, aty) = line.at(s)
            (bx_, by_, _), (btx, bty) = line.at(s1 % L)
            quad = []
            for (px, py, tx, ty) in ((ax, ay, atx, aty), (bx_, by_, btx, bty)):
                for lat in (side * (HALF - 0.2), side * (HALF + 0.2)):
                    quad.append((px - ty * lat, py + tx * lat, 0.04))
            lines.quad([quad[0], quad[2], quad[3], quad[1]], 1.0)
            s = s1
    (sx, sy, _), (tx, ty) = line.at(0.0)                           # start/finish band
    band = [(sx - ty * lat + tx * d, sy + tx * lat + ty * d, 0.04) for lat, d in
            ((-HALF, -0.6), (-HALF, 0.6), (HALF, 0.6), (HALF, -0.6))]
    lines.quad(band, 1.0)
    lines.flush()

    walls = Batch(scene, "wall", "white.tex", solid=False)       # white walls, faces inward
    scene.walls = []
    corners = [(-ROOM_X, -ROOM_Y), (ROOM_X, -ROOM_Y), (ROOM_X, ROOM_Y), (-ROOM_X, ROOM_Y)]
    for (ax, ay), (bx_, by_) in zip(corners, corners[1:] + corners[:1]):
        n = max(1, int(math.hypot(bx_ - ax, by_ - ay) // 20))
        for k in range(n):
            p = (ax + (bx_ - ax) * k / n, ay + (by_ - ay) * k / n)
            q = (ax + (bx_ - ax) * (k + 1) / n, ay + (by_ - ay) * (k + 1) / n)
            walls.quad([(p[0], p[1], 0), (q[0], q[1], 0), (q[0], q[1], WALL_H), (p[0], p[1], WALL_H)], 0.93,
                       up=(0.0, 0.0, WALL_H / 2))
            scene.walls.append([(p[0], p[1], 0.0), (q[0], q[1], 0.0), (q[0], q[1], WALL_SOLID), (p[0], p[1], WALL_SOLID)])
    walls.flush()

    trackgen.add_ground(scene, texture="white.tex", margin=600.0, drop=0.3)   # past the walls: still white
    scene.colours["ground.mod"] = [bytes([255, 255, 255, 255])] * 4

    # each ball texture lives only on the obstacle meshes, and a track ships only what its
    # drawn meshes use -- so one buried anchor triangle each (same trick as the volcano)
    for k in range(len(PALETTES)):
        a = Batch(scene, f"bank{k}", f"bball{k}.tex", solid=False)
        a.tri([(0, 0, -2), (0.1, 0, -2), (0, 0.1, -2)], [(0.5, 0.5)] * 3, 1.0)
        a.flush()
    return scene, line


def ball_spots(line, n, rng, gap=2.4, on_road=0.6):
    """n spots, `gap` m apart: about 60% on the painted road, the rest anywhere in the room,
    keeping the starting grid and the first stretch clear."""
    L = line.L
    spots = []
    cell = {}

    def free(x, y):
        cx, cy = int(x // gap), int(y // gap)
        return all(math.hypot(x - px, y - py) >= gap for i in (-1, 0, 1) for j in (-1, 0, 1)
                   for px, py in cell.get((cx + i, cy + j), ()))

    def add(x, y):
        spots.append((x, y))
        cell.setdefault((int(x // gap), int(y // gap)), []).append((x, y))

    tries = 0
    while len(spots) < n and tries < 400000:
        tries += 1
        if len(spots) < on_road * n:
            s = rng.uniform(25.0, L - 75.0)                        # not the grid, not the line
            (x, y, _), (tx, ty) = line.at(s)
            lat = rng.uniform(-HALF + 1, HALF - 1)
            x, y = x - ty * lat, y + tx * lat
        else:
            x, y = rng.uniform(-ROOM_X + 6, ROOM_X - 6), rng.uniform(-ROOM_Y + 6, ROOM_Y - 6)
            (gx, gy, _), _t = line.at(L - 30.0)
            if math.hypot(x - gx, y - gy) < 45:
                continue
        if free(x, y):
            add(x, y)
    if len(spots) < n:
        raise SystemExit(f"only found room for {len(spots)} of {n} balls")
    return spots


def make_base(drop=0.0):
    """The room with every ball mesh in it and no balls placed. Returns (line, entries)."""
    scene, line = build_scene()
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables)
    print(f"loop {line.L:.0f} m; room {2 * ROOM_X:.0f} x {2 * ROOM_Y:.0f} m; collision triangles {collide}; "
          f"textures {sorted(wanted)}")
    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=BASE, slot=SLOT,
                              textures={t: "asph.tex" for t in wanted}, closed=True, corridor=CORRIDOR)
    print(f"assembled: {res.summary()}")
    ent = archive.read(BASE)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        im = TEXTURES[name]()
        if int((np.array(im).sum(axis=2) == 0).sum()):
            raise SystemExit(f"{name} has black texels")
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), im.width, mode="opaque", wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = Image.new("RGB", (1024, 512), (255, 255, 255))           # a white sky, all round
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for cx, cy in ((-ROOM_X + 10, -ROOM_Y + 10), (ROOM_X - 10, -ROOM_Y + 10), (ROOM_X - 10, ROOM_Y - 10),
                   (-ROOM_X + 10, ROOM_Y - 10)):
        gpos, gtgt = bc.game((cx, cy, 10.0 + WALL_H / 2)), bc.game((cx * 0.3, cy * 0.3, 0.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    for k in range(len(PALETTES)):
        menv = envelope.parse(mod.build(ball_mesh(k, drop=drop)))
        ent.append(archive.ArchiveEntry(name=f"bball{k}.mod", tag=menv.tag, version=menv.version, payload=menv.payload))
    archive.write(ent, BASE)
    trackmap.install(BASE, BASE)
    return line


def write_count(spots, yaws, name):
    """BASE plus one ball record per spot, written as <name>.trk here and <name>.tra in DATA."""
    ents = archive.read(BASE)
    obt = next(e for e in ents if e.name.lower() == "track.obt")
    table = obt_mod.parse(envelope.build(obt.tag, obt.version, obt.payload))
    recs = [r for r in table.records if r != obt_mod.TERMINATOR]
    for k, ((x, y), yaw) in enumerate(zip(spots, yaws)):
        gx, _gh, gz = bc.game((x, y, 0.0))
        # x, z : YAW MASS -- the engine finds the height itself and drops it from 4 m up
        recs.append(f"obj obstacle ball bball{k % len(PALETTES)}.mod {gx:.6f},{gz:.6f}:{yaw:.1f} {BALL_MASS:.6f}")
    table.records = recs + [obt_mod.TERMINATOR]
    obt.payload = envelope.parse(obt_mod.build(table)).payload
    trk = HERE / f"{name}.trk"
    archive.write(ents, trk)
    out = DATA / f"{name}.tra"
    r = track.export_tra(trk, out, layout="flat")
    print(f"  {out.name}: {len(spots)} balls, {r.member_count} members, {out.stat().st_size:,} bytes")
    return out


def main():
    line = make_base()
    rng = random.Random(SEED)
    every = ball_spots(line, max(LADDER), rng)                    # one field; each count takes a prefix
    order = list(range(len(every)))
    rng.shuffle(order)                                            # so a prefix is spread, not one end
    yaws = [rng.uniform(0, 360) for _ in every]
    for n in LADDER:
        write_count([every[i] for i in order[:n]], [yaws[i] for i in order[:n]], f"Balls{n}")


if __name__ == "__main__":
    main()
