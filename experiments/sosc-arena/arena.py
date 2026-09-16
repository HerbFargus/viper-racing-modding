"""Preview a Streets of SimCity scenario city as a textured OBJ, at true scale.

Phase 1 of the arena track: before anything becomes a Viper track, the city has
to look like the city. This builds the ground, the roads and the props from the
player's own SoSC install and writes arena.obj + arena.mtl + PNG textures that
any OBJ viewer (and view.html beside it) can show next to in-game screenshots.

    python arena.py <sosc_dir> <city.sc2> <out_dir>

WHAT COMES FROM WHERE
    terrain   ALTM altitude + XTER slope codes; one level is measured, not
              guessed -- see level_height()
    roads     SC2K road tiles are NOT meshes in SoSC. They are textured ground
              quads: straight #78, T-junction #80 and crossing #81 in SIM3D.BMP
    ground    a grass cell of SKY.BMP's terrain sheet (#4); skirts use a dirt cell
    props     SoSC's own models, found by SC2K tile id in the SIM3D*.MAX name
              table (AP225 the tower, CO124, IN132)
    trees     tile ids 6-12: SoSC's green-keyed tree sprites (#30-#33), drawn
              here as crossed quads because OBJ has no billboards
    cows      SIM3D1.MAX object #162 -- not in the name table; SoSC spawns them
              at runtime, so where they stand is this script's choice

SCALE: a SimCity 2000 tile is 16 m and SoSC stores 262,144 units per metre
(CahootsMalone's maxis-mesh-stuff notes); BASE1X1R measures exactly 16.00 m.
"""
from __future__ import annotations

import math
import random
import re
import shutil
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "sosc-to-viper"))

import sc2                                                  # noqa: E402
import max2obj                                              # noqa: E402
import build_car                                            # noqa: E402
import missile                                              # noqa: E402

from PIL import Image, ImageChops                           # noqa: E402

UNITS_PER_M = 262144.0
TILE = sc2.TILE_M
PAD = 3                     # tiles of plain ground kept around the built-up area

ROAD_TEX = {"straight": 78, "tee": 80, "cross": 81, "diag": 79}
# SC2K road id -> (texture, quarter turns). The unturned straight runs along +y;
# the unturned tee is closed on -x. A "corner" (35-38) is not a bend: in this
# city they draw the diagonal edges of the floor's centre diamond, so they take
# #79, the diagonal road with a pavement triangle. (The ring's own corners are
# crossings, id 43 -- the ring roads run one tile past them, confirmed against
# an in-game shot of the gas station corner.)
ROADS = {
    29: ("straight", 0), 30: ("straight", 1),
    31: ("straight", 1), 32: ("straight", 0), 33: ("straight", 1), 34: ("straight", 0),
    # half a turn from the first guess: the road half of #79 belongs against the
    # asphalt floor and the pavement triangle against the grass mound
    35: ("diag", 2), 36: ("diag", 3), 37: ("diag", 0), 38: ("diag", 1),
    39: ("tee", 3), 40: ("tee", 0), 41: ("tee", 1), 42: ("tee", 2),
    43: ("cross", 0),
}

# XTER code -> corners raised one level, as (sx, sy) signs. Learned from
# Arena.sc2 itself: for every tile of each code, which neighbours sit a level
# higher (code 1 always has its -x neighbour higher, and so on).
_ALL = {(-1, -1), (1, -1), (1, 1), (-1, 1)}
RAISE = {
    0: set(),
    1: {(-1, -1), (-1, 1)}, 2: {(-1, -1), (1, -1)},
    3: {(1, -1), (1, 1)}, 4: {(-1, 1), (1, 1)},
    5: _ALL - {(1, 1)}, 6: _ALL - {(-1, 1)}, 7: _ALL - {(-1, -1)}, 8: _ALL - {(1, -1)},
    9: {(-1, -1)}, 10: {(1, -1)}, 11: {(1, 1)}, 12: {(-1, 1)},
    13: set(_ALL),
}

PROPS = {225: ("SIM3D1.MAX", "AP225"), 124: ("SIM3D3.MAX", "CO124"),
         132: ("SIM3D2.MAX", "IN132")}
