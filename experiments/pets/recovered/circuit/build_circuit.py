"""Build the hilly road course into a loadable .trk, natively.

  road + verges   trackgen.sweep over circuit.obj (x, y, elevation), 10 m stations
  walls           just inside the grass band's outer edge, both sides, all the way
  terrain         render-only heightfield in 80 m tiles: under the verges it sits
                  just below the grass; away from the track it blends into
                  rolling hills and down to a flat horizon plane at the borders
  chevrons        knock-over signs on the hairpin's outside (stock design: board on
                  a post, foot pivot, 0.5 m capsule reaching 2.5 m)
  targets         six hinged heads on the back straight's verges, for the horn ball
  cameras         our own camera.tab: fixed cameras outside the walls, aimed ahead
  timing          four gates, an eight-car grid

Frames: everything scene-level is the SOURCE frame (x, y ground, z elevation);
meshes and cameras are the GAME frame, via trackgen.to_viper.
"""
import math
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, r"C:/Users/seamus/Desktop/claude-code/viper-mod-manager")
from vrmod import archive, camtab, envelope, ili, mod, sol, tex, trackbuild, trackgen  # noqa: E402

HERE = Path(__file__).resolve().parent
TGT = HERE.parent / "targets"
sys.path.insert(0, str(TGT))
import build_targets as bt  # noqa: E402
from build_sticks import disc, stick, turn  # noqa: E402

DONOR = Path("C:/Users/seamus/Desktop/claude-code/game-files/viper-racing-usa/Data/bemidji.trk")
OUT = HERE / "limbo.trk"
HALF = 6.0                         # road half-width
GRASS_EDGE = HALF + 0.9 + 1.0 + 20.0   # 27.9 m: the outer edge of the drivable verge
WALL_OFFSET = 27.3                 # stands on the grass, so nothing reaches the edge
TERRAIN_TILE, TERRAIN_CELL, TERRAIN_MARGIN = 160.0, 10.0, 320.0
SEGMENT = 100.0                    # road chunk length
WALL_GROUP = 4                     # wall quads per drawn mesh
# The renderer queues EVERY surface of a flat .grf each frame into a 1,024-entry
# pool (begin_deferred: PoolBase(..., 0x400, 0x10)); overflow is a panic. Stock
# tracks cull with LOD/group nodes; a flat build must stay well under the pool,
# with room left for the cars.
SURFACE_BUDGET = 600
UNDER_GRASS = 0.6                  # terrain sits this far below the verge
CHEV_TEX, SIZE = "chevron.tex", 64


# ------------------------------------------------------------------ geometry
def game(p):
    return trackgen.to_viper(p)


def source_of(g):
    """Inverse of to_viper for a point: game (x, y, z) -> source (x, y, elev)."""
    return (-g[0], -g[2], g[1])


class Line:
    """The resampled centreline, with arc length, headings and projection."""

    def __init__(self, pts):
        self.p = pts
        n = len(pts)
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.L = self.cum[-1]
        self.n = n

    def at(self, s):
        s %= self.L
        k = max(i for i in range(self.n) if self.cum[i] <= s)
        a, b = self.p[k], self.p[(k + 1) % self.n]
        f = (s - self.cum[k]) / (self.cum[k + 1] - self.cum[k])
        pos = tuple(a[j] + f * (b[j] - a[j]) for j in range(3))
        tx, ty = b[0] - a[0], b[1] - a[1]
        L = math.hypot(tx, ty)
        return pos, (tx / L, ty / L)

    def nearest(self, x, y):
        """(distance, interpolated elevation) to the nearest point on the polyline."""
        best = (1e18, 0.0)
        for i in range(self.n):
            a, b = self.p[i], self.p[(i + 1) % self.n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)))
            px, py = a[0] + t * dx, a[1] + t * dy
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < best[0]:
                best = (d2, a[2] + t * (b[2] - a[2]))
        return math.sqrt(best[0]), best[1]


