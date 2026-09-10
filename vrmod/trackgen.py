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
    """Read a centreline from whichever of the supported formats `path` is."""
    suffix = Path(path).suffix.lower()
    if suffix == ".ase":
        return read_ase(path)
    if suffix == ".obj":
        return read_obj_polyline(path)
    raise ValueError(f"unsupported centreline format '{suffix}' (want .ase or .obj)")


def to_viper(p: Point, height: float = 0.0) -> Point:
    """Ground-plane point in source frame -> game frame, with y as the height."""
    return (-p[0], height, -p[1])


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


def resample(points: list[Point], spacing: float) -> list[Point]:
    """Re-space a polyline at a fixed arc length, preserving both ends."""
    if spacing <= 0 or len(points) < 2:
        return list(points)
    out = [points[0]]
    carry = 0.0
    for a, b in zip(points, points[1:]):
        seg = _dist(a, b)
        if seg == 0:
            continue
        t = spacing - carry
        while t <= seg:
            f = t / seg
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 0.0))
            t += spacing
        carry = (carry + seg) % spacing
    if _dist(out[-1], points[-1]) > 1e-9:
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
        for off, y, u in ((inner, y_inner, 0.0), (outer, y_outer, 1.0)):
            gx, gy = p[0] + nx * off, p[1] + ny * off
            wx, wy, wz = to_viper((gx, gy, 0.0), y)
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

    pts = [(p[0], p[1], 0.0) for p in centreline]
    if closed and _dist(pts[0], pts[-1]) < 1e-6:
        pts.pop()                      # a closed ring must not repeat its seam
    normals = _normals_2d(pts, closed)

    scene = TrackScene(centreline=pts)

    # Stations per segment, from the requested segment length.
    total = sum(_dist(a, b) for a, b in zip(pts, pts[1:])) or 1.0
    per_station = total / max(len(pts) - 1, 1)
    stride = max(2, int(round(segment_length / per_station))) if segment_length > 0 else len(pts)

    def emit(base: str, inner: float, outer: float, y_in: float, y_out: float,
             texture: str, code: int) -> None:
        """Sweep one band, cut into segments, each its own mesh."""
        starts = range(0, len(pts) - 1, stride) if stride < len(pts) else (0,)
        for n, s in enumerate(starts):
            e = min(s + stride + 1, len(pts))
            if e - s < 2:
                continue
            # segments share their boundary station, so the surfaces meet
            sub = pts[s:e]
            sub_n = normals[s:e]
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
        out.extend(_vert(p, flip=True) for p in quad)
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
