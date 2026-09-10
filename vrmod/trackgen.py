"""Generate a track's MKWORLD source set from a centreline.

This is the *driving* half of the track pipeline (see VIPER_RACING_FILE_FORMATS.md,
"vrTrackMaker -- the driving model, not the track"): a centreline goes in, and the
two fooland*.txt scene sources plus their swept meshes come out, ready for
mkfltoa/MKWORLD. The looks half -- the visible track -- comes from a modeller.

One invariant is worth stating up front, because it is the reason this module
exists rather than string formatting at the call site: **both scene files are
emitted from a single TrackScene**, so the rule that every driveable object
appears in BOTH files under the same name and the same surface code cannot be
violated by construction. Divergence between the two copies is the classic
authoring failure -- a track that looks right and drives wrong.

Coordinate frames, measured against vrTrackMaker's own output rather than assumed:

  - The .ase centreline and the fooland*.txt text share one frame: the ground
    plane is x/y and z is always 0.
  - The .mod meshes use the game's frame, where y is up and both ground axes are
    negated:  mesh(x, y, z) = (-ase.x, height, -ase.y)

The check that settled it: the nearest asphalt vertex to the first centreline
point lies 6.000 away under that mapping, which is exactly the Road band's
distance-to-centre -- a number that had to come out right and did.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import mod, obt as obt_mod

# Surface codes, as measured in the shipped .bpp files and confirmed from the
# generator's own output. Anything outside this set has to be hand-applied or
# retagged afterwards with `vrmod bppsurface`.
ROAD, GRASS, WATER, RUMBLE, DIRT = 0, 10, 14, 16, 20

# First modobject parameter. 0 generates collision geometry; 3 does not, which is
# what walls and scenery use -- their collision comes from .sol solids instead.
SOLID, NO_COLLISION = 0, 3


# --------------------------------------------------------------------------
# Phase 0: getting a centreline in
# --------------------------------------------------------------------------

Point = tuple[float, float, float]

_KNOT = re.compile(
    r"\*SHAPE_VERTEX_KNOT\s+\d+\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)"
)


def read_ase(path: str | Path) -> list[Point]:
    """Read a 3DS Max ASCII export, returning its spline knots.

    Only the knots are wanted; ASE carries a lot else that does not matter here.
    Note this reads whatever line endings it finds. The original vrtrackmaker
    splits on CRLF and chokes on an LF-normalised file -- which is how archived
    copies of these splines have been quietly damaged (see the file-formats doc).
    Being indifferent to that is deliberate.
    """
    text = Path(path).read_text(encoding="latin-1", errors="replace")
    pts = [(float(a), float(b), float(c)) for a, b, c in _KNOT.findall(text)]
    if not pts:
        raise ValueError(f"no *SHAPE_VERTEX_KNOT entries in {Path(path).name}")
    return pts


def ase_is_closed(path: str | Path) -> bool:
    """Whether the spline carries *SHAPE_CLOSED.

    Worth asking separately, because a closed shape's knots do NOT include the
    closing segment: path10.ASE is flagged closed but its last knot sits 201 m
    from its first. Sweeping such a path as open leaves a hole the width of that
    gap -- and since the start line sits at the seam, cars spawn over it and
    fall through the world.
    """
    return "*SHAPE_CLOSED" in Path(path).read_text(encoding="latin-1", errors="replace")


def read_obj_polyline(path: str | Path) -> list[Point]:
    """Read a centreline from an OBJ containing a polyline (`l` records).

    Blender and most modellers export a curve this way, so an author who is not
    running 3DS Max still has a route in. Vertex order follows the `l` chain when
    one is present, and falls back to file order when the OBJ is just points.
    """
    verts: list[Point] = []
    lines: list[list[int]] = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif parts[0] == "l":
            # OBJ indices are 1-based and may be negative (relative)
            idx = [int(p.split("/")[0]) for p in parts[1:]]
            lines.append([i - 1 if i > 0 else len(verts) + i for i in idx])
    if not verts:
        raise ValueError(f"no vertices in {Path(path).name}")
    if not lines:
        return verts
    order: list[int] = []
    for chain in lines:
        for i in chain:
            if not order or order[-1] != i:
                order.append(i)
    return [verts[i] for i in order]


def read_centreline(path: str | Path) -> list[Point]:
    """Read a centreline from whichever of the supported formats `path` is.

    As well as an explicit curve (.ase spline, .obj polyline), this accepts the
    ROAD SURFACE itself -- a .mod, or a directory of them -- and recovers the
    centreline from its geometry. That matters because the obvious source of
    track geometry does not export a curve at all: Bob's Track Builder gives you
    a surface, and the workaround has been to import it into 3DS Max and draw a
    spline over it by hand. See centreline_from_meshes().
    """
    p = Path(path)
    if p.is_dir():
        meshes = [mod.parse_file(f) for f in sorted(p.glob("*.mod"))]
        if not meshes:
            raise ValueError(f"no .mod files in {p}")
        return centreline_from_meshes(meshes)
    suffix = p.suffix.lower()
    if suffix == ".ase":
        return read_ase(p)
    if suffix == ".obj":
        return read_obj_polyline(p)
    if suffix == ".mod":
        return centreline_from_meshes([mod.parse_file(p)])
    if suffix == ".dof":
        # A Bob's Track Builder export. Use the road surface, not the whole
        # scene: the grass apron is a ribbon too, and its centreline is not the
        # racing line.
        from . import dof as dof_mod
        scene = dof_mod.parse_file(p)
        meshes = dof_mod.to_meshes(scene)
        road = [m for n, m in meshes.items() if n.lower().startswith(("road", "asphalt", "tarmac"))]
        if not road:
            road = list(meshes.values())[:1]
        return centreline_from_meshes(road)
    raise ValueError(
        f"unsupported centreline source '{suffix}' "
        "(want .ase, .obj, .dof, a .mod road surface, or a directory of them)")


def to_viper(p: Point, height: float = 0.0) -> Point:
    """Source frame -> game frame.

    A Point is (x, y, elevation): the first two are the ground plane, and the
    THIRD carries height above it. That component used to be a constant zero,
    which is why generated tracks were flat. `height` is added to it, so a band's
    own rise stacks on top of the centreline's elevation.
    """
    return (-p[0], height + (p[2] if len(p) > 2 else 0.0), -p[1])


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def simplify(points: list[Point], tolerance: float) -> list[Point]:
    """Douglas-Peucker on the ground plane.

    A dense export is what the tools want to be *given* (vrtrackmaker's readme
    asks for a normalisation of 1.0), but the emitted path is decimated -- the
    reference output turns 3,759 knots into 358. Straights collapse to a couple
    of points while corners keep their detail, which is the behaviour to match.
    """
    if tolerance <= 0 or len(points) < 3:
        return list(points)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        ax, ay = points[lo][0], points[lo][1]
        bx, by = points[hi][0], points[hi][1]
        dx, dy = bx - ax, by - ay
        span = math.hypot(dx, dy)
        worst, worst_i = -1.0, lo
        for i in range(lo + 1, hi):
            px, py = points[i][0], points[i][1]
            if span == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                # perpendicular distance to the chord
                d = abs(dy * px - dx * py + bx * ay - by * ax) / span
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance:
            keep[worst_i] = True
            stack.append((lo, worst_i))
            stack.append((worst_i, hi))
    return [p for p, k in zip(points, keep) if k]


def resample(points: list[Point], spacing: float, closed: bool = False) -> list[Point]:
    """Re-space a polyline at a fixed arc length, preserving both ends.

    With `closed`, the segment from the last point back to the first is walked
    too, so a ring comes out evenly sampled all the way round instead of
    stopping short at the seam.
    """
    if spacing <= 0 or len(points) < 2:
        return list(points)
    out = [points[0]]
    carry = 0.0
    pairs = list(zip(points, points[1:]))
    if closed and _dist(points[-1], points[0]) > 1e-9:
        pairs.append((points[-1], points[0]))
    for a, b in pairs:
        seg = _dist(a, b)
        if seg == 0:
            continue
        ea = a[2] if len(a) > 2 else 0.0
        eb = b[2] if len(b) > 2 else 0.0
        t = spacing - carry
        while t <= seg:
            f = t / seg
            out.append((a[0] + (b[0] - a[0]) * f,
                        a[1] + (b[1] - a[1]) * f,
                        ea + (eb - ea) * f))       # elevation rides along
            t += spacing
        carry = (carry + seg) % spacing
    if closed:
        # the ring must not repeat its seam; sweep() closes it by wrapping
        while len(out) > 1 and _dist(out[-1], out[0]) < spacing * 0.5:
            out.pop()
    elif _dist(out[-1], points[-1]) > 1e-9:
        out.append(points[-1])
    return out


# --------------------------------------------------------------------------
# Phase 1: the scene model, the sweep, and the two emitters
# --------------------------------------------------------------------------


@dataclass
class Band:
    """One lateral strip of the cross-section, measured outward from the road edge.

    `rise` is the height change across the band's own width, so a kerb sits proud
    and a verge falls away. Defaults mirror vrTrackMaker's shipped values.
    """

    base: str          # mesh base name; paired bands become <base>l / <base>r
    width: float
    rise: float
    texture: str
    code: int
    paired: bool = True


# vrTrackMaker's defaults, read from the running application. Rumble1 and Rumble2
# are two sub-strips of one kerb, which is why the tool emits a single rumble
# mesh per side rather than two.
DEFAULT_BANDS: tuple[Band, ...] = (
    Band("rumbl", 0.9, 0.1, "rumble.tex", RUMBLE),
    Band("side", 1.0, -0.2, "side.tex", RUMBLE),
    Band("grass", 20.0, 0.0, "grass.tex", GRASS),
)
DEFAULT_ROAD_HALF_WIDTH = 6.0


@dataclass
class SceneObject:
    """One `modobject()` line."""

    name: str                 # as referenced, e.g. "asphalt.mod"
    code: int
    param1: int = SOLID


@dataclass
class TrackScene:
    """Everything both scene files are written from.

    Holding one list of driveables -- rather than one per output file -- is what
    makes the both-files rule structurally unbreakable.
    """

    centreline: list[Point]
    driveables: list[SceneObject] = field(default_factory=list)
    scenery: list[SceneObject] = field(default_factory=list)
    markers: dict[str, list[Point]] = field(default_factory=dict)
    walls: list[list[Point]] = field(default_factory=list)
    grid: list[Point] = field(default_factory=list)
    meshes: dict[str, "mod.Mesh"] = field(default_factory=dict)
    wall_texture: str = "wall.tga"


def _normals_2d(pts: list[Point], closed: bool) -> list[tuple[float, float]]:
    """Unit left-normals in the ground plane, averaged across each joint so the
    ribbon does not pinch or flare where the curvature changes."""
    n = len(pts)
    out: list[tuple[float, float]] = []
    for i in range(n):
        if closed:
            a, b = pts[i - 1], pts[(i + 1) % n]
        else:
            a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0:
            out.append(out[-1] if out else (0.0, 1.0))
            continue
        out.append((-dy / length, dx / length))
    return out


def _ribbon(
    pts: list[Point],
    normals: list[tuple[float, float]],
    inner: float,
    outer: float,
    y_inner: float,
    y_outer: float,
    texture: str,
    closed: bool,
    uv_scale: float,
):
    """Build a quad strip between two lateral offsets of the centreline."""
    verts = []
    faces = []

    run = 0.0
    for i, (p, (nx, ny)) in enumerate(zip(pts, normals)):
        if i:
            run += _dist(pts[i - 1], p)
        v = run / uv_scale if uv_scale else 0.0
        elev = p[2] if len(p) > 2 else 0.0
        for off, y, u in ((inner, y_inner, 0.0), (outer, y_outer, 1.0)):
            gx, gy = p[0] + nx * off, p[1] + ny * off
            # the station's own elevation, with the band's rise stacked on top
            wx, wy, wz = to_viper((gx, gy, elev), y)
            verts.append(mod.Vertex(wx, wy, wz, 0.0, 1.0, 0.0, u, v))

    stations = len(pts)
    last = stations if closed else stations - 1
    for i in range(last):
        a = 2 * i
        b = 2 * ((i + 1) % stations)
        # two triangles per quad, wound to face up in the game's left-handed space
        faces.append((a, b, b + 1))
        faces.append((a, b + 1, a + 1))

    # Orient every ribbon the same way up.
    #
    # The winding a quad strip comes out with depends on whether its two lateral
    # offsets ascend or descend, so bands swept to the left of the centreline and
    # bands swept to the right end up facing opposite ways -- which is how the
    # first version of this shipped: asphalt and the left bands inside-out, the
    # right bands correct. Rather than reason about the sign (easy to get wrong,
    # and invisible until a compiler rejects the mesh), measure the result and
    # flip it if it faces down. Every mesh vrTrackMaker emits faces up.
    if faces:
        a, b, c = faces[0]
        va, vb, vc = verts[a], verts[b], verts[c]
        ux, uz = vb.x - va.x, vb.z - va.z
        wx, wz = vc.x - va.x, vc.z - va.z
        if uz * wx - ux * wz < 0:
            faces = [(f[0], f[2], f[1]) for f in faces]

    material = mod.Material(texture, 0, len(verts), 0, len(faces))
    return mod.Mesh(vertices=verts, materials=[material], faces=faces)


# How long a piece of one band becomes a single mesh. Shipped tracks subdivide
# heavily -- bemidji is 446 chunks averaging 12 vertices over a ~60 m footprint,
# dundas 1,117 chunks over ~40 m -- because the renderer culls per chunk, so a
# chunk spanning the whole map is always "visible" and never usefully culled.
# Sweeping each band as one track-length ribbon produced 7 chunks of 2,822
# vertices with a 1,632 m footprint, and the track did not draw at all.
DEFAULT_SEGMENT_LENGTH = 50.0


def sweep(
    centreline: list[Point],
    *,
    bands: tuple[Band, ...] = DEFAULT_BANDS,
    road_half_width: float = DEFAULT_ROAD_HALF_WIDTH,
    road_texture: str = "asphalt.tex",
    closed: bool = True,
    uv_scale: float = 10.0,
    segment_length: float = DEFAULT_SEGMENT_LENGTH,
) -> "TrackScene":
    """Sweep a cross-section along the centreline into a complete TrackScene.

    The road is one mesh spanning both sides; every other band is emitted as a
    left/right pair, which is the convention the original tool uses and which the
    shipped example sources reference by name.
    """
    if len(centreline) < 2:
        raise ValueError("centreline needs at least two points")

    pts = [(p[0], p[1], p[2] if len(p) > 2 else 0.0) for p in centreline]
    if closed and _dist(pts[0], pts[-1]) < 1e-6:
        pts.pop()                      # a closed ring must not repeat its seam
    normals = _normals_2d(pts, closed)

    scene = TrackScene(centreline=pts)

    # Stations per segment, from the requested segment length.
    total = sum(_dist(a, b) for a, b in zip(pts, pts[1:])) or 1.0
    per_station = total / max(len(pts) - 1, 1)
    stride = max(2, int(round(segment_length / per_station))) if segment_length > 0 else len(pts)

    # Segmentation and closure interact: every segment is swept as an open strip,
    # so on a ring the last one has to reach back to station 0 or the seam is
    # left open. Repeating the first station at the end makes that fall out of
    # the ordinary segmentation -- the closing stretch becomes a segment like any
    # other. Without this a closed track still had a drivable-over gap at the
    # start line, which is exactly where it is most visible.
    ring = pts + [pts[0]] if closed else pts
    ring_normals = normals + [normals[0]] if closed else normals

    def emit(base: str, inner: float, outer: float, y_in: float, y_out: float,
             texture: str, code: int) -> None:
        """Sweep one band, cut into segments, each its own mesh."""
        starts = range(0, len(ring) - 1, stride) if stride < len(ring) else (0,)
        for n, s in enumerate(starts):
            e = min(s + stride + 1, len(ring))
            if e - s < 2:
                continue
            # segments share their boundary station, so the surfaces meet
            sub = ring[s:e]
            sub_n = ring_normals[s:e]
            name = f"{base}{n:03d}.mod" if stride < len(pts) else f"{base}.mod"
            scene.meshes[name] = _ribbon(
                sub, sub_n, inner, outer, y_in, y_out, texture, False, uv_scale,
            )
            scene.driveables.append(SceneObject(name, code))

    emit("asphalt", -road_half_width, road_half_width, 0.0, 0.0, road_texture, ROAD)
    for side, sign in (("l", 1.0), ("r", -1.0)):
        offset, height = road_half_width, 0.0
        for band in bands:
            inner, outer = offset, offset + band.width
            base = f"{band.base}{side}" if band.paired else band.base
            emit(base, sign * inner, sign * outer, height, height + band.rise,
                 band.texture, band.code)
            offset, height = outer, height + band.rise

    return scene


def add_checkpoints(
    scene: "TrackScene",
    count: int = 3,
    *,
    half_width: float | None = None,
    margin: float = 2.5,
) -> None:
    """Place timing gates evenly around the lap, starting at the centreline's origin.

    The engine will not load a track it cannot find checkpoints on -- it panics
    with "Couldn't find any checkpoints!" and dies before the green flag. Two
    things about that, both learned by having it happen:

    **One gate is not enough.** Every functioning track carries two or three;
    the shipped road courses all use three. A single gate gives the engine no way
    to establish lap direction or progress, so `count` defaults to 3 and values
    below 2 are refused.

    **A gate must be wider than the road.** Shipped gates run 15-80 m against
    road widths around 12 m, so `margin` widens each gate by that factor -- a car
    running wide over the kerb still crosses it. Spanning only the asphalt lets a
    car miss the gate entirely and never complete a lap.
    """
    if count < 2:
        raise ValueError(
            "a track needs at least two checkpoints -- the engine panics with "
            "'Couldn't find any checkpoints!' otherwise"
        )
    pts = scene.centreline
    if len(pts) < 2:
        return

    base = half_width if half_width is not None else DEFAULT_ROAD_HALF_WIDTH
    width = base * margin
    normals = _normals_2d(pts, closed=True)

    scene.markers.clear()
    for k in range(count):
        i = (k * len(pts)) // count
        p, (nx, ny) = pts[i], normals[i]
        scene.markers[f"check{k + 1}"] = [
            (p[0] + nx * width, p[1] + ny * width, 0.0),
            (p[0] - nx * width, p[1] - ny * width, 0.0),
        ]


def add_grid(scene: "TrackScene", slots: int = 8, *, spacing: float = 10.0,
             offset: float = 3.0) -> None:
    """Lay out starting-grid slots behind the first checkpoint.

    Two staggered columns either side of the centreline, which is how the shipped
    tracks arrange their eight. Positions go into the scene for the object table;
    the compiler writes them out as `obj car` records.
    """
    pts = scene.centreline
    if len(pts) < 2 or slots <= 0:
        return
    normals = _normals_2d(pts, closed=True)
    total = sum(_dist(a, b) for a, b in zip(pts, pts[1:])) or 1.0
    step = spacing / total * len(pts)

    scene.grid.clear()
    for k in range(slots):
        # walk backwards from the line so the grid sits before it, not on it
        i = int(round(-(k // 2 + 1) * step)) % len(pts)
        p, (nx, ny) = pts[i], normals[i]
        side = offset if k % 2 == 0 else -offset
        scene.grid.append((p[0] + nx * side, p[1] + ny * side, 0.0))


# Kept for callers written against the single-gate helper.
def add_start_gate(scene: "TrackScene", half_width: float | None = None) -> None:
    """Deprecated: places ONE gate, which the engine rejects. Use add_checkpoints."""
    add_checkpoints(scene, 2, half_width=half_width)


# --- emitters -------------------------------------------------------------
#
# Both write CRLF and 4-decimal fixed point, matching the reference output in the
# parts that are shared. The original is a Delphi program whose reader splits on
# CRLF, so the line endings are not cosmetic.

_NL = "\r\n"


def _vert(p: Point, indent: str = "    ", flip: bool = False) -> str:
    """One vert() line. `flip` negates the ground axes.

    The two scene files do not share a frame, which is measurable in the
    reference output: the graphic file's path(center) reproduces the .ase knots
    unchanged, while the surface file's marker gates and wall quads come out with
    both ground axes negated. That asymmetry is presumably why only the surface
    pass is invoked as `mkfltoa foolandsurface.txt track.flt -viper`.
    """
    x, y = (-p[0], -p[1]) if flip else (p[0], p[1])
    return f"{indent}vert({x:.4f}, {y:.4f}, {p[2]:.4f})"


def _modobject(o: SceneObject) -> str:
    return f"  modobject({o.name}, {o.param1}, 0, {o.code}, 0)"


def write_graphic(scene: "TrackScene") -> str:
    """The visual scene source: the centreline, the gate, and every object."""
    out = [""]
    out.append("path(center)")
    out.extend(_vert(p) for p in scene.centreline)
    out.append("end")
    out.append("")
    for name, gate in scene.markers.items():
        # The gate verts belong in BOTH files -- unflipped here, negated in the
        # surface file. An empty marker block is rejected by nhmkworld, which is
        # exactly what this emitter used to write: the reference was first read
        # through a `grep -v vert(` that hid the gate, and the artifact got
        # encoded as a format rule.
        out.append(f"marker({name})")
        out.extend(_vert(p) for p in gate)
        out.append("end")
    out.append("begin")
    out.extend(_modobject(o) for o in scene.driveables)
    out.extend(_modobject(o) for o in scene.scenery)
    out.append("")
    out.append("end")
    out.append("end")
    return _NL.join(out) + _NL


def write_surface(scene: "TrackScene") -> str:
    """The collision scene source: gates with real verts, the same driveables,
    and the walls written out inline as quads rather than referenced as meshes."""
    out = []
    for name, gate in scene.markers.items():
        out.append(f"marker({name})")
        out.extend(_vert(p, flip=True) for p in gate)
        out.append("end")
        out.append("")
    out.append("begin")
    out.extend(_modobject(o) for o in scene.driveables)
    for quad in scene.walls:
        out.append(f"  object({scene.wall_texture},1,0)")
        # Walls do NOT share the markers' frame. Measured against vrTrackMaker's
        # own output: its gate verts match the mesh frame, while its wall verts
        # are negated on both ground axes (mesh x -819.9..810.5 against wall
        # column 1 -811.3..820.9). MKWORLD negates them back on the way into
        # .sol, so a wall written in the mesh frame is compiled mirrored through
        # the origin -- which, on a roughly centred circuit, drops a good share
        # of the barriers across the track as invisible walls in the road.
        out.extend(_vert(p, flip=False) for p in quad)
        out.append("    quad(0,1,2,3)")
        out.append("  end")
        out.append("")
    out.append("end")
    out.append("end")
    return _NL.join(out) + _NL



def build_obt(scene: "TrackScene") -> bytes:
    """Write the placed-object table: the timing gates and the starting grid.

    This is generated here rather than by the compiler because the scene format
    has no way to declare either. MKWORLD derives checkpoints from the marker
    blocks but nothing declares grid slots, so the shipped tracks' `obj car`
    records must have been authored by hand or by a tool that did not survive.
    Writing the whole table natively is simpler than patching the compiler's.

    Coordinates go out in the flipped ground frame, matching the surface file
    and what the compiler itself emits.
    """
    records = []
    for gate in scene.markers.values():
        (x1, y1, _), (x2, y2, _) = gate[0], gate[1]
        records.append(obt_mod.checkpoint(-x1, -y1, -x2, -y2))
    for x, y, _ in scene.grid:
        records.append(obt_mod.car(-x, -y))
    return obt_mod.build(obt_mod.create(records))


def write_scene(scene: "TrackScene", out_dir) -> list:
    """Write both sources and every swept mesh. Returns what was written."""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (
        ("foolandsurface.txt", write_surface(scene)),
        ("foolandgraphic.txt", write_graphic(scene)),
    ):
        p = d / name
        p.write_bytes(text.encode("latin-1"))
        written.append(p)
    for name, mesh in scene.meshes.items():
        p = d / name
        p.write_bytes(mod.build(mesh))
        written.append(p)
    if scene.markers or scene.grid:
        p = d / "track.obt"
        p.write_bytes(build_obt(scene))
        written.append(p)
    return written


# ---------------------------------------------------------------------------
# Recovering a centreline from an existing road surface
#
# The pipeline needs a centreline for the AI lines and the timing gates, but a
# track modeller does not necessarily export one -- Bob's Track Builder does not,
# and the workaround has been to import the road mesh into 3DS Max and draw a
# spline over it by hand.
#
# It does not have to be drawn, because a road surface IS a swept strip: its
# boundary is two long parallel chains, and the centreline is what runs between
# them. Recovering it is a topology problem, not a modelling one.
#
# The approach deliberately avoids relying on vertex ORDER. A strip exported by
# our own sweep happens to store its edges as consecutive pairs, so pairing
# v[2i]/v[2i+1] would work -- and does, exactly, against the reference mesh. But
# nothing guarantees another exporter does the same, so this works from the
# boundary edges instead: an edge used by one triangle is on the boundary, and
# for a ribbon those form two long chains (plus two short caps, or nothing at all
# when the ring is closed).


def _weld(meshes, tol: float = 0.01):
    """Merge meshes into one vertex/face soup, welding coincident vertices.

    Segmented road surfaces repeat their shared stations, and a modeller's export
    may repeat every triangle's corners, so the boundary is only meaningful once
    duplicates are collapsed.
    """
    q = 1.0 / max(tol, 1e-9)
    index: dict[tuple[int, int, int], int] = {}
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for m in meshes:
        remap = []
        for v in m.vertices:
            key = (round(v.x * q), round(v.y * q), round(v.z * q))
            i = index.get(key)
            if i is None:
                i = len(verts)
                index[key] = i
                verts.append((v.x, v.y, v.z))
            remap.append(i)
        for a, b, c in m.faces:
            ta, tb, tc = remap[a], remap[b], remap[c]
            if ta != tb and tb != tc and ta != tc:
                faces.append((ta, tb, tc))
    return verts, faces


def _boundary_chains(verts, faces):
    """Split the boundary edges into ordered chains (or loops)."""
    use: dict[tuple[int, int], int] = {}
    for a, b, c in faces:
        for i, j in ((a, b), (b, c), (c, a)):
            use[(min(i, j), max(i, j))] = use.get((min(i, j), max(i, j)), 0) + 1
    adj: dict[int, list[int]] = {}
    for (i, j), n in use.items():
        if n == 1:                      # used once -> on the boundary
            adj.setdefault(i, []).append(j)
            adj.setdefault(j, []).append(i)

    chains, seen = [], set()
    for start in adj:
        if start in seen:
            continue
        # walk from an endpoint where possible, so an open chain comes out whole
        node = start
        if len(adj[start]) > 1:
            for cand in adj:
                if cand not in seen and len(adj[cand]) == 1:
                    node = cand
                    break
        chain, prev = [], None
        while node is not None and node not in seen:
            seen.add(node)
            chain.append(node)
            nxt = None
            for cand in adj.get(node, ()):
                if cand != prev and cand not in seen:
                    nxt = cand
                    break
            prev, node = node, nxt
        if len(chain) > 1:
            chains.append(chain)
    return chains


def centreline_from_meshes(meshes, *, weld_tol: float = 0.01,
                           source_frame: bool = True) -> list[Point]:
    """Derive a centreline from one or more road-surface meshes.

    Returns points in the same frame `read_ase` produces, so the result drops
    straight into resample()/sweep(); pass source_frame=False to keep the mesh's
    own frame instead.

    Raises ValueError when the surface does not look like a strip -- better than
    returning a plausible-looking line through the middle of something that is
    not a road.
    """
    verts, faces = _weld(meshes, weld_tol)
    if not faces:
        raise ValueError("no usable triangles in the supplied meshes")

    chains = _boundary_chains(verts, faces)
    if len(chains) < 2:
        raise ValueError(
            f"expected two boundary chains for a road strip, found {len(chains)} -- "
            "this surface does not look like a swept ribbon")

    def length(ch):
        return sum(math.dist(verts[a][::2], verts[b][::2]) for a, b in zip(ch, ch[1:]))

    chains.sort(key=length, reverse=True)
    left, right = chains[0], chains[1]

    # Pair each point on the longer edge with the nearest on the other. A road is
    # roughly constant width, so nearest-point is the correct correspondence and
    # is immune to the two edges being sampled differently.
    # Pair the two edges through the TRIANGLES that join them.
    #
    # Two simpler ideas both fail on a real circuit. Nearest-point pairing looks
    # across the track at a hairpin and picks a point from a different part of
    # the lap -- and because those are still a road-width apart, the bad pair is
    # not detectable by width. Arc-length pairing fails because the outer edge of
    # a curve is longer than the inner, so equal parameter is not equal position.
    #
    # The mesh already knows the answer: every triangle spans the ribbon, so a
    # vertex on one edge is joined by an edge of some triangle to the vertices
    # opposite it. That correspondence is local, exact, and cannot jump the
    # track.
    right_set = set(right)
    neighbours: dict[int, set[int]] = {}
    for a, b, c in faces:
        for i, j in ((a, b), (b, c), (c, a)):
            neighbours.setdefault(i, set()).add(j)
            neighbours.setdefault(j, set()).add(i)

    def across(start: int, hops: int = 24) -> list[int]:
        """Walk the mesh from a left-edge vertex until the right edge is reached.

        A road is not always two vertices wide. Our own sweep emits a plain quad
        strip, so the opposite edge is an immediate neighbour -- but Bob's Track
        Builder subdivides across the width (its road came out five vertices
        across, four quads), and then the two boundaries share no triangle at
        all. Walking the graph handles both, and because it only ever moves
        through connected geometry it cannot cross to a different part of the lap
        the way a proximity search does.
        """
        frontier, seen = {start}, {start}
        for _ in range(hops):
            hits = [i for i in frontier if i in right_set]
            if hits:
                return hits
            nxt = set()
            for i in frontier:
                nxt |= neighbours.get(i, set()) - seen
            if not nxt:
                return []
            seen |= nxt
            frontier = nxt
        return []

    out: list[Point] = []
    for i in left:
        opposite = across(i)
        if not opposite:
            continue                     # an edge vertex with no rung: skip it
        lx, ly, lz = verts[i]
        rx = sum(verts[j][0] for j in opposite) / len(opposite)
        ry = sum(verts[j][1] for j in opposite) / len(opposite)
        rz = sum(verts[j][2] for j in opposite) / len(opposite)
        mx, my, mz = (lx + rx) / 2.0, (ly + ry) / 2.0, (lz + rz) / 2.0
        # the road's own height, averaged across its width, so a hilly source
        # track comes back as a hilly centreline rather than a flat plan view
        out.append((-mx, -mz, my) if source_frame else (mx, my, mz))
    if len(out) < 2:
        raise ValueError(
            "could not walk from one boundary edge to the other -- this surface "
            "does not look like a swept ribbon")
    return out


# ---------------------------------------------------------------------------
# Importing an existing track model
#
# `sweep()` builds a road from a centreline. This is the other half of the
# brief: take geometry somebody has already modelled -- in Bob's Track Builder,
# Blender, anything that exports a mesh -- and turn it into a Viper track
# without redrawing it.
#
# Two things stand between an exported mesh and a loadable track.
#
# The first is CHUNKING. The renderer culls per chunk, so a track shipped as one
# large mesh either draws entirely or not at all; a whole-track ribbon rendered
# as nothing at all, which is not an obvious symptom to trace back to geometry
# size. Shipped tracks are hundreds of small meshes (bemidji: 446 chunks, 9-12
# vertices each, 40-60 m across). An exporter has no reason to do that, so the
# import has to.
#
# The second is SURFACE CODES. Viper needs to know which triangles are road and
# which are grass; a mesh format carries a material name and nothing else. The
# convention here is that the material name says what the surface is -- anything
# starting "road", "asphalt" or "tarmac" is road, "grass" is grass, and so on --
# which is what BTB's own naming already produces (`road1`, `grass0`).

DEFAULT_CHUNK_SIZE = 50.0

# Material-name prefixes to surface codes. Ordered longest-first at match time,
# so "roadside" does not match "road".
SURFACE_PREFIXES: tuple[tuple[str, int], ...] = (
    ("asphalt", ROAD), ("tarmac", ROAD), ("road", ROAD),
    ("rumble", RUMBLE), ("kerb", RUMBLE), ("curb", RUMBLE),
    ("water", WATER), ("river", WATER), ("lake", WATER),
    ("dirt", DIRT), ("gravel", DIRT), ("sand", DIRT),
    ("grass", GRASS), ("verge", GRASS), ("ground", GRASS),
)


def surface_code(name: str, default: int = GRASS) -> int:
    """The surface code a mesh or material name implies.

    Falls back to grass rather than road: a misclassified verge is a car that
    slows down where it should not, a misclassified road is a car that grips
    where there is nothing to grip.
    """
    stem = Path(name).stem.lower()
    for prefix, code in sorted(SURFACE_PREFIXES, key=lambda p: -len(p[0])):
        if stem.startswith(prefix):
            return code
    return default


def chunk_mesh(mesh: "mod.Mesh", *, size: float = DEFAULT_CHUNK_SIZE) -> list["mod.Mesh"]:
    """Split a mesh into a grid of roughly `size`-metre tiles.

    Triangles are assigned whole, by centroid, so no geometry is cut and no new
    vertices are introduced -- a chunk's true extent therefore overruns its tile
    by up to one triangle, which is what the renderer wants anyway (a chunk
    culled at its own boundary would pop).

    Vertices are re-indexed per chunk and shared ones duplicated, because chunk
    face indices are `u16` and local to the chunk.
    """
    if size <= 0:
        raise ValueError(f"chunk size must be positive, got {size}")
    if not mesh.faces:
        return []

    texture = mesh.materials[0].name if mesh.materials else "asphalt.tex"

    tiles: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for face in mesh.faces:
        a, b, c = (mesh.vertices[i] for i in face)
        cx = (a.x + b.x + c.x) / 3.0
        cz = (a.z + b.z + c.z) / 3.0
        tiles.setdefault((math.floor(cx / size), math.floor(cz / size)), []).append(face)

    out: list["mod.Mesh"] = []
    for key in sorted(tiles):
        remap: dict[int, int] = {}
        verts: list[mod.Vertex] = []
        faces: list[tuple[int, int, int]] = []
        for face in tiles[key]:
            local = []
            for i in face:
                j = remap.get(i)
                if j is None:
                    j = len(verts)
                    remap[i] = j
                    verts.append(mesh.vertices[i])
                local.append(j)
            faces.append(tuple(local))
        if len(verts) > 0xFFFF:
            raise ValueError(
                f"chunk at {key} has {len(verts):,} vertices; face indices are u16 -- "
                "use a smaller --chunk-size")
        out.append(mod.Mesh(
            vertices=verts,
            materials=[mod.Material(texture, 0, len(verts), 0, len(faces))],
            faces=faces,
        ))
    return out


def scene_from_meshes(
    meshes: dict[str, "mod.Mesh"],
    *,
    centreline: list[Point] | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
    codes: dict[str, int] | None = None,
) -> "TrackScene":
    """Build a TrackScene from geometry that already exists.

    `meshes` is keyed by name -- `dof.to_meshes()` produces exactly this shape.
    Each is classified by `surface_code()` unless `codes` overrides it by name,
    then cut into chunks the renderer can cull.

    The centreline is recovered from whichever meshes classify as road, unless
    one is supplied. It is needed for the racing lines, the timing gates and the
    grid, none of which the geometry carries.
    """
    if not meshes:
        raise ValueError("no meshes to import")

    codes = codes or {}
    _rename_materials(meshes)
    if centreline is None:
        road = [m for n, m in meshes.items()
                if codes.get(n, surface_code(n)) == ROAD]
        if not road:
            raise ValueError(
                "no mesh classifies as road, so there is no centreline to recover -- "
                f"names seen: {sorted(meshes)}. Rename the road material to start "
                "'road', 'asphalt' or 'tarmac', or pass a centreline.")
        # Source frame, not the mesh's own: TrackScene.centreline is consumed in
        # the same convention read_ase() produces -- (x, y, elevation), which
        # to_viper() maps back onto the mesh's (x, height, z). Handing it the
        # mesh frame instead mirrors the track, and a mirrored circuit looks
        # entirely plausible until you notice the signage renders backwards.
        centreline = centreline_from_meshes(road, source_frame=True)

    scene = TrackScene(centreline=[(p[0], p[1], p[2] if len(p) > 2 else 0.0)
                                   for p in centreline])
    for name in sorted(meshes):
        code = codes.get(name, surface_code(name))
        base = Path(name).stem
        for n, piece in enumerate(chunk_mesh(meshes[name], size=chunk_size)):
            chunk_name = f"{base}{n:03d}.mod"
            scene.meshes[chunk_name] = piece
            scene.driveables.append(SceneObject(chunk_name, code))
    if not scene.meshes:
        raise ValueError("every mesh chunked to nothing -- no triangles anywhere")
    return scene


# Texture names are 8.3. A .tra directory entry has a 16-byte name field, which
# is what this first fitted names to -- and 16 is wrong. Surveying every texture
# in a full install gives 244 distinct names, and the longest is 12 characters:
# eight plus ".tex" ("asphalth.tex", "pine3o15.tex", "bboard01.tex"). Not one of
# the 244 contains an underscore.
#
# A name that fits the archive but not 8.3 is accepted by the packer, listed in
# the directory, and read back correctly by every tool here -- and the surface
# using it renders as flat untextured colour in game. It does not crash, warn or
# fall back to a placeholder, which is what makes it expensive to find.
#
# Names are therefore cut to eight alphanumeric characters, and the mesh
# materials cut identically: Viper resolves textures by NAME, so the two must
# agree exactly.
TEX_NAME_LIMIT = 12
_TEX_STEM_LIMIT = TEX_NAME_LIMIT - len(".tex")

# The game never ships a texture larger than 256. Across all 46 archives in a
# full install -- every track, every car, every .res -- the sizes are 16, 32,
# 64, 128 and 256, and nothing above. A modeller has no such limit: BTB writes
# 512 and 1024 by default. Oversized textures do not merely look wrong or load
# slowly; the surface renders as flat untextured colour.
TEX_MAX_SIZE = 256

# A texture whose alpha never drops this low has no transparency worth keeping
# -- BTB writes a specular-ish alpha into its road texture that never falls
# below 225. Encoding that as ARGB4444 gets flags=3, where every stock road and
# ground texture is flags=0 (opaque RGB565).
_OPAQUE_ALPHA_FLOOR = 128


def fit_texture_names(names) -> dict[str, str]:
    """Map texture names onto ones that fit the archive's name field.

    Deterministic for a given set, so the meshes and the `.tex` members can be
    named in separate passes and still agree. Truncated names that would
    collide get a numeric tail rather than silently becoming one texture.
    """
    out: dict[str, str] = {}
    taken: set[str] = set()
    for name in sorted(set(names)):
        stem = "".join(c for c in Path(name).stem if c.isalnum())
        stem = stem[:_TEX_STEM_LIMIT] or "tex"
        if stem in taken:
            for n in range(1, 1000):
                tail = str(n)
                cand = stem[:_TEX_STEM_LIMIT - len(tail)] + tail
                if cand not in taken:
                    stem = cand
                    break
            else:
                raise ValueError(f"cannot fit a unique name for {name!r}")
        taken.add(stem)
        out[name] = f"{stem}.tex"
    return out


def _rename_materials(meshes: dict[str, "mod.Mesh"]) -> dict[str, str]:
    """Rename every material in place to a name the archive can hold."""
    mapping = fit_texture_names(
        m.name for mesh in meshes.values() for m in mesh.materials)
    for mesh in meshes.values():
        for material in mesh.materials:
            material.name = mapping[material.name]
    return mapping


def read_meshes(path: str | Path) -> dict[str, "mod.Mesh"]:
    """Load the geometry from a model file, keyed by name.

    Accepts the same sources `read_centreline` does, but returns the whole model
    rather than a line through the middle of it.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".dof":
        from . import dof as dof_mod
        return dof_mod.to_meshes(dof_mod.parse_file(p))
    if suffix == ".mod":
        return {p.name: mod.parse(p.read_bytes())}
    if p.is_dir():
        out = {}
        for f in sorted(p.glob("*.mod")):
            out[f.name] = mod.parse(f.read_bytes())
        if out:
            return out
        raise ValueError(f"no .mod files in {p}")
    if suffix == ".obj":
        return {p.name: mod.read_obj(p)}
    raise ValueError(
        f"cannot read geometry from '{suffix}' -- want .dof, .obj, .mod, or a "
        "directory of .mod files")


