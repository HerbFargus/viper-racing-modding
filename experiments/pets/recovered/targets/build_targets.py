"""Target-practice test 2: round targets on corrected capsules, square panels on BOX wobbles.

Round (the proven path): yaw baked into the vertices, now on a capsule sized to
the disc -- radius 1.2 reaching 2.4 m, where test 1 was a 0.23 m post that
stopped at 1.2 m because tube_at wrote the "radius" into the half-length field.

Square (the new path): a BOX collider bound to the wobble id, which no stock
track does, with the yaw carried by the wobble's frame rather than the mesh.

Back faces are plain grey on both, so a wrong heading shows.
"""
import math
import struct
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, r"C:/Users/seamus/Desktop/claude-code/viper-mod-manager")
from vrmod import archive, envelope, ili, mod, sol, tex, trackbuild, trackgen  # noqa: E402

HERE = Path(__file__).resolve().parent
RING = HERE.parent / "cli" / "ring.obj"
DONOR = Path("C:/Users/seamus/Desktop/claude-code/game-files/viper-racing-usa/Data/bemidji.trk")
OUT = HERE / "limbo.trk"

TEX_NAME = "target.tex"          # 8.3, no underscore
SQ_TEX = "tgtsq.tex"
SIZE = 64
GREY, RED, WHITE = (150, 150, 155), (205, 35, 35), (240, 240, 240)   # no black: the colour-key trap
BANDS = 5
SEG = 20
R_DISC = 1.2                     # 2.4 m across
GREY_UV = (0.03, 0.03)           # a corner of the texture, outside the circle
HALF_WIDTH = 6.0
TUBE_R = R_DISC                  # the capsule's top cap IS the disc's upper half
SQ_W = 2.4
SQ_THICK = 0.3

# (metres after the start line, lateral offset; + is the left of travel, shape)
TEST_TARGETS = [(60, -2.0, "round"), (100, 2.0, "square"), (140, -2.0, "round"),
                (180, 2.0, "square"), (220, -2.0, "round"), (260, 2.0, "square"),
                (300, -2.0, "round"), (340, 2.0, "square")]


def target_image():
    img = Image.new("RGB", (SIZE, SIZE), GREY)
    px = img.load()
    c, rad = (SIZE - 1) / 2.0, SIZE / 2.0
    for y in range(SIZE):
        for x in range(SIZE):
            d = math.hypot(x - c, y - c) / rad
            if d <= 1.0:
                k = min(BANDS - 1, int(d * BANDS))       # 0 is the bullseye
                px[x, y] = RED if k % 2 == 0 else WHITE
    return img


def square_image():
    img = Image.new("RGB", (SIZE, SIZE), GREY)
    px = img.load()
    c = (SIZE - 1) / 2.0
    for y in range(SIZE):
        for x in range(SIZE):
            d = max(abs(x - c), abs(y - c)) / (SIZE / 2.0)
            k = min(BANDS - 1, int(d * BANDS))
            px[x, y] = RED if k % 2 == 0 else WHITE
    return img


def to_facing(verts, faces, texname):
    out = [mod.Vertex(x, z, -y, 0.0, 0.0, 1.0, u, v) for x, y, z, u, v in verts]
    m = mod.Mesh(vertices=out, faces=faces, materials=[])
    m.materials = [mod.Material(name=texname, vertex_start=0, vertex_end=len(out),
                                face_start=0, face_end=len(faces))]
    return m


def target_mesh(yaw_deg):
    """A standing disc, foot at the origin, bullseye turned to heading `yaw`
    IN THE VERTICES (the frame stays the stock wobble matrix)."""
    verts, faces = [], []

    def add(x, y, z, u, v):
        verts.append((x, y, z, u, v))
        return len(verts) - 1

    h = R_DISC
    c = add(0.0, h, 0.0, 0.5, 0.5)
    rim = [add(R_DISC * math.cos(a), h + R_DISC * math.sin(a), 0.0,
               0.5 + 0.5 * math.cos(a), 0.5 - 0.5 * math.sin(a))
           for a in (2 * math.pi * i / SEG for i in range(SEG))]
    faces += [(c, rim[i], rim[(i + 1) % SEG]) for i in range(SEG)]
    cb = add(0.0, h, -0.02, *GREY_UV)
    rimb = [add(R_DISC * math.cos(a), h + R_DISC * math.sin(a), -0.02, *GREY_UV)
            for a in (2 * math.pi * i / SEG for i in range(SEG))]
    faces += [(cb, rimb[(i + 1) % SEG], rimb[i]) for i in range(SEG)]

    ps = math.radians(yaw_deg)
    cs, sn = math.cos(ps), math.sin(ps)
    turned = [(x * cs + z * sn, y, -x * sn + z * cs, u, v) for x, y, z, u, v in verts]
    return to_facing(turned, faces, TEX_NAME)


