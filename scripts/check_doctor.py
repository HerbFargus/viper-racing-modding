"""Checks for the install doctor.

Runs against synthetic installs built in a temp directory, so it needs no game
files and no network. Point it at a real Data folder as an optional argument to
additionally report what that install looks like.

    python scripts/check_doctor.py [path/to/Data]
"""
from __future__ import annotations


import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, doctor, switcher  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def fake_install(root: Path, *, ilg_lines: int, modded: bool) -> Path:
    """A Data folder with just enough in it for the drivers.res check."""
    data = root / "Data"
    data.mkdir(parents=True, exist_ok=True)

    # drivers.res carrying `ilg_lines` baked AI lines
    entries = []
    for i in range(ilg_lines):
        entries.append(archive.ArchiveEntry(
            name=f"{i:03d}vipr.ilg", tag=b"NILI", version=3,
            payload=b"\x00" * 16))
    (data / "drivers.res").write_bytes(archive.to_bytes(entries))

    # every slot either stock-looking or not; an empty archive is never stock
    for slot in switcher.STOCK_TRACKS:
        (data / f"{slot}.trk").write_bytes(archive.to_bytes([]) if modded else b"")
    return data


def titles(data: Path) -> list[str]:
    return [f.title for f in doctor.check(data).findings]


def levels(data: Path, needle: str) -> list[str]:
    return [f.level for f in doctor.check(data).findings if needle in f.title]


def main() -> int:
    print("install doctor -- drivers.res")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # Counting .ilg members, not bytes: the .dnt driver tunings alongside
        # them are harmless, and it is the baked LINES that misdirect the AI.
        data = fake_install(tmp / "a", ilg_lines=524, modded=True)
        check("counts the baked AI lines",
              doctor.drivers_res_lines(data) == 524, "524 .ilg members")

        # The fault only exists once a slot holds something other than the
        # stock track, so an all-stock install must not be nagged.
        check("warns when add-ons are installed and lines are baked",
              levels(data, "AI will drive the wrong line") == [doctor.WARN],
              "warn")

        # An all-stock install must NOT be nagged: the baked lines are correct
        # for it. A slot only reads as stock if it hashes to the shipped track,
        # which cannot be synthesised, so this patches that one boundary --
        # what is under test is doctor's gating, not switcher's hashing.
        stock = fake_install(tmp / "b", ilg_lines=524, modded=False)
        real_status = switcher.status
        switcher.status = lambda d: [  # type: ignore[assignment]
            switcher.SlotStatus(slot=s.slot, display_name=s.display_name,
                                present=True, is_stock=True, size=s.size)
            for s in real_status(d)]
        try:
            check("stays quiet on an all-stock install",
                  not levels(stock, "AI will drive the wrong line")
                  and any("baked AI lines" in t for t in titles(stock)),
                  "reports it as ok, not a problem")
        finally:
            switcher.status = real_status  # type: ignore[assignment]

        empty = fake_install(tmp / "c", ilg_lines=0, modded=True)
        check("reports an empty drivers.res as correct for add-ons",
              levels(empty, "drivers.res is empty") == [doctor.OK], "ok")

        missing = fake_install(tmp / "d", ilg_lines=0, modded=True)
        (missing / "drivers.res").unlink()
        check("notices drivers.res missing entirely",
              doctor.drivers_res_lines(missing) is None
              and levels(missing, "drivers.res is missing") == [doctor.WARN], "warn")

        # The repair must be exactly the file the community circulated, and it
        # must be reversible -- this writes into a game folder.
        fixme = fake_install(tmp / "e", ilg_lines=524, modded=True)
        original = (fixme / "drivers.res").read_bytes()
        written, backup = doctor.empty_drivers_res(fixme)
        check("the repair writes the community fix byte-for-byte",
              written.read_bytes() == archive.to_bytes([]),
              f"{written.stat().st_size} bytes")
        check("the repair backs the original up first",
              backup is not None and backup.read_bytes() == original,
              backup.name if backup else "no backup")
        check("the warning clears afterwards",
              not levels(fixme, "AI will drive the wrong line"), "resolved")

        _, second = doctor.empty_drivers_res(fixme)
        check("a second repair does not clobber the first backup",
              second != backup and backup.read_bytes() == original,
              second.name if second else "none")

    if len(sys.argv) > 1:
        live = Path(sys.argv[1])
        print(f"\nagainst {live}")
        n = doctor.drivers_res_lines(live)
        print(f"  drivers.res: {'absent' if n is None else f'{n} baked AI lines'}")
        for f in doctor.check(live).findings:
            if "drivers.res" in f.title or "AI will drive" in f.title:
                print(f"  [{f.level}] {f.title}")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