def road_half_width(scene: "TrackScene") -> float:
    """Measure the road's half-width from the scene's own road chunks.

    Taken from the geometry rather than asked for, because an imported model
    already has a width and guessing a different one puts the timing gates and
    the racing-line corridor in the wrong place. Returns 0.0 when nothing in the
    scene is road.
    """
    road = {o.name for o in scene.driveables if o.code == ROAD}
    if not road or len(scene.centreline) < 2:
        return 0.0
    pts = [to_viper(p) for p in scene.centreline]
    ground = [(p[0], p[2]) for p in pts]
    n = len(ground)

    lats: list[float] = []
    for name in road:
        for v in scene.meshes[name].vertices:
            i = min(range(n), key=lambda k: (ground[k][0] - v.x) ** 2
                                            + (ground[k][1] - v.z) ** 2)
            ax, az = ground[i]
            bx, bz = ground[(i + 1) % n]
            tx, tz = bx - ax, bz - az
            L = math.hypot(tx, tz) or 1.0
            lats.append(abs((v.x - ax) * (-tz / L) + (v.z - az) * (tx / L)))
    if not lats:
        return 0.0
    lats.sort()
    # The 95th percentile, not the maximum: one stray vertex from a joining slip
    # road would otherwise widen the whole track.
    return lats[min(int(len(lats) * 0.95), len(lats) - 1)]


