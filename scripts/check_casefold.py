"""Checks for vrmod/casefold.py: finding the game's files whatever case their names are in.

A Data folder copied off the CD onto Linux can be all upper case (RACE.EXE, VIPER.CAR,
CONFIG/OPTIONS.CFG). Linux file names are case-sensitive, so these build such a folder in a temp
directory and check every lookup still lands -- and that the Data-folder test and the options-file
search, which go through it, do too. Needs no game files. Runs the same on Windows (where the
lookups would have worked anyway) and on Linux (where they wouldn't have).

    python scripts/check_casefold.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import casefold, switcher, writepaths  # noqa: E402
from vrmod.switcher_ui import is_data_folder  # noqa: E402

PASS = FAIL = 0
same = None


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    global same
    sensitive = sys.platform != "win32" and sys.platform != "darwin"
    # On a case-insensitive file system find() returns the spelling asked for (the exact join
    # exists, so it costs one stat); the real spelling only comes back where case matters.
    same = (lambda a, b: a == b) if sensitive else (lambda a, b: a.lower() == b.lower())
    print(f"casefold -- on a {'case-sensitive' if sensitive else 'case-insensitive'} file system")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "DATA"
        (d / "CONFIG").mkdir(parents=True)
        (d / "RACE.EXE").write_bytes(b"MZ")
        (d / "VIPER.CAR").write_bytes(b"car")
        (d / "Bemidji.Car").write_bytes(b"car")
        (d / "NFIELD.TRA").write_bytes(b"tra")
        (d / "CONFIG" / "OPTIONS.CFG").write_text("video_mode 2\n", encoding="ascii")
        (d / "Disabled").mkdir()
        (d / "Disabled" / "OLD.CAR").write_bytes(b"car")
        (d / "Disabled" / "nested").mkdir()
        (d / "Disabled" / "nested" / "Deep.RES").write_bytes(b"res")
        (d / "UI.RES").write_bytes(b"res")

        # find: one part, any case; the real spelling comes back
        f = casefold.find(d, "race.exe")
        check("find: race.exe finds RACE.EXE", f is not None and same(f.name, "RACE.EXE"), str(f))
        check("find: an exact spelling still works", casefold.find(d, "RACE.EXE") is not None)
        check("find: a missing file is None", casefold.find(d, "race.bin") is None)
        f = casefold.find(d, "Config/options.cfg")
        check("find: nested Config/options.cfg finds CONFIG/OPTIONS.CFG",
              f is not None and f.is_file() and same(f.parts[-2], "CONFIG")
              and same(f.name, "OPTIONS.CFG"), str(f))
        check("find: a backslash-separated path works too",
              casefold.find(d, "config\\options.cfg") is not None)
        check("find: a missing file in an existing folder is None",
              casefold.find(d, "Config/options.def") is None)
        check("find: a missing folder is None", casefold.find(d, "Setups/x.csu") is None)
        check("find: a folder that doesn't exist at all is None",
              casefold.find(d / "nowhere", "race.exe") is None)

        # find_file: a folder of the same name doesn't count
        check("find_file: a file", casefold.find_file(d, "viper.car") is not None)
        check("find_file: a folder is not a file", casefold.find_file(d, "config") is None)

        # exists
        check("exists: any case", casefold.exists(d, "Ui.Res"))
        check("exists: missing", not casefold.exists(d, "drivers.res"))

        # path: the existing file when there is one, else the plain join for writing
        p = casefold.path(d, "viper.car")
        check("path: an existing file comes back in its own spelling", same(p.name, "VIPER.CAR"), p.name)
        p = casefold.path(d, "drivers.res")
        check("path: a missing file falls back to the plain (lower-case) join",
              p == d / "drivers.res", str(p))
        p = casefold.path(d, "Config/options.def")
        check("path: a missing file under an existing folder joins under the plain name",
              p == d / "Config" / "options.def", str(p))

        # glob: one level, any case, sorted by name
        cars = [q.name for q in casefold.glob(d, "*.car")]
        check("glob: *.car finds VIPER.CAR and Bemidji.Car, sorted",
              cars == ["Bemidji.Car", "VIPER.CAR"], ", ".join(cars))
        check("glob: one level only (Disabled/OLD.CAR not included)", "OLD.CAR" not in cars)
        check("glob: no match is an empty list", casefold.glob(d, "*.trk") == [])
        check("glob: a missing folder is an empty list", casefold.glob(d / "nowhere", "*") == [])
        check("glob: a pattern with a fixed prefix", [q.name for q in casefold.glob(d, "nfield.*")]
              == ["NFIELD.TRA"])

        # rglob: every level
        res = [q.relative_to(d).as_posix() for q in casefold.rglob(d, "*.res")]
        check("rglob: *.res finds UI.RES and Disabled/nested/Deep.RES",
              res == ["Disabled/nested/Deep.RES", "UI.RES"], ", ".join(res))
        allcars = [q.name for q in casefold.rglob(d, "*.CAR")]
        check("rglob: an upper-case pattern matches lower and mixed names",
              sorted(allcars) == ["Bemidji.Car", "OLD.CAR", "VIPER.CAR"], ", ".join(allcars))
        check("rglob: a missing folder is an empty list", casefold.rglob(d / "nowhere", "*") == [])

        # the callers
        check("is_data_folder: an upper-case Data folder (only *.CAR) counts", is_data_folder(d))
        rb = Path(tmp) / "RBONLY"
        rb.mkdir()
        (rb / "RACE.BIN").write_bytes(b"MZ")
        check("is_data_folder: a folder with only RACE.BIN counts", is_data_folder(rb))
        empty = Path(tmp) / "EMPTY"
        empty.mkdir()
        check("is_data_folder: an empty folder doesn't", not is_data_folder(empty))
        opt = writepaths.options_file(d)
        check("writepaths.options_file: finds CONFIG/OPTIONS.CFG",
              opt is not None and same(opt.name, "OPTIONS.CFG"), str(opt))
        names = [p.name for p, on in switcher.car_paths(d) if on]
        check("switcher.car_paths: both upper-case cars are active",
              sorted(names) == ["Bemidji.Car", "VIPER.CAR"], ", ".join(names))
        check("switcher.available_tracks: NFIELD.TRA",
              [t.name for t in switcher.available_tracks(d)] == ["NFIELD.TRA"])

        # moving a car keeps its own spelling (no VIPER.car beside VIPER.CAR)
        moved = switcher.set_car_active(d, "VIPER.CAR", False)
        check("set_car_active: VIPER.CAR keeps its name in Disabled/", moved == "VIPER.CAR", moved)
        back = switcher.set_car_active(d, "VIPER.CAR", True)
        check("set_car_active: and back", back == "VIPER.CAR" and (d / "VIPER.CAR").is_file(), back)

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
