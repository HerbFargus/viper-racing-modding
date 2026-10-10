"""Hinge-height gauge: the same hinged head at five hinge heights, one per station.

Each station is the design that worked in game -- a 1.2 m head hinged at its
bottom edge, on a capsule as wide as the head reaching its top, with a
render-only stick below -- lowered in 0.2 m steps. A red firing line sits
FIRE_DIST before each.

The head turns only for hits AWAY from the hinge (file-formats.md §4.3), and
which way says where the ball was:

    tips BACK      the ball struck above the hinge
    tips FORWARD   it struck the capsule below the hinge
    barely moves   it struck close to the hinge
    untouched      it went over the head

The post gauge showed the ball reaching every post 0.8 m and taller from 8 m.
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_targets as bt  # noqa: E402
from build_gauge import firing_line  # noqa: E402
from build_sticks import HEAD_R, disc, stick, turn  # noqa: E402
from build_targets import archive, envelope, ili, mod, sol, tex, trackbuild, trackgen  # noqa: E402

OUT = bt.HERE / "limbo.trk"
HINGES = [0.2, 0.4, 0.6, 0.8, 1.0]
FIRST = 80.0
SPACING = 80.0
FIRE_DIST = 8.0


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
        k = min(max(i for i in range(len(cum)) if cum[i] <= s), len(pts) - 2)
        f = (s - cum[k]) / (cum[k + 1] - cum[k])
        x = pts[k][0] + f * (pts[k + 1][0] - pts[k][0])
        y = pts[k][1] + f * (pts[k + 1][1] - pts[k][1])
        tx, ty = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
        L = math.hypot(tx, ty)
        return (x, y), (tx / L, ty / L)

    def scenery(name, verts, faces):
        scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
            mod.Material(name=bt.TEX_NAME, vertex_start=0, vertex_end=len(verts),
                         face_start=0, face_end=len(faces))])
        scene.scenery.append(trackgen.SceneObject(name, trackgen.GRASS,
                                                  trackgen.NO_COLLISION))

    rows = []
    for n, hinge in enumerate(HINGES):
        s = FIRST + SPACING * n
        (x, y), (tx, ty) = at(s)
        yaw = math.degrees(math.atan2(tx, ty))
        name = f"tgt{n:02d}.mod"
        v, f = disc(HEAD_R)                               # origin at the head's bottom edge
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, bt.TEX_NAME)
        scene.wobbles.append(trackgen.Wobble(position=(x, y, hinge), mesh=name,
                                             radius=HEAD_R, height=2 * HEAD_R))
        sv, sf = stick(0.0, hinge)
        gx, _gy, gz = trackgen.to_viper((x, y, 0.0))
        scenery(f"stk{n:02d}.mod",
                [mod.Vertex(vx + gx, vy, vz + gz, 0.0, 1.0, 0.0, u, w)
                 for vx, vy, vz, u, w in turn(sv, yaw)], sf)
        (lx, ly), (ltx, lty) = at(s - FIRE_DIST)
        lv, lf = firing_line((lx, ly), ltx, lty, bt.HALF_WIDTH - 0.5)
        scenery(f"line{n:02d}.mod", lv, lf)
        dot = sum(a * b for a, b in zip(bt.front_normal_world(scene.meshes[name]),
                                        (tx, 0.0, ty)))
        rows.append((n, hinge, s, dot))

    print("stations (head is 1.2 m across, standing on its hinge):")
    for n, hinge, s, dot in rows:
        print(f"   {n + 1}  hinge {hinge:.1f} m  head {hinge:.1f}..{hinge + 2 * HEAD_R:.1f} m  "
              f"at {s:4.0f} m, line at {s - FIRE_DIST:4.0f} m  facing dot {dot:+.3f}")
    if min(r[3] for r in rows) < 0.99:
        raise SystemExit("a head faces the wrong way")

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
        y = q.position[1]
        good = (q.type == sol.TUBE and abs(y - HINGES[q.id]) < 1e-4
                and abs(y + h + r - (HINGES[q.id] + 2 * HEAD_R)) < 1e-4)
        bad += not good
        print(f"   id {q.id}  hinge {y:.2f} m  solid {max(0.0, y - h - r):.2f}..{y + h + r:.2f} m"
              f"  {'ok' if good else 'WRONG'}")
    if bad:
        raise SystemExit("colliders wrong")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
