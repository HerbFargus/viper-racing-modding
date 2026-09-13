"""Produce a standardised .zip distribution copy of every pack.

WHY. 1,718 of the 2,033 packs are .rar, which Windows cannot open without extra
software and which no Python standard library can read. For anything
distribution-facing -- a download button, an archive.org item -- .zip is simply
kinder.

WHY NOT IN PLACE. Repacking changes the bytes, and the original archive plus its
sha256 is the record of what the author actually uploaded. That record is the
part this project cannot regenerate, so it is never overwritten: the zips go to
a separate tree and the sources are left exactly as they are. A .zip source is
copied rather than re-zipped, for the same reason -- no needless byte churn on a
file that is already in the target format.

LOSSLESS, AND CHECKED. Every repack is verified member-for-member by sha256
against the source before it counts as done. A repacker that silently drops a
file would be worse than no repacker, and this corpus has already produced two
silent-loss bugs (a flattened extraction, a partial cache reuse) -- neither of
which announced itself.

Writes MAPPING.json beside the output: source path and sha256 -> distribution
path and sha256, so the catalogue can offer the zip for download while still
naming the original as provenance.

    python scripts/repack_zip.py <tree>... -o <dist-dir> [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import carpack  # noqa: E402

PACK_SUFFIXES = (".rar", ".zip")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def members_of(pack: Path) -> dict[str, str]:
    """{member path -> sha256 of its bytes}, the thing repacking must preserve."""
    out: dict[str, str] = {}
    if pack.suffix.lower() == ".zip":
        with zipfile.ZipFile(pack) as z:
            for i in z.infolist():
                if not i.is_dir():
                    out[i.filename.replace("\\", "/")] = sha256(z.read(i))
        return out
    exe = carpack.sevenzip()
    if exe is None:
        raise RuntimeError("no 7-Zip, so .rar packs cannot be read")
    tmp = Path(tempfile.mkdtemp(prefix="repack_read_"))
    try:
        subprocess.run([str(exe), "x", "-y", f"-o{tmp}", str(pack)],
                       capture_output=True, timeout=300)
        for p in sorted(tmp.rglob("*")):
            if p.is_file():
                out[p.relative_to(tmp).as_posix()] = sha256(p.read_bytes())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def repack(pack: Path, dest: Path) -> tuple[str, dict]:
    """Write dest as a .zip holding exactly what `pack` holds. Returns (how, info).

    `how` is "copied" for a source already in the target format, "repacked"
    otherwise -- worth distinguishing, because a copy is byte-identical to the
    original and a repack is not.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_members = members_of(pack)

    if pack.suffix.lower() == ".zip":
        shutil.copy2(pack, dest)
        how = "copied"
    else:
        exe = carpack.sevenzip()
        tmp = Path(tempfile.mkdtemp(prefix="repack_"))
        try:
            subprocess.run([str(exe), "x", "-y", f"-o{tmp}", str(pack)],
                           capture_output=True, timeout=300)
            files = sorted(p for p in tmp.rglob("*") if p.is_file())
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for f in files:
                    z.write(f, f.relative_to(tmp).as_posix())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        how = "repacked"

    # The verification is the point of the exercise, not a formality.
    got = members_of(dest)
    if got != src_members:
        missing = sorted(set(src_members) - set(got))
        changed = sorted(k for k in set(got) & set(src_members)
                         if got[k] != src_members[k])
        dest.unlink(missing_ok=True)
        raise ValueError(
            f"repack is not lossless: {len(missing)} member(s) missing "
            f"{missing[:3]}, {len(changed)} changed {changed[:3]}")
    return how, {"members": len(src_members),
                 "sha256": sha256(dest.read_bytes())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trees", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True,
                    help="where the .zip distribution tree goes. NOT one of the "
                         "source trees: the originals are the archival record "
                         "and are never overwritten")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    trees = [Path(t) for t in args.trees]
    for t in trees:
        if not t.is_dir():
            raise SystemExit(f"error: no such folder: {t}")
        # Is `out` INSIDE the tree, i.e. is the tree one of out's ancestors?
        # The first version of this asked the opposite -- whether out was a
        # PARENT of the tree -- which is never true for a subdirectory, so the
        # guard passed and 2.6 GB of zips landed in the source tree it exists
        # to protect.
        if args.out.resolve() == t.resolve() or t.resolve() in args.out.resolve().parents:
            raise SystemExit(
                f"error: --out {args.out} is inside a source tree. The originals "
                f"are the record of what the community actually shipped; write "
                f"the zips somewhere else.")

    packs = []
    for t in trees:
        packs += [(t, p) for p in sorted(t.rglob("*"))
                  if p.is_file() and p.suffix.lower() in PACK_SUFFIXES]
    if args.limit:
        packs = packs[:args.limit]

    print(f"repacking {len(packs):,} packs -> {args.out}")
    print(f"  7-Zip: {carpack.sevenzip()}\n")

    # Work out every destination BEFORE writing anything. Replacing the
    # extension collides whenever one folder holds both foo.rar and foo.zip --
    # valscars holds exactly that -- and the loser is silently overwritten by
    # the winner, AFTER passing its own verification. Two packs vanished that
    # way while the run reported "0 failed". Colliders keep their original
    # extension in the name (jet.rar -> jet.rar.zip) so the mapping stays
    # one-to-one and does not depend on scan order.
    dests: dict[int, Path] = {}
    claimed: dict[Path, int] = {}
    for idx, (tree, p) in enumerate(packs):
        rel = Path(tree.name) / p.relative_to(tree)
        plain = args.out / rel.with_suffix(".zip")
        if plain in claimed:
            other = claimed.pop(plain)
            ot, op = packs[other]
            dests[other] = args.out / Path(ot.name) / (
                op.relative_to(ot).parent / (op.name + ".zip"))
            dests[idx] = args.out / rel.parent / (p.name + ".zip")
        else:
            claimed[plain] = idx
            dests[idx] = plain

    mapping, failed = {}, []
    counts = {"copied": 0, "repacked": 0}
    started = time.time()
    for i, (tree, p) in enumerate(packs, 1):
        rel = Path(tree.name) / p.relative_to(tree)
        dest = dests[i - 1]
        try:
            how, info = repack(p, dest)
            counts[how] += 1
            mapping[rel.as_posix()] = {
                "source_sha256": sha256(p.read_bytes()),
                "dist": dest.relative_to(args.out).as_posix(),
                "dist_sha256": info["sha256"],
                "members": info["members"], "how": how,
            }
        except Exception as ex:
            failed.append((rel.as_posix(), f"{type(ex).__name__}: {ex}"))
        if i % 100 == 0 or i == len(packs):
            print(f"  {i:>5}/{len(packs)}  {i / max(time.time() - started, 1e-9):4.1f}/s  "
                  f"{len(failed)} failed")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "MAPPING.json").write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "Distribution copies. The SOURCE archives remain the record of "
                "what each author uploaded; source_sha256 identifies them.",
        "packs": mapping,
    }, indent=1), encoding="utf-8")

    # One file out per pack in, or something was overwritten. This is the
    # check that would have caught the collision above; per-pack verification
    # cannot, because each file is correct at the moment it is written.
    written = sum(1 for _ in args.out.rglob("*.zip"))
    expected = len(packs) - len(failed)
    if written != expected:
        print(f"\n  ERROR: {expected:,} packs should have produced {expected:,} "
              f"zips, but {written:,} are on disk -- destinations collided and "
              f"overwrote each other.")
        failed.append(("<destination collision>", f"{expected - written} lost"))

    total = sum(f.stat().st_size for f in args.out.rglob("*.zip"))
    print(f"\n  copied (already zip) {counts['copied']:>5,}")
    print(f"  repacked from rar    {counts['repacked']:>5,}")
    print(f"  failed               {len(failed):>5,}")
    print(f"  distribution size    {total / 1024 / 1024:>5,.0f} MB")
    print(f"  wrote {args.out / 'MAPPING.json'}")
    for name, err in failed[:10]:
        print(f"    FAILED {name}: {err[:100]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
