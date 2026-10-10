"""Target practice: 24 hinged heads scattered round the ring, facing oncoming traffic.

The design every gauge agreed on: a 1.2 m head hinged at its bottom edge, on a
capsule as wide as the head running from the ground to its top, over a
render-only stick. Hinges between 0.2 and 1.0 m all go over when the horn ball
hits (it arrives 0.6-0.8 m off the road), so each target draws its hinge from
that range. Round and square heads are mixed; a square gets a slightly taller
capsule so the rounded top reaches most of its corners.
"""
import math
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_targets as bt  # noqa: E402
from build_sticks import HEAD_R, disc, stick, turn  # noqa: E402
from build_targets import archive, envelope, ili, mod, sol, tex, trackbuild, trackgen  # noqa: E402

OUT = bt.HERE / "limbo.trk"
N_TARGETS = 24
SEED = 23
HINGE_RANGE = (0.3, 0.8)     # inside the 0.2-1.0 m that all tipped in game
LATERAL = 4.0                # metres either side of the centreline
SQ_EXTRA = 0.12              # a square's capsule overshoots its top to catch the corners


def square_head():
    """A 1.2 m square panel, origin at its bottom edge, facing +Z, grey back."""
    h = HEAD_R
    corners = ((-h, 0.0), (h, 0.0), (h, 2 * h), (-h, 2 * h))
    verts, faces = [], []
    for z, uvs in ((0.0, [(0, 1), (1, 1), (1, 0), (0, 0)]), (-0.02, [bt.GREY_UV] * 4)):
        base = len(verts)
        for (x, y), (u, v) in zip(corners, uvs):
            verts.append((x, y, z, u, v))
        faces += ([(base, base + 1, base + 2), (base, base + 2, base + 3)] if z == 0.0
                  else [(base, base + 2, base + 1), (base, base + 3, base + 2)])
    return verts, faces


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

    rng = random.Random(SEED)
    lap = cum[-1]
    span = (lap - 60.0 - 50.0) / N_TARGETS
    rows = []
    for n in range(N_TARGETS):
        s = 60.0 + span * (n + 0.5) + rng.uniform(-0.3, 0.3) * span
        lat = round(rng.uniform(-LATERAL, LATERAL), 1)
        hinge = round(rng.uniform(*HINGE_RANGE), 2)
        shape = rng.choice(("round", "square"))
        (cx, cy), (tx, ty) = at(s)
        x, y = cx - ty * lat, cy + tx * lat
        yaw = math.degrees(math.atan2(tx, ty))
        name = f"tgt{n:02d}.mod"
        if shape == "round":
            v, f = disc(HEAD_R)
            texname, reach = bt.TEX_NAME, 2 * HEAD_R
        else:
            v, f = square_head()
            texname, reach = bt.SQ_TEX, 2 * HEAD_R + SQ_EXTRA
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, texname)
        scene.wobbles.append(trackgen.Wobble(position=(x, y, hinge), mesh=name,
                                             radius=HEAD_R, height=reach))
        sv, sf = stick(0.0, hinge)
        gx, _gy, gz = trackgen.to_viper((x, y, 0.0))
        gv = [mod.Vertex(vx + gx, vy, vz + gz, 0.0, 1.0, 0.0, u, w)
              for vx, vy, vz, u, w in turn(sv, yaw)]
        sname = f"stk{n:02d}.mod"
        scene.meshes[sname] = mod.Mesh(vertices=gv, faces=sf, materials=[
            mod.Material(name=bt.TEX_NAME, vertex_start=0, vertex_end=len(gv),
                         face_start=0, face_end=len(sf))])
        scene.scenery.append(trackgen.SceneObject(sname, trackgen.GRASS,
                                                  trackgen.NO_COLLISION))
        dot = sum(a * b for a, b in zip(bt.front_normal_world(scene.meshes[name]),
                                        (tx, 0.0, ty)))
        rows.append((n, s, lat, hinge, shape, reach, dot))

    print(f"lap {lap:.0f} m, {N_TARGETS} targets about {span:.0f} m apart")
    for n, s, lat, hinge, shape, reach, dot in rows:
        print(f"   {n:2}  {s:6.0f} m  lateral {lat:+.1f}  {shape:6}  hinge {hinge:.2f}  "
              f"head {hinge:.2f}..{hinge + 2 * HEAD_R:.2f}  dot {dot:+.3f}")
    if min(r[-1] for r in rows) < 0.99:
        raise SystemExit("a head faces the wrong way")

    res = trackbuild.assemble(scene, donor=bt.DONOR, out_path=OUT, slot="limbo",
                              textures={bt.TEX_NAME: "asph.tex", bt.SQ_TEX: "asph.tex"},
                              closed=True, corridor=ili.corridor_for(bt.HALF_WIDTH * 2.0))
    print(f"assembled: {res.summary()}")
    ent = archive.read(OUT)
    for nm, im in ((bt.TEX_NAME, bt.target_image()), (bt.SQ_TEX, bt.square_image())):
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), bt.SIZE, mode="opaque", wrap=0))
        e = next(x for x in ent if x.name.lower() == nm)
        e.tag, e.version, e.payload = enc.tag, enc.version, enc.payload
    archive.write(ent, OUT)

    by = {x.name.lower(): x for x in archive.read(OUT)}
    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version,
                                  by["track.sol"].payload))
    bad = 0
    for q in (q for q in so.primitives if q.id >= 0):
        r, h = struct.unpack_from("<2f", q.raw, 0x58)
        _n, _s, _lat, hinge, _shape, reach, _dot = rows[q.id]
        y = q.position[1]
        bad += not (q.type == sol.TUBE and abs(y - hinge) < 1e-4
                    and abs(y + h + r - (hinge + reach)) < 1e-4 and y - h - r <= 0.0)
    ids = sorted(q.id for q in so.primitives if q.id >= 0)
    print(f"colliders: {len(ids)} wobble tubes, ids {ids[0]}..{ids[-1]}, "
          f"{'all reach the ground and the head top' if not bad else f'{bad} WRONG'}")
    if bad or ids != list(range(N_TARGETS)):
        raise SystemExit("colliders wrong")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
