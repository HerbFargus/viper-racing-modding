"""Checks for finding a rebuild baseline among the backups we already made.

THE SITUATION. An install patched a tool at a time -- rather than through
patchset.apply() -- never gets a `.vrmod-original`, so the first apply() tries to
snapshot whatever is on disk and correctly refuses: freezing a patched binary as
"pristine" means every later rebuild and every revert keeps those patches.

The old message then said "restore an original first", while an untouched copy
was usually sitting in the same folder -- every patch in this toolkit drops a
`<engine>.<name>-backup` before it writes, so the one taken before the FIRST
patch IS the original. This asserts the tool now finds and names it.

RANKING MATTERS. looks_pristine() ignores the VRAM fix by design, because the
community v1.2.5 build ships with it and is a fine baseline. So a backup taken
after four other patches passes looks_pristine() exactly as the original does,
and picking the first match can nominate a file that is not untouched at all.
A known sha256 wins outright; otherwise the least-patched copy wins and the
message says plainly how patched it still is.

Needs a real engine binary, so it takes a Data folder:

    python scripts/check_baseline_recovery.py [path/to/Data]
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import doctor, patchset, writepaths  # noqa: E402

DEFAULT = (Path.home() / "Desktop" / "claude-code" / "game-files"
           / "installs" / "v1.0-RC")

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def stamp(p: Path, age: int) -> None:
    """Backdate a file, so 'oldest first' is testable without waiting."""
    t = time.time() - age
    os.utime(p, (t, t))


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    pristine = src / "race.exe.vrmod-original"
    engine = src / "race.exe"
    if not pristine.is_file() or not engine.is_file():
        print(f"  needs a v1.0 Data folder with a race.exe and a snapshot: {src}")
        return 1
    print(f"source: {src}\n")

    clean = pristine.read_bytes()
    patched = engine.read_bytes()
    check("the fixture is usable: the snapshot and the live file differ",
          clean != patched)

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        # --- a known hash wins outright -------------------------------------
        d = tmp / "hash"
        d.mkdir()
        (d / "race.exe").write_bytes(patched)
        (d / "race.exe.vram-backup").write_bytes(clean)
        stamp(d / "race.exe.vram-backup", 10)
        found = patchset.find_pristine_backup(d)
        check("finds the untouched copy among the backups",
              found is not None and found[0].name == "race.exe.vram-backup",
              found[0].name if found else "None")
        check("and says it is verified by hash, not merely unpatched",
              found is not None and "byte-identical" in found[1],
              found[1] if found else "")
        check("the retail race.exe hash is actually in the table",
              hashlib.sha256(clean).hexdigest() in patchset.STOCK_ENGINES)

        # --- ranking: a hash match beats an older, partly-patched copy -------
        # The half-patched file is OLDER, so 'oldest first' alone would pick it.
        d = tmp / "rank"
        d.mkdir()
        (d / "race.exe").write_bytes(patched)
        (d / "race.exe.vram-backup").write_bytes(clean)
        half = tmp / "half"
        half.mkdir()
        (half / "race.exe").write_bytes(clean)
        writepaths.apply(half, writepaths.LOGS_KIND)
        (d / "race.exe.early-backup").write_bytes((half / "race.exe").read_bytes())
        stamp(d / "race.exe.early-backup", 9999)
        stamp(d / "race.exe.vram-backup", 10)
        found = patchset.find_pristine_backup(d)
        check("a verified hash beats an older but already-patched copy",
              found is not None and found[0].name == "race.exe.vram-backup",
              found[0].name if found else "None")

        # --- no hash match: least-patched wins, and says so -----------------
        d = tmp / "heur"
        d.mkdir()
        (d / "race.exe").write_bytes(patched)
        (d / "race.exe.early-backup").write_bytes((half / "race.exe").read_bytes())
        found = patchset.find_pristine_backup(d)
        check("falls back to the least-patched copy when no hash matches",
              found is not None and found[0].name == "race.exe.early-backup",
              found[0].name if found else "None")
        check("...and admits it is not actually untouched",
              found is not None and "already carries" in found[1],
              found[1] if found else "")

        # --- nothing to offer -----------------------------------------------
        d = tmp / "none"
        d.mkdir()
        (d / "race.exe").write_bytes(patched)
        check("reports None when there is no candidate at all",
              patchset.find_pristine_backup(d) is None)

        # --- a wrong-sized file is not a candidate --------------------------
        d = tmp / "size"
        d.mkdir()
        (d / "race.exe").write_bytes(patched)
        (d / "race.exe.truncated-backup").write_bytes(clean[:1024])
        check("a truncated backup is rejected on size before it is parsed",
              patchset.find_pristine_backup(d) is None)

        # --- the error message actually carries the name --------------------
        d = tmp / "msg"
        d.mkdir()
        (d / "race.exe").write_bytes(patched)
        (d / "race.exe.vram-backup").write_bytes(clean)
        try:
            patchset.apply(d)
            check("apply still refuses a patched baseline", False)
        except patchset.PatchSetError as e:
            msg = str(e)
            check("apply still refuses a patched baseline", True)
            check("the refusal names the file to restore",
                  "race.exe.vram-backup" in msg)
            check("the refusal gives a runnable command", 'copy "' in msg)
            check("the refusal still explains what force=True costs",
                  "force=True" in msg and "every revert" in msg)

        # --- and the real install is never modified by the search -----------
        before = {p.name: p.stat().st_mtime for p in d.iterdir()}
        patchset.find_pristine_backup(d)
        after = {p.name: p.stat().st_mtime for p in d.iterdir()}
        check("searching does not touch any file in the folder", before == after,
              f"{len(before)} files")

        # --- restoring it makes apply work ----------------------------------
        shutil.copy2(d / "race.exe.vram-backup", d / "race.exe")
        rep = patchset.apply(d, mode=(1920, 1080))
        check("after restoring, apply takes the snapshot and runs",
              (d / "race.exe.vrmod-original").is_file(), rep.baseline)
        check("and the snapshot is the untouched file, not the patched one",
              (d / "race.exe.vrmod-original").read_bytes() == clean)

        # --- doctor says the same thing -------------------------------------
        d = tmp / "doc"
        (d / "Config").mkdir(parents=True)
        (d / "race.exe").write_bytes(patched)
        (d / "race.exe.vram-backup").write_bytes(clean)
        titles = {f.title: f for f in doctor.check(d).findings}
        ps = next((f for t, f in titles.items() if t.startswith("Patch set")), None)
        check("doctor reports the patch set", ps is not None,
              ps.title if ps else "missing")
        if ps:
            check("doctor names the same recovery file",
                  "race.exe.vram-backup" in (ps.detail or "")
                  and "race.exe.vram-backup" in (ps.fix or ""))

    # --- the one table, not two ---------------------------------------------
    check("doctor's race.bin hashes come from patchset's table",
          doctor.STOCK_RACE_BIN == {h: e for h, (n, e)
                                    in patchset.STOCK_ENGINES.items()
                                    if n == "race.bin"},
          f"{len(doctor.STOCK_RACE_BIN)} race.bin hashes")
    check("doctor's stock mode table is patchset's",
          doctor.STOCK_MODES is patchset.STOCK_MODES)

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
