"""Horn-ball height gauge: posts of rising height, each with a firing line before it.

Seven stations along the ring, one post each on the centreline, tops at
0.4, 0.6 ... 1.6 m. A post is a proven stock-style wobble -- pivot at the foot,
collider a capsule reaching exactly the post's top -- with a small disc whose
TOP EDGE is that height, so what you see is what is solid.

A red line across the road sits FIRE_DIST before each post. Stop on it, honk,
and the post falls if the ball passes low enough. The ball spawns 3.5 m ahead of
the car and flies level, so from the line it travels only a few metres and has
barely dropped: the tallest post it knocks over and the shortest it clears
bracket its launch height (less the ball's ~0.3 m radius).
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_targets as bt  # noqa: E402
from build_sticks import disc, stick, merged, turn  # noqa: E402
from build_targets import archive, envelope, ili, mod, sol, tex, trackbuild, trackgen  # noqa: E402

OUT = bt.HERE / "limbo.trk"
TOPS = [0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]
FIRST = 80.0
SPACING = 80.0
FIRE_DIST = 8.0          # car's nose-to-post is about this less the car's front overhang
POST_R = 0.3             # collider radius: an easy aim from 8 m
DISC_R = 0.25
LINE_DEPTH = 0.6         # the firing line, along the road
LINE_Y = 0.03            # a hair above the asphalt
RED_UV = (0.5, 0.5)      # the bullseye's centre is red


def firing_line(centre, tx, ty, half_width):
    """A render-only red strip across the road, in the GAME frame, facing up."""
    nx, ny = -ty, tx
    corners = []
    for along, across in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        sx = centre[0] + tx * along * LINE_DEPTH / 2 + nx * across * half_width
        sy = centre[1] + ty * along * LINE_DEPTH / 2 + ny * across * half_width
        gx, gy, gz = trackgen.to_viper((sx, sy, 0.0), LINE_Y)
        corners.append(mod.Vertex(gx, gy, gz, 0.0, 1.0, 0.0, *RED_UV))
    faces = [(0, 1, 2), (0, 2, 3)]
    a, b, c = corners[0], corners[1], corners[2]
    ux, uz = b.x - a.x, b.z - a.z
    wx, wz = c.x - a.x, c.z - a.z
    if uz * wx - ux * wz < 0.0:                   # must face UP to be drawn from above
        faces = [(p, r, q) for p, q, r in faces]
    return corners, faces


def main():
    line = trackgen.resample(trackgen.read_centreline(bt.RING), 10.0, closed=True)
    scene = trackgen.sweep(line, road_half_width=bt.HALF_WIDTH, closed=True)
    trackgen.add_checkpoints(scene, 3, half_width=bt.HALF_WIDTH)
    trackgen.add_grid(scene, 8)
    pts = scene.centreline
    cum = [0.0]
    for p, q in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))

    def at(s):
        """Point and unit travel direction at arc length s, interpolated."""
        k = max(i for i in range(len(cum)) if cum[i] <= s)
        k = min(k, len(pts) - 2)
        f = (s - cum[k]) / (cum[k + 1] - cum[k])
        x = pts[k][0] + f * (pts[k + 1][0] - pts[k][0])
        y = pts[k][1] + f * (pts[k + 1][1] - pts[k][1])
        tx, ty = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
        L = math.hypot(tx, ty)
        return (x, y), (tx / L, ty / L)

    rows = []
    for n, top in enumerate(TOPS):
        s = FIRST + SPACING * n
        (x, y), (tx, ty) = at(s)
        yaw = math.degrees(math.atan2(tx, ty))
        name = f"tgt{n:02d}.mod"
        v, f = merged(disc(top - DISC_R), stick(0.0, top - DISC_R))
        # the generic disc is HEAD_R; scale it down to DISC_R about its own centre
        cy = top - DISC_R
        k = DISC_R / 0.6
        nd = 2 * (bt.SEG + 1)                     # disc verts come first in merged()
        v = [(vx * k, cy + (vy - cy) * k, vz, u, w) if i < nd else (vx, vy, vz, u, w)
             for i, (vx, vy, vz, u, w) in enumerate(v)]
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, bt.TEX_NAME)
        scene.wobbles.append(trackgen.Wobble(position=(x, y, 0.0), mesh=name,
                                             radius=POST_R, height=top))

        (lx, ly), (ltx, lty) = at(s - FIRE_DIST)
        lv, lf = firing_line((lx, ly), ltx, lty, bt.HALF_WIDTH - 0.5)
        lname = f"line{n:02d}.mod"
        scene.meshes[lname] = mod.Mesh(vertices=lv, faces=lf, materials=[
            mod.Material(name=bt.TEX_NAME, vertex_start=0, vertex_end=4,
                         face_start=0, face_end=2)])
        scene.scenery.append(trackgen.SceneObject(lname, trackgen.GRASS,
                                                  trackgen.NO_COLLISION))
        dot = sum(a * b for a, b in zip(bt.front_normal_world(scene.meshes[name]),
                                        (tx, 0.0, ty)))
        disc_top = max(-vv.z for vv in scene.meshes[name].vertices)
        rows.append((n, top, s, dot, disc_top))

    print("stations:")
    for n, top, s, dot, disc_top in rows:
        print(f"   {n + 1}  post top {top:.1f} m  (disc top {disc_top:.2f})  at {s:4.0f} m, "
              f"firing line at {s - FIRE_DIST:4.0f} m  facing dot {dot:+.3f}")
    if min(r[3] for r in rows) < 0.99 or any(abs(r[4] - r[1]) > 1e-3 for r in rows):
        raise SystemExit("a post faces the wrong way or its disc top is not its collider top")

    res = trackbuild.assemble(scene, donor=bt.DONOR, out_path=OUT, slot="limbo",
                              textures={bt.TEX_NAME: "asph.tex"}, closed=True,
                              corridor=ili.corridor_for(bt.HALF_WIDTH * 2.0))
    print(f"assembled: {res.summary()}")
    ent = archive.read(OUT)
    enc = envelope.parse(tex.encode_to_tex(bt.target_image().tobytes(), bt.SIZE,
                                           mode="opaque", wrap=0))
    e = next(x for x in ent if x.name.lower() == bt.TEX_NAME)
    e.tag, e.version, e.payload = enc.tag, enc.version, enc.payload
    archive.write(ent, OUT)

    by = {x.name.lower(): x for x in archive.read(OUT)}
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version,
                                  by["track.sol"].payload))
    bad = 0
    for q in sorted((q for q in so.primitives if q.id >= 0), key=lambda q: q.id):
        r, h = struct.unpack_from("<2f", q.raw, 0x58)
        good = q.type == sol.TUBE and abs(r + h - TOPS[q.id]) < 1e-4 and abs(q.position[1]) < 1e-6
        bad += not good
        print(f"   id {q.id}  radius {r:.2f}  solid 0..{r + h:.2f} m  {'ok' if good else 'WRONG'}")
    if bad:
        raise SystemExit("colliders wrong")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