def write_textures(source: str | Path, out_dir) -> list:
    """Convert the source model's textures to `.tex` alongside the scene.

    Texture resolution in Viper is by NAME, so a mesh referencing
    `road_tarmac001.tex` needs a member of exactly that name in the archive --
    a missing one is not a missing texture but a crash. Images are looked up
    next to the model, which is where every exporter puts them.
    """
    from . import tex

    src = Path(source)
    base = src.parent
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)

    meshes = read_meshes(src)
    mapping = fit_texture_names(
        m.name for mesh in meshes.values() for m in mesh.materials)

    written = []
    for original, fitted in sorted(mapping.items()):
        stem = Path(original).stem
        image = next((base / (stem + e) for e in (".tga", ".TGA")
                      if (base / (stem + e)).exists()), None)
        if image is None:
            continue
        out = d / fitted
        pixels, w, h = tex.read_tga(image)
        if w != h:
            raise ValueError(f"{image.name} is {w}x{h}; textures must be square")
        channels = len(pixels) // (w * h)

        # Drop an alpha channel that carries no transparency, so the texture is
        # encoded opaque like every stock road and ground texture.
        if channels == 4 and min(pixels[3::4]) >= _OPAQUE_ALPHA_FLOOR:
            pixels = bytes(b for i, b in enumerate(pixels) if i % 4 != 3)
            channels = 3

        if w > TEX_MAX_SIZE:
            pixels = tex.resize_nearest(pixels, w, h, TEX_MAX_SIZE, TEX_MAX_SIZE,
                                        channels=channels)
            w = h = TEX_MAX_SIZE

        # wrap=1, not the encoder's default of 0: a road texture tiles along the
        # track, and a freshly encoded texture with wrap 0 is rejected outright
        # ("unknown texture format") rather than merely looking wrong.
        out.write_bytes(tex.encode_to_tex(
            pixels, w, mode="opaque" if channels == 3 else "alpha", wrap=1))
        written.append(out)
    return written


