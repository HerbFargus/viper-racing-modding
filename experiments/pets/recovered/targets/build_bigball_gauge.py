"""Big-ball gauge: hinged targets reshaped for a 3x horn ball.

A 3x ball (1.37 m radius) spawns 0.915 m higher than stock, so its centre should
cross the targets at about 1.6 m, against the stock ball's measured 0.6-0.8 m.
A hinged head tips only if that crossing is ABOVE the hinge (leverage) and on
the capsule's straight SIDE -- inside its axis segment, hinge +- half-length --
not on its rounded top, where the push points down the post.

Each station is one hinged head behind a red firing line. What varies:

  1  control   the range's design: hinge 0.5 m, 1.2 m head, capsule to its top
  2  high      hinge 1.0 m (a taller stick), capsule to the head's top
  3  high+     hinge 1.0 m, capsule reaching 0.6 m past the head's top
  4  higher    hinge 1.4 m, capsule to the head's top
  5  tall      hinge 0.5 m, a 1.2 x 2.4 m panel, capsule to its top
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_targets as bt  # noqa: E402
from build_gauge import firing_line  # noqa: E402
from build_sticks import stick, turn  # noqa: E402
from build_targets import archive, envelope, ili, mod, sol, tex, trackbuild, trackgen  # noqa: E402

OUT = bt.HERE / "limbo.trk"
FIRST, SPACING, FIRE_DIST = 80.0, 80.0, 8.0
BALL_CENTRE = 1.6          # predicted crossing height for the 3x ball
# (label, hinge, head width, head height, capsule reach above the head's top)
STATIONS = [("control", 0.5, 1.2, 1.2, 0.0),
            ("high",    1.0, 1.2, 1.2, 0.0),
            ("high+",   1.0, 1.2, 1.2, 0.6),
            ("higher",  1.4, 1.2, 1.2, 0.0),
            ("tall",    0.5, 1.2, 2.4, 0.0)]


def round_head(w):
    """A disc of diameter w, origin at its bottom edge, facing +Z, grey back."""
    r = w / 2.0
    verts, faces = [], []

    def add(x, y, z, u, v):
        verts.append((x, y, z, u, v))
        return len(verts) - 1
    c = add(0.0, r, 0.0, 0.5, 0.5)
    rim = [add(r * math.cos(a), r + r * math.sin(a), 0.0,
               0.5 + 0.5 * math.cos(a), 0.5 - 0.5 * math.sin(a))
           for a in (2 * math.pi * i / bt.SEG for i in range(bt.SEG))]
    faces += [(c, rim[i], rim[(i + 1) % bt.SEG]) for i in range(bt.SEG)]
    cb = add(0.0, r, -0.02, *bt.GREY_UV)
    rimb = [add(r * math.cos(a), r + r * math.sin(a), -0.02, *bt.GREY_UV)
            for a in (2 * math.pi * i / bt.SEG for i in range(bt.SEG))]
    faces += [(cb, rimb[(i + 1) % bt.SEG], rimb[i]) for i in range(bt.SEG)]
    return verts, faces


def panel(w, h):
    """A w x h panel, origin at its bottom edge, facing +Z, grey back."""
    corners = ((-w / 2, 0.0), (w / 2, 0.0), (w / 2, h), (-w / 2, h))
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

    def scenery(name, verts, faces):
        scene.meshes[name] = mod.Mesh(vertices=verts, faces=faces, materials=[
            mod.Material(name=bt.TEX_NAME, vertex_start=0, vertex_end=len(verts),
                         face_start=0, face_end=len(faces))])
        scene.scenery.append(trackgen.SceneObject(name, trackgen.GRASS,
                                                  trackgen.NO_COLLISION))

    rows = []
    for n, (label, hinge, w, h, extra) in enumerate(STATIONS):
        s = FIRST + SPACING * n
        (x, y), (tx, ty) = at(s)
        yaw = math.degrees(math.atan2(tx, ty))
        name = f"tgt{n:02d}.mod"
        if h == w:
            v, f = round_head(w)
            texname = bt.TEX_NAME
        else:
            v, f = panel(w, h)
            texname = bt.SQ_TEX
        r = w / 2.0
        reach = h + extra
        scene.meshes[name] = bt.to_facing(turn(v, yaw), f, texname)
        scene.wobbles.append(trackgen.Wobble(position=(x, y, hinge), mesh=name,
                                             radius=r, height=reach))
        sv, sf = stick(0.0, hinge)
        gx, _gy, gz = trackgen.to_viper((x, y, 0.0))
        scenery(f"stk{n:02d}.mod", [mod.Vertex(vx + gx, vy, vz + gz, 0.0, 1.0, 0.0, u, ww)
                                    for vx, vy, vz, u, ww in turn(sv, yaw)], sf)
        (lx, ly), (ltx, lty) = at(s - FIRE_DIST)
        lv, lf = firing_line((lx, ly), ltx, lty, bt.HALF_WIDTH - 0.5)
        scenery(f"line{n:02d}.mod", lv, lf)
        hl = max(reach - r, 0.0)
        seg = (hinge - hl, hinge + hl)
        side = seg[0] <= BALL_CENTRE <= seg[1]
        lever = BALL_CENTRE - hinge
        dot = sum(a * b for a, b in zip(bt.front_normal_world(scene.meshes[name]),
                                        (tx, 0.0, ty)))
        rows.append((n, label, hinge, w, h, reach, seg, side, lever, dot))

    print(f"stations (3x ball's centre predicted at {BALL_CENTRE} m):")
    for n, label, hinge, w, h, reach, seg, side, lever, dot in rows:
        print(f"   {n + 1} {label:8} hinge {hinge:.1f}  head {w:.1f}x{h:.1f} ({hinge:.1f}..{hinge + h:.1f})"
              f"  solid to {hinge + reach:.1f}  straight side {max(0, seg[0]):.1f}..{seg[1]:.1f}"
              f"  -> ball hits the {'SIDE' if side else 'rounded top'}, lever {lever:+.1f} m"
              f"  dot {dot:+.3f}")
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
    for q in sorted((q for q in so.primitives if q.id >= 0), key=lambda q: q.id):
        rr, hl = struct.unpack_from("<2f", q.raw, 0x58)
        _n, _l, hinge, w, _h, reach, *_ = rows[q.id]
        bad += not (q.type == sol.TUBE and abs(q.position[1] - hinge) < 1e-4
                    and abs(rr - w / 2) < 1e-4 and abs(q.position[1] + hl + rr - (hinge + reach)) < 1e-4)
    print(f"colliders: {'all as designed' if not bad else f'{bad} WRONG'}")
    if bad:
        raise SystemExit("colliders wrong")
    print(f"{OUT.name} {OUT.stat().st_size:,} bytes  VERIFIED")


if __name__ == "__main__":
    main()
