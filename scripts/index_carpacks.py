"""Build the catalogue of community car packs.

Walks a tree of .rar/.zip packs, reads each one in place, and writes a manifest
describing all of them. Nothing is extracted, repacked or modified -- the
original archive and its sha256 remain the record of what the author uploaded.

THE MANIFEST IS THE POINT. Whatever happens to the hosting -- archive.org, a
mirror, somebody's Drive -- the catalogue is what survives, and it is what the
gallery renders. That is the lesson of this scene's first disappearance: the
files were replaceable, the knowledge of what they were was not. So the manifest
records hash, size, contents, author, title and provenance, and stays useful
even when every download link in it has rotted.

    python scripts/index_carpacks.py <tree> [-o manifest.json]

Duplicate detection is by sha256 across the whole tree, so a pack that appears
in two collections is reported once with both paths.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import carpack  # noqa: E402

DEFAULT_TREE = Path.home() / "Desktop" / "claude-code" / "viper-racing-community-cars"
PACK_SUFFIXES = (".rar", ".zip")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trees", nargs="*", type=Path, default=None,
                    help="folders of packs. Several may be given -- the cars, the "
                         "tracks and the VRgt backups live in different trees, and "
                         "one catalogue over all of them is the useful thing")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="where to write the manifest (default: <tree>/MANIFEST.json)")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N packs, for a quick look")
    ap.add_argument("--keep-domains", default="",
                    help="comma-separated email domains NOT to redact, for "
                         "company addresses where the address is provenance")
    args = ap.parse_args()

    trees = [Path(t) for t in (args.trees or [DEFAULT_TREE])]
    for t in trees:
        if not t.is_dir():
            raise SystemExit(f"error: no such folder: {t}")
    out = args.out or trees[0] / "MANIFEST.json"
    keep = tuple(d.strip().lower() for d in args.keep_domains.split(",") if d.strip())

    # (tree, pack) pairs, so each item can record which tree it came from.
    packs = []
    for t in trees:
        packs += [(t, p) for p in sorted(t.rglob("*"))
                  if p.is_file() and p.suffix.lower() in PACK_SUFFIXES]
    if args.limit:
        packs = packs[:args.limit]
    if not packs:
        raise SystemExit("error: no .rar or .zip packs under "
                         + ", ".join(str(t) for t in trees))

    if any(p.suffix.lower() == ".rar" for _, p in packs) and carpack.sevenzip() is None:
        raise SystemExit(
            "error: this tree contains .rar packs and no 7-Zip was found, so most "
            f"of it would be unreadable. Install 7-Zip or set "
            f"{carpack.SEVENZIP_ENV}.")

    print(f"indexing {len(packs):,} packs under "
          + ", ".join(t.name for t in trees))
    print(f"  7-Zip: {carpack.sevenzip()}")
    if keep:
        print(f"  keeping email domains: {', '.join(keep)}")
    print()

    started = time.time()
    records, errors = [], 0
    multi = len(trees) > 1
    for i, (tree, p) in enumerate(packs, 1):
        rel = p.relative_to(tree)
        # The collection is the folder the community filed it under; the tree
        # name prefixes it when several trees are indexed at once, so
        # "valscars" and "VRGT_Backups/cars" stay distinguishable.
        sub = rel.parts[0] if len(rel.parts) > 1 else ""
        coll = f"{tree.name}/{sub}" if multi and sub else (sub or tree.name)
        info = carpack.describe(p, collection=coll, keep_domains=keep)
        info.path = ((tree.name + "/") if multi else "") + str(rel).replace("\\", "/")
        records.append(info)
        if info.error:
            errors += 1
        if i % 100 == 0 or i == len(packs):
            rate = i / max(time.time() - started, 1e-6)
            print(f"  {i:>5}/{len(packs)}  {rate:5.1f}/s  {errors} unreadable")

    by_hash: dict[str, list[str]] = collections.defaultdict(list)
    for r in records:
        by_hash[r.sha256].append(r.path)
    dupes = {h: paths for h, paths in by_hash.items() if len(paths) > 1}

    manifest = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "trees": [str(t) for t in trees],
        "packs": len(records),
        "distinct_by_sha256": len(by_hash),
        "note": "Hashes are of the ORIGINAL archives as distributed. Emails in "
                "readme text are redacted here; the packs themselves are "
                "unmodified.",
        "items": [r.to_json() for r in records],
        "duplicates": dupes,
    }
    out.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    # ---- what the tree actually turned out to contain --------------------
    ok = [r for r in records if not r.error]
    authors = collections.Counter(r.author for r in ok if r.author)
    sources = collections.Counter(r.converted_from for r in ok if r.converted_from)
    kinds = collections.Counter(r.kind for r in records)
    ncars = sum(len(r.cars) for r in ok)
    ntracks = sum(len(r.tracks) for r in ok)
    colls = collections.Counter(r.collection for r in records)

    def pct(n: int) -> str:
        return f"{n:>5,}  ({n * 100 // max(len(records), 1):>3}%)"

    print(f"\nwrote {out}  ({out.stat().st_size:,} bytes)\n")
    print(f"  packs                {len(records):>5,}   "
          f"{dict(kinds)}")
    print(f"  distinct by sha256   {len(by_hash):>5,}   "
          f"{len(records) - len(by_hash):,} duplicate file(s)")
    print(f"  unreadable           {errors:>5,}")
    print(f"  .car files inside    {ncars:>5,}")
    print(f"  .trk files inside    {ntracks:>5,}")
    print(f"  with a readme        {pct(sum(1 for r in ok if r.readme))}")
    print(f"  with an author       {pct(sum(1 for r in ok if r.author))}")
    print(f"  with a title         {pct(sum(1 for r in ok if r.title))}")
    print(f"  with a date          {pct(sum(1 for r in ok if r.dated))}")
    print(f"  emails redacted      {sum(r.emails_redacted for r in ok):>5,}")

    print("\n  by collection:")
    for name, n in colls.most_common():
        print(f"    {n:>5,}  {name}")
    if authors:
        print("\n  most-credited authors:")
        for name, n in authors.most_common(8):
            print(f"    {n:>5,}  {name[:64]}")
    if sources:
        print("\n  converted from:")
        for name, n in sources.most_common(8):
            print(f"    {n:>5,}  {name[:64]}")
    if errors:
        print("\n  unreadable packs:")
        for r in records:
            if r.error:
                print(f"    {r.path}: {r.error[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