TREE_IDS = range(6, 13)
TREE_TEX = (30, 31, 32, 33)
COW = ("SIM3D1.MAX", 162)
COW_COUNT = 200              # over the whole map; SoSC scatters them freely
# Ground: SKY.BMP #4 (identical to TILED1.BMP, which the game loads) is an 8x8
# sheet of 32 px terrain cells, in sets:
#     0-9    water              10-15  rubble
#     16-31  dirt / water       32-47  grass / dirt      48-63  sand / grass
# Each blended set opens with its solid material and follows with transition
# art -- edges, corners, diagonals -- for tiling one material into the next.
# In game the pattern follows the SHAPE of the land: flat ground is grass (the
# berm top along the perimeter), sloped ground is tan sand (the berm faces, the
# mound sides), and the change happens across the tiles where they meet. Two
# earlier guesses -- a random cell per tile, then a smooth fade between two
# cells -- looked nothing like it, because the game draws its own transition art.
SAND_SET = range(48, 64)
GRASS_SOLID = 32
# The dark grass patches: whole tiles of a grass cell with a blue-grey blob in
# it. Not on the #4 sheet -- SKY.BMP #5 is a second terrain sheet (rock, snow,
# plain grass) and the patch is its cell 52.
PATCH_PAGE, PATCH_CELL = 5, 52
DARK_DENSITY = 0.12          # share of solid-grass tiles that take it
# SoSC's slopes are not planes: the berm faces and mound sides are jagged and
# bumpy, and their skyline is lumpy in game. One quad per sloped tile gave a
# smooth ramp that read as a different place. So a sloped ground tile is split
# into BUMP_DIV x BUMP_DIV quads with its inner points lifted by a noise keyed
# to WORLD position -- two neighbouring slope tiles agree on their shared edge --
# and any point touching a flat or road tile stays on the straight line, so
# nothing cracks where the bumps stop. The amplitude is judged from screenshots.
# Broad and low: a slope still reads as a slope and stays drivable, with a few
# low-poly facets rather than a rough surface. The first pass -- 4 m facets at
# +-1.6 m -- looked like rubble.
BUMP_DIV = 2                 # 8 m facets
BUMP_AMP = 0.8               # metres, peak either way


