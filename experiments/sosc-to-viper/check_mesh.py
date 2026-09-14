"""Checks for a converted body, measured against the cars the game shipped.

Nothing here asserts against a number I invented. Every claim is calibrated on
the STOCK cars first and the conversion is then required to land in the same
place, because the only authority on what Viper Racing's renderer tolerates is
what Monster Games actually shipped to it.

The three properties, and the defect each one exists to catch:

  winding consistency   Two triangles sharing an edge must traverse it in
                        opposite directions. Streets of SimCity renders
                        two-sided, so its meshes do not care; Viper culls
                        backfaces, and an inconsistent face is a hole you can
                        see the track through. Stock cars are not perfect
                        either -- viper.car itself carries 1% -- so the bar is
                        "no worse than stock", not "zero".

  UV range              THE one that mattered. Every stock car keeps its UVs
                        inside the unit square (exotic 1 vertex of 181 outside,
                        by a hundredth; sedan and viper none). The raw
                        conversion put 100% of the Airhawk's outside it -- v
                        running 1.0..2.0, the police car's 1.0..3.0 -- which is
                        the same texel for any sampler that wraps, and this
                        project's own renderer wraps, so it showed a clean car
                        while the game showed a see-through patch along the
                        flank.

  LOD texture ownership Every mesh in the car must reference only textures the
                        car actually contains. LODs 1..7 start out as the
                        DONOR's meshes, still naming the donor's textures: the
                        car looks right up close and morphs into a Viper GTS-R
                        in the mirror.

    python check_mesh.py <viper_install_dir> [converted_car ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vrmod import archive, envelope, mod  # noqa: E402

PASS = FAIL = 0
# The stock cars. Anything else in an install may well be a conversion -- this
# experiment's own output gets copied in there to test it, which is exactly how
# a "stock baseline" quietly becomes a measurement of your own work.
STOCK = ("viper.car", "sedan.car", "exotic.car", "4x4cos.car", "sports.car")


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def bodies(path: Path):
    """{member name: Mesh} for every .mod in a car."""
    out = {}
    for e in archive.read(path):
        if e.name.lower().endswith(".mod"):
            out[e.name] = mod.parse(envelope.build(e.tag, e.version, e.payload))
    return out


def textures(path: Path) -> set[str]:
    return {e.name.lower() for e in archive.read(path)
            if e.name.lower().endswith(".tex")}


def inconsistency(mesh) -> tuple[int, int]:
    """(inconsistent edges, shared edges). An edge traversed the SAME way by
    both of its faces means one of them is wound backwards.

    Deliberate two-sided pairs are excluded first. The conversion emits a
    handful of faces twice, once each way, where the source mesh cannot be
    oriented consistently at all; counting those as defects would make the
    mitigation look like the disease -- it took the Airhawk from 0.8% to 9.4%
    and failed a car that is fine.
    """
    twinned = set()
    first: dict[tuple[int, ...], int] = {}
    for fi, f in enumerate(mesh.faces):
        key = tuple(sorted(f))
        if key in first:
            twinned.add(fi)
            twinned.add(first[key])
        else:
            first[key] = fi

    seen: dict[tuple[int, int], int] = {}
    bad = shared = 0
    for fi, (ia, ib, ic) in enumerate(mesh.faces):
        if fi in twinned:
            continue
        for a, b in ((ia, ib), (ib, ic), (ic, ia)):
            key = (min(a, b), max(a, b))
            d = 1 if a < b else -1
            if key in seen:
                shared += 1
                if seen[key] == d:
                    bad += 1
            else:
                seen[key] = d
    return bad, shared


def signed_volume(mesh) -> float:
    """Positive for a closed surface whose faces point outward."""
    vol = 0.0
    for ia, ib, ic in mesh.faces:
        a, b, c = mesh.vertices[ia], mesh.vertices[ib], mesh.vertices[ic]
        vol += (a.x * (b.y * c.z - b.z * c.y)
                - a.y * (b.x * c.z - b.z * c.x)
                + a.z * (b.x * c.y - b.y * c.x)) / 6.0
    return vol


def outside_unit_square(mesh, tol: float = 0.02) -> int:
    return sum(1 for v in mesh.vertices
               if not (-tol <= v.u <= 1 + tol and -tol <= v.v <= 1 + tol))


def bbox(mesh) -> tuple[int, int, int]:
    """Rounded extent, as a shape fingerprint a decimation preserves."""
    xs = [v.x for v in mesh.vertices]
    ys = [v.y for v in mesh.vertices]
    zs = [v.z for v in mesh.vertices]
    return (round(max(xs) - min(xs)), round(max(ys) - min(ys)),
            round(max(zs) - min(zs)))


def similar_box(a, b, tol: float = 0.2) -> bool:
    """Decimation shrinks the hull a little as detail goes; a different car is
    a different size. 20% on every axis separates the two comfortably."""
    return all(abs(x - y) <= tol * max(abs(y), 1) for x, y in zip(a, b))


def body_of(car: Path):
    """The LOD-0 mesh, by the <prefix>0.mod convention every car follows."""
    for name, mesh in sorted(bodies(car).items()):
        if name.lower().endswith("0.mod"):
            return name, mesh
    return None, None


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("check_mesh.py <viper_install_dir> [converted_car ...]")
    install = Path(sys.argv[1])
    cars = [Path(a) for a in sys.argv[2:]]

    # ---- calibrate on the shipped cars ------------------------------------
    print("stock baseline")
    worst_ratio = 0.0
    worst_uv = 0
    stock_seen = 0
    for name in STOCK:
        path = install / name
        if not path.is_file():
            continue
        stock_seen += 1
        _, mesh = body_of(path)
        bad, shared = inconsistency(mesh)
        ratio = bad / max(shared, 1)
        out = outside_unit_square(mesh)
        worst_ratio = max(worst_ratio, ratio)
        worst_uv = max(worst_uv, out)
        print(f"    {name:12s} {len(mesh.faces):>4}f  inconsistent {bad:>3}/{shared:<4}"
              f" ({ratio:4.1%})  uvs outside {out}/{len(mesh.vertices)}")
    if not stock_seen:
        print(f"  (no stock cars in {install} -- nothing to calibrate against)")
        return 0
    print(f"  worst shipped: {worst_ratio:.1%} inconsistent, "
          f"{worst_uv} vertex(es) outside the unit square")

    if not cars:
        print("\n  no converted cars given; baseline only")
        return 0

    # ---- and hold the conversions to it -----------------------------------
    for car in cars:
        print(f"\n{car.name}")
        name, mesh = body_of(car)
        if mesh is None:
            check(f"{car.name} has a LOD-0 body", False)
            continue

        bad, shared = inconsistency(mesh)
        ratio = bad / max(shared, 1)
        check("winding no worse than the shipped cars", ratio <= max(worst_ratio, 0.01),
              f"{bad}/{shared} inconsistent ({ratio:.1%}) against {worst_ratio:.1%} stock")

        check("faces point outward", signed_volume(mesh) > 0,
              f"signed volume {signed_volume(mesh):+,.0f}")

        # The unit-square rule is the one with no slack: five of the seven
        # conversions land on zero, exactly like the shipped cars, and the
        # allowance here only covers the same rounding stock shows.
        out = outside_unit_square(mesh)
        check("uvs inside the unit square", out <= max(worst_uv, 1),
              f"{out}/{len(mesh.vertices)} outside")

        # The LOD chain. `carfork` renames the donor's files but does not
        # rebuild its meshes, so LODs 1..7 stay the DONOR's car -- and because
        # the rename makes the texture names look right, nothing about the
        # names gives it away. The shape does: a decimated LOD of this body
        # occupies the same box and samples the same textures.
        chain = {n: m for n, m in bodies(car).items()
                 if n[:-5].lower() == name[:-5].lower() and n[-5].isdigit()}
        lod0_mats = {mat.name.lower() for mat in mesh.materials}
        lod0_box = bbox(mesh)
        wrong = []
        for member, m in sorted(chain.items()):
            if member == name:
                continue
            mats = {mat.name.lower() for mat in m.materials}
            if not mats <= lod0_mats:
                wrong.append(f"{member} samples {sorted(mats - lod0_mats)}")
                continue
            if not similar_box(bbox(m), lod0_box):
                wrong.append(f"{member} is a different shape {bbox(m)}")
        check("every LOD is a reduction of this body", not wrong,
              "; ".join(wrong[:2]) or f"{len(chain)} meshes in the chain")

        # Brake lights. NOTHING here can be checked by looking: carshot renders
        # <prefix>0.mod and the wheels, and never draws the brake mesh, so a
        # render of a car with its lamps buried inside the bodywork looks
        # perfect. The same blind spot as the backface and UV-wrap ones -- the
        # only defence is to assert the geometry directly.
        brake = bodies(car).get(f"{name[:-5]}b.mod") or bodies(car).get(
            f"{name[:-5]}B.mod")
        if brake is None:
            check("the car has a brake mesh", False, "no <prefix>b.mod")
        else:
            bz = [v.z for v in brake.vertices]
            bx = [v.x for v in brake.vertices]
            body_tail = min(v.z for v in mesh.vertices)
            half = max(abs(v.x) for v in mesh.vertices)
            # On the tail, not inside it and not trailing in mid-air. The donor's
            # unfitted mesh sat 19cm inside the Airhawk and 9cm behind the Beetle.
            gap = min(bz) - body_tail
            check("brake lights sit on the car's own tail", -0.02 <= gap <= 0.12,
                  f"{gap:+.2f} from the body's rearmost point "
                  f"(inherited donor meshes were -0.19 to +0.09 out)")
            left = [v.x for v in brake.vertices if v.x < 0]
            right = [v.x for v in brake.vertices if v.x >= 0]
            check("a lamp on each side, both within the bodywork",
                  bool(left) and bool(right) and max(abs(x) for x in bx) <= half * 1.05,
                  f"x {min(bx):.2f}..{max(bx):.2f} against a half-width of {half:.2f}")
            check("the pair is symmetric",
                  bool(left) and bool(right)
                  and abs(abs(min(left)) - max(right)) <= 0.12,
                  f"outer edges |{min(left):.2f}| and {max(right):.2f}"
                  if left and right else "one side missing")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
