"""Targets on sticks: three collider strategies side by side, repeating in order.

  A  "stick"  the wobble is head + stick, pivot at the foot, collider = the stick
              (0.1 m radius, reaching the head's top). Stock style.
  B  "wide"   the same model, collider as wide as the head, all the way down.
  C  "flip"   the stick is render-only scenery; the wobble is the head alone,
              pivoting at its own centre in mid-air, on a near-sphere collider.

C is the experiment: no stock track pivots a wobble anywhere but its foot.
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_targets as bt  # noqa: E402
from build_targets import (archive, envelope, ili, mod, sol, tex,  # noqa: E402
                           trackbuild, trackgen)

OUT = bt.HERE / "limbo.trk"
HEAD_R = 0.6            # 1.2 m across
HEAD_Y = 2.0            # head centre height
STICK_W = 0.12
STICK_TOP = HEAD_Y      # runs up behind the head's centre
KINDS = ("stick", "wide", "flip")
N = 12                  # four of each
SPACING = 60.0
FLIP_HALF = 0.05        # a hair of cylinder: keeps collide_sphere_cylinder off a zero length


def disc(cy):
    """Head verts/faces (y-up, facing +Z), centred at height cy, with a grey back."""
    verts, faces = [], []

    def add(x, y, z, u, v):
        verts.append((x, y, z, u, v))
        return len(verts) - 1
    c = add(0.0, cy, 0.0, 0.5, 0.5)
    rim = [add(HEAD_R * math.cos(a), cy + HEAD_R * math.sin(a), 0.0,
               0.5 + 0.5 * math.cos(a), 0.5 - 0.5 * math.sin(a))
           for a in (2 * math.pi * i / bt.SEG for i in range(bt.SEG))]
    faces += [(c, rim[i], rim[(i + 1) % bt.SEG]) for i in range(bt.SEG)]
    cb = add(0.0, cy, -0.02, *bt.GREY_UV)
    rimb = [add(HEAD_R * math.cos(a), cy + HEAD_R * math.sin(a), -0.02, *bt.GREY_UV)
            for a in (2 * math.pi * i / bt.SEG for i in range(bt.SEG))]
    faces += [(cb, rimb[(i + 1) % bt.SEG], rimb[i]) for i in range(bt.SEG)]
    return verts, faces


def stick(y0, y1, zoff=-0.08):
    """A square post behind the head, y-up, four outward sides, grey."""
    h = STICK_W / 2.0
    verts, faces = [], []
    ring = [(-h, zoff - h), (h, zoff - h), (h, zoff + h), (-h, zoff + h)]
    for i in range(4):
        (xa, za), (xb, zb) = ring[i], ring[(i + 1) % 4]
        base = len(verts)
        for x, y, z in ((xa, y0, za), (xb, y0, zb), (xb, y1, zb), (xa, y1, za)):
            verts.append((x, y, z, *bt.GREY_UV))
        tri = [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        # outward = away from the post's axis; flip if the cross product points in
        a, b, c = (verts[j] for j in tri[0])
        u = [b[k] - a[k] for k in range(3)]
        w = [c[k] - a[k] for k in range(3)]
        nx = u[1] * w[2] - u[2] * w[1]
        nz = u[0] * w[1] - u[1] * w[0]
        mx, mz = (xa + xb) / 2.0, (za + zb) / 2.0 - zoff
        if nx * mx + nz * mz < 0:
            tri = [(p, r, q) for p, q, r in tri]
        faces += tri
    for a_, b_, c_ in faces:                      # every side must face outward
        a, b, c = verts[a_], verts[b_], verts[c_]
        u = [b[k] - a[k] for k in range(3)]
        w = [c[k] - a[k] for k in range(3)]
        nx, nz = u[1] * w[2] - u[2] * w[1], u[0] * w[1] - u[1] * w[0]
        mx = (a[0] + b[0] + c[0]) / 3.0
        mz = (a[2] + b[2] + c[2]) / 3.0 - zoff
        assert nx * mx + nz * mz > 0, "a stick side faces inward"
    return verts, faces


def merged(*parts):
    verts, faces = [], []
    for v, f in parts:
        base = len(verts)
        verts += v
        faces += [(a + base, b + base, c + base) for a, b, c in f]
    return verts, faces


def turn(verts, yaw):
    cs, sn = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    return [(x * cs + z * sn, y, -x * sn + z * cs, u, v) for x, y, z, u, v in verts]


def main():
    line = trackgen.resample(trackgen.read_centreline(bt.RING), 10.0, closed=True)
    scene = trackgen.sweep(line, road_half_width=bt.HALF_WIDTH, closed=True)
    trackgen.add_checkpoints(scene, 3, half_width=bt.HALF_WIDTH)
    trackgen.add_grid(scene, 8)
    pts = scene.centreline
    cum = [0.0]
    for p, q in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))

    rows = []
    for n in range(N):
        kind = KINDS[n % 3]
        s = 60.0 + SPACING * n
        lat = 2.5 if n % 2 else -2.5
        i = min(range(len(pts)), key=lambda k: abs(cum[k] - s))
        p0, p1 = pts[(i - 1) % len(pts)], pts[(i + 1) % len(pts)]
        tx, ty = p1[0] - p0[0], p1[1] - p0[1]
        L = math.hypot(tx, ty)
        tx, ty = tx / L, ty / L
        foot = (pts[i][0] - ty * lat, pts[i][1] + tx * lat, 0.0)
        yaw = math.degrees(math.atan2(tx, ty))
        name = f"tgt{n:02d}.mod"
        if kind in ("stick", "wide"):
            v, f = merged(disc(HEAD_Y), stick(0.0, STICK_TOP))
            scene.meshes[name] = bt.to_facing(turn(v, yaw), f, bt.TEX_NAME)
            scene.wobbles.append(trackgen.Wobble(
                position=foot, mesh=name,
                radius=0.1 if kind == "stick" else HEAD_R, height=HEAD_Y + HEAD_R))
        else:
            # the head alone, centred on its own middle -- which is where it pivots
            v, f = disc(0.0)
            scene.meshes[name] = bt.to_facing(turn(v, yaw), f, bt.TEX_NAME)
            scene.wobbles.append(trackgen.Wobble(
                position=(foot[0], foot[1], HEAD_Y), mesh=name,
                radius=HEAD_R, height=HEAD_R + FLIP_HALF))
            # the stick: render-only scenery in the GAME frame, stopping short of
            # the head's collider so nothing solid shares its space
            sv, sf = stick(0.0, HEAD_Y - HEAD_R - 0.05)
            gx, _gy, gz = trackgen.to_viper(foot)
            sname = f"stk{n:02d}.mod"
            gv = [mod.Vertex(x + gx, y, z + gz, 0.0, 1.0, 0.0, u, w)
                  for x, y, z, u, w in turn(sv, yaw)]
            scene.meshes[sname] = mod.Mesh(vertices=gv, faces=sf, materials=[
                mod.Material(name=bt.TEX_NAME, vertex_start=0, vertex_end=len(gv),
                             face_start=0, face_end=len(sf))])
            scene.scenery.append(trackgen.SceneObject(sname, trackgen.GRASS,
                                                      trackgen.NO_COLLISION))
        dot = sum(a * b for a, b in zip(bt.front_normal_world(scene.meshes[name]),
                                        (tx, 0.0, ty)))
        rows.append((n, kind, s, lat, yaw, dot))

    print("self-check: every head faces the oncoming car (1.0 = dead on)")
    for n, kind, s, lat, yaw, dot in rows:
        print(f"   {n:2}  {kind:5}  {s:4.0f} m  lateral {lat:+.1f}  yaw {yaw:+7.1f}  dot {dot:+.3f}")
    if min(r[-1] for r in rows) < 0.99:
        raise SystemExit("a head is not facing the oncoming car")

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
    print("colliders:")
    bad = 0
    for q in sorted((q for q in so.primitives if q.id >= 0), key=lambda q: q.id):
        r, h = struct.unpack_from("<2f", q.raw, 0x58)
        y = q.position[1]
        kind = KINDS[q.id % 3]
        want = {"stick": (0.1, 0.0), "wide": (HEAD_R, 0.0), "flip": (HEAD_R, HEAD_Y)}[kind]
        good = q.type == sol.TUBE and abs(r - want[0]) < 1e-4 and abs(y - want[1]) < 1e-4
        bad += not good
        print(f"   id {q.id:2}  {kind:5}  radius {r:.2f}  half-length {h:.2f}  "
              f"pivot {y:.2f} m up  solid {max(0.0, y - h - r):.2f}..{y + h + r:.2f} m"
              f"  {'ok' if good else 'WRONG'}")
    if bad:
        raise SystemExit("colliders wrong")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
