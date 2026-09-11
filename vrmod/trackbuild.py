"""Assemble a complete, installable track archive from a generated scene.

WHAT THIS REPLACES. The historical chain was `trackgen` to write MKWORLD's source
set, then `make-track.bat` (MKWORLD, then `nhmkworld`) to compile it, then
`compile-track.bat`/`mkres` to pack. Every compiled member now has a native
writer, so the whole thing runs here:

    track.grf   grf.build()             render geometry
    track.bpp   bpp.build_tree()        collision tree -- the step that needed
                                        nhmkworld until it didn't
    track.obt   trackgen.build_obt()    scene objects
    track.bsp   bsp.build()             the fixed 108-byte world-bounds record
    track.sol   sol.empty()/build()     barrier primitives
    *.ili/.ild  ili.generate()          racing and checkpoint lines

WHAT A DONOR SUPPLIES, and why that is not cheating. Three members are authored
configuration rather than compiled output, and the original `compile-track.bat`
copied them verbatim too:

    aidef.ccs, <slot>.ccs   AI and handling tuning, 140 bytes each
    camera.tab              broadcast camera definitions

Textures come from the donor as well, renamed to the names the swept meshes
reference. A generated track has no art of its own; borrowing a stock track's
asphalt and grass is what makes it drivable rather than untextured. Supply your
own by passing `textures`.

TEXTURE NAMES are 8.3 and at most 12 characters, and a name that breaks that
rule fails silently -- the surface renders as flat colour with no error. See the
format reference; this checks rather than trusting the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import archive, bpp, bsp, envelope, grf, ili, sol, trackgen

GRF_TAG, GRF_VERSION = b"FARG", 3
OBT_TAG, OBT_VERSION = b"BATS", 0
BSP_TAG, BSP_VERSION = b"TPSB", 0
SOL_TAG, SOL_VERSION = b"LBOS", 2
BPP_TAG, BPP_VERSION = b"TPPB", 2
ILI_TAG, ILI_VERSION = b"NILI", 3

# Members that are configuration, not compiled output.
DONOR_CONFIG = ("aidef.ccs", "camera.tab")

TEX_NAME_LIMIT = 12


@dataclass
class BuildResult:
    path: Path
    members: list[tuple[str, int]] = field(default_factory=list)
    triangles: int = 0
    nodes: int = 0
    depth: int = 0
    textures: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        total = sum(n for _, n in self.members)
        return (f"{len(self.members)} members, {total:,} bytes; "
                f"{self.triangles:,} collision triangles in {self.nodes:,} nodes "
                f"(depth {self.depth})")


def _donor_members(donor: Path) -> dict[str, archive.ArchiveEntry]:
    return {e.name.lower(): e for e in archive.read(donor)}


# What a swept track asks for, against what a stock track calls the same thing.
# Guessing by name does not work -- a generated track wants `grass.tex` and
# bemidji's is `grs.tex` -- and guessing WRONG is invisible: a mesh whose texture
# is missing from the archive renders as flat colour with no error, or takes the
# renderer down with "tmap: unknown texture format". So the map is explicit, and
# a name with no stand-in is a hard failure rather than a silently dropped
# member.
STOCK_STAND_INS = {
    "asphalt.tex": ("asph.tex",),
    "grass.tex": ("grs.tex",),
    "rumble.tex": ("redwht.tex", "blwh.tex"),      # kerbing: red/white, then black/white
    "side.tex": ("blwh.tex", "strpy.tex"),
}

# The sky is four fixed members every track carries; without them the horizon
# renders as nothing.
SKY_TEXTURES = ("sky1.tex", "sky2.tex", "sky3.tex", "sky4.tex")


def _texture_map(scene, donor_entries, overrides=None):
    """Which donor texture stands in for each name the meshes reference."""
    wanted = sorted({m.name for mesh in scene.meshes.values() for m in mesh.materials})
    out, missing = {}, []
    for want in wanted:
        pick = None
        if overrides and want in overrides:
            pick = overrides[want].lower()
        elif want.lower() in donor_entries:
            pick = want.lower()
        else:
            for cand in STOCK_STAND_INS.get(want.lower(), ()):
                if cand in donor_entries:
                    pick = cand
                    break
        if pick is None or pick not in donor_entries:
            missing.append(want)
        else:
            out[want] = pick
    if missing:
        raise ValueError(
            f"no texture for {missing} in the donor. A mesh whose texture is not "
            f"in the archive renders as flat colour, or panics the renderer -- "
            f"pass `textures={{'{missing[0]}': '<a donor .tex>'}}` to choose one")
    return out


def assemble(scene, *, donor: str | Path, out_path: str | Path,
             slot: str = "track", textures: dict | None = None,
             corridor: float | None = None, closed: bool = True,
             speed: float | None = None, **bpp_kw) -> BuildResult:
    """Build a complete track archive from a TrackScene.

    `donor` is a stock .trk to take configuration and art from. `slot` names the
    per-track .ccs member, which the game looks for by the track's own name.
    """
    donor = Path(donor)
    out_path = Path(out_path)
    src = _donor_members(donor)

    entries: list[archive.ArchiveEntry] = []

    def add(name: str, tag: bytes, version: int, payload: bytes) -> None:
        entries.append(archive.ArchiveEntry(
            name=name, tag=tag, version=version, payload=payload))

    # ---- render geometry -------------------------------------------------
    tex_for = _texture_map(scene, src, textures)
    chunks = []
    for obj in list(scene.driveables) + list(getattr(scene, "scenery", [])):
        mesh = scene.meshes.get(obj.name)
        if mesh is None or not mesh.faces:
            continue
        name = mesh.materials[0].name if mesh.materials else "asphalt.tex"
        chunks.append((mesh, name))
    if not chunks:
        raise ValueError("the scene has no drawable geometry")
    add("track.grf", GRF_TAG, GRF_VERSION,
        envelope.parse(grf.build(chunks, GRF_VERSION)).payload)

    # ---- collision -------------------------------------------------------
    tris = trackgen.collision_triangles(scene)
    tree = bpp.build_tree(tris, **bpp_kw)
    add("track.bpp", BPP_TAG, BPP_VERSION, bpp.build(tree))

    # ---- scene objects, world bounds, barriers ---------------------------
    # build_obt returns a COMPLETE file, envelope included -- storing that as a
    # payload wraps it twice, and the reader then reads "0SER" as a record count.
    add("track.obt", OBT_TAG, OBT_VERSION,
        envelope.parse(trackgen.build_obt(scene)).payload)
    add("track.bsp", BSP_TAG, BSP_VERSION, envelope.parse(bsp.build()).payload)
    add("track.sol", SOL_TAG, SOL_VERSION, envelope.parse(sol.empty(SOL_VERSION)).payload)

    # ---- racing lines ----------------------------------------------------
    # THE CENTRELINE IS IN THE SOURCE FRAME; the meshes are not. to_viper()
    # negates both ground axes, so a line built from the raw centreline comes out
    # mirrored through the origin -- the AI then drives a perfect lap of a road
    # that is not there. Measured before this: 40 of 40 waypoints landed on the
    # road only after negating. Same trap as the walls, which needed flip=False.
    pts = [(v[0], v[2]) for v in
           (trackgen.to_viper(p) for p in scene.centreline)]
    half = trackgen.DEFAULT_ROAD_HALF_WIDTH
    corr = corridor if corridor is not None else ili.corridor_for(half * 2.0)
    # `gates` is the cumulative distance of each checkpoint, which is what the
    # checkpoint line's sector tags split on. Taken from the scene so the lines
    # and the object table agree about where the gates are.
    gates = list(getattr(scene, "gate_distances", ()) or ()) or None
    common = dict(closed=closed, corridor=corr, gates=gates)
    if speed is not None:
        common["speed"] = speed
    for member, kind, sectors, rev in (
            ("default.ili", ili.KIND_ILI, False, False),
            ("rdefault.ili", ili.KIND_ILI, False, True),
            ("track.ild", ili.KIND_ILD, True, False)):
        line = ili.generate(list(reversed(pts)) if rev else pts,
                            kind=kind, sectors=sectors, **common)
        add(member, ILI_TAG, ILI_VERSION, envelope.parse(ili.build(line)).payload)

    # ---- configuration and art, from the donor ---------------------------
    for want in DONOR_CONFIG:
        e = src.get(want)
        if e is not None:
            add(e.name, e.tag, e.version, e.payload)
    ccs = next((e for n, e in src.items()
                if n.endswith(".ccs") and not n.startswith("aidef")), None)
    if ccs is not None:
        add(f"{slot}.ccs", ccs.tag, ccs.version, ccs.payload)
    shot = src.get("trackmap.stp")
    if shot is not None:
        add(shot.name, shot.tag, shot.version, shot.payload)

    for sky in SKY_TEXTURES:
        e = src.get(sky)
        if e is not None:
            add(e.name, e.tag, e.version, e.payload)

    used = {}
    for want, donor_name in sorted(tex_for.items()):
        e = src[donor_name]
        if len(want) > TEX_NAME_LIMIT or "_" in want:
            raise ValueError(
                f"texture name {want!r} breaks the 8.3 rule -- the game fails "
                f"silently on these, rendering flat colour with no error")
        add(want, e.tag, e.version, e.payload)
        used[want] = donor_name

    out_path.write_bytes(archive.to_bytes(entries))
    r = tree.build_report
    return BuildResult(
        path=out_path,
        members=[(e.name, len(e.payload)) for e in entries],
        triangles=len(tree.triangles), nodes=len(tree.nodes),
        depth=r["max_depth"], textures=used)
