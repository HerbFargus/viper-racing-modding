"""Find the "invisible cactus" bug: where a track's collision and render meshes disagree.

Viper Racing keeps what you SEE (`.grf`) and what you HIT (`.bpp`) in two separate
files, and the build pipeline generates them together from one source (see the
reference, build-pipeline section). Edit a compiled `.grf` without regenerating
`.bpp` -- as track mods routinely do -- and the two drift apart:

  * COLLISION WITHOUT GEOMETRY -- an "invisible wall". You deleted a cactus from
    the render mesh but its collision triangles are still in the BSP, so the car
    hits something that is no longer drawn. This is the one that ruins a lap.
  * GEOMETRY WITHOUT COLLISION -- a "drive-through" prop. You added scenery to the
    render mesh without collision, so the car passes straight through it. Usually
    harmless, sometimes wrong (a new wall you can drive through).

Both files share one world coordinate frame (verified: their bounding boxes
coincide), so the check is geometric: for each triangle in one mesh, is there any
triangle of the other nearby? "Nearby" is measured between triangle centroids,
which is cheap and robust to the two meshes tessellating the same surface
differently. A voxel hash keeps it linear rather than O(n*m) -- a track has tens
of thousands of triangles in each mesh.

This is a HEURISTIC, not a proof. The two meshes never match triangle-for-triangle
even on a clean track: the render mesh has cosmetic detail (kerb paint, tent tops,
distant scenery) with no collision, and the collision mesh simplifies gentle
terrain the render mesh tessellates finely. So a clean track has a nonzero baseline
of one-sided triangles. What flags a real bug is a *cluster* of collision-without-
geometry in a compact region -- an object's worth of triangles, all orphaned
together -- which is exactly what a deleted prop leaves behind.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import archive, grf, bpp


@dataclass
class Cluster:
    """A connected group of orphaned collision triangles."""
    count: int
    cx: float
    cy: float
    cz: float
    radius: float          # 3D spread
    xz_radius: float       # horizontal footprint
    y_extent: float        # vertical extent

    @property
    def object_like(self) -> bool:
        """Compact footprint with real height -- a prop (cactus, sign, tree),
        not a terrain feature. A ground sheet is wide and flat (big xz_radius,
        tiny height); a terrain sliver is tight but flat (tiny height); banking
        is tall but wide. A standing prop is the one combination left: a small
        horizontal footprint that also has vertical extent.

        The thresholds are calibrated against the eight stock tracks, which have
        no deleted props by construction (their scenery is present in both files):
        every one of their ~167 collision-only terrain clusters is excluded, so a
        hit on a real track is a genuine geometry/collision mismatch, not terrain.
        """
        return self.xz_radius <= 10.0 and self.y_extent >= 2.0 and self.count >= 8


@dataclass
class Report:
    grf_triangles: int
    bpp_triangles: int
    collision_without_geometry: int      # invisible walls (raw; includes terrain)
    geometry_without_collision: int      # drive-through props
    cell: float
    clusters: list[Cluster] = field(default_factory=list)   # of the invisible walls

    @property
    def suspects(self) -> list[Cluster]:
        """The clusters that look like deleted PROPS rather than collision-only
        terrain -- the ones actually worth investigating."""
        return [c for c in self.clusters if c.object_like]


def _grf_centroids(payload_with_envelope: bytes) -> list[tuple[float, float, float]]:
    g = grf.parse(payload_with_envelope)
    v = g.mesh.vertices
    out = []
    for a, b_, c in g.mesh.faces:
        out.append(((v[a].x + v[b_].x + v[c].x) / 3.0,
                    (v[a].y + v[b_].y + v[c].y) / 3.0,
                    (v[a].z + v[b_].z + v[c].z) / 3.0))
    return out


def _bpp_centroids(payload: bytes) -> list[tuple[float, float, float]]:
    b = bpp.parse(payload)
    out = []
    for t in b.triangles:
        v0, v1, v2 = t.v
        out.append(((v0[0] + v1[0] + v2[0]) / 3.0,
                    (v0[1] + v1[1] + v2[1]) / 3.0,
                    (v0[2] + v1[2] + v2[2]) / 3.0))
    return out


def _hash(points, cell):
    grid = {}
    for p in points:
        key = (int(p[0] // cell), int(p[1] // cell), int(p[2] // cell))
        grid.setdefault(key, []).append(p)
    return grid


def _orphans(points, grid, cell, radius):
    """Points with no other-mesh point within `radius`, checking the 27 neighbour cells."""
    r2 = radius * radius
    out = []
    for p in points:
        cx, cy, cz = int(p[0] // cell), int(p[1] // cell), int(p[2] // cell)
        near = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q in grid.get((cx + dx, cy + dy, cz + dz), ()):
                        if (p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2 <= r2:
                            near = True
                            break
                    if near:
                        break
                if near:
                    break
            if near:
                break
        if not near:
            out.append(p)
    return out


def _cluster(points, cell):
    """Group orphaned points into connected blobs via the same voxel grid."""
    remaining = {i: p for i, p in enumerate(points)}
    grid = {}
    for i, p in remaining.items():
        grid.setdefault((int(p[0]//cell), int(p[1]//cell), int(p[2]//cell)), []).append(i)
    seen = set()
    clusters = []
    for i, p in remaining.items():
        if i in seen:
            continue
        stack, members = [i], []
        while stack:
            j = stack.pop()
            if j in seen:
                continue
            seen.add(j)
            members.append(remaining[j])
            q = remaining[j]
            cx, cy, cz = int(q[0]//cell), int(q[1]//cell), int(q[2]//cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for k in grid.get((cx+dx, cy+dy, cz+dz), ()):
                            if k not in seen:
                                stack.append(k)
        n = len(members)
        mx = sum(m[0] for m in members) / n
        my = sum(m[1] for m in members) / n
        mz = sum(m[2] for m in members) / n
        rad = max(((m[0]-mx)**2 + (m[1]-my)**2 + (m[2]-mz)**2) ** 0.5 for m in members)
        xzr = max(((m[0]-mx)**2 + (m[2]-mz)**2) ** 0.5 for m in members)
        yext = max(m[1] for m in members) - min(m[1] for m in members)
        clusters.append(Cluster(n, mx, my, mz, rad, xzr, yext))
    clusters.sort(key=lambda c: (c.object_like, c.count), reverse=True)
    return clusters


def _load(track) -> tuple[bytes, bytes]:
    """(grf-with-envelope, bpp-payload) from a .trk/.tra archive."""
    grf_env = bpp_pl = None
    for e in archive.read(track):
        n = e.name.lower()
        if n.endswith(".grf"):
            grf_env = e.to_standalone_bytes()
        elif n.endswith(".bpp"):
            bpp_pl = e.payload
    if grf_env is None or bpp_pl is None:
        raise ValueError(f"{track}: need both a .grf and a .bpp inside the archive")
    return grf_env, bpp_pl


def check(track, *, cell: float = 8.0, radius: float = 6.0,
          min_cluster: int = 6) -> Report:
    """Compare one track's collision and render meshes. `track` is a .trk/.tra path.

    `radius` is how close an other-mesh triangle must be to count as "matched",
    in world units (metres). `cell` is the voxel size; keep it >= radius.
    `min_cluster` (default 6) is the smallest orphan cluster reported: 6 is the
    lowest floor that produces zero false positives across the eight stock tracks.

    NOTE the single-track limit: a deleted prop whose collision footprint is only
    a few triangles cannot be told apart from a terrain feature by geometry alone,
    so `check()` reliably finds larger orphaned objects but can miss a tiny one.
    To catch any edit, however small, diff a track against its original with
    `diff()` -- the shared terrain cancels and only the change remains.
    """
    grf_env, bpp_pl = _load(track)
    gc = _grf_centroids(grf_env)
    bc = _bpp_centroids(bpp_pl)

    g_grid = _hash(gc, cell)
    b_grid = _hash(bc, cell)

    # collision triangles with no render triangle nearby -> invisible walls
    cwg = _orphans(bc, g_grid, cell, radius)
    # render triangles with no collision triangle nearby -> drive-through props
    gwc = _orphans(gc, b_grid, cell, radius)

    clusters = [c for c in _cluster(cwg, cell) if c.count >= min_cluster]
    return Report(grf_triangles=len(gc), bpp_triangles=len(bc),
                  collision_without_geometry=len(cwg),
                  geometry_without_collision=len(gwc),
                  cell=cell, clusters=clusters)


@dataclass
class Diff:
    """What changed between an original track and an edited one."""
    lost_render: list[Cluster] = field(default_factory=list)     # collision now uncovered
    lost_collision: list[Cluster] = field(default_factory=list)  # geometry now intangible


def diff(original, edited, *, cell: float = 8.0, radius: float = 6.0,
         min_cluster: int = 2) -> Diff:
    """Compare an edited track against its original and report only what the edit
    changed -- the reliable way to catch a broken-collision mod of any size.

    `lost_render`: places where the edited track kept collision but lost the render
    geometry that covered it in the original -- **new invisible walls**, the cactus
    bug exactly. `lost_collision`: geometry present in both but whose collision the
    edit dropped -- **new drive-through** objects.

    Because both tracks share the same terrain, the terrain baseline that limits
    single-track `check()` cancels out, so `min_cluster` can be as low as 2 without
    false positives.
    """
    og, ob = _load(original)
    eg, eb = _load(edited)
    ogc, obc = _grf_centroids(og), _bpp_centroids(ob)
    egc, ebc = _grf_centroids(eg), _bpp_centroids(eb)

    # a point is "gone" if the original had a point there but the edit does not
    def gone(orig_pts, edit_pts):
        edit_grid = _hash(edit_pts, cell)
        return _orphans(orig_pts, edit_grid, cell, radius)

    lost_r = gone(ogc, egc)                       # render triangles the edit removed
    lost_c = gone(obc, ebc)                       # collision triangles the edit removed

    # a removed render triangle is a NEW invisible wall only if collision is still
    # there in the edited track; a removed collision triangle is a new drive-through
    # only if the render is still there.
    e_bpp_grid = _hash(ebc, cell)
    e_grf_grid = _hash(egc, cell)
    walls = [p for p in lost_r if not _orphans([p], e_bpp_grid, cell, radius)]
    through = [p for p in lost_c if not _orphans([p], e_grf_grid, cell, radius)]

    return Diff(
        lost_render=[c for c in _cluster(walls, cell) if c.count >= min_cluster],
        lost_collision=[c for c in _cluster(through, cell) if c.count >= min_cluster])
