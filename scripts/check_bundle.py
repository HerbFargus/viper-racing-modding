"""Check vrmod.bundle catches what it claims to.

Every BAD rule exists because that mistake fails SILENTLY in game -- the texture
renders flat, or the face renders not at all, and nothing anywhere says why. So
the only thing that makes the rule worth having is that it actually fires, which
is what this asserts: a good bundle passes, and each deliberately-broken one is
refused for the right reason.

Run:  python scripts/check_bundle.py [a-real-car.car]
"""
from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vrmod import archive, bundle, mod, tex  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  -- {detail}" if detail else ""))


def write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)
    return path


def bad_messages(rep) -> list[str]:
    return [f.message for f in rep.findings if f.level == bundle.BAD]


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else None
    if src is None or not src.is_file():
        print("give me a .car containing a ball.mod to build fixtures from")
        return 2
    ents = {e.name.lower(): e for e in archive.read(src)}
    if "ball.mod" not in ents:
        print(f"{src.name} has no ball.mod")
        return 2
    ball = ents["ball.mod"].to_standalone_bytes()
    mesh = mod.parse(ball)
    tex_names = sorted({mt.name.lower() for mt in mesh.materials})
    good = {"ball.mod": ball}
    for n in tex_names:
        if n in ents:
            good[ents[n].name] = ents[n].to_standalone_bytes()
    if "horn.sfx" in ents:
        good["horn.sfx"] = ents["horn.sfx"].to_standalone_bytes()

    work = Path(tempfile.mkdtemp(prefix="check_bundle_"))
    print(f"fixtures from {src.name}: {sorted(good)}\n")

    # --- the good case ----------------------------------------------------
    z = write_zip(work / "herb_sosc-missile.zip", good)
    rep = bundle.inspect(z)
    check("a well-formed bundle passes", rep.verdict == bundle.OK,
          "; ".join(bad_messages(rep)))
    check("the filename yields author and part",
          rep.author == "herb" and rep.part == "sosc-missile",
          f"author={rep.author!r} part={rep.part!r}")

    # --- a texture the mesh names is absent -------------------------------
    missing = {k: v for k, v in good.items() if not k.lower().endswith(".tex")}
    rep = bundle.inspect(write_zip(work / "herb_no-texture.zip", missing))
    check("a missing texture is refused",
          rep.verdict == bundle.BAD
          and any("not in the bundle" in m for m in bad_messages(rep)))

    # --- a .tex name over the 12-character limit --------------------------
    long_name = {}
    for k, v in good.items():
        long_name["averylongtexturename.tex" if k.lower().endswith(".tex") else k] = v
    rep = bundle.inspect(write_zip(work / "herb_long-name.zip", long_name))
    check("an over-long .tex name is refused",
          any("characters, over the 12" in m for m in bad_messages(rep)))

    # --- a texture that is not a power of two -----------------------------
    odd = dict(good)
    first_tex = next(k for k in good if k.lower().endswith(".tex"))
    odd[first_tex] = tex.encode_to_tex(bytes(3) * (24 * 24), 24, mode="opaque") \
        if False else odd[first_tex]
    # encode_to_tex refuses a non-power-of-two itself, so forge the header
    raw = bytearray(good[first_tex])
    info = tex.parse(bytes(raw))
    # mip_count drives size: size == 2 ** (mip_count - 1); a bogus count fakes a
    # 1024-wide texture without needing 1024 x 1024 of pixels
    import struct
    hdr = 20 + 8            # envelope + into the tex header's mip_count field
    struct.pack_into("<i", raw, hdr, 11)
    odd[first_tex] = bytes(raw)
    rep = bundle.inspect(write_zip(work / "herb_oversize.zip", odd))
    check("an oversized texture is refused",
          any("must be square, a power of two" in m for m in bad_messages(rep)),
          f"declared {tex.parse(bytes(raw)).size}px")

    # --- a UV addressing off the page -------------------------------------
    off = dict(good)
    m2 = mod.parse(ball)
    verts = list(m2.vertices)
    v0 = verts[0]
    verts[0] = mod.Vertex(v0.x, v0.y, v0.z, v0.nx, v0.ny, v0.nz, 1.6, v0.v)
    off["ball.mod"] = mod.build(mod.Mesh(vertices=verts, materials=list(m2.materials),
                                         faces=list(m2.faces), version=m2.version))
    rep = bundle.inspect(write_zip(work / "herb_uv-off.zip", off))
    check("a UV outside the page is refused",
          any("outside their page" in m for m in bad_messages(rep)))

    # --- a bundle leaning on a stock shared texture -----------------------
    shared = dict(good)
    m3 = mod.parse(ball)
    mats = [mod.Material("wheels.tex", mt.vertex_start, mt.vertex_end,
                         mt.face_start, mt.face_end) for mt in m3.materials]
    shared["ball.mod"] = mod.build(mod.Mesh(vertices=list(m3.vertices), materials=mats,
                                            faces=list(m3.faces), version=m3.version))
    for k in [k for k in shared if k.lower().endswith(".tex")]:
        del shared[k]
    rep = bundle.inspect(write_zip(work / "herb_shared.zip", shared))
    check("a stock shared texture is allowed, not refused",
          rep.verdict == bundle.OK
          and any("stock shared texture" in f.message for f in rep.findings),
          "; ".join(bad_messages(rep)))

    # --- a bundle carrying a stock shared name -----------------------------
    clash = dict(good)
    clash["ucar.tex"] = next(v for k, v in good.items() if k.lower().endswith(".tex"))
    rep = bundle.inspect(write_zip(work / "herb_clash.zip", clash))
    warns = [f.message for f in rep.findings if f.level == bundle.WARN]
    check("a stock shared name is flagged, not refused",
          rep.verdict == bundle.WARN and any("every car in the race" in m for m in warns),
          f"verdict={rep.verdict} warns={len(warns)}")

    # --- the swap sweep ----------------------------------------------------
    keep = bundle.sweep_on_swap(src)
    check("swap sweep lists the part's own textures",
          sorted(keep) == sorted(n for n in tex_names if n in ents),
          f"{keep}")

    inst = src.parent
    stock = inst / "viper.car"
    if (inst / "race.res").is_file():
        tmp_car = work / "stockball.car"
        res = {e.name.lower(): e for e in archive.read(inst / "race.res")}
        base = archive.read(stock) if stock.is_file() else archive.read(src)
        base = archive.upsert_entry(base, "ball.mod",
                                    res["ball.mod"].to_standalone_bytes())
        archive.write(base, tmp_car)
        keep = bundle.sweep_on_swap(tmp_car)
        check("swap sweep never deletes a stock shared texture",
              "wheels.tex" not in keep, f"would delete {keep}")

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
