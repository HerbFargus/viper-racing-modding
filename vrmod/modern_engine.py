"""The modern engine: viper-racing-port's DLL, installed beside the game.

WHAT IT IS. `dinput.dll` from the viper-racing-port project. The game imports DirectInput, and Windows
looks in the game's own folder first, so a dinput.dll there loads with the game -- race.exe / race.bin
are never modified, and nothing in the patch set (which rebuilds the binary from a snapshot) is
touched. On load it:

  * lifts the engine's hard limits: 512 physics objects, 1,024 world and graphics objects, the model /
    surface / deferred-draw pools, the ~119-texture crash, the 250-entry texture table; and replaces the
    all-pairs collision loop with a broad-phase (2,000 obstacles run smoothly);
  * replaces the platform layer, per viperport.ini: an SDL2 window with SDL keyboard, mouse and game
    controllers; DirectDraw and Direct3D emulated on OpenGL 3.3 -- the 3D at the screen's native
    resolution with Hor+ widescreen, the HUD laid over it, clean Alt-Tab; DirectSound emulated on SDL2
    audio (no crackle, so no dsoal needed).

It supports v1.0 race.exe, v1.1 race.bin and the community 1.2.4-1.2.6 race.bin, and does nothing on a
build it doesn't recognise. One switch, everything on (see the project notes on keeping options simple):
`install` writes all three platform switches on; `remove` takes it all out again.

WHERE. Beside the binary the install actually runs: the Data folder on every pressing (on v1.0 the
Data folder's contents ARE the game directory, race.exe included).

WHAT IS OURS. dinput.dll is ours when it carries the string "viperport"; SDL2.dll when it matches the
bundled copy byte for byte. A dinput.dll that isn't ours (some other mod's) is set aside as
dinput.dll.vrmod-backup -- not a .dll, so it can't load -- and put back by remove.

The files come from vrmod/assets/modern_engine/, refreshed by scripts/update_modern_engine.py, whose
SOURCE.txt names the viper-racing-port commit they were built from.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets" / "modern_engine"
DLL, SDL, INI, LOG = "dinput.dll", "SDL2.dll", "viperport.ini", "viperport.log"
FOREIGN_BACKUP = "dinput.dll.vrmod-backup"
MARK = b"viperport"

ABSENT, INSTALLED, OUTDATED, FOREIGN = "absent", "installed", "outdated", "foreign"

INI_TEXT = """\
; viperport settings -- written by vrmod (Modern engine). The engine-limit fixes are always on.
[platform]
; 1 = SDL2 window, keyboard, mouse and game controllers; 0 = the game's own
sdl=1
; gl = OpenGL in place of DirectDraw/Direct3D (needs sdl=1); ddraw = the game's own
renderer=gl
; sdl = SDL audio in place of DirectSound (needs sdl=1); dsound = the game's own
audio=sdl
"""


class ModernEngineError(Exception):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bundled() -> dict:
    """What vrmod ships: the viper-racing-port commit and the files' hashes."""
    info = {"available": (ASSETS / DLL).is_file() and (ASSETS / SDL).is_file(), "commit": None}
    src = ASSETS / "SOURCE.txt"
    if src.is_file():
        for line in src.read_text(encoding="utf-8").splitlines():
            if line.startswith("viper-racing-port commit "):
                info["commit"] = line.split()[2][:7]
    return info


def is_ours(dll: Path) -> bool:
    try:
        return MARK in dll.read_bytes()
    except OSError:
        return False


def status(data_dir: str | Path) -> dict:
    """{"state": absent | installed | outdated | foreign, "ini": {...} or None, "commit": bundled commit,
    "log": path or None}. outdated = ours, but not the build vrmod bundles."""
    d = Path(data_dir)
    dll = d / DLL
    if not dll.is_file():
        state = ABSENT
    elif not is_ours(dll):
        state = FOREIGN
    elif (ASSETS / DLL).is_file() and _sha(dll) != _sha(ASSETS / DLL):
        state = OUTDATED
    else:
        state = INSTALLED
    ini = None
    if (d / INI).is_file():
        ini = {}
        for line in (d / INI).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split(";", 1)[0].strip()
            if "=" in line:
                k, v = (s.strip() for s in line.split("=", 1))
                ini[k.lower()] = v.lower()
    return {"state": state, "ini": ini, "commit": bundled()["commit"],
            "log": str(d / LOG) if (d / LOG).is_file() else None}


def active(data_dir: str | Path) -> dict:
    """Which parts are actually on: the DLL is ours and the ini switches them on."""
    st = status(data_dir)
    ours = st["state"] in (INSTALLED, OUTDATED)
    ini = st["ini"] or {}
    sdl = ours and ini.get("sdl") == "1"
    return {"limits": ours, "sdl": sdl, "gl": sdl and ini.get("renderer") == "gl",
            "audio": sdl and ini.get("audio") == "sdl"}


def install(data_dir: str | Path) -> str:
    """Put the bundled modern engine beside the game, everything on. Idempotent."""
    d = Path(data_dir)
    if not bundled()["available"]:
        raise ModernEngineError(f"the modern engine isn't bundled with this vrmod ({ASSETS} is missing)")
    if not d.is_dir():
        raise ModernEngineError(f"no folder {d}")
    notes = []
    dll = d / DLL
    if dll.is_file() and not is_ours(dll):
        if (d / FOREIGN_BACKUP).exists():
            raise ModernEngineError(f"{DLL} here isn't the modern engine, and {FOREIGN_BACKUP} already exists -- "
                                    "move one of them aside first")
        dll.rename(d / FOREIGN_BACKUP)
        notes.append(f"the {DLL} that was here is kept as {FOREIGN_BACKUP}")
    shutil.copy2(ASSETS / DLL, dll)
    if (d / SDL).is_file() and _sha(d / SDL) != _sha(ASSETS / SDL):
        notes.append(f"replaced a different {SDL}")
    shutil.copy2(ASSETS / SDL, d / SDL)
    (d / INI).write_text(INI_TEXT, encoding="utf-8")
    commit = bundled()["commit"] or "unknown"
    return (f"Modern engine installed (viper-racing-port {commit}): {DLL}, {SDL} and {INI} beside the game. "
            "Takes effect on the next launch; its log is viperport.log" + ("; " + "; ".join(notes) if notes else "") + ".")


def remove(data_dir: str | Path) -> str:
    """Take the modern engine out again; puts back a dinput.dll it had set aside."""
    d = Path(data_dir)
    gone = []
    if (d / DLL).is_file() and is_ours(d / DLL):
        (d / DLL).unlink()
        gone.append(DLL)
    if (d / SDL).is_file() and (ASSETS / SDL).is_file() and _sha(d / SDL) == _sha(ASSETS / SDL):
        (d / SDL).unlink()
        gone.append(SDL)
    if (d / INI).is_file():
        (d / INI).unlink()
        gone.append(INI)
    back = ""
    if (d / FOREIGN_BACKUP).is_file() and not (d / DLL).exists():
        (d / FOREIGN_BACKUP).rename(d / DLL)
        back = f"; the earlier {DLL} is back in place"
    if not gone:
        return "The modern engine isn't installed here -- nothing to remove" + back + "."
    return f"Modern engine removed ({', '.join(gone)}){back}. The game runs stock on the next launch."
