"""Check that decimation (`vrmod modlod`, `moddecimate`) shrinks a mesh without tearing it.

The old decimator collapsed each material block on its own, so the two sides of every material
boundary moved apart: the Streets of SimCity cars went from 0 open edges at LOD 0 to 91-249 at
LOD 1, and the Willys jeep to 1,079 (floating mirrors, a vanished windscreen frame) -- and the
chase camera draws LOD 1. For every generated level this checks, against LOD 0:

  - no new open edges, once records are welded by rounded position (an open edge is one used by
    exactly one triangle);
  - winding: no edge traversed twice in the same direction that LOD 0 didn't already have, and a
    positive signed volume;
  - UV seams: every record is an original one (same material, position and UV), and no triangle
    takes its corners from two different LOD 0 texture charts (which would smear an atlas);
  - and the levels really shrink, since full-size copies in every LOD slot hang race loading.

A synthetic cube (two materials, one UV seam across a flat face) always runs. The installed
test cars under game-files/installs/v1.0-RC run when present -- azzaroni.car.bak (a pre-fix
SoSC car), willys.car (an 11,040-record baked-atlas body) and viper.car -- read-only: the
chains are built in memory and nothing is written.

Run:  python scripts/check_modlod.py
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, car, envelope, mod  # noqa: E402

FAILS: list[str] = []
INSTALL = Path(__file__).resolve().parents[2] / "game-files" / "installs" / "v1.0-RC"


def check(ok: bool, what: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        FAILS.append(what)


def _pos(v: mod.Vertex) -> tuple:
    return (round(v.x, 4), round(v.y, 4), round(v.z, 4))


def _rec(m: mod.Mesh, mi: int, i: int) -> tuple:
    v = m.vertices[i]
    return (m.materials[mi].name, mi, _pos(v), round(v.u, 4), round(v.v, 4))


def _face_recs(m: mod.Mesh) -> list[tuple]:
    return [tuple(_rec(m, mi, i) for i in m.faces[fi])
            for mi, mt in enumerate(m.materials) for fi in range(mt.face_start, mt.face_end)]


def topology(m: mod.Mesh) -> dict:
    """Welded open edges, same-direction duplicate edges and signed volume."""
    ids: dict[tuple, int] = {}
    w = [ids.setdefault(_pos(v), len(ids)) for v in m.vertices]
    und, dire, vol = Counter(), Counter(), 0.0
    for a, b, c in m.faces:
        A, B, C = w[a], w[b], w[c]
        if len({A, B, C}) < 3:
            continue
        for p, q in ((A, B), (B, C), (C, A)):
            und[(min(p, q), max(p, q))] += 1
            dire[(p, q)] += 1
        va, vb, vc = m.vertices[a], m.vertices[b], m.vertices[c]
        vol += (va.x * (vb.y * vc.z - vb.z * vc.y) - va.y * (vb.x * vc.z - vb.z * vc.x)
                + va.z * (vb.x * vc.y - vb.y * vc.x)) / 6
    return {"open": sum(1 for n in und.values() if n == 1),
            "dupdir": sum(1 for n in dire.values() if n > 1), "volume": vol}


def charts(m0: mod.Mesh) -> dict[tuple, set[int]]:
    """Each LOD 0 record -> the texture charts it belongs to (triangles joined across edges whose
    two ends are the same records on both sides)."""
    fr = _face_recs(m0)
    parent = list(range(len(fr)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first: dict[frozenset, int] = {}
    for fi, f in enumerate(fr):
        for e in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            k = frozenset(e)
            if k in first:
                parent[find(fi)] = find(first[k])
            else:
                first[k] = fi
    out: dict[tuple, set[int]] = defaultdict(set)
    for fi, f in enumerate(fr):
        for r in f:
            out[r].add(find(fi))
    return out


def check_chain(label: str, m0: mod.Mesh, levels: list[mod.Mesh]) -> None:
    t0 = topology(m0)
    chart_of = charts(m0)
    originals = {_rec(m0, mi, i) for mi, mt in enumerate(m0.materials)
                 for i in range(mt.vertex_start, mt.vertex_end)}
    print(f"{label}: LOD 0 {len(m0.vertices)} records, {t0['open']} open edges, "
          f"{t0['dupdir']} same-direction edges, volume {t0['volume']:.3f}")
    for n, m in enumerate(levels, 1):
        t = topology(m)
        recs = {_rec(m, mi, i) for mi, mt in enumerate(m.materials)
                for i in range(mt.vertex_start, mt.vertex_end)}
        cross = sum(1 for f in _face_recs(m)
                    if not (chart_of.get(f[0], set()) & chart_of.get(f[1], set())
                            & chart_of.get(f[2], set())))
        print(f"  LOD {n}: {len(m.vertices)} records, {len(m.faces)} faces, open {t['open']}, "
              f"same-direction {t['dupdir']}, volume {t['volume']:.3f}, cross-chart faces {cross}")
        check(t["open"] <= t0["open"], f"{label} LOD {n}: no new open edges ({t['open']} vs {t0['open']})")
        check(t["dupdir"] <= t0["dupdir"], f"{label} LOD {n}: no new same-direction edges")
        check(t["volume"] > 0, f"{label} LOD {n}: positive signed volume")
        check(recs <= originals, f"{label} LOD {n}: every record is an original (material, position, UV)")
        check(cross == 0, f"{label} LOD {n}: no triangle spans two texture charts")
        check(all(mt.face_end > mt.face_start for mt in m.materials),
              f"{label} LOD {n}: every material keeps triangles")


def cube(n: int = 8) -> mod.Mesh:
    """A closed n x n-subdivided cube, outward CCW in the game's left-handed space. Material
    'a.tex' takes +x, +y, +z and 'b.tex' the rest, so three cube edges are material boundaries;
    every side is its own UV chart, and the +y side is cut into two charts down the middle."""
    sides = [  # origin, u axis, v axis, material
        ((1, -1, -1), (0, 0, 2), (0, 2, 0), "a"),     # +x
        ((-1, 1, -1), (0, 0, 2), (2, 0, 0), "a"),     # +y
        ((-1, -1, 1), (0, 2, 0), (2, 0, 0), "a"),     # +z
        ((-1, -1, -1), (0, 2, 0), (0, 0, 2), "b"),    # -x
        ((-1, -1, -1), (2, 0, 0), (0, 0, 2), "b"),    # -y
        ((-1, -1, -1), (2, 0, 0), (0, 2, 0), "b"),    # -z
    ]
    blocks: dict[str, tuple[list, list]] = {"a": ([], []), "b": ([], [])}
    for si, (o, du, dv, mat) in enumerate(sides):
        verts, faces = blocks[mat]
        cut = n // 2 if si == 1 else None
        index: dict[tuple, int] = {}

        def vid(i: int, j: int, chart: int) -> int:
            k = (i, j, chart)
            if k not in index:
                p = [o[a] + du[a] * i / n + dv[a] * j / n for a in range(3)]
                index[k] = len(verts)
                verts.append(mod.Vertex(*p, 0.0, 0.0, 0.0, 0.1 * si + 0.05 * chart + i / (10 * n),
                                        j / (10 * n)))
            return index[k]

        for i in range(n):
            for j in range(n):
                chart = int(cut is not None and i >= cut)
                a, b, c, d = vid(i, j, chart), vid(i + 1, j, chart), vid(i + 1, j + 1, chart), vid(i, j + 1, chart)
                for f in ((a, b, c), (a, c, d)):
                    faces.append(f if _outward(verts, f) else (f[0], f[2], f[1]))
    vertices, faces, materials = [], [], []
    for name, (bv, bf) in blocks.items():
        off, fstart = len(vertices), len(faces)
        vertices += bv
        faces += [(a + off, b + off, c + off) for a, b, c in bf]
        materials.append(mod.Material(f"{name}.tex", off, len(vertices), fstart, len(faces)))
    return mod.Mesh(vertices, materials, faces)


def _outward(verts: list[mod.Vertex], f: tuple[int, int, int]) -> bool:
    """Is this triangle wound the way topology()'s positive volume means, for a solid around 0?"""
    a, b, c = (verts[i] for i in f)
    u = (b.x - a.x, b.y - a.y, b.z - a.z)
    w = (c.x - a.x, c.y - a.y, c.z - a.z)
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    return n[0] * a.x + n[1] * a.y + n[2] * a.z > 0


