"""NILI -- .ili / .ild / .ilg AI driving line.

A track's racing line, stored as a loop of waypoints. Every track ships
`default.ili` (the racing line), `rdefault.ili` (the reverse-direction
variant) and `track.ild` (a third line variant); `drivers.res` carries
hundreds of per-skill-tier `.ilg` files in the same format.

    payload +0   3 x int32   header (see HEADER_SIZE below)
    payload +12  N x 68-byte records, 17 x float32 each:
        field[1]  X  (world space, feet)
        field[2]  Z  (world space, feet)
        field[6]  target speed
        field[9]  cumulative arc length from record 0 (feet), monotonic

Record count is derived from the payload length rather than read from the
header: (len(payload) - 12) is always an exact multiple of 68 across every
stock track, which pins the header size at 12 without having to know what
those three ints mean.

Two field notes worth keeping, both established by measurement rather than
assumption:

  * **Waypoints are in the same native space as the mesh.** Measuring each
    waypoint's distance to the nearest `grf.py` mesh vertex on Rock Island
    gives 7.8 ft for +Z versus 165 ft for -Z, so no flip is needed to sample
    heights or to compare against raw geometry -- and this module works
    entirely in that native space.
    The flip that published notes describe "versus exported OBJ/GLB meshes"
    is real, but it belongs to the EXPORTER: `mod.to_obj()` negates Z to
    convert Viper's left-handed space to a right-handed one. So anything
    drawing these waypoints into an exported/rendered scene has to negate Z
    on the way out (see `viewer._build_track_path`), while anything comparing
    them to raw file data must not.
  * **There is no height field.** field[6] looks like a plausible elevation
    at a glance (58-71 on Bemidji) but it is target SPEED -- the same field
    reads 34-59 on Rock Island, a road course, while Bemidji is a flat
    oval whose road surface sits near Y=0. Height must be sampled from the
    track mesh; see sample_heights().
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import envelope

TAG = b"ILIN"          # the logical name
ENVELOPE_TAG = b"NILI"  # what the envelope and archive directory actually carry
                        # (these formats store 4CCs byte-reversed)
HEADER_SIZE = 12
RECORD_SIZE = 68
FIELD_COUNT = 17

FIELD_X = 1
FIELD_Z = 2
FIELD_SPEED = 6
FIELD_DISTANCE = 9


@dataclass
class Waypoint:
    x: float
    z: float
    speed: float
    distance: float


def parse(data: bytes) -> list[Waypoint]:
    """Parse a standalone .ili/.ild/.ilg resource into its waypoint loop."""
    payload = envelope.parse(data).payload
    return parse_payload(payload)


def parse_payload(payload: bytes) -> list[Waypoint]:
    body = len(payload) - HEADER_SIZE
    if body <= 0 or body % RECORD_SIZE:
        raise ValueError(
            f"payload of {len(payload)} bytes is not {HEADER_SIZE} + a whole "
            f"number of {RECORD_SIZE}-byte records"
        )
    out = []
    for i in range(body // RECORD_SIZE):
        f = struct.unpack_from(f"<{FIELD_COUNT}f", payload, HEADER_SIZE + i * RECORD_SIZE)
        out.append(Waypoint(
            x=f[FIELD_X], z=f[FIELD_Z], speed=f[FIELD_SPEED], distance=f[FIELD_DISTANCE],
        ))
    return out


def sample_surface(points: list[Waypoint], mesh):
    """Find the road surface height under each waypoint, by dropping a
    vertical ray onto the track mesh.

    The line format stores no Y, so height has to come from the geometry.
    Two simpler approaches were tried first and both fail:

      * Nearest vertex, or a median of vertices within a radius, picks up
        whatever scenery stands near the line -- kerbs, walls, grandstand
        footings -- and lands well off the driving surface.
      * Smoothing those samples along the loop then flattens real hills, which
        on an undulating course (Rock Island, Sunset Mesa) drives the camera
        straight through the terrain.

    So this projects each waypoint onto every triangle it falls inside and
    interpolates the true surface height. A waypoint can sit under more than
    one surface (a bridge over a road, terrain beneath the track), so
    candidates are resolved by CONTINUITY: the first waypoint takes the median
    candidate, and each subsequent one takes whichever candidate is closest to
    the height already chosen for its predecessor. That follows a single
    connected ribbon of road over crests and dips instead of hopping between
    stacked surfaces.
    """
    tris = _triangles_by_cell(mesh)
    candidates = [_surface_at(tris, p.x, p.z) for p in points]

    known = [c for c in candidates if c]
    if not known:
        return [0.0] * len(points), [(0.0, 1.0, 0.0)] * len(points)
    first = sorted(h for h, _ in known[0])
    seed = first[len(first) // 2]

    heights: list[float] = []
    normals: list[tuple] = []
    prev, prev_n = seed, (0.0, 1.0, 0.0)
    # Two passes round the loop: the first settles from an arbitrary seed, the
    # second re-runs with the loop's own end state so the start/finish join
    # agrees with the rest.
    for _ in range(2):
        heights, normals = [], []
        for cand in candidates:
            if cand:
                chosen = min(cand, key=lambda hn: abs(hn[0] - prev))
                # Road surfaces come in near-coincident stacks -- every stock
                # track has about three layers within a few centimetres of
                # each other (base, markings, terrain beneath). The visible
                # one is the topmost, so having picked the right stack by
                # continuity, CLIMB to it.
                #
                # Climb one step at a time rather than jumping to the highest
                # in range: a single pass leaves the camera under any layer
                # more than COINCIDENT above the first pick, which is what
                # still clipped where a banked turn meets a hill. Stepping
                # keeps each move small, so it follows a stack upward without
                # ever leaping onto a genuinely separate floor above.
                while True:
                    higher = [hn for hn in cand
                              if chosen[0] < hn[0] <= chosen[0] + COINCIDENT]
                    if not higher:
                        break
                    chosen = max(higher, key=lambda hn: hn[0])
                prev, prev_n = chosen
            heights.append(prev)
            normals.append(prev_n)
    # Smoothing runs AFTER the climb and averages neighbours, which can pull a
    # point back down under a layer it had correctly stepped onto -- worst
    # exactly at transitions, where a banked turn meets a hill. So re-clear
    # afterwards: this pass only ever raises, and is deliberately not smoothed
    # again, since a small step is better than clipping through the road.
    heights = _smooth_loop(heights, window=3)
    for i, cand in enumerate(candidates):
        if not cand:
            continue
        y = heights[i]
        while True:
            higher = [h for h, _ in cand if y < h <= y + COINCIDENT]
            if not higher:
                break
            y = max(higher)
        heights[i] = y
    return heights, _smooth_normals(normals)


_CELL = 64.0
# How far above the driving surface to keep clear. Any surface within this
# distance is treated as part of the same road stack and stepped up onto,
# because a camera at eye height would otherwise be UNDERNEATH it and the
# road would clip through the view. Measured across all 8 stock tracks, the
# intruding surfaces sit 0.05-1.57 m above the road (median 0.13), so a
# threshold at eye height catches all of them; a real separate floor -- a
# bridge deck over a road -- is several metres up and stays separate.
COINCIDENT = 1.6


def _triangles_by_cell(mesh) -> dict:
    """Bucket triangles into a coarse XZ grid so each waypoint only tests
    nearby ones -- a track has thousands of faces and every waypoint would
    otherwise scan all of them."""
    grid: dict[tuple[int, int], list] = {}
    verts = mesh.vertices
    for face in mesh.faces:
        try:
            a, b, c = (verts[i] for i in face)
        except IndexError:
            continue
        tri = ((a.x, a.y, a.z), (b.x, b.y, b.z), (c.x, c.y, c.z))
        xs = (tri[0][0], tri[1][0], tri[2][0])
        zs = (tri[0][2], tri[1][2], tri[2][2])
        for cx in range(int(min(xs) // _CELL), int(max(xs) // _CELL) + 1):
            for cz in range(int(min(zs) // _CELL), int(max(zs) // _CELL) + 1):
                grid.setdefault((cx, cz), []).append(tri)
    return grid


def _surface_at(grid: dict, x: float, z: float):
    """Every surface directly below/above (x, z) as (height, normal) pairs.

    Height is barycentric interpolation on each triangle whose XZ projection
    contains the point; the normal is that triangle's face normal, flipped to
    point upward so a road reads the same way regardless of its winding.
    """
    out = []
    for tri in grid.get((int(x // _CELL), int(z // _CELL)), ()):
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
        d = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
        if abs(d) < 1e-9:
            continue
        u = ((bz - cz) * (x - cx) + (cx - bx) * (z - cz)) / d
        v = ((cz - az) * (x - cx) + (ax - cx) * (z - cz)) / d
        w = 1.0 - u - v
        if u < -1e-6 or v < -1e-6 or w < -1e-6:
            continue
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length < 1e-9:
            continue
        if ny < 0:
            nx, ny, nz = -nx, -ny, -nz
        out.append((u * ay + v * by + w * cy, (nx / length, ny / length, nz / length)))
    return out


def _heights_at(grid: dict, x: float, z: float) -> list[float]:
    return [h for h, _ in _surface_at(grid, x, z)]


def _smooth_loop(values: list[float], window: int = 5) -> list[float]:
    """Circular moving average over a closed loop of samples.

    Even with a median, individual samples pick up scenery that happens to
    stand near the racing line -- raw sampling produced a -134 ft outlier on
    Castlegreen, which is a grandstand footing rather than road. A driving
    line's real elevation changes gradually, so averaging over neighbours
    removes those spikes while preserving genuine gradients (Rock Island and
    Sunset Mesa really do climb and fall).

    The loop wraps, so the smoothing wraps too -- otherwise the start/finish
    join gets a visible step.
    """
    n = len(values)
    if n < window or window < 2:
        return values
    half = window // 2
    return [
        sum(values[(i + k) % n] for k in range(-half, half + 1)) / (2 * half + 1)
        for i in range(n)
    ]


def parse_file(path) -> list[Waypoint]:
    from pathlib import Path
    return parse(Path(path).read_bytes())


def sample_heights(points: list[Waypoint], mesh) -> list[float]:
    """Road height under each waypoint. See sample_surface()."""
    return sample_surface(points, mesh)[0]


def _smooth_normals(normals, window: int = 5):
    """Circular moving average over surface normals, re-normalised.

    Face normals jump between adjacent triangles, so a camera using them as
    its up vector would twitch polygon to polygon. Banking changes gradually,
    so averaging over neighbours tracks it without the facet chatter.
    """
    n = len(normals)
    if n < window or window < 2:
        return normals
    half = window // 2
    out = []
    for i in range(n):
        sx = sy = sz = 0.0
        for k in range(-half, half + 1):
            nx, ny, nz = normals[(i + k) % n]
            sx += nx; sy += ny; sz += nz
        length = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
        out.append((sx / length, sy / length, sz / length))
    return out


DENSIFY_FACTOR = 5


def densify(points: list[Waypoint], factor: int = DENSIFY_FACTOR) -> list[Waypoint]:
    """Subdivide a waypoint loop with a centripetal Catmull-Rom through XZ.

    Stock lines are sparse -- roughly 25 m between waypoints -- and a camera
    path built straight from them cuts the chord across every crest. Measured
    on Rock Island that put the camera up to 1.93 m BELOW the road over a hill,
    which reads as the road clipping through the view. Subdividing first, then
    sampling the surface at every sub-point, makes the path follow the crest
    instead of tunnelling under it.

    Speed is interpolated linearly; distance is recomputed from the subdivided
    geometry so arc length stays consistent.
    """
    n = len(points)
    if n < 4 or factor < 2:
        return points

    def cr(p0, p1, p2, p3, t):
        t2, t3 = t * t, t * t * t
        return 0.5 * ((2 * p1) + (-p0 + p2) * t
                      + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                      + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)

    out = []
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        p0, p3 = points[(i - 1) % n], points[(i + 2) % n]
        for k in range(factor):
            t = k / factor
            out.append(Waypoint(
                x=cr(p0.x, a.x, b.x, p3.x, t),
                z=cr(p0.z, a.z, b.z, p3.z, t),
                speed=a.speed + (b.speed - a.speed) * t,
                distance=0.0,
            ))
    run = 0.0
    for i, wp in enumerate(out):
        nxt = out[(i + 1) % len(out)]
        wp.distance = run
        run += math.hypot(nxt.x - wp.x, nxt.z - wp.z)
    return out


# ---------------------------------------------------------------------------
# Full-fidelity read/write
#
# parse() above surfaces the four fields callers actually reason about. Writing
# a line back needs all seventeen, plus the header, so `Line` keeps the records
# whole and `build()` puts them back byte for byte.
#
# What the seventeen floats hold, surveyed across every line in every track on
# hand (min/max over bemidji's forward AI line shown for scale):
#
#    [0]  always 0.0
#    [1]  X position                                   -216 .. 227
#    [2]  Z position                                   -405 .. 505
#    [3]  direction / tangent term                      -30 .. 30
#    [4]  direction / tangent term                      -41 .. 35
#    [5]  constant -20000.0 in every record of every track
#    [6]  target speed                                   59 .. 71
#    [7]  curvature-shaped, very small                    0 .. 0.006
#    [8]  segment length to the next waypoint            30 .. 46
#    [9]  cumulative distance around the lap              0 .. 2268
#   [10]  ~-1.7e38 sentinel, drifting slightly per record
#   [11]  always 0.0
#   [12]  distance-shaped lookahead                      30 .. 962
#   [13]  distance-shaped lookbehind                   -184 .. 747
#   [14]  small monotonic accumulator                     0 .. 36
#   [15]  lateral / offset term                          -12 .. 14
#   [16]  constant -1.58e38 sentinel
#
# Field 8 is confirmed as the step: it equals distance[i+1] - distance[i]. Fields
# 12 and 13 carry distances from neighbouring records rather than this one, so
# they are precomputed lookahead tables -- which is why generating a line from
# scratch needs more than filling in positions and speeds.

HEADER_FORMAT = "<3i"
HEADER_MAGIC = -2

# One file that is NOT this format, and is easy to mistake for it: nhmkworld
# writes an out/track.ild of its own, under envelope version 16 and with a
# different header shape. make-track.bat never copies it -- the track.ild that
# ships comes from `mkilicc -nolat track.ili tra	rack.ild`. So the intermediate
# is discarded, and parse_line() rejecting it is correct rather than a gap.


@dataclass
class Line:
    """A complete racing line: the header plus every field of every record."""

    records: list[tuple[float, ...]] = dataclass_field(default_factory=list)
    magic: int = HEADER_MAGIC
    record_size: int = RECORD_SIZE
    version: int = 3

    @property
    def waypoints(self) -> list[Waypoint]:
        """The friendly view -- the same four fields parse() returns."""
        return [Waypoint(x=r[FIELD_X], z=r[FIELD_Z],
                         speed=r[FIELD_SPEED], distance=r[FIELD_DISTANCE])
                for r in self.records]

    def set_field(self, index: int, values: list[float]) -> None:
        """Replace one field across every record, leaving the other sixteen."""
        if len(values) != len(self.records):
            raise ValueError(f"need {len(self.records)} values, got {len(values)}")
        self.records = [
            tuple(v if k == index else r[k] for k in range(FIELD_COUNT))
            for r, v in zip(self.records, values)
        ]


def parse_line(data: bytes) -> Line:
    """Parse a line keeping every field, from a complete file or a payload."""
    version = 3
    if data[:4] == envelope.MAGIC:
        env = envelope.parse(data)
        if env.tag != ENVELOPE_TAG:
            raise ValueError(f"expected tag {ENVELOPE_TAG!r}, got {env.tag!r}")
        version, payload = env.version, env.payload
    else:
        payload = data

    if len(payload) < HEADER_SIZE:
        raise ValueError(f"payload too short to be a line: {len(payload)} bytes")
    magic, record_size, count = struct.unpack_from(HEADER_FORMAT, payload, 0)
    need = HEADER_SIZE + count * record_size
    if need != len(payload):
        raise ValueError(
            f"header says {count} records of {record_size} bytes, needing "
            f"{need:,}, but the payload is {len(payload):,}")

    records = [struct.unpack_from(f"<{FIELD_COUNT}f", payload, HEADER_SIZE + i * record_size)
               for i in range(count)]
    return Line(records=records, magic=magic, record_size=record_size, version=version)


def build(line: Line) -> bytes:
    """Serialise a Line to complete file bytes. Round-trips byte for byte."""
    body = bytearray(struct.pack(HEADER_FORMAT, line.magic, line.record_size, len(line.records)))
    for r in line.records:
        if len(r) != FIELD_COUNT:
            raise ValueError(f"record must have {FIELD_COUNT} fields, got {len(r)}")
        body += struct.pack(f"<{FIELD_COUNT}f", *r)
    return envelope.build(ENVELOPE_TAG, line.version, bytes(body))


def parse_line_file(path) -> Line:
    return parse_line(Path(path).read_bytes())


def write_line_file(path, line: Line):
    p = Path(path)
    p.write_bytes(build(line))
    return p


# ---------------------------------------------------------------------------
# Generating a racing line
#
# What each of the seventeen fields holds was surveyed when the reader was
# written; this fills them for a line built from a centreline. Most are derived
# from the geometry and are exact. Three are not, and are marked below, because
# the shipped data does not make them obvious:
#
#   [12] and [13] are distances to the boundaries of a segmentation of the lap
#        whose rule is not known. They are piecewise "constant minus cumulative
#        distance", resetting at irregular intervals (bemidji's blocks run 9, 6,
#        21, 2, 2, 5, 4, 3 records). Here they are filled with distance to the
#        next and previous CHECKPOINT, which has the same shape and is the most
#        plausible reading.
#   [7]  is curvature-shaped and tiny (0 .. 0.006 across a whole track). Filled
#        with a turn-rate estimate.
#   [15] is a lateral or banking term in the range +-13. Filled with zero.
#
# If a generated line drives correctly, these are advisory. If the AI behaves
# oddly, they are where to look first.

FIELD_DIR_X = 3
FIELD_DIR_Z = 4
FIELD_MARK = 5           # -20000.0 in every record of every track
FIELD_CURVE = 7
FIELD_STEP = 8           # distance to the next waypoint
FIELD_SENTINEL_A = 10    # ~-1.7e38
FIELD_AHEAD = 12
FIELD_BEHIND = 13
FIELD_TIME = 14          # cumulative lap time, seconds
FIELD_LATERAL = 15
FIELD_SENTINEL_B = 16    # ~-1.58e38

MARK_VALUE = -20000.0
SENTINEL_A = -1.7014118346046923e38
SENTINEL_B = -1.5800920945002098e38


def generate(points, *, speed: float = 60.0, gates=None,
             closed: bool = True, version: int = 3) -> Line:
    """Build a racing line from a centreline.

    `points` are (x, z) or (x, y, z) in the game's frame -- the same frame the
    meshes and the object table use. `speed` is the target in metres per second
    (60 m/s is about 134 mph, close to what the shipped lines carry). `gates` is
    the cumulative distance of each checkpoint, used for fields 12 and 13.
    """
    pts = [(p[0], p[2] if len(p) > 2 else p[1]) for p in points]
    if len(pts) < 3:
        raise ValueError("a racing line needs at least three points")

    n = len(pts)
    nxt = lambda i: (i + 1) % n if closed else min(i + 1, n - 1)
    prv = lambda i: (i - 1) % n if closed else max(i - 1, 0)

    step = [math.dist(pts[i], pts[nxt(i)]) for i in range(n)]
    dist, run = [], 0.0
    for i in range(n):
        dist.append(run)
        run += step[i]
    total = run

    # Cumulative time, which is what field 14 holds -- confirmed against bemidji,
    # where 286.85 m at 4.708 s gives 60.9 m/s against a speed field of ~61.
    time, t = [], 0.0
    for i in range(n):
        time.append(t)
        t += step[i] / max(speed, 1e-6)

    marks = sorted(gates) if gates else [0.0, total / 2.0]

    records = []
    for i in range(n):
        x, z = pts[i]
        ax, az = pts[nxt(i)]
        bx, bz = pts[prv(i)]
        dx, dz = ax - x, az - z

        # turn rate: how much the heading swings here, per metre travelled
        h0 = math.atan2(z - bz, x - bx)
        h1 = math.atan2(az - z, ax - x)
        turn = (h1 - h0 + math.pi) % (2 * math.pi) - math.pi
        curve = abs(turn) / max(step[i], 1e-6)

        ahead = next((m for m in marks if m > dist[i]), marks[0] + total)
        behind = next((m for m in reversed(marks) if m <= dist[i]), marks[-1] - total)

        r = [0.0] * FIELD_COUNT
        r[FIELD_X] = x
        r[FIELD_Z] = z
        r[FIELD_DIR_X] = dx
        r[FIELD_DIR_Z] = dz
        r[FIELD_MARK] = MARK_VALUE
        r[FIELD_SPEED] = speed
        r[FIELD_CURVE] = curve
        r[FIELD_STEP] = step[i]
        r[FIELD_DISTANCE] = dist[i]
        r[FIELD_SENTINEL_A] = SENTINEL_A
        r[FIELD_AHEAD] = ahead - dist[i]
        r[FIELD_BEHIND] = behind - dist[i]
        r[FIELD_TIME] = time[i]
        r[FIELD_LATERAL] = 0.0
        r[FIELD_SENTINEL_B] = SENTINEL_B
        records.append(tuple(r))

    return Line(records=records, version=version)