def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ terrain
def add_terrain(scene, line):
    xs = [p[0] for p in line.p]; ys = [p[1] for p in line.p]
    zmin = min(p[2] for p in line.p)
    base = zmin - 0.15 - UNDER_GRASS               # the horizon plane's level
    x0, x1 = min(xs) - TERRAIN_MARGIN, max(xs) + TERRAIN_MARGIN
    y0, y1 = min(ys) - TERRAIN_MARGIN, max(ys) + TERRAIN_MARGIN
    nx = int(math.ceil((x1 - x0) / TERRAIN_CELL)); ny = int(math.ceil((y1 - y0) / TERRAIN_CELL))

    # a smooth regional surface: inverse-distance-weighted track elevation
    samples = line.p[::3]

    def regional(x, y):
        num = den = 0.0
        for p in samples:
            w = 1.0 / ((x - p[0]) ** 2 + (y - p[1]) ** 2 + 90.0 ** 2)
            num += w * p[2]; den += w
        return num / den

    H = {}
    worst_poke = -1e9
    for j in range(ny + 1):
        for i in range(nx + 1):
            x, y = x0 + i * TERRAIN_CELL, y0 + j * TERRAIN_CELL
            d, e = line.nearest(x, y)
            near = e - 0.2 - UNDER_GRASS                    # the verge is 0.2 below the road
            hills = 7.0 * math.sin(x / 160.0 + 0.7) * math.cos(y / 210.0 - 0.4)
            far = regional(x, y) + max(0.0, hills)
            h = near + (far - near) * smoothstep(GRASS_EDGE + 4, GRASS_EDGE + 140, d)
            edge = min(x - x0, x1 - x, y - y0, y1 - y)       # fade to the horizon plane
            h = base + (h - base) * smoothstep(0.0, 120.0, edge)
            if d < GRASS_EDGE + 2:
                worst_poke = max(worst_poke, h - (e - 0.2))
            H[i, j] = h

    per = int(TERRAIN_TILE / TERRAIN_CELL)
    tiles = 0
    for tj in range(0, ny, per):
        for ti in range(0, nx, per):
            verts, idx = [], {}
            for j in range(tj, min(tj + per, ny) + 1):
                for i in range(ti, min(ti + per, nx) + 1):
                    x, y = x0 + i * TERRAIN_CELL, y0 + j * TERRAIN_CELL
                    g = game((x, y, H[i, j]))
                    idx[i, j] = len(verts)
                    verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, x / 12.0, y / 12.0))
            faces = []
            for j in range(tj, min(tj + per, ny)):
                for i in range(ti, min(ti + per, nx)):
                    a, b, c, d_ = idx[i, j], idx[i + 1, j], idx[i + 1, j + 1], idx[i, j + 1]
                    faces += [(a, b, c), (a, c, d_)]
            # face UP (derived from the built vertices, as add_ground does)
            va, vb, vc = verts[faces[0][0]], verts[faces[0][1]], verts[faces[0][2]]
            if (vb.z - va.z) * (vc.x - va.x) - (vb.x - va.x) * (vc.z - va.z) < 0.0:
                faces = [(p, r, q) for p, q, r in faces]
            name = f"terr{tiles:03d}.mod"
            scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
                mod.Material(name="grass.tex", vertex_start=0, vertex_end=len(verts),
                             face_start=0, face_end=len(faces))])
            scene.scenery.append(trackgen.SceneObject(name, trackgen.GRASS, trackgen.NO_COLLISION))
            tiles += 1
    return tiles, worst_poke, base


# ------------------------------------------------------------------ signs
def chevron_image():
    """Red board, white chevrons pointing +u (right, once the UVs are un-mirrored)."""
    img = Image.new("RGB", (SIZE, SIZE), (200, 30, 30))
    d = ImageDraw.Draw(img)
    for cx in (16, 40):
        d.polygon([(cx - 8, 12), (cx + 2, 12), (cx + 16, 32), (cx + 2, 52), (cx - 8, 52), (cx + 6, 32)],
                  fill=(245, 245, 245))
    return img


def chevron_mesh(yaw, arrow_right):
    """A 1.0 x 0.9 m board on a 0.1 m post, foot at the origin, front facing +Z.

    The game draws left-handed, so a viewer facing a +Z front sees local +x on
    their LEFT: u runs 1 -> 0 across the front to read un-mirrored, and flips
    again for a left-pointing arrow.
    """
    w, y0, y1 = 0.5, 1.1, 2.0
    u_l, u_r = (1.0, 0.0) if arrow_right else (0.0, 1.0)
    front = [(-w, y0, 0.0, u_l, 1.0), (w, y0, 0.0, u_r, 1.0), (w, y1, 0.0, u_r, 0.0), (-w, y1, 0.0, u_l, 0.0)]
    back = [(x, y, -0.02, *bt.GREY_UV) for x, y, _z, _u, _v in front]
    verts = front + back
    faces = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6)]
    sv, sf = stick(0.0, y0, zoff=-0.05)
    base = len(verts)
    verts += sv
    faces += [(a + base, b + base, c + base) for a, b, c in sf]
    return bt.to_facing(turn(verts, yaw), faces, CHEV_TEX)