def square_mesh():
    """A 2.4 m square panel, foot at the origin, facing +Z UN-yawed: this one's
    frame carries the yaw, so model and box collider turn together."""
    verts, faces = [], []
    h = SQ_W / 2.0
    corners = ((-h, 0.0), (h, 0.0), (h, SQ_W), (-h, SQ_W))
    for z, uvs in ((0.0, [(0, 1), (1, 1), (1, 0), (0, 0)]), (-0.02, [GREY_UV] * 4)):
        base = len(verts)
        for (x, y), (u, v) in zip(corners, uvs):
            verts.append((x, y, z, u, v))
        if z == 0.0:     # front: counter-clockwise seen from +Z
            faces += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        else:            # back: reversed
            faces += [(base, base + 2, base + 1), (base, base + 3, base + 2)]
    return to_facing(verts, faces, SQ_TEX)


def front_normal_world(m, yaw=0.0):
    """Take the first front triangle through the wobble's frame to the world."""
    rows = sol.wobble_matrix(yaw)
    r = (rows[0:3], rows[3:6], rows[6:9])
    a, b, c = m.faces[0]

    def w(i):
        v = m.vertices[i]
        return tuple(v.x * r[0][k] + v.y * r[1][k] + v.z * r[2][k] for k in range(3))
    pa, pb, pc = w(a), w(b), w(c)
    u = [pb[k] - pa[k] for k in range(3)]
    t = [pc[k] - pa[k] for k in range(3)]
    n = (u[1]*t[2] - u[2]*t[1], u[2]*t[0] - u[0]*t[2], u[0]*t[1] - u[1]*t[0])
    L = math.sqrt(sum(q * q for q in n)) or 1.0
    return tuple(q / L for q in n)