# ---------------------------------------------------------------------------
# Walls
#
# `.sol` holds the track's solid collision -- the barriers a car hits rather
# than drives on -- and writing one from scratch was long treated as blocked,
# because its spatial tail is not understood well enough to synthesise.
#
# It does not have to be synthesised. The surface scene file already has a
# syntax for a wall: an inline `object(<texture>,1,0)` followed by four verts
# and a `quad(0,1,2,3)`, and MKWORLD turns each one into exactly one `.sol`
# primitive. Measured on a real track: 246 declared quads produced a 69,262-byte
# `.sol` carrying 246 primitives, against the 48-byte empty file the same scene
# produces with no walls declared, and at the same version (2) as the stock
# tracks. That is the same MKWORLD run the pipeline already makes for `.bsp`, so
# walls cost no new tool.
#
# A wall is TWO things, and vrTrackMaker keeps them apart:
#
#   the collision   object(wall.tga,1,0) + a quad, in the SURFACE file only,
#                   which MKWORLD compiles into a .sol primitive
#   the appearance  an ordinary mesh in the GRAPHIC file, listed with param1=3
#                   (NO_COLLISION) so it is drawn but not solid
#
# Its output carries four such meshes -- wallcli/wallclo/wallcri/wallcro, the
# left and right barriers' inner and outer faces -- none of which appears in the
# surface file at all. The stock tracks do the same thing by hand: they have no
# wall-specific texture, just scenery (fncing.tex, fense.tex, brk.tex, concr.tex)
# with .sol boxes and tubes placed alongside to approximate it.
#
# add_walls() below emits only the collision half, which is why a generated wall
# is invisible. Emitting the appearance half is what importing a modelled
# barrier will need, and it belongs in the graphic file with param1=3.