def yaw_facing_traffic(tx, ty):
    return math.degrees(math.atan2(tx, ty))       # proven on the ring (source-frame travel)


def merge_walls(scene):
    """Combine consecutive wall quads WALL_GROUP at a time: same texture, one surface."""
    names = sorted(o.name for o in scene.scenery if o.name.startswith("wall"))
    keep = [o for o in scene.scenery if not o.name.startswith("wall")]
    groups = [names[i:i + WALL_GROUP] for i in range(0, len(names), WALL_GROUP)]
    for gi, grp in enumerate(groups):
        verts, faces = [], []
        for nm in grp:
            m = scene.meshes.pop(nm)
            base = len(verts)
            verts += m.vertices
            faces += [(a + base, b + base, c + base) for a, b, c in m.faces]
        name = f"wallg{gi:03d}.mod"
        scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
            mod.Material(name=m.materials[0].name, vertex_start=0, vertex_end=len(verts),
                         face_start=0, face_end=len(faces))])
        keep.append(trackgen.SceneObject(name, trackgen.GRASS, trackgen.NO_COLLISION))
    scene.scenery[:] = keep
    return len(groups)


# ------------------------------------------------------------------ build
def main():
    raw = trackgen.read_centreline(HERE / "circuit.obj")
    pts = trackgen.resample(raw, 10.0, closed=True)
    line = Line(pts)
    scene = trackgen.sweep(pts, road_half_width=HALF, closed=True, segment_length=SEGMENT)
    trackgen.add_checkpoints(scene, 4, half_width=HALF)
    trackgen.add_grid(scene, 8)
    quads = trackgen.add_walls(scene, offset=WALL_OFFSET, height=1.5)
    wall_meshes = trackgen.add_wall_meshes(scene, texture="strpy.tex")
    wall_meshes = merge_walls(scene)
    tiles, poke, base = add_terrain(scene, line)
    trackgen.add_ground(scene, margin=TERRAIN_MARGIN + 1500.0, drop=0.15 + UNDER_GRASS)
    print(f"lap {line.L:.0f} m, {line.n} stations; walls {quads} quads / {wall_meshes} meshes; "
          f"terrain {tiles} tiles, highest point near the verge {poke:+.2f} m relative to the grass "
          f"(must be < 0)")
    if poke >= 0:
        raise SystemExit("terrain pokes through the verge")

    # --- chevrons round the hairpin's outside -------------------------------
    wob_rows = []
    hair = [1860 + 24 * k for k in range(6)]
    for n, s in enumerate(hair):
        (x, y, z), (tx, ty) = line.at(s)
        (_, _, _), (ax, ay) = line.at(s - 20)
        (_, _, _), (bx, by) = line.at(s + 20)
        turn_left = (ax * by - ay * bx) > 0          # source frame: CCW = left
        side = -1.0 if turn_left else 1.0            # outside of the turn
        nx_, ny_ = -ty, tx                           # left of travel
        pos = (x + nx_ * side * 9.5, y + ny_ * side * 9.5, z)
        name = f"chev{n:02d}.mod"
        scene.meshes[name] = chevron_mesh(yaw_facing_traffic(tx, ty), arrow_right=not turn_left)
        scene.wobbles.append(trackgen.Wobble(position=pos, mesh=name, radius=0.5, height=2.5))
        wob_rows.append(("chevron", s, "left" if turn_left else "right"))

    # --- hinged targets on the back straight's verges -----------------------
    for n, s in enumerate([2640 + 60 * k for k in range(6)]):
        (x, y, z), (tx, ty) = line.at(s)
        lat = 10.0 if n % 2 else -10.0
        hinge = (0.4, 0.55, 0.45, 0.6, 0.35, 0.5)[n]
        foot = (x - ty * lat, y + tx * lat, z)
        yaw = yaw_facing_traffic(tx, ty)
        name = f"tgt{n:02d}.mod"
        v, f = disc(0.6)
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, bt.TEX_NAME)
        scene.wobbles.append(trackgen.Wobble(position=(foot[0], foot[1], z + hinge), mesh=name,
                                             radius=0.6, height=1.2))
        sv, sf = stick(0.0, hinge)
        g = game(foot)
        gv = [mod.Vertex(vx + g[0], vy + g[1], vz + g[2], 0.0, 1.0, 0.0, u, w)
              for vx, vy, vz, u, w in turn(sv, yaw)]
        sname = f"stk{n:02d}.mod"
        scene.meshes[sname] = mod.Mesh(vertices=gv, faces=sf, materials=[
            mod.Material(name=bt.TEX_NAME, vertex_start=0, vertex_end=len(gv),
                         face_start=0, face_end=len(sf))])
        scene.scenery.append(trackgen.SceneObject(sname, trackgen.GRASS, trackgen.NO_COLLISION))
        wob_rows.append(("target", s, "left" if lat > 0 else "right"))

    surfaces = (sum(len(scene.meshes[o.name].materials) for o in scene.driveables + scene.scenery
                    if o.name in scene.meshes) + len(scene.wobbles))
    print(f"surfaces drawn per frame: {surfaces} (budget {SURFACE_BUDGET}; the pool is 1,024)")
    if surfaces > SURFACE_BUDGET:
        raise SystemExit("too many surfaces for a flat .grf")

    # --- assemble ------------------------------------------------------------
    res = trackbuild.assemble(scene, donor=DONOR, out_path=OUT, slot="limbo",
                              textures={bt.TEX_NAME: "asph.tex", CHEV_TEX: "asph.tex"},
                              closed=True, corridor=ili.corridor_for(HALF * 2.0))
    print(f"assembled: {res.summary()}")

    # --- our textures and cameras --------------------------------------------
    cams = []
    for k in range(10):
        s = k * line.L / 10
        (x, y, z), (tx, ty) = line.at(s)
        (ax, ay, az), _ = line.at(s + 45)
        (_, _, _), (bx, by) = line.at(s + 45)
        side = 1.0 if k % 2 == 0 else -1.0
        cam_src = (x - ty * side * 33.0, y + tx * side * 33.0, z + 6.0)
        gpos, gtgt = game(cam_src), game((ax, ay, az + 1.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for nm, im in ((bt.TEX_NAME, bt.target_image()), (CHEV_TEX, chevron_image())):
        if any(p == (0, 0, 0) for p in im.getdata()):
            raise SystemExit(f"{nm} has black pixels")
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), SIZE, mode="opaque", wrap=0))
        by[nm].tag, by[nm].version, by[nm].payload = enc.tag, enc.version, enc.payload
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)

    # --- verify ---------------------------------------------------------------
    by = {e.name.lower(): e for e in archive.read(OUT)}
    back = camtab.parse(envelope.build(by["camera.tab"].tag, by["camera.tab"].version,
                                       by["camera.tab"].payload))
    aim_err = []
    for c, k in zip(back, range(10)):
        (ax, ay, az), _ = line.at(k * line.L / 10 + 45)
        t = game((ax, ay, az + 1.0))
        dv = [t[0] - c.x, t[1] - c.y, t[2] - c.z]
        L = math.sqrt(sum(q * q for q in dv))
        f = c.forward
        aim_err.append(math.degrees(math.acos(max(-1, min(1, sum(a * b / L for a, b in zip(f, dv)))))))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    tubes = sorted(q.id for q in so.primitives if q.id >= 0)
    for nm in (bt.TEX_NAME, CHEV_TEX):
        tex.parse(envelope.build(by[nm].tag, by[nm].version, by[nm].payload))
    print(f"cameras: {len(back)}, worst aim error {max(aim_err):.2f} deg")
    print(f"wobbles: {len(tubes)} tubes, ids {tubes[0]}..{tubes[-1]}; " +
          ", ".join(f"{k} {s:.0f} m ({side})" for k, s, side in wob_rows))
    print(f"solids: {sum(1 for q in so.primitives if q.type == sol.BOX)} wall boxes")
    if len(back) != 10 or max(aim_err) > 1.0 or tubes != list(range(len(wob_rows))):
        raise SystemExit("verification failed")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
