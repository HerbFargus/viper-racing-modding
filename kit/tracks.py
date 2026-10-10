"""Finishing a generated track after trackbuild.assemble: textures, sky, cameras, solid
boxes, obstacles, menu picture, install -- plus the slope rules for height().

SLOPE RULES (confirmed in game on the Coliseum):
  * A near-vertical COLLISION triangle acts as a wall for anything passing over it, however
    high. Every jump lip needs a real back slope -- 35 degrees works (Coliseum: 14 m over 20 m)
    -- and so does the back of a landing ramp that faces the takeoff.
  * The .bpp holds one floor per (x, z): nothing drivable under a drivable deck.
  * A solid roof over the road is a launch pad. Keep roofs drawn-only (Batch solid=False).
  * Only a soft landing is on a DOWNslope, and only when the car barely clears the crest.
  * Steep sides are fine where nobody flies over them: Cats vs Dogs' roof uses 78-degree
    sides as rails.

BUDGETS: collision triangles <= ~16,500 (the .bpp); drawn chunks <= 990 verts; drawn
surfaces well under 600 (the 1,024 pool is shared with the cars); textures 8.3, <= 256 px,
~119 in all with the cars on the stock engine; placed objects (cars + checkpoints + obstacles
+ wobbles) <= 512, keep one spare for the horn ball. .sol spheres/boxes cost none of these.

OBSTACLES: `obj obstacle ball|cube <mesh>.mod X,Z:YAW MASS` -- X, Z from game(); YAW in
DEGREES; MASS in POUNDS (50 rolls nicely, 10,000 crushes cars). The mesh is centred on its
own middle; a ball's collision radius is half the mesh HEIGHT; the engine drops each one
from 4 m over the ground at the start, so put them on level ground. A track only ships
textures its DRAWN meshes use -- give obstacles a texture some prop draws (or bury an anchor
triangle). Obstacles in the race path have crashed AI races; test solo, then with AI.

WATER: surface code 14 (trackgen.WATER). The car floats on it, with no grip. Make it flat at
one height; Ridge Valley's own texture is wat2.tex.
"""
from __future__ import annotations

import math
import shutil
import struct
from pathlib import Path

import numpy as np
from PIL import Image

import kit
from kit.terrain import game
from vrmod import archive, camtab, envelope, mod, obt, sky, sol, stp, switcher, tex, track, trackmap


def by_name(entries):
    return {e.name.lower(): e for e in entries}


def set_member(entry, raw: bytes):
    """Overwrite an archive entry with standalone file bytes."""
    env = envelope.parse(raw)
    entry.tag, entry.version, entry.payload = env.tag, env.version, env.payload


def image_tex(im: Image.Image, wrap: int = 0) -> bytes:
    """An opaque .tex from a square power-of-two PIL image, with no texel on the 0x0000 key."""
    a = np.array(im.convert("RGB"))
    a = np.maximum(a, 6)
    return tex.encode_to_tex(Image.fromarray(a).tobytes(), im.width, mode="opaque", wrap=wrap)


def stock_member(trk: Path, name: str) -> archive.ArchiveEntry:
    """A member from a stock track -- e.g. Ridge Valley's water: stock_member(<hastings>, 'wat2.tex')."""
    return by_name(archive.read(trk))[name.lower()]


def set_sky(entries, im: Image.Image):
    by = by_name(entries)
    for name, raw in zip(sky.TILES, sky.build_tiles(im.tobytes(), im.width, im.height, 256)):
        set_member(by[name], raw)


def cameras(entries, spots):
    """Fixed trackside cameras: spots = [(source position, source target), ...]."""
    cams = []
    for pos, tgt in spots:
        gp, gt = game(pos), game(tgt)
        cams.append(camtab.Camera("fixed", *gp, *camtab.aim(gp, gt)))
    by_name(entries)["camera.tab"].payload = camtab.build(cams)


def closed_box(template, a, b, height, thickness):
    """A free-standing solid box on the source-frame segment a -> b (base at a's z). main's
    box_from_segment keeps the barrier template's open ends (mode 3 at +0x68), which cars
    drive straight through; 0 closes them."""
    prim = sol.box_from_segment(template, game(a), game(b), height=height, thickness=thickness)
    raw = bytearray(prim.raw)
    struct.pack_into("<i", raw, 0x68, 0)
    return sol.Primitive(raw=bytes(raw))


