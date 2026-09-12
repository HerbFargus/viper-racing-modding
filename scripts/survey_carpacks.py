"""Find out how much of the community corpus is actually usable.

The gallery plan -- standardise the packs, host them, catalogue them -- rests on
an assumption nobody has checked: that the mods in these ~2,000 archives still
load and render. This answers that before any of it is built on, because
discovering that a slice of the corpus is broken AFTER uploading 1.8 GB and
publishing a catalogue around it is the expensive order to find out.

It extracts each pack's own assets to a temp folder, runs the same vrmod
analysis the gallery builder runs, throws the extraction away, and reports. It
writes nothing into either repo and commits nothing: this is a measurement, not
a build.

WHAT COUNTS AS "ITS OWN". Retexture and add-on packs routinely ship the STOCK
car or track alongside their own work -- viper.car appears in 31 packs. Those
are not the pack's contribution, so they are excluded, and the stock names are
read from a real pristine install rather than hardcoded.

    python scripts/survey_carpacks.py [--manifest MANIFEST.json] [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, car, carpack, carshot, envelope  # noqa: E402
from vrmod import mod as mod_mod  # noqa: E402
from vrmod import track as track_mod, viewer  # noqa: E402

CC = Path.home() / "Desktop" / "claude-code"
DEFAULT_MANIFEST = CC / "viper-racing-community-cars" / "MANIFEST.json"
PRISTINE = CC / "game-files" / "installs" / "v1.0-RC"

# Used only if no pristine install is to hand.
FALLBACK_STOCK = {
    "viper.car", "exotic.car", "plane.car", "sedan.car", "sports.car",
    "bemidji.trk", "dundas.trk", "hastings.trk", "heaven.trk", "kenyon.trk",
    "limbo.trk", "nfield.trk", "uptown.trk",
}


def stock_names() -> tuple[set[str], str]:
    """The assets the game itself ships, so a pack is not credited with them."""
    if PRISTINE.is_dir():
        names = {p.name.lower() for p in PRISTINE.iterdir()
                 if p.suffix.lower() in (".car", ".trk")}
        if names:
            return names, f"read from {PRISTINE.name}"
    return set(FALLBACK_STOCK), "built-in fallback list"


def extract(pack: Path, names: list[str], dest: Path) -> list[Path]:
    """Pull just the named members out, flat. Returns what landed."""
    if pack.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(pack) as z:
            for n in names:
                (dest / Path(n).name).write_bytes(z.read(n))
    else:
        exe = carpack.sevenzip()
        subprocess.run([str(exe), "e", "-y", f"-o{dest}", str(pack)] + names,
                       capture_output=True, timeout=180)
    return sorted(p for p in dest.iterdir() if p.is_file())


def analyse_car(path: Path, render: bool) -> dict:
    entries = archive.read(path)
    prov = car.texture_provenance(path)
    mods = [e for e in entries if e.name.lower().endswith(".mod")]
    peak = 0
    for e in mods:
        try:
            peak = max(peak, len(mod_mod.parse(
                envelope.build(e.tag, e.version, e.payload)).vertices))
        except Exception:
            pass
    out = {"parts": len(mods), "peak_vertices": peak,
           "provenance": prov["verdict"], "missing": len(prov["missing"]),
           "cockpit": any(e.name.lower() == "cockpit.tab" for e in entries)}
    if render:
        carshot.to_png(path)
        out["rendered"] = True
    return out


def analyse_track(path: Path, render: bool) -> dict:
    mesh = viewer._track_render_mesh(path)
    try:
        miles = track_mod.length_miles(path)
    except Exception:
        miles = None
    out = {"vertices": len(mesh.vertices), "faces": len(mesh.faces),
           "miles": round(miles, 2) if miles else None}
    if render:
        carshot.track_to_png(path)
        out["rendered"] = True
    return out


def classify_assetless(item: dict) -> str:
    """What a pack that ships none of its own cars or tracks actually is."""
    sfx = collections.Counter(
        Path(m["name"]).suffix.lower() for m in item.get("members", ()))
    if any(item.get(k) for k in ("cars", "tracks")):
        return "stock assets only (a retexture or an add-on riding on them)"
    if sfx.get(".tex") or sfx.get(".bmp") or sfx.get(".tga"):
        return "loose textures"
    if sfx.get(".exe") or sfx.get(".dll"):
        return "a tool, not a mod"
    if sfx.get(".mod"):
        return "loose .mod meshes (parts, not a whole car)"
    if set(sfx) <= {".txt", ".jpg", ".jpeg", ".nfo", ".png", ".gif", ""}:
        return "documentation or screenshots only"
    return "something else: " + ", ".join(f"{k or '(none)'}x{v}"
                                          for k, v in sfx.most_common(4))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None,
                    help="write the per-asset results as JSON")
    ap.add_argument("--no-render", action="store_true",
                    help="skip thumbnail rendering (faster, but then the survey "
                         "cannot say whether a mod is actually VIEWABLE)")
    args = ap.parse_args()

    if not args.manifest.is_file():
        raise SystemExit(f"error: no manifest at {args.manifest} -- run "
                         f"scripts/index_carpacks.py first")
    manifest = carpack.load_manifest(args.manifest)
    items = manifest["items"][:args.limit] if args.limit else manifest["items"]
    stock, how = stock_names()
    render = not args.no_render

    print(f"surveying {len(items):,} packs from {args.manifest.name}")
    print(f"  stock assets excluded: {len(stock)} ({how})")
    print(f"  rendering thumbnails: {'yes' if render else 'NO -- viewability untested'}\n")

    roots = {t.split("\\")[-1].split("/")[-1]: Path(t) for t in manifest["trees"]}
    results, assetless = [], []
    started = time.time()

    for n, item in enumerate(items, 1):
        own = [a for a in (item.get("cars") or []) + (item.get("tracks") or [])
               if Path(a).name.lower() not in stock]
        if not own:
            assetless.append((item["path"], classify_assetless(item)))
        else:
            rel = item["path"]
            root = roots.get(rel.split("/")[0])
            pack = (root.parent / rel) if root else Path(rel)
            if not pack.is_file():
                results.append({"pack": rel, "asset": None,
                                "error": "pack not found on disk"})
            else:
                tmp = Path(tempfile.mkdtemp(prefix="survey_"))
                try:
                    got = extract(pack, own, tmp)
                    for f in got:
                        rec = {"pack": rel, "asset": f.name,
                               "kind": "car" if f.suffix.lower() == ".car" else "track",
                               "author": item.get("author")}
                        try:
                            fn = analyse_car if rec["kind"] == "car" else analyse_track
                            rec.update(fn(f, render))
                        except Exception as ex:
                            rec["error"] = f"{type(ex).__name__}: {ex}"[:160]
                        results.append(rec)
                except Exception as ex:
                    results.append({"pack": rel, "asset": None,
                                    "error": f"extract: {type(ex).__name__}: {ex}"[:160]})
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
        if n % 100 == 0 or n == len(items):
            print(f"  {n:>5}/{len(items)}  {n / max(time.time() - started, 1e-9):4.1f}/s  "
                  f"{sum(1 for r in results if r.get('error'))} failed")

    # ---- what the corpus turned out to be --------------------------------
    ok = [r for r in results if not r.get("error")]
    bad = [r for r in results if r.get("error")]
    cars = [r for r in ok if r["kind"] == "car"]
    tracks = [r for r in ok if r["kind"] == "track"]
    verdicts = collections.Counter(r.get("provenance") for r in cars)

    print(f"\n{'=' * 62}\n  ASSETS\n")
    print(f"  analysed            {len(results):>6,}")
    print(f"    loaded            {len(ok):>6,}  ({len(ok) * 100 // max(len(results), 1)}%)")
    print(f"    failed            {len(bad):>6,}")
    print(f"    cars              {len(cars):>6,}")
    print(f"    tracks            {len(tracks):>6,}")
    if render and ok:
        print(f"    rendered          {sum(1 for r in ok if r.get('rendered')):>6,}")

    if cars:
        print("\n  car texture provenance (does it ship what it references?):")
        for v, c in verdicts.most_common():
            print(f"    {c:>6,}  {v}")
        big = sorted(cars, key=lambda r: -r.get("peak_vertices", 0))[:5]
        print("\n  highest-poly cars:")
        for r in big:
            print(f"    {r['peak_vertices']:>7,} verts  {r['asset']:<18} "
                  f"{(r.get('author') or '-')[:24]}")

    if bad:
        kinds = collections.Counter(r["error"].split(":")[0] for r in bad)
        print("\n  failures by kind:")
        for k, c in kinds.most_common(8):
            print(f"    {c:>6,}  {k}")
        print("\n  first few:")
        for r in bad[:6]:
            print(f"    {r['pack']}: {r['error'][:80]}")

    print(f"\n{'=' * 62}\n  PACKS SHIPPING NONE OF THEIR OWN ({len(assetless):,})\n")
    for kind, c in collections.Counter(k for _, k in assetless).most_common(8):
        print(f"    {c:>6,}  {kind}")

    if args.out:
        args.out.write_text(json.dumps(
            {"results": results,
             "assetless": [{"pack": p, "kind": k} for p, k in assetless]},
            indent=1), encoding="utf-8")
        print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
