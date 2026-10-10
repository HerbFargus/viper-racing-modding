"""Boulder Lab: measure how track boulders behave, before designing the temple-canyon run.

A walled 1 km straight descent at 10 degrees (the down lane, 64 m wide) beside a return lane
climbing back up, flat plateaus and turns at both ends, and a 250 m runout at the bottom.

  * Five boulders sit 200 m uphill of the grid, side by side, released at race start:
      green   8 m, mass  1,000     yellow  8 m, mass  3,000     orange  8 m, mass 10,000
      red     8 m, mass 30,000     blue    4 m, mass  3,000
    Numbered boards every 100 m (distance from the boulders' start, measured down the slope)
    let you pace them and read your speedo, or time them.
  * A purple boulder sits beside the grid: if it has rolled ahead of you by the green flag, the
    physics runs during the countdown.

Everything is walled (.sol boxes 12 m tall, sunk 2 m) so the boulders stay in the down lane
until the bottom, where they run out onto the flat and stop wherever they stop.
"""
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ballroom"))
sys.path.insert(0, str(HERE.parent / "circuit"))
sys.path.insert(0, str(HERE.parent / "ballpit"))
import build_ballroom as B  # noqa: E402  (Batch, ball_mesh, bc, vrmod)
import build_ballpit as BP  # noqa: E402  (sunny_sky)
from build_river import delaunay  # noqa: E402
from art import colourise, tile_noise, to_img  # noqa: E402

bc = B.bc
from vrmod import archive, camtab, envelope, mod, obt as obt_mod, sky, tex, track, trackbuild, trackgen, trackmap  # noqa: E402

NAME = "BoulderLab"
OUT = HERE / f"{NAME}.trk"
DATA = B.DATA
SLOT = "hastings"
SEED = 1981

# ---- the slope (source frame: x east, y north, z up) ------------------------------------------
ANGLE = math.radians(10.0)
TAN = math.tan(ANGLE)
SLOPE_LEN = 1000.0
H = SLOPE_LEN * math.sin(ANGLE)                        # 173.6 m of drop
X1 = H / TAN                                           # where the slope meets the bottom (984.8)
BLEND = 30.0                                           # each end eases in over +-30 m

Y_DOWN, Y_RET, Y_MED = -35.0, 25.0, -3.0               # lane centres, and the median wall
Y_OUT_DOWN, Y_OUT_RET = -67.0, 45.0                    # outer walls
X_TOP_TURN, X_BOT_TURN, TURN_R = -76.3, 1063.7, 30.0   # turn centres (x = 3.7 mod 10: see below)
X_END_TOP, X_END_BOT = -120.0, 1250.0                  # end walls
WALL_H, WALL_SINK = 10.0, 2.0

START_X = 283.7                                        # the start line, on the down lane
BOULDER_X = 40.0                                       # the boulders' start
BOULDERS = [  # (colour, radius, mass, y)
    ((70, 170, 70), 4.0, 1000.0, Y_DOWN - 24.0),
    ((230, 200, 50), 4.0, 3000.0, Y_DOWN - 12.0),
    ((240, 130, 40), 4.0, 10000.0, Y_DOWN),
    ((210, 50, 50), 4.0, 30000.0, Y_DOWN + 12.0),
    ((60, 110, 220), 2.0, 3000.0, Y_DOWN + 24.0),
]
COUNTDOWN = ((150, 70, 200), 3.0, 3000.0, 252.0, Y_DOWN - 24.0)   # beside the grid
MAX_VERTS = B.MAX_VERTS


def z_of(x):
    """The floor's height: H on the top plateau, 10 degrees down to 0, flat at the bottom; each
    corner eased by a parabola so the slope changes smoothly."""
    if x <= -BLEND:
        return H
    if x <= BLEND:
        return H - TAN * (x + BLEND) ** 2 / (4 * BLEND)
    if x <= X1 - BLEND:
        return H - TAN * x
    if x <= X1 + BLEND:
        return TAN * (X1 + BLEND - x) ** 2 / (4 * BLEND)
    return 0.0


