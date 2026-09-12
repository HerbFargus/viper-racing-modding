"""Set the number of AI opponents in a race (the field size).

WHY A TOOL. The in-game opponent selector hard-clamps to 7 and, once you touch it,
overwrites the count back to 7 on save -- so the only way to run a bigger field is
to write the persistent config value directly and then NOT touch the selector.

THE HARD CAP is 16 total cars = 15 AI + the player. Confirmed in game: 15 AI races
fine (16/16 grid), 16 AI panics immediately with

    Panic : AIGetCarForDriver: No car for driver 16

because the driver/car pool is 16 slots (indices 0-15) and the player is driver 0,
so AI are drivers 1..15. Asking for driver 16 has no car and the game aborts. This
tool therefore refuses anything above 15 AI -- raising it further would mean
expanding the driver pool in race.bin, which is out of scope.

The three persistent keys live in the game's live `Config/options.cfg` (what the
game reads and rewrites at runtime; `options.def` is only the shipped default):

    ai_car_count <n>     the AI opponent count  (the field reads THIS one)
    ai_cars      <n>     duplicate the game also keeps
    car_count    <n+1>   total cars = AI + the player

Note the game rewrites options.cfg on exit, and the opponent selector clamps to 7,
so a set made here survives only until the selector is touched in-game.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import writepaths

MAX_AI = 15                 # 15 AI + player = 16 total; 16 AI hits the driver-16 panic
DEFAULT_AI = 7
KEYS_AI = ("ai_car_count", "ai_cars")
KEY_TOTAL = "car_count"
OPTIONS_CFG = "options.cfg"
OPTIONS_DEF = "options.def"
BACKUP_SUFFIX = ".aifield-backup"


class AiFieldError(RuntimeError):
    """The options file can't be found or the request is out of range."""


def options_path(data_dir: str | Path) -> Path | None:
    """The live options file, preferring what the game actually reads at runtime.

    Delegates to writepaths.options_file, which owns the search because it owns
    the `Config\\` redirect. This used to look only under data_dir.parent, which
    is the v1.1 layout: on a v1.0 install -- where the Data folder IS the game
    root -- it missed Config/options.cfg entirely and fell through to
    options.def, so this function returned the SHIPPED DEFAULT and every caller
    silently read or wrote the wrong file.
    """
    return writepaths.options_file(data_dir)


def _read(text: str, key: str) -> int | None:
    m = re.search(rf"(?m)^{re.escape(key)}\s+(-?\d+)", text)
    return int(m.group(1)) if m else None


def _write(text: str, key: str, val: int) -> str:
    """Set key to val, adding it to the [GAME] section if it is missing."""
    pat = rf"(?m)^({re.escape(key)})\s+-?\d+"
    if re.search(pat, text):
        return re.sub(pat, rf"\g<1> {val}", text)
    # not present -- insert under [GAME]
    m = re.search(r"(?m)^\[GAME\]\s*$", text)
    if not m:
        raise AiFieldError(f"no [GAME] section and no {key} line to edit")
    at = m.end()
    return text[:at] + f"\n{key} {val}" + text[at:]


def status(data_dir: str | Path) -> dict:
    """Current field settings, or {} with a note if no options file exists yet."""
    f = options_path(data_dir)
    if f is None:
        return {"file": None}
    t = f.read_text(encoding="utf-8", errors="replace")
    ai = _read(t, "ai_car_count")
    return {
        "file": f,
        "ai_car_count": ai,
        "ai_cars": _read(t, "ai_cars"),
        "car_count": _read(t, KEY_TOTAL),
        "total": None if ai is None else ai + 1,
    }


def set_count(data_dir: str | Path, ai_count: int) -> dict:
    """Set the AI opponent count (0..15). Returns the applied values.

    Refuses > MAX_AI so it cannot produce the driver-16 panic. Backs the options
    file up once (`.aifield-backup`).
    """
    if ai_count < 0:
        raise AiFieldError("ai_count must be >= 0")
    if ai_count > MAX_AI:
        raise AiFieldError(
            f"{ai_count} AI would need {ai_count + 1} cars; the driver pool is 16 "
            f"(15 AI + player) and asking for driver {ai_count} panics with "
            f"'AIGetCarForDriver: No car for driver {ai_count}'. Max is {MAX_AI} AI.")
    f = options_path(data_dir)
    if f is None:
        raise AiFieldError(
            "no options.cfg or options.def found -- run the game once so it writes "
            "Config/options.cfg, then set the count.")
    bak = f.with_suffix(f.suffix + BACKUP_SUFFIX)
    if not bak.is_file():
        bak.write_bytes(f.read_bytes())
    t = f.read_text(encoding="utf-8", errors="replace")
    for k in KEYS_AI:
        t = _write(t, k, ai_count)
    t = _write(t, KEY_TOTAL, ai_count + 1)
    f.write_text(t, encoding="utf-8")
    return {"file": f, "ai_car_count": ai_count, "ai_cars": ai_count,
            "car_count": ai_count + 1, "total": ai_count + 1}


def revert(data_dir: str | Path) -> str:
    f = options_path(data_dir)
    if f is None:
        raise AiFieldError("no options file to revert")
    bak = f.with_suffix(f.suffix + BACKUP_SUFFIX)
    if not bak.is_file():
        raise AiFieldError(f"no {bak.name} to restore from")
    f.write_bytes(bak.read_bytes())
    bak.unlink()
    return f"restored {f.name} from backup"