def bump_noise(a: int, b: int) -> float:
    """Deterministic value in [-1, 1] for a lattice point."""
    n = (a * 374761393 + b * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 32767.5 - 1.0
DIRT_CELL = (2, 0)


class Obj:
    """Accumulates an OBJ: positions, uvs, and faces grouped by material."""

    def __init__(self):
        self.v, self.vt = [], []
        self.faces: dict[str, list] = {}

    def face(self, mat: str, pts, uvs):
        base_v, base_t = len(self.v), len(self.vt)
        self.v.extend(pts)
        self.vt.extend(uvs)
        self.faces.setdefault(mat, []).append(
            [(base_v + i + 1, base_t + i + 1) for i in range(len(pts))])

    def write(self, out: Path, mtl: dict[str, str]):
        L = ["mtllib arena.mtl"]
        L += [f"v {x:.3f} {y:.3f} {z:.3f}" for x, y, z in self.v]
        L += [f"vt {u:.5f} {v:.5f}" for u, v in self.vt]
        for mat, fs in self.faces.items():
            L.append(f"usemtl {mat}")
            L += ["f " + " ".join(f"{a}/{b}" for a, b in f) for f in fs]
        (out / "arena.obj").write_text("\n".join(L) + "\n", encoding="utf-8")
        M = []
        for mat, png in mtl.items():
            M += [f"newmtl {mat}", "Kd 1 1 1", f"map_Kd {png}", ""]
        (out / "arena.mtl").write_text("\n".join(M), encoding="utf-8")


def level_height(geo: Path) -> float:
    """Metres per terrain level, measured off SoSC's own slope rail (RL46).

    A slope rail climbs exactly one level across its tile: its top runs 0.42 m
    above the ground at the low edge and one level + 0.42 m at the high edge.
    """
    blob = (geo / "SIM3D2.MAX").read_bytes()
    addr, nf, nv = max2obj.models(blob)["RL46"]
    verts = max2obj.read_model(blob, addr, nf, nv)[0]
    lo = max(v[1] for v in verts if v[0] / UNITS_PER_M > 6.0)
    hi = max(v[1] for v in verts if v[0] / UNITS_PER_M < -6.0)
    return (hi - lo) / UNITS_PER_M


def alt_height(a: int, level: float, base: int) -> float:
    """Metres above zero for altitude level `a`: a halfpipe, not a staircase.

    In game the berm rises like a low-poly halfpipe -- the first level off the
    floor is a gentle grass ramp, the next is steeper, the top steepest -- where
    equal 7.92 m steps gave three identical ramps. So the k-th level above the
    base rises k/2 of a level: 0.5, 1.0, 1.5, ... The berm (3 levels) keeps its
    full 3-level height, and a 1-level island becomes a gentle 4 m mound. Below
    the base the steps stay even. The k/2 shape is judged from screenshots.
    """
    n = a - base
    if n <= 0:
        return a * level
    return (base + n * (n + 1) / 4) * level


def _tile_corner_level(city, tx, ty, s) -> int:
    """The level tile (tx, ty) itself gives its corner `s`."""
    up = RAISE.get(city.grids["XTER"][tx][ty] & 0x0F, set())
    return city.altitude[tx][ty] + (1 if s in up else 0)


def corner_heights(city, x, y, level):
    """Height of each corner of tile (x, y).

    Only TERRAIN takes the halfpipe profile. A road is a straight slope in game:
    a ramp climbs even 7.92 m levels, the height SoSC's own slope rail and road
    pieces are built to. So any corner a road tile touches sits at the even
    height, and the ground around it bends to meet the road rather than leaving
    a step at the kerb. The two profiles agree at the floor and at the ring.

    ONE HEIGHT PER GRID CORNER for terrain. A SimCity 2000 city does not always
    agree with itself: at the berm's outer corners, tiles sharing a corner name
    different levels for it (15 corners in Arena.sc2, and no other reading of
    the slope codes removes them -- checked by fitting every code). Built as
    per-tile corners, each one became a cliff, and the halfpipe profile stretched
    the cliff walls into spikes. Terrain corners now take the highest level any
    of their tiles gives, so the ground is continuous. Corners touching a road
    keep each tile's own level: there the step is real -- the sides of the floor
    jumps are exactly such cliffs, drawn in game as concrete walls.
    """
    B = city.grids["XBLD"]
    out = {}
    for s in _ALL:
        gx, gy = x + (s[0] + 1) // 2, y + (s[1] + 1) // 2
        owners = [(tx, ty) for tx in (gx - 1, gx) for ty in (gy - 1, gy)
                  if 0 <= tx < sc2.SIZE and 0 <= ty < sc2.SIZE]
        if any(B[tx][ty] in ROADS for tx, ty in owners):
            out[s] = _tile_corner_level(city, x, y, s) * level
        else:
            lv = max(_tile_corner_level(city, tx, ty, (2 * (gx - tx) - 1, 2 * (gy - ty) - 1))
                     for tx, ty in owners)
            out[s] = alt_height(lv, level, city.base_level)
    return out


def rotate_uv(u, v, quarter):
    for _ in range(quarter % 4):
        u, v = 1 - v, u
    return u, v


def save(img: Image.Image, out: Path, name: str, mtl: dict, key_green=False) -> str:
    if name not in mtl:
        if key_green:
            img = img.convert("RGBA")
            img.putdata([(r, g, b, 0) if (g > 200 and r < 60 and b < 60) else (r, g, b, 255)
                         for r, g, b, _ in img.getdata()])
        img.save(out / "tex" / f"{name}.png")
        mtl[name] = f"tex/{name}.png"
    return name


def atlas_image(atl, pal, index):
    w, h, px = atl[index]
    im = Image.frombytes("P", (w, h), px)
    im.putpalette(bytes(c for rgb in pal for c in rgb))
    return im.convert("RGB")


def cell(img: Image.Image, row: int, col: int, px=32):
    return img.crop((col * px, row * px, (col + 1) * px, (row + 1) * px))


AUTOTILE_IDS = set(range(39, 44))      # T-junctions and crossings


def autotile_image(tee: Image.Image, cross: Image.Image, road, x, y) -> tuple[str, Image.Image]:
    """A junction tile fitted to its neighbours, the way SoSC draws paving.

    The open floor -- 943 crossing tiles -- carries a regular grid of grey
    panels, one where every four crossing tiles meet, which is #81's corner
    squares repeated. What #81 alone gets wrong is the EDGE: where the paving
    meets grass or a ramp, the game draws a kerb. So each quarter of the tile is
    chosen from what touches that corner:
        both sides road                     grey panel quarter (a quarter of #81)
        one side not road                   straight kerb along that side
        neither side road                   the two kerbs together
    (A pass that left interior quarters as plain asphalt stripped the panels off
    the floor.)
    `road(x, y)` says whether a tile is paved. +x is image right, +y image top.
    """
    H = 64
    plain = cross.crop((32, 32, 32 + H, 32 + H))
    kerb_left = tee.crop((0, 32, H, 32 + H))
    kerb = {
        (-1, 0): kerb_left,
        (1, 0): kerb_left.transpose(Image.FLIP_LEFT_RIGHT),
        (0, 1): kerb_left.transpose(Image.ROTATE_270),
        (0, -1): kerb_left.transpose(Image.ROTATE_270).transpose(Image.FLIP_TOP_BOTTOM),
    }
    img = Image.new("RGB", (2 * H, 2 * H))
    key = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            side_x, side_y, diag = road(x + sx, y), road(x, y + sy), road(x + sx, y + sy)
            box = (0 if sx < 0 else H, 0 if sy > 0 else H)
            if side_x and side_y:
                # The grey panel quarter, road on both sides or not. In game the
                # open floor carries a regular grid of grey panels, one where
                # every four crossing tiles meet; plain asphalt here left the
                # floor bare. Kerbs are only for sides that meet non-road ground.
                q, code = cross.crop((box[0], box[1], box[0] + H, box[1] + H)), "n"
            elif side_y:
                q, code = kerb[(sx, 0)], "x"
            elif side_x:
                q, code = kerb[(0, sy)], "y"
            else:
                # kerbs are light and asphalt dark, so the lighter of the two
                # quarters is both kerbs at once
                q, code = ImageChops.lighter(kerb[(sx, 0)], kerb[(0, sy)]), "c"
            img.paste(q, box)
            key.append(code)
    return "j" + "".join(key), img


def load_objx(geo: Path, file: str, index: int):
    blob = (geo / file).read_bytes()
    off = [m.start() for m in re.finditer(b"OBJX", blob)][index]
    nv, nf = struct.unpack_from("<HH", blob, off + 8)
    return max2obj.read_model(blob, off, nf, nv)


def load_named(geo: Path, file: str, name: str):
    blob = (geo / file).read_bytes()
    addr, nf, nv = max2obj.models(blob)[name]
    return max2obj.read_model(blob, addr, nf, nv)


def place_model(obj: Obj, mtl, out, verts, faces, pal, atl, at, yaw=0.0, tag="m",
                seen=None):
    """Drop a SoSC model into the scene at `at` (metres), textured like the game.

    `seen` collects the materials used. A model stands ON the ground rather than
    being ground, and only this knows which materials are its: naming alone does
    not say, and a tower body taken for a driving surface lands in the collision
    tree above the berm it stands on.
    """
    build_car.unit_uvs(faces)
    c, s = math.cos(yaw), math.sin(yaw)
    for f in faces:
        if f["n"] < 3:
            continue
        t = f["type"]
        if t == 13:
            name = save(atlas_image(atl, pal, f["tex"]), out, f"p{f['tex']:03d}", mtl)
            # NOT flipped here, unlike the car and prop pipelines. Their extra
            # 1 - v is right for VIPER's .mod, which counts V from the other end;
            # this is an OBJ for a GL viewer. Copied across, it drew the cow's
            # hide upside down -- a plain brown body with a tan patch where the
            # game shows dark markings on the back and a face with an eye.
            # Settled by rendering both against an in-game shot of the cow.
            uvs = list(f["uv"])
        elif t == 18:
            name = save(missile.cell_image(atl, pal, f["atlas"], f["tex"]), out,
                        f"c{f['atlas']:03d}_{f['tex']:03d}", mtl)
            uvs = list(f["uv"])
        else:
            rgb = build_car.shade_of(pal, f["tex"], t)
            name = save(Image.new("RGB", (4, 4), rgb), out, "k%02x%02x%02x" % rgb, mtl)
            uvs = [(0.5, 0.5)] * f["n"]
        pts = []
        for i in f["idx"]:
            x, y, z = (a / UNITS_PER_M for a in verts[i])
            pts.append((at[0] + c * x - s * z, at[1] + y, at[2] + s * x + c * z))
        if seen is not None:
            seen.add(name)
        obj.face(name, pts, uvs)


def build(sosc: Path, city_path: Path, out: Path) -> dict:
    geo, bmp = sosc / "GEO", sosc / "BMP"
    (out / "tex").mkdir(parents=True, exist_ok=True)
    city = sc2.read(city_path)
    level = level_height(geo)
    pal = build_car.palette((geo / "SIM3D2.MAX").read_bytes())
    atl = build_car.atlas(bmp / "SIM3D.BMP")
    sky = build_car.atlas(bmp / "SKY.BMP")
    terrain_sheet = atlas_image(sky, pal, 4)

    obj, mtl = Obj(), {}
    # SoSC's own transition art, scored. For every cell of the sand/grass set,
    # plus solid grass: how grassy it is at its four corners and four edge
    # midpoints, 0 = sand, 1 = grass. Naming the cells by eye failed -- the set
    # holds edges, corners, diagonals and near-duplicates, not a tidy bitmask --
    # so each tile instead takes the cell whose samples best match the pattern
    # it needs.
    def box_mean(im, x, y, s=8):
        px = list(im.crop((x, y, x + s, y + s)).getdata())
        return [sum(p[i] for p in px) / len(px) for i in range(3)]

    def cell_img(i):
        return cell(terrain_sheet, i // 8, i % 8).convert("RGB")

    # Sample boxes in IMAGE coordinates of a 32 px cell (y down), on a 5x5 grid:
    # corners, edges AND the interior. Corners and edge midpoints alone cannot
    # tell the set's near-duplicates apart -- each edge and corner comes twice,
    # once with the sand bulging into the grass and once with the grass bulging
    # into the sand. The whole grid is matched against the corner pattern.
    SAMPLES = {(ix, iy): (ix * 6, iy * 6) for ix in range(5) for iy in range(5)}
    green = lambda m: m[1] - m[0]
    sand_g = green(box_mean(cell_img(SAND_SET[0]), 0, 0, 32))
    grass_g = green(box_mean(cell_img(GRASS_SOLID), 0, 0, 32))

    def grassy(im, xy):
        return min(1.0, max(0.0, (green(box_mean(im, *xy)) - sand_g) / (grass_g - sand_g)))

    # Every cell in all four quarter turns. The sheet does not draw every edge
    # in every direction -- there is no good "grass on the -x side" cell, and
    # those berm faces fell back to solid sand in a dead straight line -- but
    # sand and grass have no grain, so a turned cell serves. An unturned cell
    # keeps a small edge (ROTATE_PENALTY) so edges that already matched stay put.
    candidates = [(i, q) for i in list(SAND_SET) + [GRASS_SOLID] for q in range(4)]
    scored = {(i, q): {k: grassy(cell_img(i).rotate(90 * q), xy) for k, xy in SAMPLES.items()}
              for i, q in candidates}
    ROTATE_PENALTY = 0.25

    # Sand is a matter of HEIGHT. Checked against three in-game views:
    #   the four islands   flat tops one level up are sand, their slopes grass
    #   the berm           the first tier off the floor is grass, above it sand
    #   the berm top       green beside the road -- but those are tower and tree
    #                      tiles, and SoSC's building lot (BASE1X1R) is textured
    #                      with the solid grass cell, so built tiles stay grass
    # So open ground whose altitude is above the city's base level is sand.
    # (Earlier rules keyed on slope sanded the island slopes and left the island
    # tops green -- exactly backwards.)
    from collections import Counter
    base_level = Counter(a for col in city.altitude for a in col).most_common(1)[0][0]
    city.base_level = base_level          # alt_height() measures from it

    def sloped(x, y):
        """Sandy ground -- kept under the old name the ground code calls."""
        return (0 <= x < sc2.SIZE and 0 <= y < sc2.SIZE
                and city.grids["XBLD"][x][y] == 0
                and city.altitude[x][y] > base_level)

    # The islands draw their sand/grass boundary the other way round from the
    # berm: GRASS bites into the sand along the top edge, where the berm hangs
    # sand teeth into the grass. An island is any patch of sand not joined to
    # the berm -- and COMPACT, filling at least half its bounding box. The berm
    # is not one patch: roads cut L-shaped strips off its inner face, which
    # fill about a sixth of their box (the islands about two thirds), and
    # taking every patch but the largest striped those faces with grass.
    sand_tiles = {(x, y) for x in range(sc2.SIZE) for y in range(sc2.SIZE) if sloped(x, y)}
    patches, seen = [], set()
    for t in sorted(sand_tiles):
        if t in seen:
            continue
        stack, patch = [t], set()
        seen.add(t)
        while stack:
            px, py = stack.pop()
            patch.add((px, py))
            for q in ((px + dx, py + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                if q in sand_tiles and q not in seen:
                    seen.add(q)
                    stack.append(q)
        patches.append(patch)
    def compact(patch):
        xs, ys = [t[0] for t in patch], [t[1] for t in patch]
        return len(patch) >= 0.5 * (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)

    island = set().union(set(), *(p for p in patches if compact(p)))

    def plain_tiles(tiles):
        """The plain-ground tiles among `tiles`. Roads and built tiles have no
        say in where sand goes: counted as "not sand" they pulled grass over the
        berm top by the towers, where the game runs sand up to the tower bases."""
        return [(tx, ty) for tx, ty in tiles
                if 0 <= tx < sc2.SIZE and 0 <= ty < sc2.SIZE and city.grids["XBLD"][tx][ty] == 0]

    def lattice(x, y):
        # The sand/grass boundary as the game draws it: SAND TEETH HANGING INTO
        # THE GRASS at every tile corner along the berm's boundary, grass lobes
        # between. That is a 3x3 pattern per tile, which four corners cannot
        # express -- tried, and every corner-only rule tiled either the
        # grass-bite arcs (cell 55) or ran the sand to the foot of the slope. So:
        #   corners        sand if ANY plain tile around them is sandy
        #   edge midpoints sand only if BOTH tiles sharing the edge are sandy
        #   centre         the tile's own ground
        # A boundary corner comes out sand and the midpoint beside it grass,
        # which is what the sheet's sand-bow cells (50, 59, ...) draw. Where the
        # sand is an island's, ANY and BOTH swap, and the grass bites instead.
        # On an island every neighbour has a say, roads and built lots included:
        # left out, they gave the island sides a straight edge with no teeth.
        def vote(tiles, berm_rule, island_rule):
            if any(t in island for t in tiles):
                return island_rule(sloped(*t) for t in tiles)
            p = plain_tiles(tiles)
            return bool(p) and berm_rule(sloped(*t) for t in p)

        L = {}
        for i, sx in ((0, -1), (1, 0), (2, 1)):
            for j, sy in ((0, -1), (1, 0), (2, 1)):
                if sx and sy:                                   # corner
                    sand = vote([(x + dx, y + dy) for dx in (0, sx) for dy in (0, sy)], any, all)
                elif sx or sy:                                  # edge midpoint
                    sand = vote([(x, y), (x + sx, y + sy)], all, any)
                else:                                           # centre
                    sand = sloped(x, y)
                L[(i, j)] = 0.0 if sand else 1.0
        return L

    def targets(L):
        target = {}
        for (ix, iy) in SAMPLES:
            u, v = (ix * 6 + 4) / 32, 1 - (iy * 6 + 4) / 32      # tile coords, +y = image top
            gu, gv = u * 2, v * 2
            i0, j0 = min(int(gu), 1), min(int(gv), 1)
            fu, fv = gu - i0, gv - j0
            target[(ix, iy)] = ((1 - fu) * (1 - fv) * L[(i0, j0)] + fu * (1 - fv) * L[(i0 + 1, j0)]
                                + (1 - fu) * fv * L[(i0, j0 + 1)] + fu * fv * L[(i0 + 1, j0 + 1)])
        return target

    # Dark patches in the grass: in game, whole tiles of cell 47 scattered
    # through the plain grass (confirmed by the user against SoSC). A tile that
    # would take solid grass takes 47 instead, now and then.
    dark_tiles = set()
    patch_mat = save(cell(atlas_image(sky, pal, PATCH_PAGE), PATCH_CELL // 8, PATCH_CELL % 8).convert("RGB"),
                     out, f"p{PATCH_PAGE}c{PATCH_CELL}", mtl)

    def ground_mat(x, y):
        L = lattice(x, y)
        target = targets(L)
        pool = candidates
        # An island's edge tiles lose their teeth to solid sand: a grass corner
        # is too small a share of the samples to outscore it. So a sand tile
        # with grass right beside it on an island may not take solid sand.
        # Only right beside: a grass tile touching at a corner alone streaked
        # the sand behind the staircase edges. (The berm is left as it was.)
        if (sloped(x, y) and len(set(L.values())) > 1
                and any((x + dx, y + dy) in island for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                and any(not sloped(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))):
            pool = [c for c in candidates if c[0] != SAND_SET[0]]
        i, q = min(pool, key=lambda c: sum((scored[c][k] - target[k]) ** 2 for k in SAMPLES)
                   + (ROTATE_PENALTY if c[1] else 0.0))
        if i == GRASS_SOLID and bump_noise(x * 7 + 101, y * 13 + 57) > 1 - 2 * DARK_DENSITY:
            dark_tiles.add((x, y))
            return patch_mat
        return save(cell_img(i).rotate(90 * q), out, f"t{i:02d}" + (f"r{q}" if q else ""), mtl)

    dirt = save(cell(terrain_sheet, *DIRT_CELL), out, "dirt", mtl)
    # The side of a road ramp is plain grey concrete in game (the floor jumps),
    # not earth: the paving slabs in the corner of #79 are that grey.
    concrete = save(atlas_image(atl, pal, ROAD_TEX["diag"]).crop((4, 4, 36, 36)),
                    out, "concrete", mtl)
    road_mat = {k: save(atlas_image(atl, pal, i), out, f"road{i:03d}", mtl)
                for k, i in ROAD_TEX.items()}

    tee_img = atlas_image(atl, pal, ROAD_TEX["tee"])
    cross_img = atlas_image(atl, pal, ROAD_TEX["cross"])
    diag_lum = atlas_image(atl, pal, ROAD_TEX["diag"]).convert("L")

    def open_corner(x, y):
        """The corner of a diagonal tile whose two sides are not road."""
        return next(((sx, sy) for sx in (-1, 1) for sy in (-1, 1)
                     if not is_road(x + sx, y) and not is_road(x, y + sy)), None)

    def diag_turn(x, y, fallback):
        """The quarter turn that puts #79's pavement triangle into the open
        corner (the one whose two sides are not road), on every diagonal tile.

        Judged over AREAS, not points. One sample per corner tied: #79 has a
        light kerb nub in the corner opposite its pavement, just as bright at a
        single pixel (149 against 149), and the tie took the wrong turn -- a
        quarter out, which is how the floor corners and half the island edges
        came out backwards. Now each turn scores the mean brightness over the
        open corner's region against the opposite corner's, and the pavement
        triangle wins by its whole area. (Measured on #79: pavement above the
        line x + y = 142 px of 128, the dash parallel to it at x + y = 189.)
        """
        c = open_corner(x, y)
        if c is None:
            return fallback
        n = diag_lum.size[0] - 1
        steps = (0.06, 0.14, 0.22, 0.30)

        def region(cx, cy, q):
            total = 0
            for a in steps:
                for b in steps:
                    u = a if cx < 0 else 1 - a
                    v = b if cy < 0 else 1 - b
                    tu, tv = rotate_uv(u, v, q)
                    total += diag_lum.getpixel((min(n, int(tu * n)), min(n, int((1 - tv) * n))))
            return total / (len(steps) ** 2)

        return max(range(4), key=lambda q: region(c[0], c[1], q) - region(-c[0], -c[1], q))


    def is_road(x, y):
        return 0 <= x < sc2.SIZE and 0 <= y < sc2.SIZE and city.grids["XBLD"][x][y] in ROADS

    def bumpy(x, y):
        """Sloped open ground -- the only surface SoSC roughens."""
        return (0 <= x < sc2.SIZE and 0 <= y < sc2.SIZE and not is_road(x, y)
                and city.grids["XTER"][x][y] & 0x0F != 0)

    x0, y0, x1, y1 = city.bounds()
    x0, y0 = max(0, x0 - PAD), max(0, y0 - PAD)
    x1, y1 = min(sc2.SIZE - 1, x1 + PAD), min(sc2.SIZE - 1, y1 + PAD)
    B = city.grids["XBLD"]
    P = lambda x, y, sx, sy, h: ((x + (sx + 1) / 2) * TILE, h, (y + (sy + 1) / 2) * TILE)

    # ground and roads, one quad per tile
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            h = corner_heights(city, x, y, level)
            order = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
            pts = [P(x, y, sx, sy, h[(sx, sy)]) for sx, sy in order]
            base_uv = [((sx + 1) / 2, (sy + 1) / 2) for sx, sy in order]
            if B[x][y] in AUTOTILE_IDS:
                name, img = autotile_image(tee_img, cross_img, is_road, x, y)
                obj.face(save(img, out, name, mtl), pts, base_uv)
            elif B[x][y] in ROADS:
                kind, q = ROADS[B[x][y]]
                if kind == "diag":
                    # #79 on every diagonal tile -- floor corners and island edges
                    obj.face(road_mat[kind], pts,
                             [rotate_uv(u, v, diag_turn(x, y, q)) for u, v in base_uv])
                else:
                    obj.face(road_mat[kind], pts, [rotate_uv(u, v, q) for u, v in base_uv])
            elif not bumpy(x, y):
                obj.face(ground_mat(x, y), pts, base_uv)
            else:
                mat, N = ground_mat(x, y), BUMP_DIV
                def sub(i, j):
                    lo = h[(-1, -1)] + (h[(1, -1)] - h[(-1, -1)]) * i / N
                    hi = h[(-1, 1)] + (h[(1, 1)] - h[(-1, 1)]) * i / N
                    base = lo + (hi - lo) * j / N
                    xs = {x} | ({x - 1} if i == 0 else set()) | ({x + 1} if i == N else set())
                    ys = {y} | ({y - 1} if j == 0 else set()) | ({y + 1} if j == N else set())
                    s = all(bumpy(tx, ty) for tx in xs for ty in ys)
                    lift = BUMP_AMP * bump_noise(x * N + i, y * N + j) if s else 0.0
                    return ((x + i / N) * TILE, base + lift, (y + j / N) * TILE)
                for i in range(N):
                    for j in range(N):
                        obj.face(mat, [sub(i, j), sub(i + 1, j), sub(i + 1, j + 1), sub(i, j + 1)],
                                 [(i / N, j / N), ((i + 1) / N, j / N),
                                  ((i + 1) / N, (j + 1) / N), (i / N, (j + 1) / N)])

    # skirts where neighbouring tiles disagree about a shared edge
    skirts = 0
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            h = corner_heights(city, x, y, level)
            for dx, dy in ((1, 0), (0, 1)):
                nx, ny = x + dx, y + dy
                if nx > x1 or ny > y1:
                    continue
                g = corner_heights(city, nx, ny, level)
                if dx:
                    a, b = ((1, -1), (1, 1)), ((-1, -1), (-1, 1))
                else:
                    a, b = ((-1, 1), (1, 1)), ((-1, -1), (1, -1))
                ha, hb = [h[k] for k in a], [g[k] for k in b]
                if any(abs(p - q) > 1e-6 for p, q in zip(ha, hb)):
                    e = [P(x, y, *a[0], ha[0]), P(x, y, *a[1], ha[1]),
                         P(x, y, *a[1], hb[1]), P(x, y, *a[0], hb[0])]
                    side = concrete if (B[x][y] in ROADS or B[nx][ny] in ROADS) else dirt
                    obj.face(side, e, [(0, 0), (1, 0), (1, 1), (0, 1)])
                    skirts += 1

    # SoSC's own props, by tile id
    models = {k: load_named(geo, *v) for k, v in PROPS.items()}
    placed = {}
    # Where each prop and cow stands, for anything downstream that has to put
    # something at the same spot -- the track build gives them collision boxes.
    prop_at: list[tuple[int, tuple[float, float, float]]] = []
    prop_materials: set[str] = set()      # materials belonging to things ON the ground
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            tid = B[x][y]
            # the tile's own surface, which a neighbouring road may have bent
            ground = sum(corner_heights(city, x, y, level).values()) / 4
            centre = ((x + 0.5) * TILE, ground, (y + 0.5) * TILE)
            if tid in models:
                verts, faces = models[tid]
                place_model(obj, mtl, out, verts, [dict(f) for f in faces], pal, atl, centre,
                            seen=prop_materials)
                placed[tid] = placed.get(tid, 0) + 1
                prop_at.append((tid, tuple(round(a, 1) for a in centre)))
            elif tid in TREE_IDS:
                rnd = random.Random(x * 131 + y)
                for k in range(3):
                    tex = save(atlas_image(atl, pal, rnd.choice(TREE_TEX)), out,
                               f"tree{TREE_TEX[k % 4]:03d}", mtl, key_green=True)
                    tx = centre[0] + rnd.uniform(-5, 5)
                    tz = centre[2] + rnd.uniform(-5, 5)
                    w, hgt = 7.0, 8.0
                    for ang in (0.0, math.pi / 2):
                        cx, cz = math.cos(ang) * w / 2, math.sin(ang) * w / 2
                        obj.face(tex, [(tx - cx, ground, tz - cz), (tx + cx, ground, tz + cz),
                                       (tx + cx, ground + hgt, tz + cz), (tx - cx, ground + hgt, tz - cz)],
                                 [(0, 0), (1, 0), (1, 1), (0, 1)])
                placed["trees"] = placed.get("trees", 0) + 1

    # Cows: anywhere at all. SoSC spawns them at runtime in all sorts of places --
    # on the roads as readily as on the grass -- so they are scattered over the
    # whole map at random, facing any way, standing on the surface under them.
    cow_verts, cow_faces = load_objx(geo, *COW)
    rnd = random.Random(1997)
    cow_at = []
    for _ in range(COW_COUNT):
        px, py = rnd.uniform(x0, x1 + 1), rnd.uniform(y0, y1 + 1)
        tx, ty = min(int(px), x1), min(int(py), y1)
        fx, fy = px - tx, py - ty
        h = corner_heights(city, tx, ty, level)
        lo = h[(-1, -1)] * (1 - fx) + h[(1, -1)] * fx
        hi = h[(-1, 1)] * (1 - fx) + h[(1, 1)] * fx
        at = (px * TILE, lo * (1 - fy) + hi * fy, py * TILE)
        cow_at.append(tuple(round(a, 1) for a in at))
        place_model(obj, mtl, out, cow_verts, [dict(f) for f in cow_faces], pal, atl, at,
                    yaw=rnd.uniform(0, 2 * math.pi), seen=prop_materials)

    obj.write(out, mtl)
    return {"city": city.name, "level_m": level, "tiles": (x1 - x0 + 1, y1 - y0 + 1),
            "size_m": ((x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE), "skirts": skirts,
            "props": placed, "cows": len(cow_at),
            "cow_at": cow_at, "prop_at": prop_at,
            # the tree sprites are this script's own billboards, and the only
            # materials it names "tree"
            "prop_materials": sorted(prop_materials | {n for n in mtl if n.startswith("tree")}),
            "island_sand": len(island), "dark_patch_tiles": len(dark_tiles),
            "materials": len(mtl), "vertices": len(obj.v)}


def main(argv):
    if len(argv) != 3:
        raise SystemExit("arena.py <sosc_dir> <city.sc2> <out_dir>")
    r = build(Path(argv[0]), Path(argv[1]), Path(argv[2]))
    shutil.copy(HERE / "view.html", Path(argv[2]) / "view.html")
    for k, v in r.items():
        if isinstance(v, list) and len(v) > 4:
            print(f"  {k:12} {len(v)} placed, first {v[0]}")
        else:
            print(f"  {k:12} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