def slope_dist(x0, x1, n=4000):
    """Distance along the floor from x0 to x1."""
    xs = np.linspace(x0, x1, n)
    zs = np.array([z_of(x) for x in xs])
    return float(np.sum(np.hypot(np.diff(xs), np.diff(zs))))


def x_at_dist(d, x0=BOULDER_X):
    """The x reached d metres down the floor from x0."""
    lo, hi = x0, X_END_BOT
    for _ in range(40):
        mid = (lo + hi) / 2
        if slope_dist(x0, mid, 600) < d:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---- art -----------------------------------------------------------------------------------------
def floor_tex(size=256, seed=11):
    """Sandy stone with soft 16 m slabs -- low contrast (big floors shimmer with sharp edges)."""
    u = np.arange(size)[None, :] / size
    v = np.arange(size)[:, None] / size

    def seam(c):
        x = (c * 4) % 1.0
        return np.exp(-(np.minimum(x, 1 - x) / 0.05) ** 2)
    img = colourise(tile_noise(size, 8, 4, 0.55, seed), (170, 150, 116), (196, 176, 138))
    img = img * (1 - 0.14 * np.maximum(seam(u), seam(v))[..., None])
    return to_img(img)


def wall_tex(size=128, seed=21):
    img = colourise(tile_noise(size, 8, 3, 0.5, seed), (140, 138, 132), (170, 166, 158))
    v = np.arange(size)[:, None] / size
    img = np.where(np.broadcast_to((v > 0.08) & (v < 0.16), img.shape[:2])[..., None], [230, 190, 40], img)
    return to_img(img)


def rock_tex(rgb, size=128, seed=31):
    n = tile_noise(size, 8, 4, 0.55, seed)
    base = np.array(rgb, np.float32)
    img = base * (0.7 + 0.45 * n[..., None])
    return Image.fromarray(np.clip(img, 10, 255).astype(np.uint8))


