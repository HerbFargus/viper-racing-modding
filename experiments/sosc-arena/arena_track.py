"""The arena as a loadable Viper Racing track.

Phase 2, step 2: the preview's geometry, the ring route from route.py, and
SoSC's own textures, assembled into a .trk.

    python arena_track.py <sosc_dir> <city.sc2> <work_dir> <donor.trk> <out.trk>

`work_dir` is where arena.py's OBJ and PNGs are built (reused if already there);
`donor.trk` is a stock track, which supplies the configuration, the sky and the
camera set -- none of which this generates.

HOW THE PIECES MAP ONTO THE TOOLKIT

    arena.py            the city as one OBJ with ~50 materials
    split_by_material   -> one mesh per material, which is what surface codes
                           are really about: one mesh holding both road and
                           grass would drive entirely as whichever won
    scene_from_meshes   chunks each for the renderer and builds the scene
    trackbuild.assemble writes every member natively -- no MKWORLD, no nhmkworld

THREE THINGS THIS DOES ITSELF, because the toolkit's track path was written for
a swept ribbon wearing borrowed art rather than an imported city:

**Its own textures.** `assemble` maps every material onto a member of the DONOR
archive, which is right for a generated track and wrong here -- SoSC's art is
the whole point. Every texture is handed a donor stand-in to satisfy that map,
and its payload is replaced afterwards with the real one, encoded from the
preview's PNGs.

**Its own .sol.** `assemble` builds barrier boxes at ONE height for the whole
track (it takes the first wall's). A 1.9 m cow and an 18 m tower cannot share
that, so the primitives are built here, each at its own height.

**Its own gates and grid.** trackgen spaces gates evenly from the line's origin;
these sit at the start and just past each corner, where a shortcut across the
arena floor cannot avoid them. See route.py.
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import arena                                                # noqa: E402
import route as route_mod                                   # noqa: E402

from vrmod import (archive, dekey, envelope, grf, ili, mod, obt, sol, tex,  # noqa: E402
                   trackbuild, trackgen)

from PIL import Image                                       # noqa: E402

# A RENDER CHUNK IS NOT A .mod OBJECT, and its ceiling is far lower than the
# 5,000-vertex one the car tutorial is about. Measured across the shipped
# tracks: no chunk anywhere exceeds 864 vertex records (nfield's biggest is
# 148, hastings' 864, and every track's median is 4). The first build here ran
# to 3,492, with 30 chunks over 1,024 -- and the game died with an access
# violation while loading it. So chunks are split until each is under a
# stock-like cap, however small that makes them.
CHUNK_CORNERS = 480
CHUNK_SIZES = (800.0, 400.0, 200.0, 100.0, 50.0, 25.0, 12.0)
ROAD_WIDTH = 16.0             # a SimCity tile: the ring road's full width
COW_BOX = (1.8, 2.7, 1.9)     # the cow mesh's own size: x, z, height
COW_MATERIAL = "p168"         # the cow hide -- 25,200 of the track's 45,705 faces

# ARENA_DROP=p168 leaves a material out of the track entirely, geometry and
# collision both. A bisect lever, not a setting: the first track that loaded
# rendered nothing and died with a lost DirectDraw surface on a 16 MB card,
# and it carries 107,165 vertex records where the biggest stock track has
# 15,635. Dropping the cows halves it without changing anything else.
DROP_MATERIALS = tuple(m for m in os.environ.get("ARENA_DROP", "").split(",") if m)

# THE WOBBLE EXPERIMENT. `obj wobble pole <int>` is the one .obt record carrying
# no coordinates, and nothing has ever explained what its integer references.
# The shipped data points at the .sol TUBE list: every track with wobbles has
# TUBEs, the indices run contiguously from 0, and hastings carries exactly 15
# TUBEs and exactly 15 wobbles. Better still, a TUBE's record holds a SEQUENTIAL
# ID at +0x30 (0, 1, 2 ...) where every BOX holds -1 -- so the integer most
# likely names that id.
#
# The test: every cow becomes a TUBE with its own id, and the first
# ARENA_WOBBLE of them also get a wobble record. If the guess is right, those
# cows tip over when hit and the rest stay solid -- in the same drive, which is
# what makes it a test rather than a hope. The count stays under dundas's 170,
# the most any shipped track carries, because the pool is fixed ("Too many
# wobjects allocated--increase MAX_OBJECTS").
WOBBLE_COWS = int(os.environ.get("ARENA_WOBBLE", "50"))
# ARENA_PLACED=8 emits that many cow billboards as PLACED MODELS in our own
# .grf, each paired with a .sol tube of the same id and an `obj wobble pole N`
# record. ANSWERED: a facing registers from a flat chain, hung off the root's
# +08 -- no node tree needed. Eight of these drive and topple in game.
PLACED_COWS = int(os.environ.get("ARENA_PLACED", "0"))
# The facing model's name in scene.meshes. It is NOT in scene.driveables or
# scene.scenery, so it is never drawn as ordinary geometry -- registering it
# here is purely what makes its texture ship, since trackbuild sweeps every
# material of every scene mesh.
FACING_MESH = "cowface.mod"

# THE OTHER DOOR: `obj obstacle <ball|cube|prism> <mesh.mod> <x>,<y>:<z> <r>`.
# The .obt parser accepts it, no shipped track uses it, and it places a NAMED
# MESH at a position with a radius -- the horn ball's own machinery, which the
# game already knocks around a circuit. That needs no scene graph at all: a
# .mod member in the archive and a line of text in a file we already write.
# Where the wobble route needs a record type nobody has decoded, this one needs
# only a name to resolve.
OBSTACLE_COWS = int(os.environ.get("ARENA_OBSTACLE", "50"))
# ball | cube | prism -- the collision shape the Ball phob is given. PRISM by
# default: driven in game, a prism cow topples when hit and SETTLES, where a
# ball cow drops and keeps rolling away like the horn ball it is built from.
# Same record, same mesh, one word; nothing in the file says which is better.
OBSTACLE_KIND = os.environ.get("ARENA_OBSTACLE_KIND", "prism")
# ARENA_OBSTACLE_MESH=ball.mod isolates the mechanism from the mesh: ball.mod is
# hardcoded in the engine and lives in race.res, so it certainly resolves. If
# balls appear at the cows, `obj obstacle` works and only our mesh lookup is
# broken; if nothing appears, the record is inert and the mesh never mattered.
# The first drive produced neither a ResourceGet failure nor a "Bad obstacle
# record" -- the engine accepted the line and did nothing with it.
OBSTACLE_MESH = os.environ.get("ARENA_OBSTACLE_MESH", "cow.mod")
OBSTACLE_RADIUS = 1.4
# ARENA_COW_TUBES=0 drops the cows' .sol tubes. With them in place the car hits
# the tube and stops, so an obstacle at the same spot never gets touched --
# which is exactly what the first drive showed. Without them, the obstacle is
# the only thing there: drive through the cow and the record is being ignored,
# bounce off it and it is a physics body, hit something immovable and it exists
# but is static.
COW_TUBES = os.environ.get("ARENA_COW_TUBES", "1") != "0"

# ARENA_TEST_ROW=1 puts a row of test objects straight across the start straight,
# 50-90 m ahead of the grid, instead of scattering them among 200 cows where they
# have to be hunted for. Two record types at once, because one drive answers two
# questions: `obj obstacle cube ball.mod` (a mesh the engine certainly resolves,
# since it is hardcoded and lives in race.res) and `obj static box` (a collider
# that names no mesh at all). Whatever the engine refuses, it says so in the log
# -- "Bad obstacle type", "Bad static record" -- so even silence is evidence.
TEST_ROW = os.environ.get("ARENA_TEST_ROW", "0") == "1"
# The cow's collider, as confirmed in game 2026-09-15. It was written as
# `radius=1.4`, but tube_at then put that into the tube's HALF-length and kept
# the donor's 0.23 m radius -- so what knocked the cows over was a 0.46 m post
# reaching 1.63 m above their feet. Kept exactly that, now said honestly; a
# capsule as wide as the cow (radius ~0.9) would be easier to hit, untried.
COW_TUBE_RADIUS = 0.23
COW_TUBE_HEIGHT = 1.63        # above the feet, where the wobble pivots
# The donor's own tube is fine as a carrier now: sol.tube_at WRITES the
# orientation rather than inheriting it. The two sign flips this used to work
# around are not noise -- there are exactly two tube matrices, and which one a
# tube gets depends on whether it is a wobble (931 tubes, 7 tracks, 0
# exceptions). See sol.TUBE_MATRIX_WOBBLE.
# Measured from the model itself (AP225 is 14.58 m square and 43.75 m tall),
# not guessed: the first pass used a 6 m box 18 m tall, so a car clipped the
# tower's corners and anything above 18 m was thin air.
TOWER_BOX, TOWER_HEIGHT = 14.6, 43.75
TOWER_ID = 225

# Material name -> surface code. arena.py's names carry the meaning; Viper's own
# prefix table reads every one of them as grass.
CODE_EXACT = {"concrete": trackgen.ROAD, "dirt": trackgen.DIRT}
CODE_PREFIX = (("road", trackgen.ROAD), ("j", trackgen.ROAD))
PROP_PREFIXES = ("tree", "p")          # tree sprites; p<page>... the SoSC models

# The skirts: the vertical faces that close the step between two tiles at
# different heights. They are drawn but never collided, because `.bpp` answers
# one surface per ground position and a vertical face sits directly above the
# ground it joins -- 8,374 conflicting fragments on the first build, which is
# the tree telling us a wall is not a floor. Retail tracks put vertical
# surfaces in `.sol` for the same reason. Nothing is lost by driving through
# them: they are inside the slopes, under the road.
SKIRT_MATERIALS = ("concrete", "dirt")


def code_for_material(name: str) -> int:
    """Road for roads and the arena floor, sand for the sand cells, else grass."""
    stem = "".join(c for c in name.lower() if c.isalnum())
    if stem in CODE_EXACT:
        return CODE_EXACT[stem]
    for prefix, code in CODE_PREFIX:
        if stem.startswith(prefix):
            return code
    if stem.startswith("t") and stem[1:3].isdigit():
        return trackgen.DIRT if 48 <= int(stem[1:3]) <= 63 else trackgen.GRASS
    return trackgen.GRASS


def is_prop(name: str, prop_materials: set[str]) -> bool:
    """Whether a material belongs to something standing ON the ground.

    arena.py says which materials its models, trees and cows use, and that is
    the only reliable answer. Guessing from the name put the towers' own
    geometry in the collision tree -- 8,374 fragments where a tower body at
    97 m sat above the berm at 55 m -- and, the other way, mistook the dark
    grass patch (p5c52) for a prop, which would have left holes in the ground.
    """
    stem = "".join(c for c in name.lower() if c.isalnum())
    return name in prop_materials or stem.startswith(SKIRT_MATERIALS)


def box_mesh(cx: float, cy: float, cz: float, sx: float, sz: float, h: float) -> "mod.Mesh":
    """An upright box, game frame, for collision only: scene_from_meshes turns a
    COLLIDER mesh's vertical faces into the quads that become .sol primitives,
    and nothing ever draws it."""
    x0, x1 = cx - sx / 2, cx + sx / 2
    z0, z1 = cz - sz / 2, cz + sz / 2
    y0, y1 = cy, cy + h
    corners = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    verts, faces = [], []
    for i in range(4):
        ax, az = corners[i]
        bx, bz = corners[(i + 1) % 4]
        nx, nz = _unit(bz - az, -(bx - ax))
        n = len(verts)
        verts += [mod.Vertex(ax, y0, az, nx, 0.0, nz, 0.0, 0.0),
                  mod.Vertex(bx, y0, bz, nx, 0.0, nz, 1.0, 0.0),
                  mod.Vertex(bx, y1, bz, nx, 0.0, nz, 1.0, 1.0),
                  mod.Vertex(ax, y1, az, nx, 0.0, nz, 0.0, 1.0)]
        faces += [(n, n + 1, n + 2), (n, n + 2, n + 3)]
    return mod.Mesh(vertices=verts, faces=faces,
                    materials=[mod.Material(name="box.tex", vertex_start=0,
                                            vertex_end=len(verts), face_start=0,
                                            face_end=len(faces))])


def _unit(dx, dz):
    n = math.hypot(dx, dz) or 1.0
    return dx / n, dz / n


def arena_stats(sosc: Path, city_path: Path, work: Path) -> dict:
    """arena.build()'s placements, rebuilt only when the OBJ is not there.

    The cow and tower positions come out of the build, and rebuilding the whole
    city to ask where a cow stands makes every track run a minute longer, so
    they are cached beside the model.
    """
    cache = work / "placements.json"
    if (work / "arena.obj").exists() and cache.exists():
        return json.loads(cache.read_text())
    stats = arena.build(sosc, city_path, work)
    keep = {k: stats[k] for k in ("cow_at", "prop_at", "prop_materials")}
    cache.write_text(json.dumps(keep))
    return stats


def prop_boxes(stats: dict) -> list[tuple[float, float, float, float, float, float]]:
    """(centre x, ground y, centre z, size x, size z, height) for every solid.

    Cows and towers only: the trees are billboards you drive through in SoSC
    too, and the gas station and warehouse sit off the ring.
    """
    return [(x, y, z, TOWER_BOX, TOWER_BOX, TOWER_HEIGHT)
            for tid, (x, y, z) in stats.get("prop_at", []) if tid == TOWER_ID]


def to_source_point(g):
    """Game frame -> source frame: the inverse of trackgen.to_viper.

    to_viper((x, y, elev)) is (-x, elev, -y), so a game point (gx, gy, gz) came
    from source (-gx, -gz, gy). scene.wobbles are declared in the SOURCE frame,
    like the centreline, the walls and the grid, and trackbuild flips them once
    for both the tube and the facing so the two cannot drift. The arena's cow
    positions arrive already in the game's frame, hence this.
    """
    return (-g[0], -g[2], g[1])


def cows_near_route(cows, stations, n: int) -> tuple[list, list]:
    """Split the cows into (knockable, solid): the `n` nearest the racing line
    become obstacles, the rest keep their .sol tubes.

    Nearest the line because a cow you never drive past may as well not be
    knockable -- and a tube at the same spot would stop the car before the
    obstacle registered, which is what the first obstacle test ran into.
    """
    if n <= 0 or not stations:
        return [], list(cows)
    ground = [(s[0], s[1]) for s in stations]
    step = max(1, len(ground) // 400)          # every ~10 m is close enough
    sample = ground[::step]
    ranked = sorted(cows, key=lambda c: min((c[0] - sx) ** 2 + (c[2] - sy) ** 2
                                            for sx, sy in sample))
    return ranked[:n], ranked[n:]


def cow_positions(stats: dict) -> list:
    """Where the cows stand, unless they were dropped from the build."""
    if COW_MATERIAL in DROP_MATERIALS:
        return []
    return [tuple(p) for p in stats.get("cow_at", [])]


def split_per_instance(mesh: "mod.Mesh", centres, drop=()) -> list["mod.Mesh"]:
    """One mesh per placed instance, by which centre each face is nearest.

    `drop` names centre indices to leave out of the drawn mesh entirely. A cow
    that becomes a wobble must NOT also keep its solid prop: the static model
    stands in the very spot its billboard does and body-blocks it, so the car
    hits a cow that cannot move and the wobble behind it is never reached.

    A WobbleObject draws a SINGLE model: every shipped wobble tube has its own
    small render chunk about a metre from it (nfield's are 4-corner `Rtbig.tex`
    pairs, hastings' 12-corner `bk1.tex`). Our cows were merged into large
    shared chunks by material and position, so there was no single model for
    `direct_model_draw` to fetch, and the game died drawing the first wobble.
    """
    buckets: dict[int, list] = {}
    for face in mesh.faces:
        v = mesh.vertices[face[0]]
        k = min(range(len(centres)),
                key=lambda i: (centres[i][0] - v.x) ** 2 + (centres[i][2] - v.z) ** 2)
        buckets.setdefault(k, []).append(face)
    out = []
    for k in sorted(buckets):
        if k in drop:
            continue
        remap: dict[int, int] = {}
        verts, faces = [], []
        for face in buckets[k]:
            tri = []
            for i in face:
                j = remap.get(i)
                if j is None:
                    j = len(verts)
                    remap[i] = j
                    verts.append(mesh.vertices[i])
                tri.append(j)
            faces.append(tuple(tri))
        name = mesh.materials[0].name if mesh.materials else "tex"
        out.append(mod.Mesh(vertices=verts, faces=faces,
                            materials=[mod.Material(name=name, vertex_start=0,
                                                    vertex_end=len(verts), face_start=0,
                                                    face_end=len(faces))]))
    return out


def read_arena_obj(path: Path) -> "mod.Mesh":
    """Read arena.obj WITHOUT mod.read_obj's Z mirror.

    `read_obj` is the inverse of `to_obj`: it negates Z, flips V and swaps the
    winding, which is right for round-tripping a Viper `.mod` through a
    modeller. arena.py's OBJ is not a round-trip -- it is built in world
    coordinates directly -- so that mirror put the whole city at negative Z
    while the route, the gates and the grid stayed positive. In game the car
    spawned 1,300 m from the track, fell through empty sky at 0 mph, and the
    world rendered as nothing.

    So Z is negated back and the winding swapped back with it: a mirror turns
    every face inside out, and Viper culls backfaces. The V flip is kept --
    that one is a real difference between an OBJ and a `.mod`.
    """
    mesh = mod.read_obj(path)
    for v in mesh.vertices:
        v.z, v.nz = -v.z, -v.nz
    mesh.faces = [(a, c, b) for a, b, c in mesh.faces]
    return mesh


def faces_up(mesh: "mod.Mesh") -> int:
    """Wind every face of a ground mesh so its normal points up. Returns how
    many had to be turned.

    VIPER CULLS BACKFACES, and arena.py emits its tile quads in the order that
    makes the normal point DOWN -- invisible from above, which is what "no
    textures rendering" turned out to mean. The preview never showed it because
    view.html draws double-sided. Measured against the shipped tracks: ground
    faces there are up (bemidji 1,055 up against 3 down), ours were 14,396 down
    and none up.

    Only ground is turned. The SoSC models keep their own winding: that game
    renders two-sided, so its winding is arbitrary -- the car conversion found
    101 of the Airhawk's 520 faces disagreeing with their neighbours -- and
    there is no single answer to impose here.
    """
    turned = 0
    faces = []
    for a, b, c in mesh.faces:
        va, vb, vc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        ux, uz = vb.x - va.x, vb.z - va.z
        wx, wz = vc.x - va.x, vc.z - va.z
        if uz * wx - ux * wz < 0.0:
            faces.append((a, c, b))
            turned += 1
        else:
            faces.append((a, b, c))
    mesh.faces = faces
    return turned


def bbox(points) -> str:
    xs, ys, zs = zip(*points)
    return (f"x {min(xs):8.0f}..{max(xs):8.0f}  y {min(ys):6.0f}..{max(ys):6.0f}  "
            f"z {min(zs):8.0f}..{max(zs):8.0f}")


def split_to_cap(mesh: "mod.Mesh") -> list["mod.Mesh"]:
    """Chunk a mesh until no piece holds more than CHUNK_CORNERS vertices.

    Chunking by a fixed size cannot do this: one material covers the whole map
    but its density varies wildly -- the arena floor's panels against a dozen
    tiles of sand -- so the same size gives 4-vertex chunks in one place and
    3,492-vertex chunks in another. Sizes are tried in order until the biggest
    piece fits.
    """
    pieces = [mesh]
    for size in CHUNK_SIZES:
        pieces = trackgen.chunk_mesh(mesh, size=size)
        if max((len(p.vertices) for p in pieces), default=0) <= CHUNK_CORNERS:
            break
    return pieces


def build_scene(work: Path, line, gates, grid, prop_materials, cows=(),
                drop_cows=()) -> tuple["trackgen.TrackScene", dict]:
    """The scene, and the original-material -> member-name texture map.

    The map has to be taken BEFORE scene_from_meshes runs: it renames every
    material to fit 8.3, and the PNGs on disk are under the original names.
    """
    full = read_arena_obj(work / "arena.obj")
    pieces = trackgen.split_by_material(full)
    if not pieces:
        raise ValueError("the arena OBJ carries a single material -- nothing to classify")

    originals = [p.materials[0].name for p in pieces.values() if p.materials]
    tex_names = trackgen.fit_texture_names(originals)

    meshes, codes, roles = {}, {}, {}
    turned = [0]
    for piece in pieces.values():
        if not piece.materials:
            continue
        material = piece.materials[0].name
        if material in DROP_MATERIALS:
            continue
        stem = "".join(c for c in material if c.isalnum()).lower() or "mesh"
        prop = is_prop(material, prop_materials)
        code = code_for_material(material)
        role = trackgen.PROP if prop else trackgen.SURFACE
        if not prop:
            turned[0] += faces_up(piece)
        parts = (split_per_instance(piece, cows, drop_cows)
                 if material == COW_MATERIAL and cows else split_to_cap(piece))
        for k, part in enumerate(parts):
            name = f"{'obj' if prop else 'ta'}{stem}x{k:03d}.mod"
            meshes[name] = part
            codes[name] = code
            roles[name] = role

    # The pieces are already cut to the cap, so the scene must not cut them
    # again by a size of its own: one chunk per piece, whatever its extent.
    scene = trackgen.scene_from_meshes(
        meshes, centreline=line, chunk_size=1e9, codes=codes, roles=roles)
    scene.markers = {name: pts for name, _i, pts in gates}
    scene.grid = list(grid)
    print(f"  winding  {turned[0]:,} ground faces turned to face up")
    return scene, tex_names


# cow_tube lived here. It is now sol.tube_at, which additionally writes the
# orientation rather than inheriting it -- this version's claim that "every
# shipped TUBE carries the identical matrix" was wrong. There are two, and
# which one a tube gets depends on whether it is a wobble.


def our_sol(donor: Path, cows, boxes, id_count: int = 0) -> tuple[bytes, int]:
    """track.sol: a TUBE per cow first, then a BOX per tower.

    ONLY THE FIRST `id_count` TUBES CARRY AN ID; every other primitive gets -1,
    as every plain primitive does on every shipped track. An id is not
    decoration -- it names the facing model a wobble draws -- so a tube holding
    id N while no wobble N exists is a dangling claim on that slot. Stock hands
    out exactly as many ids as the track has wobbles: hastings 15 of 15,
    uptown 47 of 47, nfield 50 of 299, dundas 170 of 349. Giving all 200 cows
    an id while declaring 8 wobbles is what left seven of the eight missing.

    The cows come first so their ids and their positions in the list agree.
    """
    src = {e.name.lower(): e for e in archive.read(donor)}
    e = src["track.sol"]
    donor_sol = sol.parse(envelope.build(e.tag, e.version, e.payload))
    # sol.tube_at writes the orientation itself, so ANY shipped TUBE serves as a
    # carrier and there is no more borrowing one from a track that happens to
    # have wobbles. That borrowing was concealing a real bug: a tube's matrix
    # depends on whether it is a wobble, and the documented fallback here -- the
    # donor's own first TUBE -- would have inherited the wrong one, because
    # bemidji's single tube is a plain one.
    tube_template = sol.tube_template(donor_sol)
    prims = [sol.tube_at(tube_template, at, radius=COW_TUBE_RADIUS,
                         half_length=COW_TUBE_HEIGHT - COW_TUBE_RADIUS,
                         ident=i if i < id_count else -1)
             for i, at in enumerate(cows)]
    wall = sol.wall_template(donor_sol)
    prims += [sol.box_from_segment(wall, (cx - sx / 2, cy, cz), (cx + sx / 2, cy, cz),
                                   height=h, thickness=sz)
              for cx, cy, cz, sx, sz, h in boxes]
    index, tail = sol.build_spatial_index(prims)
    built = sol.Sol(primitives=prims, index=index, tail=tail, version=trackbuild.SOL_VERSION)
    return sol.build(built), len(cows)


def billboard_mesh(width: float, height: float, texture: str, cross: bool = False):
    """A flat board standing on the origin -- the stock chevron's own shape.

    NOT USED BY DEFAULT: the arena's wobbles are the real 3D cow mesh, built by
    cow_facing_mesh. This is kept because a flat board is the more forgiving
    style where a wobble should FLATTEN as well as topple, which a rigid mesh
    cannot. `cross=True` builds the crossed pair that was tried first and read
    badly going over -- one of its two planes is always edge-on to the fall.

    A FACING model's local up is -z, not +y. Every stock chevron runs z from 0
    at its base to about -2.5 at its top, with x and y spanning the board, and
    the node's own centre puts that base on the ground at the .sol tube. Built
    standing in +y instead, the cow would lie flat.
    """
    pts, uvs = [], []
    planes = [(1.0, 0.0), (0.0, 1.0)] if cross else [(1.0, 0.0)]
    for ax, ay in planes:
        w = width / 2
        pts += [(-w*ax, -w*ay, 0.0), (w*ax, w*ay, 0.0),
                (w*ax, w*ay, -height), (-w*ax, -w*ay, -height)]
        uvs += [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    vs = [mod.Vertex(x, y, z, 0.0, 0.0, 1.0, u, v) for (x, y, z), (u, v) in zip(pts, uvs)]
    faces = []
    for q in range(len(planes)):
        b = q * 4
        faces += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    m = mod.Mesh(vertices=vs, faces=faces, materials=[])
    m.materials = [mod.Material(name=texture, vertex_start=0, vertex_end=len(vs),
                                face_start=0, face_end=len(faces))]
    return m


# append_placed_models lived here. It is now grf.append_facings, reached through
# trackbuild.assemble from scene.wobbles -- so the ids on the facing, the tube
# and the record are assigned once, from one list, instead of by three loops
# that had to be kept counting the same way.


def our_obt(scene, wobbles: int, obstacles=(), extra=()) -> bytes:
    """track.obt: the gates and grid trackgen writes, plus wobble records.

    trackgen.build_obt has no way to declare a wobble, so the table is built
    here instead of patched. Coordinates go out in the flipped ground frame,
    exactly as build_obt writes them; a wobble record has none.
    """
    records = []
    for gate in scene.markers.values():
        (x1, y1, _), (x2, y2, _) = gate[0], gate[1]
        records.append(obt.checkpoint(-x1, -y1, -x2, -y2))
    for x, y, _ in scene.grid:
        records.append(obt.car(-x, -y))
    records += [obt.wobble(i) for i in range(wobbles)]
    # Obstacles carry their own coordinates, in the game's frame (x, height, z)
    # rather than the flipped one the gates and grid use -- they name a mesh and
    # a place, not a line on the ground.
    # `%f,%f:%f` is GROUND x, GROUND z : HEIGHT -- not x, height, z. The comma
    # pair is a ground position, exactly as it is in `obj checkpoint %s %f,%f
    # %f,%f`, and the colon introduces the elevation. Written the other way the
    # engine still builds the object (the count rose by exactly the number of
    # records) but puts it off the map sideways and hundreds of metres up:
    # invisible, intangible, and silent in the log.
    for x, y, z in obstacles:
        records.append(f"obj obstacle {OBSTACLE_KIND} {OBSTACLE_MESH} "
                       f"{x:.6f},{z:.6f}:{y:.6f} {OBSTACLE_RADIUS:.6f}")
    records += list(extra)
    return obt.build(obt.create(records))


def test_row_records(stations) -> list[str]:
    """A row of test objects across the start straight, in the game's frame.

    Stations are 4 m apart and run clockwise from the start line, so station 12
    is roughly 50 m ahead. Each object is placed on the road surface at that
    station's own height, offset sideways across the 16 m road.
    """
    if len(stations) < 30:
        return []

    # A STATION IS (x, y_on_the_map, height) -- the first two are the ground
    # plane and the THIRD is height, the same convention route.py writes and
    # trackgen's to_viper() consumes. Reading the second as height put a test
    # row 681 m up in empty sky, which no count-based check would ever catch.
    def place(k, side):
        x, y, h = stations[k]
        ax, ay = stations[k + 1][0] - stations[k - 1][0], stations[k + 1][1] - stations[k - 1][1]
        n = math.hypot(ax, ay) or 1.0
        px, py = -ay / n, ax / n                      # left of travel, on the ground
        return x + px * side, y + py * side, h

    # BEHIND the line, not ahead of it. The start sits at the far end of the
    # dip's 32 m flat and the road climbs immediately after it, so stations
    # 12-24 ahead are 17 m up the slope -- the row would hang in the air over
    # it. Negative indices walk back along the flat the grid is parked on,
    # where the road is level at the line's own height.
    out = []
    for k, side in ((-2, -6.0), (-3, -2.0), (-4, 2.0), (-5, 6.0)):
        x, y, h = place(k, side)
        out.append(f"obj obstacle cube ball.mod {x:.6f},{y:.6f}:{h + 1.0:.6f} 2.000000")
    for k, side in ((-7, -4.0), (-7, 4.0)):
        x, y, h = place(k, side)
        out.append(f"obj static box {x:.6f},{h:.6f},{y:.6f} "
                   f"2.000000,0.000000,0.000000 0.000000,3.000000,0.000000")
    return out


def cow_mesh_member(work: Path, cows, prop_materials) -> bytes | None:
    """One cow as a standalone `.mod`, centred on its own origin.

    `obj obstacle` names a mesh and a position, so the mesh has to sit at the
    origin and be placed by the record -- unlike the world geometry, which
    carries its own absolute coordinates.
    """
    if not cows:
        return None
    full = read_arena_obj(work / "arena.obj")
    pieces = trackgen.split_by_material(full)
    cow_piece = next((p for p in pieces.values()
                      if p.materials and p.materials[0].name == COW_MATERIAL), None)
    if cow_piece is None:
        return None
    one = split_per_instance(cow_piece, cows)[0]
    cx = sum(v.x for v in one.vertices) / len(one.vertices)
    cy = min(v.y for v in one.vertices)          # stand it on its own feet
    cz = sum(v.z for v in one.vertices) / len(one.vertices)
    for v in one.vertices:
        v.x, v.y, v.z = v.x - cx, v.y - cy, v.z - cz
    for mat in one.materials:
        mat.name = trackgen.fit_texture_names([mat.name])[mat.name]
    return mod.build(one)


def cow_facing_mesh(work: Path, cows) -> "mod.Mesh | None":
    """One cow in a FACING model's own frame: origin at its feet, up along -z.

    A facing's local up is -z -- every stock chevron runs z from 0 at its base
    to about -2.5 at its top -- and a wobble topples by rotating about its
    origin, so the cow has to stand ON that origin or it pivots about its
    middle. The rotation is -90 degrees about x, (x, y, z) -> (x, z, -y), which
    is proper, so the winding survives it and no face turns inside out.

    A REAL COW, not a billboard: a facing node carries an arbitrary
    mrModelInfo, so there is no reason for it to be flat. Stock facings are
    tiny -- 28 vertices is the largest in any shipped track, and this cow is
    328 -- but that is chevrons being chevrons, not an engine limit. The same
    mrModelBuildLit path builds car models of 1,200 to 20,000 vertices, and a
    wobble's physics comes from its `.sol` tube, not from its mesh.
    """
    if not cows:
        return None
    full = read_arena_obj(work / "arena.obj")
    pieces = trackgen.split_by_material(full)
    cow_piece = next((p for p in pieces.values()
                      if p.materials and p.materials[0].name == COW_MATERIAL), None)
    if cow_piece is None:
        return None
    one = split_per_instance(cow_piece, cows)[0]
    cx = sum(v.x for v in one.vertices) / len(one.vertices)
    cy = min(v.y for v in one.vertices)          # stand it on its own feet
    cz = sum(v.z for v in one.vertices) / len(one.vertices)
    for v in one.vertices:
        x, y, z = v.x - cx, v.y - cy, v.z - cz
        v.x, v.y, v.z = x, z, -y
    for mat in one.materials:
        mat.name = trackgen.fit_texture_names([mat.name])[mat.name]
    return one


def our_textures(work: Path, tex_names: dict) -> dict[str, bytes]:
    """The preview's PNGs as .tex files, keyed by the member name each becomes."""
    out = {}
    for original, member in tex_names.items():
        png = work / "tex" / f"{original}.png"
        if not png.exists():
            continue
        im = Image.open(png)
        size = min(1 << max(3, (max(im.size) - 1).bit_length()), trackgen.TEX_MAX_SIZE)
        if im.size != (size, size):
            im = im.resize((size, size), Image.NEAREST)
        if im.mode == "RGBA" and min(im.getdata(band=3)) < 128:
            out[member] = tex.encode_to_tex(im.tobytes(), size, mode="colorkey", wrap=0)
        else:
            out[member] = tex.encode_to_tex(im.convert("RGB").tobytes(), size,
                                            mode="opaque", wrap=1)
    return out


def patch_wobble_centres(path: Path, cows, wobbles: int) -> tuple[int, int]:
    """VESTIGIAL, and it never did anything. Kept only so the pre-facing path
    still runs; the facing path skips it entirely.

    The observation behind it was real -- hastings' 15 wobble tubes and its 15
    chunks "carrying a non-zero centre" do correspond exactly -- but the reading
    was wrong twice over. Those 15 records are the type-4 FACING nodes, and the
    "centre" was their +0x3c seen 24 bytes out of true by grf.parse()'s resync.
    A type-3 chunk has no centre field at all: +36 is the ptr2 slot the loader
    fills in, so what this writes is overwritten at load.

    And `WobbleObject::Draw` does not follow a centre. It draws a model HANDLE,
    resolved once in the constructor by GrafLookupDynoModel from the wobble's
    id -- see file-formats.md §4.3, and grf.build_facing_chunk for the node
    that actually registers it.
    """
    entries = archive.read(path)
    ent = next(e for e in entries if e.name.lower() == "track.grf")
    g = grf.parse(envelope.build(ent.tag, ent.version, ent.payload))
    m = g.mesh
    centroid = []
    for c in g.chunks:
        vs = m.vertices[c.corner_start:c.corner_end]
        centroid.append((sum(v.x for v in vs) / len(vs),
                         sum(v.z for v in vs) / len(vs)) if vs else None)

    patched, skipped = [], 0
    for k in range(wobbles):
        x, y, z = cows[k]
        best, closest = None, float("inf")
        for i, c in enumerate(centroid):
            if c is None or not g.chunks[i].texture.lower().startswith(COW_MATERIAL):
                continue
            d = (c[0] - x) ** 2 + (c[1] - z) ** 2
            if d < closest:
                best, closest = i, d
        if best is None or not g.layout[best].exact:
            skipped += 1
            continue
        g.layout[best].center = (x, y + 0.5, z)      # the tube's own position
        patched.append(best)

    buf = bytearray(grf.to_bytes(g))
    for i in patched:
        struct.pack_into("<3f", buf, envelope.SIZE + g.layout[i].center_offset,
                         *g.layout[i].center)
    env = envelope.parse(bytes(buf))
    ent.tag, ent.version, ent.payload = env.tag, env.version, env.payload
    archive.write(entries, path)
    return len(patched), skipped


def add_member(path: Path, name: str, whole: bytes, tag: bytes, version: int) -> None:
    """Put a member into the archive, replacing one of that name if present.

    `obj obstacle` resolves its mesh BY NAME, the way the engine resolves
    ball.mod, so the mesh has to be a member of an archive the game has loaded
    -- the track's own will do.
    """
    if whole[:4] == envelope.MAGIC:
        env = envelope.parse(whole)
        tag, version, payload = env.tag, env.version, env.payload
    else:
        payload = whole
    entries = archive.read(path)
    for e in entries:
        if e.name.lower() == name.lower():
            e.tag, e.version, e.payload = tag, version, payload
            break
    else:
        entries.append(archive.ArchiveEntry(name=name, tag=tag, version=version,
                                            payload=payload))
    archive.write(entries, path)


def replace_members(path: Path, payloads: dict[str, bytes]) -> int:
    """Swap complete files (envelope included) in for members of the archive."""
    entries = archive.read(path)
    swapped = 0
    for e in entries:
        whole = payloads.get(e.name.lower())
        if whole is None:
            continue
        env = envelope.parse(whole)
        e.tag, e.version, e.payload = env.tag, env.version, env.payload
        swapped += 1
    archive.write(entries, path)
    return swapped


def main(argv):
    if len(argv) != 5:
        raise SystemExit("arena_track.py <sosc_dir> <city.sc2> <work_dir> <donor.trk> <out.trk>")
    sosc, city_path, work, donor, out_path = (Path(a) for a in argv)
    work.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stats = arena_stats(sosc, city_path, work)

    r = route_mod.build(sosc, city_path)
    line = [route_mod.to_source(p) for p in r["stations"]]
    gates = [(name, i, [route_mod.to_source(p) for p in pts]) for name, i, pts in r["gates"]]
    cows = cow_positions(stats)
    # Choose the wobble cows BEFORE the geometry is built. Each one gets a
    # billboard, and its solid prop has to come out of the drawn mesh: left in,
    # it stands in front of its own wobble and there is nothing to knock over.
    placed_cows, rest_cows = cows_near_route(cows, r["stations"], PLACED_COWS)
    placed_set = set(placed_cows)
    drop_cows = {i for i, c in enumerate(cows) if c in placed_set}
    scene, tex_names = build_scene(
        work, line, gates, [route_mod.to_source(p) for p in r["grid"]],
        set(stats.get("prop_materials", ())), cows, drop_cows)

    # THE WOBBLES, declared on the scene so trackbuild emits all three pieces --
    # the facing node, the `.sol` tube and the `obj wobble` record -- from one
    # list, with the ids agreeing by construction rather than by three separate
    # loops happening to count the same way.
    if placed_cows:
        facing = cow_facing_mesh(work, cows)
        if facing is None:
            raise SystemExit("no cow mesh to use as a facing model")
        wrong = [c for c in placed_cows
                 if trackgen.to_viper(to_source_point(c)) != tuple(c)]
        if wrong:
            raise SystemExit(f"frame conversion is wrong for {len(wrong)} wobbles")
        scene.meshes[FACING_MESH] = facing
        scene.wobbles = [trackgen.Wobble(position=to_source_point(c),
                                         mesh=FACING_MESH, radius=COW_TUBE_RADIUS,
                                         height=COW_TUBE_HEIGHT)
                         for c in placed_cows]
        print(f"  facing model: one cow, {len(facing.vertices)} verts, "
              f"{len(facing.faces)} faces, texture {facing.materials[0].name} "
              f"(largest facing in any shipped track is 28 verts)")

    st = r["stations"]
    cum, total = [0.0], 0.0
    for i in range(1, len(st)):
        total += math.dist(st[i - 1][:2], st[i][:2])
        cum.append(total)
    scene.gate_distances = [cum[i] for _n, i, _p in gates]

    donor_entries = {e.name.lower() for e in archive.read(donor)}
    stand_in = next(n for n in sorted(donor_entries) if n.endswith(".tex"))
    wanted = sorted({m.name for mesh in scene.meshes.values() for m in mesh.materials})
    common = dict(donor=donor, out_path=out_path, slot=out_path.stem.lower(),
                  textures={w: stand_in for w in wanted},
                  corridor=ili.corridor_for(ROAD_WIDTH), closed=True)
    try:
        result = trackbuild.assemble(scene, **common)
    except Exception as e:                                      # noqa: BLE001
        # The strict check refuses a tree where some fragment would answer with
        # the wrong surface or height. Worth seeing rather than hiding, but not
        # worth blocking a first drive: a dropped fragment is a patch of ground
        # whose grip is its neighbour's.
        if "strict=False" not in str(e):
            raise
        print(f"  collision tree, strict: {str(e).splitlines()[0]}")
        result = trackbuild.assemble(scene, strict=False, **common)
        print("  built with strict=False")

    boxes = prop_boxes(stats)
    # The placed-model experiment takes the cows nearest the racing line, so
    # they are met early. They get a tube carrying their own id and a wobble
    # record; they must NOT also be obstacles, or two mechanisms fight over one
    # animal, and the tube must be the one whose id the wobble names.
    knockable, solid = cows_near_route(rest_cows, r["stations"], OBSTACLE_COWS)
    wobbles = len(placed_cows) if PLACED_COWS else min(WOBBLE_COWS, len(cows))
    payloads = {k.lower(): v for k, v in our_textures(work, tex_names).items()}
    # Tube ids are positional, so the placed cows must come FIRST: wobble N
    # names tube id N, and that tube has to be the one under placed model N.
    tube_cows = list(placed_cows) + (list(solid) if COW_TUBES else [])
    sol_payload, tube_count = our_sol(donor, tube_cows, boxes, wobbles)
    payloads["track.sol"] = sol_payload
    obstacles = [(x, y, z) for x, y, z in knockable]
    extra = test_row_records(r["stations"]) if TEST_ROW else []
    payloads["track.obt"] = our_obt(scene, wobbles, obstacles, extra)
    swapped = replace_members(out_path, payloads)

    # THE COLOUR-KEY TRAP. A texel whose colour quantises to raw 0x0000 (or
    # 0x0020, the same black with green's insignificant low bit set) sits on the
    # reserved transparent marker, and drivers that honour it in OPAQUE textures
    # punch holes wherever the art is black -- the cows' own markings came out
    # see-through. The sweep lifts those texels to 0x0040, still black to look
    # at, and leaves colorkey and alpha textures alone, where 0x0000 means what
    # it says. Run over the finished archive so every mip level is covered:
    # averaging two dark texels lands back on the marker.
    cow_member = (cow_mesh_member(work, cows, set(stats.get("prop_materials", ())))
                  if OBSTACLE_MESH == "cow.mod" else None)
    if cow_member and obstacles:
        add_member(out_path, OBSTACLE_MESH, cow_member, mod.TAG, 1)

    # The facing nodes were emitted by trackbuild.assemble from scene.wobbles,
    # through grf.append_facings -- nothing is appended to the archive here.
    placed_count = len(scene.wobbles)

    if placed_cows:
        # The facing nodes ARE the wobble models, so the old centre patch is now
        # not just unnecessary but destructive: it rewrites the whole .grf
        # through grf.parse()/to_bytes(), whose resync has never seen a type-4
        # node and would mangle the ones just appended. Its premise is dead too
        # -- the "chunks carrying a centre" it matched in hastings were these
        # very facings, read 24 bytes out of true.
        centred, no_centre = 0, 0
    else:
        centred, no_centre = patch_wobble_centres(out_path, cows, wobbles)

    swept, reports = dekey.sweep_bytes(out_path.read_bytes())
    lifted = sum(r.lifted for r in reports)
    if lifted:
        out_path.write_bytes(swept)

    # The meshes and the placed objects must share a frame. They did not once,
    # and nothing said so until the game drew an empty sky.
    # The facing mesh is in its own LOCAL frame, so it would wreck this bbox.
    verts = [(v.x, v.y, v.z) for name, m in scene.meshes.items()
             if name != FACING_MESH for v in m.vertices]
    print(f"  meshes   {bbox(verts)}")
    print(f"  grid+gates {bbox([trackgen.to_viper(p) for p in scene.grid] + [trackgen.to_viper(p) for g in scene.markers.values() for p in g])}")
    print(f"  {out_path.name}  {out_path.stat().st_size:,} bytes")
    print(f"  {len(scene.driveables)} driveable chunks, {len(scene.scenery)} scenery, "
          f"{max((len(m.vertices) for m in scene.meshes.values()), default=0)} vertices in the biggest")
    print(f"  {result.triangles:,} collision triangles, {result.nodes:,} nodes")
    print(f"  collision: {tube_count} cow TUBEs + {len(boxes)} tower BOXes; "
          f"{wobbles} tubes carry ids 0..{max(wobbles - 1, 0)}, "
          f"{max(tube_count - wobbles, 0)} carry -1 like every stock plain primitive")
    if placed_count:
        print(f"  WOBBLES: {placed_count} cow facings emitted by trackbuild from "
              f"scene.wobbles (ids 0..{placed_count-1}), each with a tube of the "
              f"same id and an `obj wobble pole` record")
    print(f"  wobble models: {centred} cow chunks given a centre at their tube"
          + (f", {no_centre} skipped (no patchable chunk)" if no_centre else ""))
    print(f"  cows: {len(knockable)} knockable (obstacles, no tube), {len(solid)} solid (tubes)")
    print(f"  obstacles: {len(obstacles)} `obj obstacle {OBSTACLE_KIND} {OBSTACLE_MESH}` records"
          + (f", {OBSTACLE_MESH} added ({len(cow_member):,} bytes)" if cow_member and obstacles
             else " (no mesh member)"))
    print(f"  {swapped - 1}/{len(wanted)} textures replaced with SoSC's own")
    print(f"  {lifted:,} black texels lifted off the transparency marker "
          f"in {sum(1 for r in reports if r.lifted)} textures")
    print(f"  gates at {[round(d) for d in scene.gate_distances]} m of {total:.0f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
