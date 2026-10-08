"""Find the game's files whatever case their names are in.

WHY THIS EXISTS. Windows file names ignore case, so vrmod has always joined
paths like `data / "race.exe"` and found RACE.EXE just the same. Linux file
names don't: a Data folder copied off the CD can be all upper case (RACE.EXE,
VIPER.CAR, CONFIG/OPTIONS.CFG), and an exact-case join then finds nothing --
the folder reads as "not a Data folder", the engine as "not installed". The game
itself never cares (the Linux engine maps every path case-insensitively), so
vrmod mustn't either.

WHAT THIS DOES. `find(folder, "Config/options.cfg")` returns the existing path
that matches each part case-insensitively (the exact spelling first, so on
Windows, or a lower-case folder, it costs one stat), or None. `glob(folder,
"*.car")` lists the files whose names match the pattern case-insensitively,
sorted. `path(folder, name)` is `find` that falls back to the plain join, for
code that wants a path to write to even when the file isn't there yet.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path


def _child(folder: Path, name: str) -> Path | None:
    exact = folder / name
    if exact.exists():
        return exact
    low = name.lower()
    try:
        for entry in folder.iterdir():
            if entry.name.lower() == low:
                return entry
    except OSError:
        pass
    return None


def find(folder: str | Path, name: str) -> Path | None:
    """The existing file or folder `name` (one part, or several joined by / or \\) under `folder`, any case."""
    here = Path(folder)
    for part in name.replace("\\", "/").split("/"):
        if not part or part == ".":
            continue
        nxt = _child(here, part)
        if nxt is None:
            return None
        here = nxt
    return here


def path(folder: str | Path, name: str) -> Path:
    """`find`, or the plain join when nothing matches (a file about to be written)."""
    return find(folder, name) or Path(folder) / name.replace("\\", "/")


def exists(folder: str | Path, name: str) -> bool:
    return find(folder, name) is not None


def glob(folder: str | Path, pattern: str) -> list[Path]:
    """The entries of `folder` whose names match `pattern` (fnmatch, one level), any case, sorted by name."""
    folder = Path(folder)
    low = pattern.lower()
    try:
        return sorted((e for e in folder.iterdir() if fnmatch.fnmatchcase(e.name.lower(), low)),
                      key=lambda e: e.name.lower())
    except OSError:
        return []