def _font(px):
    for f in ("arialbd.ttf", "arial.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            continue
    return ImageFont.load_default()


def board_tex(text, size=256, px=150):
    im = Image.new("RGB", (size, size), (30, 34, 44))
    d = ImageDraw.Draw(im)
    d.rectangle([4, 4, size - 5, size - 5], outline=(230, 190, 40), width=8)
    f = _font(px)
    bb = d.textbbox((0, 0), text, font=f)
    d.text(((size - (bb[2] - bb[0])) / 2 - bb[0], (size - (bb[3] - bb[1])) / 2 - bb[1]), text,
           fill=(245, 245, 240), font=f)
    return im


def legend_tex(size=256):
    im = Image.new("RGB", (size, size), (30, 34, 44))
    d = ImageDraw.Draw(im)
    d.rectangle([4, 4, size - 5, size - 5], outline=(230, 190, 40), width=6)
    f = _font(24)
    rows = [("BOULDER LAB", (245, 245, 240))] + [
        (f"{r * 2:.0f} m  mass {m:,.0f}", c) for c, r, m, _y in BOULDERS] + [
        ("purple: countdown test", COUNTDOWN[0])]
    for i, (t, c) in enumerate(rows):
        d.text((16, 14 + i * 38), t, fill=tuple(int(v) for v in c) if i else c, font=f)
    return im


DISTS = list(range(100, 1201, 100))
TEXTURES = {"labflr.tex": floor_tex, "labwall.tex": wall_tex, "legend.tex": legend_tex,
            "chequer.tex": (lambda: B.Image.new("RGB", (8, 8), (240, 240, 240)))}
TEXTURES.update({f"d{d:04d}.tex": (lambda d=d: board_tex(str(d))) for d in DISTS})
TEXTURES.update({f"bld{k}.tex": (lambda c=c: rock_tex(c)) for k, (c, _r, _m, _y) in enumerate(BOULDERS)})
TEXTURES["bld5.tex"] = lambda: rock_tex(COUNTDOWN[0])


# ---- geometry --------------------------------------------------------------------------------------
def build_floor(scene):
    pts = []
    xs = sorted(set(list(np.arange(X_END_TOP, X_END_BOT + 0.1, 20.0))
                    + list(np.arange(-BLEND - 10, BLEND + 10.1, 5.0))
                    + list(np.arange(X1 - BLEND - 10, X1 + BLEND + 10.1, 5.0))))
    ys = list(np.arange(Y_OUT_DOWN, Y_OUT_RET + 0.1, 8.0)) + [Y_MED]
    for x in xs:
        for y in sorted(set(ys)):
            pts.append((float(x), float(y)))
    tris = delaunay(pts)
    floor = B.Batch(scene, "floor", "labflr.tex", True)
    for t in tris:
        P = [(pts[i][0], pts[i][1], z_of(pts[i][0])) for i in t]
        floor.tri(P, [(p[0] / 64.0, p[1] / 64.0) for p in P], 0.95)
    floor.flush()
    return len(tris)


def wall_line(scene, walls, drawn, a, b, step=10.0):
    """A wall from a to b: solid .sol boxes every `step` m (base sunk WALL_SINK, WALL_H above the
    floor), and a drawn double-sided concrete face."""
    ax, ay = a
    bx, by = b
    n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / step)))
    for k in range(n):
        x0, y0 = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
        x1, y1 = ax + (bx - ax) * (k + 1) / n, ay + (by - ay) * (k + 1) / n
        z0, z1 = z_of(x0), z_of(x1)
        walls.append([(x0, y0, z0 - WALL_SINK), (x1, y1, z1 - WALL_SINK), (x1, y1, z1 + WALL_H), (x0, y0, z0 + WALL_H)])
        q = [(x0, y0, z0 - 0.5), (x1, y1, z1 - 0.5), (x1, y1, z1 + WALL_H), (x0, y0, z0 + WALL_H)]
        uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        nx, ny = -(y1 - y0), (x1 - x0)
        for s in (1, -1):
            face = ((x0 + x1) / 2 + nx * s, (y0 + y1) / 2 + ny * s, (z0 + z1) / 2 + 5)
            drawn.tri([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], 0.85, up=face)
            drawn.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 0.85, up=face)


def board(scene, texname, x0, x1, y, face_y, lift=3.0, tall=6.0, stem=None):
    b = B.Batch(scene, stem or texname.split(".")[0], texname, False)
    z0, z1 = z_of(x0), z_of(x1)
    q = [(x0, y, z0 + lift), (x1, y, z1 + lift), (x1, y, z1 + lift + tall), (x0, y, z0 + lift + tall)]
    uv = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
    face = ((x0 + x1) / 2, face_y, (z0 + z1) / 2 + lift)
    b.tri([q[0], q[1], q[2]], [uv[0], uv[1], uv[2]], 1.0, up=face)
    b.tri([q[0], q[2], q[3]], [uv[0], uv[2], uv[3]], 1.0, up=face)
    b.flush()


def centreline():
    pts = []
    for x in np.arange(START_X, X_BOT_TURN + 0.01, 10.0):
        pts.append((float(x), Y_DOWN))
    cy = (Y_DOWN + Y_RET) / 2
    r = (Y_RET - Y_DOWN) / 2
    n = int(math.ceil(math.pi * r / 10.0))
    for k in range(1, n):
        a = -math.pi / 2 + math.pi * k / n
        pts.append((X_BOT_TURN + r * math.cos(a), cy + r * math.sin(a)))
    for x in np.arange(X_BOT_TURN, X_TOP_TURN - 0.01, -10.0):
        pts.append((float(x), Y_RET))
    for k in range(1, n):
        a = math.pi / 2 + math.pi * k / n
        pts.append((X_TOP_TURN + r * math.cos(a), cy + r * math.sin(a)))
    for x in np.arange(X_TOP_TURN, START_X - 0.01, 10.0):
        pts.append((float(x), Y_DOWN))
    return [(x, y, z_of(x)) for x, y in pts]


