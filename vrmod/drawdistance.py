"""How far the game draws, and how to push it past the slider.

`draw_distance` in `options.cfg` is not a distance. Tracing the setting through
`race.bin` -- the one code reference to the string loads it into a variable at
0x540344, and the transform right after is:

    fld   dword [draw_distance]
    fmul  dword [1700.0]
    fadd  dword [300.0]
    fstp  dword [draw_distance]

so what the renderer uses is

    effective = value * 1700 + 300

and the value itself is a **fraction**. `options.def` ships 0.5, which is 1,150
units; the in-game slider at full is 1.0, which is 2,000.

**There is no clamp.** The setting beside it, `detail_level`, is read the same way
and then floored at 0.5 (`cmp ... 0x3f000000; jge`); `draw_distance` gets no such
treatment, which is why writing a larger number simply works. The community's
"Infinity View Extender" exploits exactly this: it writes 100, i.e. 170,300
units, far past anything a track occupies.

That tool edited **line 92 of options.cfg by number**, which is why it has to be
run on an untouched file -- on an install whose layout differs it overwrites
whatever else is on that line. This reads and writes by key.

Note the game rewrites `options.cfg` when it exits, so change this with the game
closed or it will be overwritten.
"""
from __future__ import annotations

import re
from pathlib import Path

from .aifield import options_path

KEY = "draw_distance"

# From the transform in race.bin: effective = value * SCALE + BASE.
SCALE = 1700.0
BASE = 300.0

DEFAULT_VALUE = 0.5          # what options.def ships
SLIDER_MAX = 1.0             # the in-game slider at full
INFINITY_VALUE = 100.0       # what the community view extender writes

# The key, its separator, the number, then trailing blanks and an optional CR --
# `$` in MULTILINE matches before the LF, so a CRLF file leaves the CR to match
# here rather than being swallowed into the value.
_LINE = re.compile(rf"^({KEY}[ \t]+)([-\d.eE+]+)([ \t]*\r?)$", re.M)


class SettingError(RuntimeError):
    pass


def _read_raw(p: Path) -> str:
    """Read without translating line endings.

    `read_text` turns CRLF into LF, and writing that back rewrites every line in
    the file. The game's files are CRLF; `newline=""` keeps them that way so a
    write touches one value and nothing else.
    """
    return p.read_text("latin-1", errors="replace", newline="")


def effective(value: float) -> float:
    """Units the renderer actually uses for a stored `draw_distance`."""
    return value * SCALE + BASE


def value_for(units: float) -> float:
    """The stored value that yields `units` of draw distance."""
    if units < BASE:
        raise SettingError(
            f"{units:g} is below the floor: the transform adds {BASE:g}, so "
            f"nothing under that is reachable")
    return (units - BASE) / SCALE


def _options(data_dir: str | Path) -> Path:
    p = options_path(data_dir)
    if p is None:
        raise SettingError(
            "no options.cfg or options.def found -- run the game once so it "
            "writes one")
    return p


def read(data_dir: str | Path) -> tuple[float, Path]:
    """The stored value and the file it came from."""
    p = _options(data_dir)
    m = _LINE.search(_read_raw(p))
    if not m:
        raise SettingError(f"no {KEY} line in {p.name}")
    return float(m.group(2)), p


def write(data_dir: str | Path, value: float) -> tuple[float, Path]:
    """Set the stored value, leaving the rest of the file byte for byte.

    Rewrites the line matching KEY wherever it is -- not a line number, and not
    a whole-file reformat.
    """
    if value <= 0:
        raise SettingError(f"{KEY} must be positive, got {value:g}")
    p = _options(data_dir)
    text = _read_raw(p)
    if not _LINE.search(text):
        raise SettingError(f"no {KEY} line in {p.name}")
    new = _LINE.sub(lambda m: f"{m.group(1)}{value:.6f}{m.group(3)}", text, count=1)
    with p.open("w", encoding="latin-1", newline="") as fh:
        fh.write(new)
    return value, p