def car_chain(path: Path) -> tuple[mod.Mesh, list[mod.Mesh]]:
    entries = archive.read(path)
    prefix = car.body_prefix(entries).lower()
    out, _ = car.build_lod_chain(entries)
    meshes = {e.name.lower(): mod.parse(envelope.build(e.tag, e.version, e.payload))
              for e in out if e.name.lower().endswith(".mod")}
    return meshes[f"{prefix}0.mod"], [meshes[f"{prefix}{i}.mod"] for i in range(1, 8)]


def main() -> int:
    m0 = cube()
    check(topology(m0)["open"] == 0, "cube fixture is closed")
    levels = [mod.decimate(m0, max(12, round(len(m0.vertices) * f))) for f in car._LOD_FRACS]
    check_chain("cube", m0, levels)
    check(len(levels[0].vertices) < len(m0.vertices), "cube LOD 1 is smaller than LOD 0")
    check(len(levels[-1].vertices) <= len(m0.vertices) // 4, "cube LOD 7 is at most a quarter of LOD 0")

    # The +y side's middle seam (z = 0) may only be shortened along itself: no triangle on that
    # side may cross it, and both charts keep triangles.
    for n, m in enumerate(levels, 1):
        top = [[m.vertices[i] for i in f] for f in m.faces
               if all(abs(m.vertices[i].y - 1) < 1e-9 for i in f)]
        crossing = sum(1 for t in top if min(v.z for v in t) < -1e-9 < 1e-9 < max(v.z for v in t))
        halves = {max(v.z for v in t) > 1e-9 for t in top}
        check(crossing == 0 and halves == {True, False},
              f"cube LOD {n}: the +y UV seam is intact on its own line")

    # The load budget: LOD 0 x LODs 1-4 (Car::Car's nearest-vertex maps), LODs 5-7 free.
    check(car.load_cost([325, 299, 221, 186, 122, 79, 48, 26]) == 325 * 828, "load cost is LOD 0 x LODs 1-4")
    big = cube(40)
    entries = [archive.ArchiveEntry(name="big0.mod", tag=mod.TAG, version=1,
                                    payload=envelope.parse(mod.build(big)).payload)]
    out, _ = car.build_lod_chain(entries)
    counts = car.lod_vertex_counts(out)
    print(f"cube(40) chain {counts}: {car.load_cost(counts) / 1e6:.1f}M per car")
    check(car.load_cost(counts) <= car.LOAD_BUDGET, "a generated chain fits the load budget when the mesh allows")
    check(all(a >= b for a, b in zip(counts, counts[1:])), "a generated chain never grows")

    for name in ("azzaroni.car.bak", "willys.car", "viper.car"):
        path = INSTALL / name
        if not path.exists():
            print(f"{name}: not installed, skipped")
            continue
        m0, levels = car_chain(path)
        check_chain(name, m0, levels)
        check(len(levels[0].vertices) < len(m0.vertices) * 0.8, f"{name} LOD 1 is under 80% of LOD 0")
        check(len(levels[-1].vertices) < len(m0.vertices) * 0.6, f"{name} LOD 7 is under 60% of LOD 0")

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
