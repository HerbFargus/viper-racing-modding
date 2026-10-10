"""Ball Pit: the temple arena's footprint as a ball pit you swim through.

THE PIT is the Rotunda's floor -- 360 m across, flat to 150 m out, then banked up 12 m to the
rim -- padded like a soft-play mat. Round the rim stand three stacked inflatable rings (tubes
8 m thick, shaded as if blown up), with a solid wall just inside them.

THE BALLS: 200 of them, 10 m across, in twelve solid colours, spread evenly over the pit and
up onto the bank, about 21 m apart -- room to drive between them. (250 at 32 m, then 400 at
16 m, were too packed.) An INVISIBLE ceiling bubble (.sol boxes, 4 m thick, from
62 m at the rim to 110 m at the crown) keeps the heap in. 200 balls + 8 cars + 4 checkpoints
is 212 of the engine's 512 physics objects.

THE RACE: a lap line round the middle at 91 m radius (the Rotunda's), a clear starting grid,
four checkpoints. The AI will shove through the balls as best it can.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ballroom"))
sys.path.insert(0, str(HERE.parent / "circuit"))
sys.path.insert(0, str(HERE.parent / "dome"))
import build_ballroom as B  # noqa: E402  (Batch, ball meshes, bc, vrmod)
import build_coliseum as CO  # noqa: E402  (ball colours, flat_box, delaunay's import path)
from build_river import delaunay  # noqa: E402
from art import colourise, tile_noise, to_img  # noqa: E402

bc = B.bc
from vrmod import archive, camtab, envelope, mod, obt as obt_mod, sky, sol, tex, track, trackbuild, trackgen, trackmap  # noqa: E402
from vrmod.trackgen import GRASS, NO_COLLISION  # noqa: E402

NAME = "BallPit"
OUT = HERE / f"{NAME}.trk"
DATA = B.DATA
SLOT = "dundas"
SEED = 1987

# ---- the pit (source frame: x east, y north, z up), the Rotunda's footprint ------------------
CX, CY = 13.7, 7.3                                  # centre, off the world origin
R_FLAT, R_RIM, RIM_H = 150.0, 180.0, 12.0           # flat floor, then a 12 m bank to the rim
R_LINE, CORRIDOR = 91.0, 91.0                       # the lap, and its corridor (centre to rim)

# ---- the inflatable rings --------------------------------------------------------------
TUBE = 8.0                                          # tube radius
R_TUBE = R_RIM + TUBE + 0.5                         # tube centre-line radius: inner face at the rim
RING_Z = [RIM_H + TUBE, RIM_H + 3 * TUBE, RIM_H + 5 * TUBE]    # stacked: top at 60 m
RING_COLOURS = [(226, 52, 52), (246, 200, 40), (52, 118, 226)]
MAJOR, MINOR = 96, 16

# ---- the invisible ceiling ---------------------------------------------------------------
CEIL_RIM, CEIL_CROWN, R_CEIL = 62.0, 110.0, R_RIM + 1.0
SHELL = [1.0, 0.88, 0.72, 0.52, 0.3]                # terrace radii, as fractions of R_CEIL
SLAB = 4.0                                          # ceiling slab thickness: nothing tunnels through
WALL_TOP = CEIL_RIM + 2.0

# ---- the balls -------------------------------------------------------------------------------
N_BALLS, BALL_R, BALL_MASS = 200, 5.0, 40.0          # 250 x 32 m, then 400 x 16 m, were too packed
BALL_RINGS, BALL_SEGS = 10, 14                      # 165 vertices a ball: 400 of them are drawn
B.BALL_R, B.BALL_MASS = BALL_R, BALL_MASS             # ball_mesh sizes from these (it was drawing 16 m balls)
GRID_CLEAR = 45.0                                   # no ball spawns within this of the starting grid

MAX_VERTS = B.MAX_VERTS


def P(r, a_deg, z=0.0):
    a = math.radians(a_deg)
    return (CX + r * math.cos(a), CY + r * math.sin(a), z)


def floor_z(r):
    if r <= R_FLAT:
        return 0.0
    if r >= R_RIM:
        return RIM_H
    return RIM_H * ((r - R_FLAT) / (R_RIM - R_FLAT)) ** 1.6


def ceil_z(r):
    return CEIL_RIM + (CEIL_CROWN - CEIL_RIM) * math.sqrt(max(0.0, 1 - (r / R_CEIL) ** 2))


# ---- art --------------------------------------------------------------------------------------
def mat_tex(size=256, seed=71):
    """Soft-play mat: a big pastel-blue tile every 16 m (4 per 64 m tile), seams soft and low in
    contrast -- large floors shimmer with anything sharper (the Coliseum's lesson)."""
    u = np.arange(size)[None, :] / size
    v = np.arange(size)[:, None] / size

    def seam(c):
        x = (c * 4) % 1.0
        return np.exp(-(np.minimum(x, 1 - x) / 0.06) ** 2)
    s = np.maximum(seam(u), seam(v))
    base = colourise(tile_noise(size, 8, 3, 0.5, seed), (96, 150, 206), (110, 164, 220))
    img = base * (1 - 0.18 * s[..., None])
    return to_img(img)


def ring_tex(rgb, size=128):
    """An inflated tube: v runs round the tube (0 = its outer-top), u along it. A soft sheen on
    top, shade underneath, and faint weld seams every 1/8 of the texture."""
    u = np.arange(size)[None, :] / size
    v = np.arange(size)[:, None] / size
    ang = 2 * np.pi * v                               # 0 at the top of the tube
    light = 0.62 + 0.38 * np.cos(ang - 0.5)            # lit from above and a little inward
    sheen = 0.35 * np.exp(-(((v - 0.07 + 0.5) % 1.0 - 0.5) / 0.04) ** 2)
    img = np.array(rgb, np.float32)[None, None, :] * light[..., None]
    img = img + (255 - img) * sheen[..., None]
    welds = np.exp(-((((u * 8) % 1.0) - 0.5) / 0.02) ** 2) * 0.12
    img = img * (1 - welds[..., None])
    return Image.fromarray(np.clip(np.broadcast_to(img, (size, size, 3)), 8, 255).astype(np.uint8))


def sunny_sky(w=1024, h=512, seed=5):
    y = np.linspace(0, 1, h)[:, None, None]
    img = np.array([66, 132, 224], np.float32) * (1 - y) + np.array([176, 212, 246], np.float32) * y
    img = np.broadcast_to(img, (h, w, 3)).copy()
    n = tile_noise(w, 16, 5, 0.55, seed)[:h, :w]
    cloud = np.clip((n - 0.55) * 3.2, 0, 1) * (0.3 + 0.7 * np.linspace(0, 1, h)[:, None])
    img = img * (1 - cloud[..., None]) + 250 * cloud[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


TEXTURES = {"mat.tex": mat_tex, "chequer.tex": CO.check_tex}
TEXTURES.update({f"ring{k}.tex": (lambda c=c: ring_tex(c)) for k, c in enumerate(RING_COLOURS)})
TEXTURES.update({f"{CO.ball_name(k)}.tex": (lambda c=c: CO.ball_tex(c)) for k, c in enumerate(CO.BALL_COLOURS)})


# ---- geometry ------------------------------------------------------------------------------------
class ShadedBatch(B.Batch):
    """B.Batch with a grey PER VERTEX -- the tubes are pre-lit round their curve."""

    def tri3(self, P, uv, greys, out):
        g = [bc.game(tuple(p)) for p in P]
        a, b, c = (np.array(q) for q in g)
        want = np.array(bc.game(tuple(out))) - (a + b + c) / 3
        order = [0, 1, 2] if np.dot(np.cross(b - a, c - a), want) >= 0 else [0, 2, 1]
        if len(self.v) + 3 > MAX_VERTS:
            self.flush()
        base = len(self.v)
        for k in order:
            self.v.append(mod.Vertex(*g[k], 0.0, 1.0, 0.0, *uv[k]))
            gv = int(max(40, min(255, greys[k] * 255)))
            self.c.append(bytes([gv, gv, gv, 0xFF]))
        self.f.append((base, base + 1, base + 2))


SUN = np.array([-0.4, -0.3, 0.87]) / np.linalg.norm([-0.4, -0.3, 0.87])


def add_rings(scene):
    """Three stacked tori round the rim, drawn from outside and within, shaded by the sun."""
    for k, zc in enumerate(RING_Z):
        b = ShadedBatch(scene, f"ring{k}_", f"ring{k}.tex", False)
        for i in range(MAJOR):
            for j in range(MINOR):
                quad = []
                for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    a = 2 * math.pi * (i + di) / MAJOR
                    t = 2 * math.pi * (j + dj) / MINOR                    # 0 = the tube's top
                    rr = R_TUBE + TUBE * math.sin(t) * -1.0               # t = pi/2: the inner face
                    rr = R_TUBE - TUBE * math.sin(t)
                    z = zc + TUBE * math.cos(t)
                    n = np.array([-math.sin(t) * math.cos(a), -math.sin(t) * math.sin(a), math.cos(t)])
                    p = (CX + rr * math.cos(a), CY + rr * math.sin(a), z)
                    grey = 0.55 + 0.45 * max(0.0, float(n @ SUN))
                    quad.append((p, ((i + di) / MAJOR * 12.0, (j + dj) / MINOR), grey, n))
                (p0, uv0, g0, n0), (p1, uv1, g1, _), (p2, uv2, g2, _), (p3, uv3, g3, _) = quad
                centre = np.mean([q[0] for q in quad], axis=0)
                out = tuple(centre + n0 * 5)
                b.tri3([p0, p1, p2], [uv0, uv1, uv2], [g0, g1, g2], out)
                b.tri3([p0, p2, p3], [uv0, uv2, uv3], [g0, g2, g3], out)
        b.flush()


def floor_points():
    pts = [(CX, CY)]
    radii = list(np.arange(10.0, R_FLAT + 0.1, 12.0)) + list(np.arange(R_FLAT + 3.0, R_RIM + 0.1, 3.0))
    for r in radii:
        n = max(8, int(2 * math.pi * r / 12.0))
        off = random.Random(int(r)).uniform(0, 360.0 / n)
        pts += [P(r, off + 360.0 * k / n)[:2] for k in range(n)]
    return pts


def build_floor(scene):
    pts = floor_points()
    tris = delaunay(pts)
    Z = [floor_z(math.hypot(x - CX, y - CY)) for x, y in pts]
    mat = B.Batch(scene, "mat", "mat.tex", True)
    n = 0
    for t in tris:
        Pp = [(pts[i][0], pts[i][1], Z[i]) for i in t]
        cx = sum(p[0] for p in Pp) / 3 - CX
        cy = sum(p[1] for p in Pp) / 3 - CY
        if math.hypot(cx, cy) > R_RIM + 0.01:
            continue
        mat.tri(Pp, [(p[0] / 64.0, p[1] / 64.0) for p in Pp], 0.95)
        n += 1
    mat.flush()
    return n


def add_start_line(scene, line):
    b = B.Batch(scene, "startln", "chequer.tex", False)
    (x, y, _), (tx, ty) = line.at(0.0)
    nx, ny = -ty, tx
    q = [(x + nx * l + tx * d, y + ny * l + ty * d, 0.05) for l, d in ((-14, -1.5), (-14, 1.5), (14, 1.5), (14, -1.5))]
    uv = [(0.02, 0.02), (0.98, 0.02), (0.98, 0.98), (0.02, 0.98)]
    b.tri(q[:3], uv[:3], 1.0)
    b.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 1.0)
    b.flush()


def base_wall_quads():
    quads = []
    n = 72
    for k in range(n):
        a0, a1 = 360.0 * k / n, 360.0 * (k + 1) / n
        p0, p1 = P(R_RIM + 1.0, a0), P(R_RIM + 1.0, a1)
        quads.append([(p0[0], p0[1], 0.0), (p1[0], p1[1], 0.0), (p1[0], p1[1], WALL_TOP), (p0[0], p0[1], WALL_TOP)])
    return quads


def ceiling_prims(template):
    """Invisible terraces: a SLAB-thick tread across each band at the height of its outer (lower)
    edge, a riser at its inner edge up to the next band, and a flat cap over the crown."""
    prims = []

    def box(p0, p1, width, height, top):
        return sol.box_from_segment(template, bc.game((p0[0], p0[1], top - height)),
                                    bc.game((p1[0], p1[1], top - height)), height=height, thickness=width)

    for k, f_out in enumerate(SHELL):
        r_out = f_out * R_CEIL
        f_in = SHELL[k + 1] if k + 1 < len(SHELL) else None
        z = ceil_z(r_out)
        if f_in is None:                                            # the crown cap
            step = 40.0
            for gx in np.arange(-r_out, r_out, step):
                for gy in np.arange(-r_out, r_out, step):
                    cx, cy = gx + step / 2, gy + step / 2
                    if math.hypot(cx, cy) < r_out + step / 2:
                        prims.append(box((CX + cx - step / 2 - 1, CY + cy), (CX + cx + step / 2 + 1, CY + cy),
                                         step + 2, SLAB, z + SLAB))
            break
        r_in = f_in * R_CEIL
        rm = (r_in + r_out) / 2
        n = max(16, int(round(2 * math.pi * r_out / 20.0)))     # short enough that the outer edge is covered
        for j in range(n):
            a0, a1 = 360.0 * j / n - 2.5, 360.0 * (j + 1) / n + 2.5
            p0, p1 = P(rm, a0), P(rm, a1)
            prims.append(box(p0, p1, (r_out - r_in) + 4.0, SLAB, z + SLAB))          # tread, 4 m of overlap
            q0, q1 = P(r_in, a0), P(r_in, a1)
            prims.append(box(q0, q1, SLAB, ceil_z(r_in) - z + SLAB, ceil_z(r_in) + SLAB))   # riser
    return prims


def ball_spots(line, rng):
    """N_BALLS spots, sunflower-spaced over the pit (so every ball overlaps its neighbours about
    equally -- the burst is even), keeping clear of the starting grid."""
    (gx, gy, _), _t = line.at(line.L - 30.0)
    spots = []
    golden = math.pi * (3 - math.sqrt(5))
    k = 0
    while len(spots) < N_BALLS and k < 5000:
        r = (R_RIM - 10.0) * math.sqrt((k + 0.5) / (N_BALLS * 1.2))     # out onto the bank: less overlap
        a = k * golden
        x, y = CX + r * math.cos(a), CY + r * math.sin(a)
        k += 1
        if math.hypot(x - gx, y - gy) < GRID_CLEAR:
            continue
        spots.append((x, y))
    if len(spots) < N_BALLS:
        raise SystemExit(f"only placed {len(spots)} balls")
    rng.shuffle(spots)
    return spots


def main():
    rng = random.Random(SEED)
    n = int(round(2 * math.pi * R_LINE / 10.0))
    pts = [P(R_LINE, 360.0 * k / n) for k in range(n)]              # anticlockwise
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=R_LINE / 2.5 + 1.0)
    grid = []
    for k in range(8):
        (x, y, _), (tx, ty) = line.at(line.L - 16.0 - 10.0 * (k // 2))
        lat = 5.0 if k % 2 else -5.0
        grid.append((x - ty * lat, y + tx * lat, 0.0))
    scene.grid = grid
    nf = build_floor(scene)
    add_rings(scene)
    add_start_line(scene, line)
    scene.walls = base_wall_quads()
    for k in range(len(CO.BALL_COLOURS)):                            # anchors: ball textures ship with the track
        a = B.Batch(scene, f"bank{k:02d}", f"{CO.ball_name(k)}.tex", False)
        a.tri([(CX, CY, -3), (CX + 0.1, CY, -3), (CX, CY + 0.1, -3)], [(0.5, 0.5)] * 3, 1.0)
        a.flush()
    trackgen.add_ground(scene, texture="mat.tex", margin=300.0, drop=0.5)
    scene.colours["ground.mod"] = [bytes([200, 200, 200, 255])] * 4
    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables)
    print(f"floor triangles {nf}; largest chunk {biggest} verts; collision triangles {collide}; "
          f"surfaces {len(drawn)}; textures {sorted(wanted)}")
    if biggest > MAX_VERTS or collide > 16500:
        raise SystemExit("over budget")

    trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                        textures={t: "asph.tex" for t in wanted}, closed=True, corridor=CORRIDOR)
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        im = TEXTURES[name]()
        a = np.array(im)
        a[..., :3] = np.maximum(a[..., :3], 6)
        enc = envelope.parse(tex.encode_to_tex(Image.fromarray(a).tobytes(), im.width, mode="opaque", wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = sunny_sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for k in range(4):
        pos = P(R_RIM - 8.0, 45.0 + 90.0 * k, 50.0)
        gpos, gtgt = bc.game(pos), bc.game(P(40.0, 45.0 + 90.0 * k + 180.0, 5.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    for k in range(len(CO.BALL_COLOURS)):
        mesh = B.ball_mesh(k, rings=BALL_RINGS, segs=BALL_SEGS, texture=f"{CO.ball_name(k)}.tex")
        menv = envelope.parse(mod.build(mesh))
        ent.append(archive.ArchiveEntry(name=f"{CO.ball_name(k)}.mod", tag=menv.tag, version=menv.version,
                                        payload=menv.payload))
    e = next(x for x in ent if x.name.lower() == "track.sol")
    s0 = sol.parse(envelope.build(e.tag, e.version, e.payload))
    prims = list(s0.primitives) + ceiling_prims(sol.wall_template(s0))
    index, tail = sol.build_spatial_index(prims)
    env = envelope.parse(sol.build(sol.Sol(primitives=prims, index=index, tail=tail, version=s0.version)))
    e.tag, e.version, e.payload = env.tag, env.version, env.payload
    table = obt_mod.parse(envelope.build(by["track.obt"].tag, by["track.obt"].version, by["track.obt"].payload))
    recs = [r for r in table.records if r != obt_mod.TERMINATOR]
    spots = ball_spots(line, rng)
    for k, (x, y) in enumerate(spots):
        gx, _gh, gz = bc.game((x, y, 0.0))
        recs.append(f"obj obstacle ball {CO.ball_name(k % len(CO.BALL_COLOURS))}.mod {gx:.6f},{gz:.6f}:"
                    f"{rng.uniform(0, 360):.1f} {BALL_MASS:.6f}")
    table.records = recs + [obt_mod.TERMINATOR]
    by["track.obt"].payload = envelope.parse(obt_mod.build(table)).payload
    archive.write(ent, OUT)
    trackmap.install(OUT, OUT)
    out = DATA / f"{NAME}.tra"
    track.export_tra(OUT, out, layout="flat")
    phys = N_BALLS + 8 + 4
    print(f"{out.name}: {len(prims)} solids ({len(s0.primitives)} wall), {len(spots)} balls; physics objects "
          f"{phys}/512; {out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
