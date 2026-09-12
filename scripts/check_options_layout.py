"""Checks for finding the options file, and for reading the video mode from it.

TWO BUGS THIS PINS DOWN, both found the same way -- a conclusion that fit the
one sample it was derived from.

1. THE LAYOUT. `Config\\` is a relative path, resolved against the working
   directory, which is wherever the executable you started lives. The two
   pressings put that in different places relative to the Data folder:

       v1.0   race.exe IS in the Data folder        -> Config is data_dir/Config
       v1.1   the launcher sits one level up        -> Config is data_dir.parent/Config

   The search used to look only at data_dir.parent, so on a v1.0 install it
   missed the live options.cfg entirely and fell through to options.def -- the
   SHIPPED DEFAULT. Doctor then told someone racing at 1920x1080 that they were
   at 640x480, and aifield read and wrote the wrong file.

2. THE NUMBERING. There is exactly one video key, `video_mode`, holding a MENU
   INDEX 1-4. An options file also carries a line reading `video mode N`, which
   was documented as a second key holding a label-table slot 0-3. It is not a
   key: load_options splits each line at the FIRST space, so it parses as an
   option named `video` with the string value "mode N", and nothing reads an
   option called `video`. The old regex `video[ _]mode` matched that junk line
   first, because it comes first in the file.

   The value 2 is why this went unnoticed: slot = 4 - index, so index 2 IS
   slot 2. Every sample anyone had read 2, the one value where both readings
   agree. The test below uses values that disagree.

Synthetic only -- no game files, no network.

    python scripts/check_options_layout.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import (aifield, doctor, resolution, switcher_ui,  # noqa: E402
                   writepaths)

PASS = FAIL = 0

# A minimal options file. The junk line comes FIRST, exactly as it does in
# MGI's own shipped options.def, so an unanchored regex hits it first.
def options(space_value: int, underscore_value: int | None) -> str:
    body = ["version 1", "[GX]", f"video mode {space_value}", "detail_level 1.000000"]
    if underscore_value is not None:
        body += ["[GAME]", f"video_mode {underscore_value}", "ai_car_count 7"]
    else:
        body += ["[GAME]", "ai_car_count 7"]
    return "\n".join(body) + "\n"


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def v10(root: Path, cfg: str | None, def_: str | None) -> Path:
    """A v1.0 install: the Data contents ARE the game root."""
    data = root / "v1.0-RC"
    (data / "Config").mkdir(parents=True)
    if cfg is not None:
        (data / "Config" / "options.cfg").write_text(cfg, encoding="utf-8")
    if def_ is not None:
        (data / "Config" / "options.def").write_text(def_, encoding="utf-8")
        (data / "options.def").write_text(def_, encoding="utf-8")
    return data


def v11(root: Path, cfg: str | None, def_: str | None) -> Path:
    """A v1.1 install: Data sits inside the game folder, Config beside it."""
    game = root / "Viper Racing"
    data = game / "Data"
    data.mkdir(parents=True)
    (game / "Config").mkdir()
    if cfg is not None:
        (game / "Config" / "options.cfg").write_text(cfg, encoding="utf-8")
    if def_ is not None:
        (data / "options.def").write_text(def_, encoding="utf-8")
    return data


def main() -> int:
    print("options file: layout\n")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        # --- the bug, exactly as it presented -----------------------------
        # Live cfg says index 4 (1920x1080); the shipped def still says 2.
        # Reading the def reports 640x480 to someone racing at 1920x1080.
        d = v10(tmp / "a", cfg=options(4, 4), def_=options(2, 2))
        f = writepaths.options_file(d)
        check("v1.0: finds Config/options.cfg beside the Data contents",
              f is not None and f.name == "options.cfg"
              and f.parent.parent == d, str(f.relative_to(tmp)) if f else "None")
        check("v1.0: prefers the live .cfg over the shipped .def",
              doctor.video_mode(d) == 4, f"video_mode {doctor.video_mode(d)}")

        # --- the other pressing still works -------------------------------
        d = v11(tmp / "b", cfg=options(4, 3), def_=options(2, 2))
        f = writepaths.options_file(d)
        check("v1.1: finds Config/options.cfg one level up",
              f is not None and f.name == "options.cfg"
              and f.parent.parent == d.parent, str(f.relative_to(tmp)) if f else "None")
        check("v1.1: reads it, not the .def beside Data",
              doctor.video_mode(d) == 3, f"video_mode {doctor.video_mode(d)}")

        # --- the trap that made data_dir.parent look right ----------------
        # Two installs side by side. A v1.0 install's .parent is just the folder
        # holding it, so a Config there belongs to a DIFFERENT copy of the game.
        root = tmp / "c"
        (root / "Config").mkdir(parents=True)
        (root / "Config" / "options.cfg").write_text(options(1, 1), encoding="utf-8")
        d = v10(root, cfg=options(4, 4), def_=None)
        check("v1.0: does NOT read a sibling install's Config",
              doctor.video_mode(d) == 4, f"video_mode {doctor.video_mode(d)}")

        # --- falling back is still allowed, just last ---------------------
        d = v10(tmp / "d", cfg=None, def_=options(2, 2))
        f = writepaths.options_file(d)
        check("with no .cfg at all it falls back to the shipped .def",
              f is not None and f.name == "options.def", f.name if f else "None")

        d = tmp / "e"
        d.mkdir()
        check("with no options file at all it reports None",
              writepaths.options_file(d) is None and doctor.video_mode(d) is None)

        # --- aifield shares the search ------------------------------------
        d = v10(tmp / "f", cfg=options(4, 4), def_=options(2, 2))
        check("aifield reads the same live file, not the .def",
              aifield.options_path(d) == writepaths.options_file(d),
              aifield.options_path(d).name)

        print("\noptions file: the video keys\n")

        # --- the junk line must be ignored --------------------------------
        # Values chosen to DISAGREE: the junk line says 1, the real key says 4.
        # The old `video[ _]mode` regex returned 1 here.
        d = v10(tmp / "g", cfg=options(1, 4), def_=None)
        check("ignores the junk `video mode` line and reads `video_mode`",
              doctor.video_mode(d) == 4, f"junk says 1, video_mode says 4 -> "
              f"{doctor.video_mode(d)}")

        # --- index -> slot -------------------------------------------------
        # slot = MODES - index, because the labels run in descending order.
        for index, slot in ((1, 3), (2, 2), (3, 1), (4, 0)):
            d = v10(tmp / f"h{index}", cfg=options(9, index), def_=None)
            check(f"menu index {index} is table slot {slot}",
                  doctor.video_slot(d) == slot, f"got {doctor.video_slot(d)}")

        check("index 2 is the one value where both readings agree -- which is "
              "why the wrong one survived", resolution.MODES - 2 == 2)

        # --- out of range --------------------------------------------------
        for bad in (0, 5, -1):
            d = v10(tmp / f"i{bad}", cfg=options(9, bad), def_=None)
            check(f"menu index {bad} is refused rather than indexed",
                  doctor.video_mode(d) == bad and doctor.video_slot(d) is None)

        # A slot 0-3 written into the real key is exactly what the old reading
        # would produce. 0 is out of range for a menu index, so it is caught.
        d = v10(tmp / "j", cfg=options(9, 0), def_=None)
        check("a slot-style 0 does not silently index the table",
              doctor.video_slot(d) is None)

        # --- missing key ----------------------------------------------------
        d = v10(tmp / "k", cfg=options(4, None), def_=None)
        check("a file with only the junk line reports no video mode",
              doctor.video_mode(d) is None)

    print("\nthe Config folder itself\n")

    # The paint the car viewer renders is a paintN.tex the game writes into
    # Config/, so the same layout rule applies -- and _paint_dir was still
    # looking only beside Data, which meant every v1.0 install silently got the
    # stand-in colour instead of the player's actual paint.
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        d = v10(tmp / "p10", cfg=options(4, 4), def_=None)
        (d / "Config" / "paint0.tex").write_bytes(b"\x00" * 32)
        check("v1.0: the paint dir resolves inside the Data contents",
              switcher_ui._paint_dir(d) == d / "Config",
              str(switcher_ui._paint_dir(d)))

        d = v11(tmp / "p11", cfg=options(4, 4), def_=None)
        (d.parent / "Config" / "paint0.tex").write_bytes(b"\x00" * 32)
        check("v1.1: the paint dir resolves beside Data",
              switcher_ui._paint_dir(d) == d.parent / "Config",
              str(switcher_ui._paint_dir(d)))

        # An empty Config must not win over the populated one: `containing`
        # is what separates "a Config exists" from "the paint is in it".
        d = v10(tmp / "pboth", cfg=options(4, 4), def_=None)
        (d.parent / "Config").mkdir(parents=True, exist_ok=True)
        (d / "Config" / "paint0.tex").write_bytes(b"\x00" * 32)
        check("an empty sibling Config does not shadow the populated one",
              switcher_ui._paint_dir(d) == d / "Config")

        d = v10(tmp / "pnone", cfg=options(4, 4), def_=None)
        check("no paint anywhere reports None, so the viewer falls back",
              switcher_ui._paint_dir(d) is None)

    print("\nthe CLI teaches the same numbering\n")

    # `--set` takes a menu index, but the listing beside it used to print bare
    # table positions 0-3, and the help text's own example was `--set 0`. So the
    # tool documented an index that set_mode rejects. Pin the example to a value
    # set_mode will actually accept.
    import re as _re
    import subprocess

    out = subprocess.run(
        [sys.executable, "-m", "vrmod.cli", "resolution", "--help"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True).stdout
    examples = [int(x) for x in _re.findall(r"--set (\d+)", out)]
    check("the --set help gives an example at all", bool(examples), str(examples))
    check("every index the --set help suggests is one set_mode accepts",
          all(1 <= e <= resolution.MODES and e != resolution.BOOT_GATE_INDEX
              for e in examples),
          f"suggests {examples}, valid is 1-{resolution.MODES} "
          f"except {resolution.BOOT_GATE_INDEX}")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
