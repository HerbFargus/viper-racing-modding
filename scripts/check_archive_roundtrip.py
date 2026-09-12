"""Check vrmod.archive against every real .trk/.car/.res the game ships.

Three levels of proof, in order of strength:
  1. In-memory round-trip: read(archive) -> to_bytes(entries) == the original bytes.
  2. Filesystem round-trip: unpack(archive, tmp) -> pack(tmp, rebuilt) == the original
     bytes. Exercises the path a user actually takes, not just the in-memory one.
  3. Cross-check: unpack() output diffed against real rescrack.exe output, byte for
     byte. The strongest check, because it proves agreement with the 1998 tool rather
     than merely with ourselves. It needs reference folders generated once by hand and
     skips cleanly when they are absent.

Run:  python scripts/check_archive_roundtrip.py [Data-folder] [rescrack-ref-folder]
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive  # noqa: E402

DEFAULT_DATA = (Path.home() / "Desktop" / "claude-code" / "game-files"
                / "installs" / "v1.1-pristine" / "Data")
# Folders of rescrack.exe output, one per archive (see RESCRACK_REF). The tool itself
# is at reference-files/tools/community/rescrack.exe; these are its results, which have
# to be produced once by hand before the cross-check can run.
DEFAULT_RESCRACK_REF = (Path.home() / "Desktop" / "claude-code" / "reference-files"
                        / "tools" / "community" / "rescrack-output")

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
MOD_TOOLS = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_RESCRACK_REF

ARCHIVES = (
    [f"{t}.trk" for t in
     ["bemidji", "dundas", "hastings", "heaven", "kenyon", "limbo", "nfield", "uptown"]]
    + [f"{c}.car" for c in ["exotic", "plane", "sedan", "sports", "viper"]]
    + [f"{r}.res" for r in
       ["common", "drivers", "ui", "race", "postrace", "paintkit",
        "easy", "medium", "hard", "career1", "career2", "career3", "career4"]]
)

# rescrack reference folders available for cross-check, keyed by archive filename
RESCRACK_REF = {
    "bemidji.trk": "rescrack-trk-bemidji",
    "viper.car": "rescrack-car-viper",
    "drivers.res": "rescrack-res-drivers",
}


def main():
    print(f"Data folder: {DATA}\n")
    total = len(ARCHIVES)
    mem_pass = fs_pass = 0
    failures = []
    skipped = []

    for name in ARCHIVES:
        path = DATA / name
        if not path.exists():
            skipped.append(name)
            continue
        original = path.read_bytes()

        # 1. in-memory round-trip
        entries = archive.read(path)
        rebuilt = archive.to_bytes(entries)
        mem_ok = rebuilt == original
        mem_pass += mem_ok

        # 2. filesystem round-trip (exercises unpack()/pack() exactly as a user would)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive.unpack(path, tmp / "loose")
            out_path = tmp / name
            archive.pack(tmp / "loose", out_path)
            fs_ok = out_path.read_bytes() == original
        fs_pass += fs_ok

        status = "OK" if (mem_ok and fs_ok) else "FAIL"
        if not (mem_ok and fs_ok):
            failures.append((name, mem_ok, fs_ok))
        print(f"{name:16s} entries={len(entries):5d}  "
              f"mem={'OK' if mem_ok else 'FAIL':4s}  "
              f"fs={'OK' if fs_ok else 'FAIL':4s}  {status}")

    checked = total - len(skipped)
    print(f"\nin-memory round-trip: {mem_pass}/{checked} byte-exact")
    print(f"filesystem round-trip: {fs_pass}/{checked} byte-exact")
    if skipped:
        # Absent archives are not failures: ViperGT ships on no disc, and a v1.0 tree
        # has a different file set from a v1.1 one.
        print(f"not present in {DATA.name}, skipped: {', '.join(skipped)}")

    # 3. cross-check unpack() output against real rescrack.exe output
    print("\ncross-check vs. real rescrack.exe output:")
    for name, ref_folder in RESCRACK_REF.items():
        ref_dir = MOD_TOOLS / ref_folder
        if not ref_dir.exists():
            print(f"  {name}: reference folder {ref_dir} not found, skipping")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            our_names = archive.unpack(DATA / name, tmp)
            mismatches = 0
            checked_members = 0
            for member_name in our_names:
                ref_file = ref_dir / member_name
                if not ref_file.exists():
                    # rescrack didn't extract this one (e.g. drivers.res case-collisions)
                    continue
                checked_members += 1
                if (tmp / member_name).read_bytes() != ref_file.read_bytes():
                    mismatches += 1
            print(f"  {name}: {checked_members} members compared against "
                  f"{ref_folder}, {mismatches} mismatches")

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for name, mem_ok, fs_ok in failures:
            print(f"  {name}: mem={mem_ok} fs={fs_ok}")
        sys.exit(1)
    else:
        print("\nAll archives round-trip byte-exact.")


if __name__ == "__main__":
    main()