DEFAULT_WALL_HEIGHT = 1.5
DEFAULT_WALL_SPACING = 4          # stations per quad


def add_walls(
    scene: "TrackScene",
    *,
    offset: float,
    height: float = DEFAULT_WALL_HEIGHT,
    stride: int = DEFAULT_WALL_SPACING,
    sides: str = "both",
    texture: str = "wall.tga",
) -> int:
    """Run barrier walls alongside the centreline. Returns the quad count.

    `offset` is the lateral distance from the centreline, in metres -- put it
    outside the road AND its verges, or a car will scrape a wall while still on
    the track. `stride` is how many stations each quad spans: fewer means more
    quads and a closer fit through corners.

    Each quad becomes one `.sol` primitive when MKWORLD compiles the surface
    file, so the count here is the count that ends up in the track.
    """
    pts = scene.centreline
    n = len(pts)
    if n < 3:
        raise ValueError("walls need a centreline of at least three stations")
    if offset <= 0:
        raise ValueError(f"wall offset must be positive, got {offset}")
    if height <= 0:
        raise ValueError(f"wall height must be positive, got {height}")
    stride = max(1, int(stride))

    signs = {"both": (1.0, -1.0), "left": (1.0,), "right": (-1.0,)}.get(sides)
    if signs is None:
        raise ValueError(f"sides must be 'both', 'left' or 'right', got {sides!r}")

    normals = _normals_2d(pts, True)
    added = 0
    for i in range(0, n, stride):
        j = (i + stride) % n
        ax, ay, ae = pts[i]
        bx, by, be = pts[j]
        nax, nay = normals[i]
        nbx, nby = normals[j]
        for sgn in signs:
            a = (ax + nax * offset * sgn, ay + nay * offset * sgn, ae)
            b = (bx + nbx * offset * sgn, by + nby * offset * sgn, be)
            # bottom edge along the track, then back along the top
            scene.walls.append([
                a, b,
                (b[0], b[1], b[2] + height),
                (a[0], a[1], a[2] + height),
            ])
            added += 1
    scene.wall_texture = texture
    return added
