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
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import arena                                                # noqa: E402
import route as route_mod                                   # noqa: E402

from vrmod import archive, dekey, envelope, ili, mod, sol, tex, trackbuild, trackgen  # noqa: E402

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
    boxes = ([] if COW_MATERIAL in DROP_MATERIALS else
             [(x, y, z, COW_BOX[0], COW_BOX[1], COW_BOX[2])
              for x, y, z in stats.get("cow_at", [])])
    boxes += [(x, y, z, TOWER_BOX, TOWER_BOX, TOWER_HEIGHT)
              for tid, (x, y, z) in stats.get("prop_at", []) if tid == TOWER_ID]
    return boxes


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


def build_scene(work: Path, line, gates, grid, prop_materials) -> tuple["trackgen.TrackScene", dict]:
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
        for k, part in enumerate(split_to_cap(piece)):
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


def our_sol(donor: Path, boxes) -> bytes:
    """track.sol: one BOX per solid prop, each at its own height."""
    src = {e.name.lower(): e for e in archive.read(donor)}
    e = src["track.sol"]
    template = sol.wall_template(sol.parse(envelope.build(e.tag, e.version, e.payload)))
    prims = [sol.box_from_segment(template, (cx - sx / 2, cy, cz), (cx + sx / 2, cy, cz),
                                  height=h, thickness=sz)
             for cx, cy, cz, sx, sz, h in boxes]
    index, tail = sol.build_spatial_index(prims)
    built = sol.Sol(primitives=prims, index=index, tail=tail, version=trackbuild.SOL_VERSION)
    return sol.build(built)


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
    scene, tex_names = build_scene(
        work, line, gates, [route_mod.to_source(p) for p in r["grid"]],
        set(stats.get("prop_materials", ())))

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
    payloads = {k.lower(): v for k, v in our_textures(work, tex_names).items()}
    payloads["track.sol"] = our_sol(donor, boxes)
    swapped = replace_members(out_path, payloads)

    # THE COLOUR-KEY TRAP. A texel whose colour quantises to raw 0x0000 (or
    # 0x0020, the same black with green's insignificant low bit set) sits on the
    # reserved transparent marker, and drivers that honour it in OPAQUE textures
    # punch holes wherever the art is black -- the cows' own markings came out
    # see-through. The sweep lifts those texels to 0x0040, still black to look
    # at, and leaves colorkey and alpha textures alone, where 0x0000 means what
    # it says. Run over the finished archive so every mip level is covered:
    # averaging two dark texels lands back on the marker.
    swept, reports = dekey.sweep_bytes(out_path.read_bytes())
    lifted = sum(r.lifted for r in reports)
    if lifted:
        out_path.write_bytes(swept)

    # The meshes and the placed objects must share a frame. They did not once,
    # and nothing said so until the game drew an empty sky.
    verts = [(v.x, v.y, v.z) for m in scene.meshes.values() for v in m.vertices]
    print(f"  meshes   {bbox(verts)}")
    print(f"  grid+gates {bbox([trackgen.to_viper(p) for p in scene.grid] + [trackgen.to_viper(p) for g in scene.markers.values() for p in g])}")
    print(f"  {out_path.name}  {out_path.stat().st_size:,} bytes")
    print(f"  {len(scene.driveables)} driveable chunks, {len(scene.scenery)} scenery, "
          f"{max((len(m.vertices) for m in scene.meshes.values()), default=0)} vertices in the biggest")
    print(f"  {result.triangles:,} collision triangles, {result.nodes:,} nodes")
    print(f"  {len(boxes)} solid props (cows and towers) as .sol boxes")
    print(f"  {swapped - 1}/{len(wanted)} textures replaced with SoSC's own")
    print(f"  {lifted:,} black texels lifted off the transparency marker "
          f"in {sum(1 for r in reports if r.lifted)} textures")
    print(f"  gates at {[round(d) for d in scene.gate_distances]} m of {total:.0f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