def main():
    line = trackgen.resample(trackgen.read_centreline(RING), 10.0, closed=True)
    scene = trackgen.sweep(line, road_half_width=HALF_WIDTH, closed=True)
    trackgen.add_checkpoints(scene, 3, half_width=HALF_WIDTH)
    trackgen.add_grid(scene, 8)

    pts = scene.centreline                               # SOURCE frame
    cum = [0.0]
    for p, q in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))

    checks = []
    for n, (s, lat, shape) in enumerate(TEST_TARGETS):
        i = min(range(len(pts)), key=lambda k: abs(cum[k] - s))
        p0, p1 = pts[(i - 1) % len(pts)], pts[(i + 1) % len(pts)]
        tx, ty = p1[0] - p0[0], p1[1] - p0[1]
        L = math.hypot(tx, ty)
        tx, ty = tx / L, ty / L                          # direction of travel, source frame
        nx, ny = -ty, tx                                 # its left, source frame
        pos = (pts[i][0] + nx * lat, pts[i][1] + ny * lat, 0.0)
        # to_viper negates both ground axes, so travel in the game is (-tx, -ty);
        # facing the approaching car is (tx, ty). Confirmed in game, test 1.
        yaw = math.degrees(math.atan2(tx, ty))
        name = f"tgt{n:02d}.mod"
        if shape == "round":
            scene.meshes[name] = target_mesh(yaw)
            scene.wobbles.append(trackgen.Wobble(position=pos, mesh=name,
                                                 radius=TUBE_R, height=2 * R_DISC))
            f = front_normal_world(scene.meshes[name])
        else:
            scene.meshes[name] = square_mesh()
            scene.wobbles.append(trackgen.Wobble(
                position=pos, mesh=name, shape="box", width=SQ_W, height=SQ_W,
                thickness=SQ_THICK, yaw=yaw))
            f = front_normal_world(scene.meshes[name], yaw)
        want = (tx, 0.0, ty)
        checks.append((n, s, lat, shape, yaw, sum(a * b for a, b in zip(f, want))))

    print("self-check: does each front face the oncoming car? (1.0 = dead on)")
    for n, s, lat, shape, yaw, dot in checks:
        print(f"   target {n}  {s:>4} m  lateral {lat:+.0f} m  {shape:6}  yaw {yaw:+7.1f}"
              f"  facing dot {dot:+.3f}")
    if min(c[-1] for c in checks) < 0.99:
        raise SystemExit("a target is not facing the oncoming car -- refusing to build")

    img, sq = target_image(), square_image()
    blacks = sum(1 for im in (img, sq) for p in im.getdata() if p == (0, 0, 0))
    print(f"\ntextures: {SIZE}x{SIZE}, {blacks} pure-black pixels (must be 0)")
    if blacks:
        raise SystemExit("black pixels would hit the colour-key marker")

    res = trackbuild.assemble(scene, donor=DONOR, out_path=OUT, slot="limbo",
                              textures={TEX_NAME: "asph.tex", SQ_TEX: "asph.tex"},
                              closed=True, corridor=ili.corridor_for(HALF_WIDTH * 2.0))
    print(f"assembled: {res.summary()}")

    ent = archive.read(OUT)
    for nm, im in ((TEX_NAME, img), (SQ_TEX, sq)):
        enc = envelope.parse(tex.encode_to_tex(im.tobytes(), SIZE, mode="opaque", wrap=0))
        e = next(x for x in ent if x.name.lower() == nm)
        e.tag, e.version, e.payload = enc.tag, enc.version, enc.payload
    archive.write(ent, OUT)

    # verify the finished archive
    by = {x.name.lower(): x for x in archive.read(OUT)}
    p = envelope.parse(envelope.build(by["track.grf"].tag, by["track.grf"].version,
                                      by["track.grf"].payload)).payload
    ids, stack, seen = [], [struct.unpack_from("<3i", p, 0)[2]], set()
    while stack:
        off = stack.pop()
        while off and off not in seen and 12 <= off <= len(p) - 0x4c:
            seen.add(off)
            t, child, sib = struct.unpack_from("<3i", p, off)
            if t == 4 and struct.unpack_from("<i", p, off + 0x38)[0] == 4:
                ids.append(struct.unpack_from("<i", p, off + 0x48)[0])
            if child:
                stack.append(child)
            off = sib
    for nm in (TEX_NAME, SQ_TEX):
        tex.parse(envelope.build(by[nm].tag, by[nm].version, by[nm].payload))
    print(f"\nfacings in the .grf: {sorted(ids)}   both textures decode   "
          f"{OUT.name} {OUT.stat().st_size:,} bytes")
    if sorted(ids) != list(range(len(TEST_TARGETS))):
        raise SystemExit("facing ids wrong")

    so = sol.parse(envelope.build(by["track.sol"].tag, by["track.sol"].version,
                                  by["track.sol"].payload))
    print("colliders in the .sol:")
    bad = 0
    for q in sorted((q for q in so.primitives if q.id >= 0), key=lambda q: q.id):
        f4 = struct.unpack_from("<4f", q.raw, 0x58)
        kind = q.type.decode().strip()
        want = "TUBE" if TEST_TARGETS[q.id][2] == "round" else "BOX"
        dims = (f"radius {f4[0]:.2f}  half-length {f4[1]:.2f}  reaches {f4[0] + f4[1]:.2f} m"
                if kind == "TUBE" else
                f"half-extents {f4[0]:.2f} x {f4[1]:.2f} x {f4[2]:.2f}  max {f4[3]:.2f}")
        bad += kind != want
        print(f"   id {q.id}  {kind:4}  {dims}  {'ok' if kind == want else 'WRONG TYPE'}")
    if bad:
        raise SystemExit("collider types wrong")
    print("VERIFIED")


if __name__ == "__main__":
    main()
