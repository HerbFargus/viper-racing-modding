"""Checks for the Backups folder.

The point of this change is tidiness, and tidiness is never worth a broken
restore. So most of what is checked here is that moving a backup did not cost
anything: an install that predates the folder must still restore, a migrated
one must still restore, and the two must agree about which file a backup
belongs to.

    python scripts/check_backups.py path/to/install
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import backups, cli, dekey, doctor  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("check_backups.py path/to/install")
    src = Path(sys.argv[1])
    cars = sorted(src.glob("*.car"))[:3]
    if not cars:
        raise SystemExit(f"no .car files under {src}")

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for c in cars:
            shutil.copy2(c, d / c.name)
        car = d / cars[0].name
        pristine = car.read_bytes()

        # ---- an edit backup lands in the folder, not beside the file --------
        b1 = cli._store_edit_backup(car)
        check("an edit backup goes into the folder",
              b1.parent.name == backups.DIR_NAME and b1.is_file(),
              f"{b1.parent.name}/{b1.name}")
        check("nothing is left loose in Data",
              not [p for p in d.iterdir() if p.is_file() and backups.is_archive_backup(p)],
              f"{len(list(d.iterdir()))} entries in Data, "
              f"{len(list(backups.folder(d).iterdir()))} in {backups.DIR_NAME}/")

        # The name still carries .bak even inside the folder. If anyone ever
        # moves these back by hand, that suffix is what stops the engine trying
        # to load "viper_original.car" and panicking for its missing members.
        check("the copy is still not a loadable game file",
              b1.suffix.lower() == ".bak", b1.name)

        # ---- the file it belongs to is still identifiable --------------------
        check("a foldered backup resolves to its original",
              backups.target_of(b1, d) == car,
              f"{b1.name} -> {backups.target_of(b1, d).name}")

        # ---- and a restore still works --------------------------------------
        car.write_bytes(b"ruined")
        found = cli.find_original_backup(car)
        check("find_original_backup sees into the folder",
              found is not None and found == b1,
              found.name if found else "nothing found")
        shutil.copy2(found, car)
        check("restoring from the folder returns the original bytes",
              car.read_bytes() == pristine, f"{len(pristine):,} bytes")

    # ---- an install from BEFORE the folder existed ---------------------------
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for c in cars:
            shutil.copy2(c, d / c.name)
        car = d / cars[0].name
        pristine = car.read_bytes()
        # the old layout: loose, beside the file
        legacy = car.with_name(f"{car.stem}_original{car.suffix}.bak")
        shutil.copy2(car, legacy)
        legacy_sweep = car.with_name(car.name + dekey.BACKUP_SUFFIX)
        shutil.copy2(car, legacy_sweep)
        car.write_bytes(b"ruined")

        found = cli.find_original_backup(car)
        check("a pre-folder install still restores",
              found is not None and found == legacy,
              found.name if found else "nothing found")
        check("find() sees loose backups too",
              len(backups.find(d)) == 2, f"{len(backups.find(d))} found")
        check("and dekey's revert finds its loose backup",
              [b.name for b in dekey.backups(d)] == [legacy_sweep.name],
              ", ".join(b.name for b in dekey.backups(d)) or "none")

        # ---- migration ------------------------------------------------------
        planned = backups.migrate(d, dry_run=True)
        check("a dry-run migration moves nothing",
              len(planned) == 2 and legacy.exists() and not backups.folder(d).exists(),
              f"{len(planned)} planned")
        moved = backups.migrate(d)
        check("migration files every loose archive backup",
              len(moved) == 2
              and not [p for p in d.iterdir()
                       if p.is_file() and backups.is_archive_backup(p)],
              f"{len(moved)} moved")
        after = cli.find_original_backup(car)
        check("and the restore path follows them",
              after is not None and after.parent.name == backups.DIR_NAME,
              after.name if after else "nothing found")
        shutil.copy2(after, car)
        check("the bytes survive the round trip",
              car.read_bytes() == pristine, f"{len(pristine):,} bytes")

        # ---- doctor --------------------------------------------------------
        # The finding that offers the migration must stop once there is nothing
        # loose, or it becomes a permanent nag with a button that does nothing.
        acts = [f.action for f in doctor.check(d).findings]
        check("doctor stops offering the move once it is done",
              "backups" not in acts,
              f"{len([a for a in acts if a])} actionable finding(s)")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