def main():
    pts = centreline()
    line = bc.Line(pts)
    scene = trackgen.TrackScene(centreline=list(pts))
    trackgen.add_checkpoints(scene, 4, half_width=26.0)
    grid = []
    for k in range(8):
        (gx, gy, _), (tx, ty) = line.at(line.L - 16.0 - 10.0 * (k // 2))
        lat = 5.0 if k % 2 else -5.0
        grid.append((gx - ty * lat, gy + tx * lat, z_of(gx - ty * lat)))
    scene.grid = grid
    nf = build_floor(scene)
    walls, drawn = [], B.Batch(scene, "wall", "labwall.tex", False)
    wall_line(scene, walls, drawn, (X_END_TOP, Y_OUT_DOWN), (X_END_BOT, Y_OUT_DOWN))
    wall_line(scene, walls, drawn, (X_END_TOP, Y_OUT_RET), (X_END_BOT, Y_OUT_RET))
    wall_line(scene, walls, drawn, (X_END_TOP, Y_OUT_DOWN), (X_END_TOP, Y_OUT_RET))
    wall_line(scene, walls, drawn, (X_END_BOT, Y_OUT_DOWN), (X_END_BOT, Y_OUT_RET))
    wall_line(scene, walls, drawn, (X_TOP_TURN, Y_MED), (X_BOT_TURN, Y_MED))
    drawn.flush()
    scene.walls = walls
    for d in DISTS:                                       # distance boards, both sides of the down lane
        x = x_at_dist(d)
        board(scene, f"d{d:04d}.tex", x + 7, x - 7, Y_OUT_DOWN + 0.15, Y_OUT_DOWN + 5, stem=f"bo{d:04d}")
        if x + 7 < X_BOT_TURN:
            board(scene, f"d{d:04d}.tex", x - 7, x + 7, Y_MED - 0.15, Y_MED - 5, stem=f"bm{d:04d}")
    board(scene, "legend.tex", 215.0, 230.0, Y_MED - 0.15, Y_MED - 5, lift=1.0, tall=15.0, stem="legend")
    trackgen.add_ground(scene, texture="labflr.tex", margin=600.0, drop=2.0)   # something beyond the walls
    scene.colours["ground.mod"] = [bytes([150, 150, 150, 255])] * 4
    sl = B.Batch(scene, "startln", "chequer.tex", False)
    x = START_X
    sl.tri([(x - 1.5, Y_OUT_DOWN, z_of(x - 1.5) + 0.05), (x + 1.5, Y_OUT_DOWN, z_of(x + 1.5) + 0.05),
            (x + 1.5, Y_MED, z_of(x + 1.5) + 0.05)], [(0, 0), (1, 0), (1, 1)], 1.0)
    sl.tri([(x - 1.5, Y_OUT_DOWN, z_of(x - 1.5) + 0.05), (x + 1.5, Y_MED, z_of(x + 1.5) + 0.05),
            (x - 1.5, Y_MED, z_of(x - 1.5) + 0.05)], [(0, 0), (1, 1), (0, 1)], 1.0)
    sl.flush()
    for k in range(len(BOULDERS) + 1):                   # anchors: boulder textures ship with the track
        a = B.Batch(scene, f"banc{k}", f"bld{k}.tex", False)
        a.tri([(0, -20, -5), (0.1, -20, -5), (0, -19.9, -5)], [(0.5, 0.5)] * 3, 1.0)
        a.flush()
    drawn_names = [o.name for o in scene.driveables + scene.scenery if o.name in scene.meshes]
    wanted = {m.materials[0].name for m in scene.meshes.values() if m.materials}
    biggest = max(len(scene.meshes[nm].vertices) for nm in drawn_names)
    collide = sum(len(scene.meshes[o.name].faces) for o in scene.driveables)
    print(f"slope {SLOPE_LEN:.0f} m at {math.degrees(ANGLE):.0f} deg ({H:.1f} m drop); lap {line.L:.0f} m; "
          f"floor triangles {nf}; walls {len(walls)} boxes; largest chunk {biggest}; collision {collide}")

    trackbuild.assemble(scene, donor=bc.DONOR, out_path=OUT, slot=SLOT,
                        textures={t: "asph.tex" for t in wanted}, closed=True, corridor=64.0)
    ent = archive.read(OUT)
    by = {e.name.lower(): e for e in ent}
    for name in sorted(wanted):
        a = np.array(TEXTURES[name]().convert("RGB"))
        a[..., :3] = np.maximum(a[..., :3], 6)
        enc = envelope.parse(tex.encode_to_tex(Image.fromarray(a).tobytes(), a.shape[1], mode="opaque", wrap=0))
        by[name].tag, by[name].version, by[name].payload = enc.tag, enc.version, enc.payload
    s_img = BP.sunny_sky()
    for tname, raw in zip(sky.TILES, sky.build_tiles(s_img.tobytes(), s_img.width, s_img.height, 256)):
        enc = envelope.parse(raw)
        by[tname].tag, by[tname].version, by[tname].payload = enc.tag, enc.version, enc.payload
    cams = []
    for cx, cy, tx_, ty_ in ((150.0, Y_OUT_DOWN + 4, BOULDER_X, Y_DOWN), (500.0, Y_OUT_DOWN + 4, 300.0, Y_DOWN),
                             (900.0, Y_OUT_DOWN + 4, 700.0, Y_DOWN), (1200.0, Y_OUT_DOWN + 4, 1000.0, Y_DOWN)):
        gpos = bc.game((cx, cy, z_of(cx) + 14.0))
        gtgt = bc.game((tx_, ty_, z_of(tx_) + 2.0))
        cams.append(camtab.Camera("fixed", *gpos, *camtab.aim(gpos, gtgt)))
    by["camera.tab"].payload = camtab.build(cams)
    specs = [(c, r, m, BOULDER_X, y) for c, r, m, y in BOULDERS] + [COUNTDOWN]
    for k, (_c, r, _m, _x, _y) in enumerate(specs):
        B.BALL_R = r
        mesh = B.ball_mesh(k, rings=10, segs=14, texture=f"bld{k}.tex")
        menv = envelope.parse(mod.build(mesh))
        ent.append(archive.ArchiveEntry(name=f"bld{k}.mod", tag=menv.tag, version=menv.version, payload=menv.payload))
    table = obt_mod.parse(envelope.build(by["track.obt"].tag, by["track.obt"].version, by["track.obt"].payload))
    recs = [r for r in table.records if r != obt_mod.TERMINATOR]
    for k, (_c, _r, m, x, y) in enumerate(specs):
        gx, _gh, gz = bc.game((x, y, 0.0))
        recs.append(f"obj obstacle ball bld{k}.mod {gx:.6f},{gz:.6f}:0.0 {m:.6f}")
    table.records = recs + [obt_mod.TERMINATOR]
    by["track.obt"].payload = envelope.parse(obt_mod.build(table)).payload
    archive.write(ent, OUT)
    trackmap.install(OUT, OUT)
    out = DATA / f"{NAME}.tra"
    track.export_tra(OUT, out, layout="flat")
    print(f"{out.name}: {len(specs)} boulders; {out.stat().st_size:,} bytes; grid from x "
          f"{min(g[0] for g in grid):.0f} to {max(g[0] for g in grid):.0f} (boulders at x {BOULDER_X:.0f})")


if __name__ == "__main__":
    main()