def add_boxes(entries, boxes):
    """Append closed boxes [(a, b, height, thickness)] to track.sol and rebuild its index."""
    e = by_name(entries)["track.sol"]
    s = sol.parse(envelope.build(e.tag, e.version, e.payload))
    tpl = sol.wall_template(s)
    prims = list(s.primitives) + [closed_box(tpl, a, b, h, t) for a, b, h, t in boxes]
    index, tail = sol.build_spatial_index(prims)
    set_member(e, sol.build(sol.Sol(primitives=prims, index=index, tail=tail, version=s.version)))
    return len(prims)


def add_obstacles(entries, meshes: dict, records):
    """meshes {name.mod: mod.Mesh}; records [(mesh name, source x, source y, yaw deg, mass lb, kind)]."""
    for name, m in meshes.items():
        env = envelope.parse(mod.build(m))
        entries.append(archive.ArchiveEntry(name=name, tag=env.tag, version=env.version, payload=env.payload))
    e = by_name(entries)["track.obt"]
    table = obt.parse(envelope.build(e.tag, e.version, e.payload))
    recs = [r for r in table.records if r != obt.TERMINATOR]
    for name, x, y, yaw, mass, kind in records:
        gx, _gy, gz = game((x, y, 0.0))
        recs.append(f"obj obstacle {kind} {name} {gx:.6f},{gz:.6f}:{yaw % 360:.1f} {mass:.6f}")
    table.records = recs + [obt.TERMINATOR]
    set_member(e, obt.build(table))
    return len(obt.parse(obt.build(table)).objects)


def finish(entries, out: Path, name: str, menu: Image.Image | None = None, tra_dir: Path | None = None) -> Path:
    """Write the .trk, render its track map, export <name>.tra (+ <name>.stp menu picture,
    180 x 120) into tra_dir (default: next to out)."""
    archive.write(entries, out)
    trackmap.install(out, out)
    tra_dir = Path(tra_dir or out.parent)
    tra = tra_dir / f"{name}.tra"
    track.export_tra(out, tra, layout="flat")
    if menu is not None:
        im = menu.convert("RGB").resize((180, 120))
        (tra_dir / f"{name}.stp").write_bytes(stp.to_loose(stp.build_from_rgb(im.tobytes(), 180, 120)))
    return tra


def install(tra: Path, slot: str, data: Path = kit.INSTALL) -> str:
    """Copy <name>.tra (+ .stp) into the game folder and swap it into `slot`. The stock file is
    kept once as <slot>_AS_<name>.btr; switcher.restore(data, slot) puts it back. The menu
    name is cut to the slot's width: Bemidji 7, Dundas 6, Ridge Valley 12, Castlegreen 11,
    Rock Island 11, Arena/Limbo, Sunset Mesa 11, Silverdale 10. The game must not be running."""
    for f in (tra, tra.with_suffix(".stp")):
        if f.exists() and f.parent != data:
            shutil.copy2(f, data / f.name)
    switcher.install(data, data / tra.name, slot, force=True)
    st = {s.slot: s for s in switcher.status(data)}[slot]
    return f"{slot}: menu shows '{st.display_name}', stock kept as {st.backup.name if st.backup else None}"


def render(trk: Path, png: Path, fit_source_rect=None, yaw=200.0, pitch=50.0, size=(900, 560)):
    """A textured still from vrmod's software renderer, framed on a source-frame rectangle
    (x0, x1, y0, y1[, height]). The quickest look at a build without the game."""
    from vrmod import carshot, viewer
    mesh = viewer._track_render_mesh(trk)
    kw = {}
    if fit_source_rect:
        x0, x1, y0, y1, *z = fit_source_rect
        top = z[0] if z else 10.0
        kw["fit"] = [game((x, y, zz)) for x in (x0, x1) for y in (y0, y1) for zz in (0.0, top)]
    px, w, h = carshot.render(mesh, style="textured", width=size[0], height=size[1], yaw=yaw, pitch=pitch,
                              textures=carshot.track_material_textures(trk, mesh), **kw)
    rows = [bytearray(px[y * w * 3:(y + 1) * w * 3]) for y in range(h)]
    Path(png).write_bytes(viewer._rgb_png(w, h, rows))
