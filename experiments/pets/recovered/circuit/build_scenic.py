"""The hilly road course, dressed as a landscape. Every texture and model is generated.

Over build_circuit.py's layout, cameras, chevrons and targets:
  road          generated asphalt (markings painted in), kerbs, a dirt shoulder
                with DIRT physics, grass verges
  terrain       240 m tiles, each split by ground type -- grass, dry meadow, and
                rock where the slope passes ~24 degrees -- with sun-and-slope
                shading baked into vertex colours (track geometry draws pre-lit)
  barriers      armco rail on posts along both sides; the collision boxes stay
  vegetation    pines on the higher, forested ground, oaks in the meadows, bushes
                near the barriers: crossed double-sided billboards, clustered
  sky           a generated panorama with a distant ridge line

Budgets: the flat .grf queues every surface each frame into a 1,024-entry pool,
so the whole scene is held under SURFACE_BUDGET; and no chunk exceeds the
engine's 1,500-vertex object buffer.
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
import art  # noqa: E402
import build_circuit as bc  # noqa: E402
import build_targets as bt  # noqa: E402
from build_sticks import disc, stick, turn  # noqa: E402
from vrmod import archive, camtab, envelope, ili, mod, sky, sol, tex, trackbuild, trackgen  # noqa: E402
from vrmod.trackgen import Band, DIRT, GRASS, RUMBLE  # noqa: E402

OUT = HERE / "limbo.trk"
SEGMENT = 150.0
TILE, CELL, MARGIN = 240.0, 10.0, 400.0
SURFACE_BUDGET = 650
MAX_VERTS = 1500
ARMCO_H, ARMCO_STEP = 0.8, 12            # visual height; stations per armco chunk
SUN = np.array([-0.45, -0.55, 0.70])     # toward the sun, source frame (south-west, high)
SUN = SUN / np.linalg.norm(SUN)
BANDS = (Band("rumbl", 0.9, 0.1, "kerb.tex", RUMBLE),
         Band("side", 1.0, -0.2, "dirt.tex", DIRT),
         Band("grass", 20.0, 0.0, "grass.tex", GRASS))
GENERATED = {name: (fn, mode) for name, (fn, mode) in art.ALL.items()}
GENERATED["chevron.tex"] = (bc.chevron_image, "opaque")
GENERATED["target.tex"] = (bt.target_image, "opaque")

random.seed(7)


def grey(v):
    v = int(max(40, min(255, round(v * 255))))
    return bytes((v, v, v, 0xFF))


def vnoise(x, y, scale, seed):
    """Smooth value noise at world coordinates, for placement decisions."""
    rng = np.random.default_rng(seed)
    lat = rng.random((64, 64))
    gx, gy = x / scale, y / scale
    x0, y0 = math.floor(gx), math.floor(gy)
    fx, fy = gx - x0, gy - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    g = lambda i, j: lat[j % 64, i % 64]
    return ((g(x0, y0) * (1 - fx) + g(x0 + 1, y0) * fx) * (1 - fy)
            + (g(x0, y0 + 1) * (1 - fx) + g(x0 + 1, y0 + 1) * fx) * fy)


# ------------------------------------------------------------------ terrain
class Terrain:
    def __init__(self, line):
        xs = [p[0] for p in line.p]; ys = [p[1] for p in line.p]
        self.x0, self.x1 = min(xs) - MARGIN, max(xs) + MARGIN
        self.y0, self.y1 = min(ys) - MARGIN, max(ys) + MARGIN
        self.nx = int(math.ceil((self.x1 - self.x0) / CELL))
        self.ny = int(math.ceil((self.y1 - self.y0) / CELL))
        zmin = min(p[2] for p in line.p)
        self.base = zmin - 0.15 - bc.UNDER_GRASS
        samples = line.p[::3]
        H = np.zeros((self.ny + 1, self.nx + 1)); D = np.zeros_like(H)
        worst = -1e9
        for j in range(self.ny + 1):
            for i in range(self.nx + 1):
                x, y = self.x0 + i * CELL, self.y0 + j * CELL
                d, e = line.nearest(x, y)
                near = e - 0.2 - bc.UNDER_GRASS
                num = den = 0.0
                for p in samples:
                    w = 1.0 / ((x - p[0]) ** 2 + (y - p[1]) ** 2 + 90.0 ** 2)
                    num += w * p[2]; den += w
                hills = (9.0 * math.sin(x / 170.0 + 0.7) * math.cos(y / 220.0 - 0.4)
                         + 4.0 * math.sin(x / 61.0 + 1.3) * math.sin(y / 83.0 + 0.2))
                # the land rises into real hills away from the track
                big = (22.0 * math.sin(x / 260.0 + 2.1) * math.cos(y / 310.0 + 0.9) + 12.0
                       + 8.0 * math.sin(x / 140.0 - 0.6) * math.sin(y / 170.0 + 1.7))
                far = (num / den + max(-2.0, hills)
                       + max(0.0, big) * bc.smoothstep(60.0, 320.0, d))
                h = near + (far - near) * bc.smoothstep(bc.GRASS_EDGE + 4, bc.GRASS_EDGE + 150, d)
                edge = min(x - self.x0, self.x1 - x, y - self.y0, self.y1 - y)
                h = self.base + (h - self.base) * bc.smoothstep(0.0, 160.0, edge)
                if d < bc.GRASS_EDGE + 2:
                    worst = max(worst, h - (e - 0.2))
                H[j, i] = h; D[j, i] = d
        self.H, self.D, self.worst = H, D, worst
        gy, gx = np.gradient(H, CELL)
        n = np.stack([-gx, -gy, np.ones_like(H)], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        lam = np.clip(n @ SUN, 0, None)
        self.shade = np.clip(0.34 + 0.62 * lam / SUN[2], 0.3, 1.0)
        self.slope = np.hypot(gx, gy)

    def height(self, x, y):
        fi = (x - self.x0) / CELL; fj = (y - self.y0) / CELL
        i, j = int(fi), int(fj); fi -= i; fj -= j
        i = min(max(i, 0), self.nx - 1); j = min(max(j, 0), self.ny - 1)
        H = self.H
        return ((H[j, i] * (1 - fi) + H[j, i + 1] * fi) * (1 - fj)
                + (H[j + 1, i] * (1 - fi) + H[j + 1, i + 1] * fi) * fj)

    def kind(self, i, j):
        """Ground type of cell (i, j) by its centre."""
        x, y = self.x0 + (i + 0.5) * CELL, self.y0 + (j + 0.5) * CELL
        s = self.slope[j:j + 2, i:i + 2].mean()
        if s > 0.45:
            return "rock.tex"
        if self.D[j:j + 2, i:i + 2].min() > 45 and vnoise(x, y, 140.0, 3) > 0.55:
            return "meadow.tex"
        return "grass.tex"

    def emit(self, scene):
        per = int(TILE / CELL)
        count, kinds = 0, {}
        for tj in range(0, self.ny, per):
            for ti in range(0, self.nx, per):
                cells = {}
                for j in range(tj, min(tj + per, self.ny)):
                    for i in range(ti, min(ti + per, self.nx)):
                        cells.setdefault(self.kind(i, j), []).append((i, j))
                for texname, cl in cells.items():
                    verts, cols, idx, faces = [], [], {}, []
                    uvs = 8.0 if texname == "rock.tex" else 12.0
                    def vid(i, j):
                        if (i, j) not in idx:
                            x, y = self.x0 + i * CELL, self.y0 + j * CELL
                            g = bc.game((x, y, self.H[j, i]))
                            idx[i, j] = len(verts)
                            verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, x / uvs, y / uvs))
                            jitter = 0.94 + 0.08 * vnoise(x, y, 23.0, 9)
                            cols.append(grey(self.shade[j, i] * jitter))
                        return idx[i, j]
                    for i, j in cl:
                        a, b, c, d = vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)
                        faces += [(a, b, c), (a, c, d)]
                    va, vb, vc = (verts[k] for k in faces[0])
                    if (vb.z - va.z) * (vc.x - va.x) - (vb.x - va.x) * (vc.z - va.z) < 0.0:
                        faces = [(p, r, q) for p, q, r in faces]
                    name = f"t{count:03d}{texname[0]}.mod"
                    scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
                        mod.Material(name=texname, vertex_start=0, vertex_end=len(verts),
                                     face_start=0, face_end=len(faces))])
                    scene.colours[name] = cols
                    scene.scenery.append(trackgen.SceneObject(name, GRASS, trackgen.NO_COLLISION))
                    kinds[texname] = kinds.get(texname, 0) + 1
                    count += 1
        return count, kinds


# ------------------------------------------------------------------ armco
def add_armco(scene, line):
    chunks = 0
    for side in (1.0, -1.0):
        run = 0.0
        for k0 in range(0, line.n, ARMCO_STEP):
            verts, cols, faces = [], [], []
            for k in range(k0, min(k0 + ARMCO_STEP, line.n) + 1):
                s = line.cum[k % line.n] if k < line.n else line.L
                (x, y, z), (tx, ty) = line.at(s)
                px, py = x - ty * side * (bc.WALL_OFFSET - 0.05), y + tx * side * (bc.WALL_OFFSET - 0.05)
                if k > k0:
                    run += math.hypot(px - last[0], py - last[1])
                last = (px, py)
                u = run / 4.0
                for h, v, c in ((ARMCO_H, 0.0, 1.0), (0.0, 1.0, 0.78)):
                    g = bc.game((px, py, z - 0.2 + h))
                    verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, u, v))
                    cols.append(grey(c))
            for q in range((len(verts) - 2) // 2):
                t0, b0, t1, b1 = 2 * q, 2 * q + 1, 2 * q + 2, 2 * q + 3
                faces += [(t0, b0, b1), (t0, b1, t1)]
            # face the road: the first quad's normal must point toward the centreline
            a, b, c = (verts[i] for i in faces[0])
            n = np.cross([b.x - a.x, b.y - a.y, b.z - a.z], [c.x - a.x, c.y - a.y, c.z - a.z])
            (x, y, z), _ = line.at(line.cum[k0])
            toward = np.array(bc.game((x, y, z))) - np.array([a.x, a.y, a.z])
            if np.dot(n, toward) < 0:
                faces = [(p, r, q) for p, q, r in faces]
            name = f"armco{chunks:03d}.mod"
            scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
                mod.Material(name="armco.tex", vertex_start=0, vertex_end=len(verts),
                             face_start=0, face_end=len(faces))])
            scene.colours[name] = cols
            scene.scenery.append(trackgen.SceneObject(name, GRASS, trackgen.NO_COLLISION))
            chunks += 1
    return chunks


# ------------------------------------------------------------------ vegetation
KINDS = {"pine.tex": (9.0, 15.0, 0.52), "oak.tex": (7.0, 11.0, 0.85), "bush.tex": (1.4, 2.4, 1.5)}


def place_vegetation(terr, line):
    trees = []
    rng = random.Random(11)
    tries = 0
    while tries < 26000:
        tries += 1
        x = rng.uniform(terr.x0 + 40, terr.x1 - 40); y = rng.uniform(terr.y0 + 40, terr.y1 - 40)
        i, j = int((x - terr.x0) / CELL), int((y - terr.y0) / CELL)
        d = terr.D[j, i]
        if d < bc.GRASS_EDGE + 6 or terr.slope[j, i] > 0.5:
            continue
        forest = vnoise(x, y, 180.0, 21)
        h = terr.H[j, i]
        if forest > 0.58 and rng.random() < (forest - 0.5) * 1.6:
            kind = "pine.tex" if (h > 6 or rng.random() < 0.6) else "oak.tex"
        elif d < 70 and rng.random() < 0.05:
            kind = "bush.tex"
        elif rng.random() < 0.012:
            kind = "oak.tex"
        else:
            continue
        lo, hi, aspect = KINDS[kind]
        trees.append((kind, x, y, terr.height(x, y) - 0.2, rng.uniform(lo, hi), aspect,
                      rng.uniform(0, 180), rng.uniform(0.82, 1.0)))
    return trees


def add_vegetation(scene, trees, block=320.0):
    groups = {}
    for t in trees:
        key = (t[0], int(t[1] // block), int(t[2] // block))
        groups.setdefault(key, []).append(t)
    chunks = 0
    for (kind, _, _), members in sorted(groups.items()):
        for start in range(0, len(members), MAX_VERTS // 16):
            verts, cols, faces = [], [], []
            for kind_, x, y, z, hgt, aspect, yaw, tone in members[start:start + MAX_VERTS // 16]:
                w = hgt * aspect / 2
                for plane in (yaw, yaw + 90.0):
                    ca, sa = math.cos(math.radians(plane)), math.sin(math.radians(plane))
                    base = len(verts)
                    for dx, dz, u, v, c in ((-w, 0, 0, 1, 0.62), (w, 0, 1, 1, 0.62), (w, hgt, 1, 0, 1.0), (-w, hgt, 0, 0, 1.0)):
                        g = bc.game((x + dx * ca, y + dx * sa, z + dz))
                        verts.append(mod.Vertex(g[0], g[1], g[2], 0.0, 1.0, 0.0, u, v))
                        cols.append(grey(c * tone))
                    faces += [(base, base + 1, base + 2), (base, base + 2, base + 3),     # both sides
                              (base, base + 2, base + 1), (base, base + 3, base + 2)]
            name = f"veg{chunks:03d}.mod"
            scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
                mod.Material(name=kind, vertex_start=0, vertex_end=len(verts),
                             face_start=0, face_end=len(faces))])
            scene.colours[name] = cols
            scene.scenery.append(trackgen.SceneObject(name, GRASS, trackgen.NO_COLLISION))
            chunks += 1
    return chunks


# ------------------------------------------------------------------ build
def main():
    raw = trackgen.read_centreline(HERE / "circuit.obj")
    pts = trackgen.resample(raw, 10.0, closed=True)
    line = bc.Line(pts)
    scene = trackgen.sweep(pts, bands=BANDS, road_half_width=bc.HALF, closed=True,
                           segment_length=SEGMENT)
    trackgen.add_checkpoints(scene, 4, half_width=bc.HALF)
    trackgen.add_grid(scene, 8)
    wall_quads = trackgen.add_walls(scene, offset=bc.WALL_OFFSET, height=1.5)

    terr = Terrain(line)
    if terr.worst >= 0:
        raise SystemExit(f"terrain pokes through the verge by {terr.worst:.2f} m")
    tiles, kinds = terr.emit(scene)
    trackgen.add_ground(scene, margin=MARGIN + 1600.0, drop=0.15 + bc.UNDER_GRASS)
    scene.colours["ground.mod"] = [grey(0.84)] * 4
    armco = add_armco(scene, line)
    trees = place_vegetation(terr, line)
    veg = add_vegetation(scene, trees)
    counts = {}
    for t in trees:
        counts[t[0]] = counts.get(t[0], 0) + 1

    # chevrons and targets, as proven in build_circuit
    for n, s in enumerate([1860 + 24 * k for k in range(6)]):
        (x, y, z), (tx, ty) = line.at(s)
        (_, _, _), (ax, ay) = line.at(s - 20)
        (_, _, _), (bx, by) = line.at(s + 20)
        turn_left = (ax * by - ay * bx) > 0
        side = -1.0 if turn_left else 1.0
        pos = (x - ty * side * 9.5, y + tx * side * 9.5, z)
        name = f"chev{n:02d}.mod"
        scene.meshes[name] = bc.chevron_mesh(bc.yaw_facing_traffic(tx, ty), arrow_right=not turn_left)
        scene.wobbles.append(trackgen.Wobble(position=pos, mesh=name, radius=0.5, height=2.5))
    for n, s in enumerate([2640 + 60 * k for k in range(6)]):
        (x, y, z), (tx, ty) = line.at(s)
        lat = 10.0 if n % 2 else -10.0
        hinge = (0.4, 0.55, 0.45, 0.6, 0.35, 0.5)[n]
        foot = (x - ty * lat, y + tx * lat, z)
        yaw = bc.yaw_facing_traffic(tx, ty)
        name = f"tgt{n:02d}.mod"
        v, f = disc(0.6)
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, bt.TEX_NAME)
        scene.wobbles.append(trackgen.Wobble(position=(foot[0], foot[1], z + hinge), mesh=name,
                                             radius=0.6, height=1.2))
        sv, sf = stick(0.0, hinge)
        g = bc.game(foot)
        gv = [mod.Vertex(vx + g[0], vy + g[1], vz + g[2], 0.0, 1.0, 0.0, u, w)
              for vx, vy, vz, u, w in turn(sv, yaw)]
        sname = f"stk{n:02d}.mod"
        scene.meshes[sname] = mod.Mesh(vertices=gv, faces=sf, materials=[
            mod.Material(name=bt.TEX_NAME, vertex_start=0, vertex_end=len(gv),
                         face_start=0, face_end=len(sf))])
        scene.scenery.append(trackgen.SceneObject(sname, GRASS, trackgen.NO_COLLISION))

    drawn = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    surfaces = sum(len(scene.meshes[nm].materials) for nm in drawn) + len(scene.wobbles)
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn)
    print(f"lap {line.L:.0f} m; terrain {tiles} chunks {kinds}; armco {armco} chunks; "
          f"vegetation {veg} chunks {counts}")
    print(f"surfaces per frame {surfaces} (budget {SURFACE_BUDGET}, pool 1,024); "
          f"largest chunk {biggest} verts (limit {MAX_VERTS}); terrain clearance under the verge "
          f"{-terr.worst:.2f} m")
    if surfaces > SURFACE_BUDGET or biggest > MAX_VERTS:
        raise SystemExit("over budget")

    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    res = trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot="limbo",
                              textures={t: "asph.tex" for t in wanted}, closed=True,
                              corridor=ili.corridor_for(bc.HALF * 2.0))
    print(f"assembled: {res.summary()}")

    # generated art over every texture, the sky, and our cameras
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    missing = sorted(t for t in wanted if t not in GENERATED)
    if missing:
        raise SystemExit(f"no generator for {missing}")
    for name in sorted(wanted):
        fn, mode = GENERATED[name]
        im = fn()
        a = np.array(im)
        if mode == "opaque" and int((a.sum(axis=2) == 0).sum()):
            raise SystemExit(f"{name} has black texels")
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), im.width, mode=mode, wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = art.sky()
    for tname, raw_tile in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw_tile)
        e = by[tname]
        e.tag, e.version, e.payload = enc.tag, enc.version, enc.payload
    cams = []
    for k in range(10):
        s = k * line.L / 10
        (x, y, z), (tx, ty) = line.at(s)
        (ax, ay, az), _ = line.at(s + 45)
        side = 1.0 if k % 2 == 0 else -1.0
        cam_src = (x - ty * side * 33.0, y + tx * side * 33.0, terr.height(x - ty * side * 33.0, y + tx * side * 33.0) + 6.0)
        gpos, gtgt = bc.game(cam_src), bc.game((ax, ay, az + 1.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    archive.write(ent, OUT)

    by = {e.name.lower(): e for e in archive.read(OUT)}
    for name in sorted(wanted) + list(sky.TILES):
        tex.parse(envelope.build(by[name].tag, by[name].version, by[name].payload))
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version, by["track.sol"].payload))
    ids = sorted(q.id for q in so.primitives if q.id >= 0)
    print(f"textures: {len(wanted)} generated + 4 sky tiles, all decode; wobbles {ids[0]}..{ids[-1]}; "
          f"{sum(1 for q in so.primitives if q.type == sol.BOX)} wall boxes; {len(cams)} cameras")
    if ids != list(range(12)):
        raise SystemExit("wobble ids wrong")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
