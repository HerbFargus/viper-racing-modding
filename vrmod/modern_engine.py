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

THE INI. install() creates viperport.ini when there is none, and otherwise only makes sure the three
[platform] switches are on -- every other line, comment and section the player added stays as it was,
with the file's own line endings. The one other setting vrmod offers is the Graphics preset
(set_graphics): [graphics] anisotropic= and msaa=, missing keys meaning 0 (the original look).
Anisotropic filtering only applies where the game filters textures, so Enhanced and High also set
`filtering yes` and `mipmap yes` in the game's options.cfg (Original leaves those alone).

THE STANDALONE (v1.0 only). The bundle also carries viperport.exe, viper-racing-port's loader: it runs
the game on the port's code alone. It maps the user's own v1.0 race.exe as data, fills every original
function with int3 and runs the port's rewrite of each, using the same dinput.dll and SDL2.dll. It
takes a vrmod-patched race.exe (the DLL carries vrmod's patches as rewrites) and refuses a race.exe
with patches it doesn't know. It is installed only beside a v1.0 race.exe -- the race.bin pressings
keep the DLL route -- and play() below decides, per launch, which of the two runs.

WHERE. Beside the binary the install actually runs: the Data folder on every pressing (on v1.0 the
Data folder's contents ARE the game directory, race.exe included).

WHAT IS OURS. dinput.dll and viperport.exe are ours when they carry the string "viperport" (or match
the bundled copy); SDL2.dll when it matches the bundled copy byte for byte. A dinput.dll that isn't
ours (some other mod's) is set aside as dinput.dll.vrmod-backup -- not a .dll, so it can't load -- and
put back by remove. A viperport.exe that isn't ours is left alone, and Play uses race.exe.

PLAY. play() starts the game the way this install starts: on v1.0 with the engine installed,
viperport.exe -- after asking it (`viperport.exe --probe --race race.exe`: exit 0 = it will run this
race.exe, otherwise one line saying why not) -- and race.exe through the DLL if it says no; race.exe on
any other v1.0; on the race.bin pressings the `Viper Racing.exe` launcher, which starts race.bin (with
the engine DLL beside it when installed). A viperport.exe too old to know --probe is launched and
watched instead: a non-zero exit within a few seconds counts as a refusal.

THE MODEL EDITOR (v1.0 only). v1.0's race.exe carries MGI's model editor (Ctrl+E on the main menu),
which needs a modtool.res no disc shipped. install() also writes vrmod's (modtool.py) when the one
there is missing, the community stand-in or an earlier one of ours -- never over anyone else's -- and
remove() takes it out, putting back the stand-in it replaced.

LINUX. There is no DLL route on Linux: race.exe / race.bin are Windows programs, and vrmod never runs
them there. The engine is viper-racing-port's native standalone instead -- `viperport` (a 32-bit ELF),
its launcher `viperport.sh`, `lib/libSDL2-2.0.so.0`, README-linux.txt and LICENSES/ -- which, like
viperport.exe, reads the user's v1.0 race.exe as data and runs the port's rewrite of every function.
So on Linux (IS_LINUX) install() puts those files beside a v1.0 race.exe only and refuses anything else
("the Linux engine runs v1.0's race.exe only"); status() reports the same shape as on Windows, with
"state" (and "standalone") read from the ELF, ours by the viperport mark or the bundled sha256 and
outdated when it, viperport.sh or the SDL2 library differ from the bundle; remove() takes those files out
(lib/ and LICENSES/ too once empty). viperport.ini is created when absent and otherwise left as it is:
the standalone forces SDL, so the [platform] switches don't matter there. Play starts viperport.sh from
the Data folder after asking the ELF (`viperport --probe <race.exe>`), and there is no fallback: an
install without the engine, or with no v1.0 race.exe, has no Linux route and says so.

The files come from vrmod/assets/modern_engine/ (the Linux ones from its linux/ folder), refreshed by
scripts/update_modern_engine.py, whose SOURCE.txt names the viper-racing-port commit they were built from.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path, PurePosixPath

from . import casefold, drawdistance, modtool, writepaths

ASSETS = Path(__file__).resolve().parent / "assets" / "modern_engine"
DLL, SDL, INI, LOG = "dinput.dll", "SDL2.dll", "viperport.ini", "viperport.log"
EXE = "viperport.exe"                     # the standalone loader (v1.0 only)
RACE_EXE, RACE_BIN, LAUNCHER = "race.exe", "race.bin", "Viper Racing.exe"
FOREIGN_BACKUP = "dinput.dll.vrmod-backup"
MARK = b"viperport"
PROBE_FLAG = b"--probe"                   # a viperport.exe knows --probe only if it carries the string
V10_TIMESTAMP = 0x362DE68C                # v1.0 race.exe's PE timestamp -- what viperport.exe checks first

ABSENT, INSTALLED, OUTDATED, FOREIGN = "absent", "installed", "outdated", "foreign"

# ---- Linux: the native standalone (see LINUX above) ----
IS_LINUX = sys.platform.startswith("linux")   # which engine this vrmod installs; the checks flip it on any OS
LINUX_ASSETS = ASSETS / "linux"
ELF, SH, LIBSDL = "viperport", "viperport.sh", "lib/libSDL2-2.0.so.0"   # beside race.exe, as in the tarball
LINUX_README, LINUX_LICENSES = "README-linux.txt", "LICENSES"
LINUX_JUNK = ("viperport-probe.txt", "viperport-check.txt")   # the ELF's --probe / --check reports
V10_ONLY = "the Linux engine runs v1.0's race.exe only"


def platform() -> str:
    return "linux" if IS_LINUX else "windows"


def linux_files() -> list[str]:
    """The Linux engine's files, relative to the game folder: what install() copies (the bundle's
    linux/ folder, ELF first) and remove() takes out."""
    lic = LINUX_ASSETS / LINUX_LICENSES
    docs = sorted(f"{LINUX_LICENSES}/{p.name}" for p in lic.iterdir() if p.is_file()) if lic.is_dir() else []
    return [ELF, SH, LIBSDL, LINUX_README, *docs]

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


PLATFORM = {"sdl": "1", "renderer": "gl", "audio": "sdl"}   # what install() makes sure of in [platform]

# Graphics presets: [graphics] in viperport.ini. Missing keys mean 0, the original look.
PRESETS = {"original": {"anisotropic": 0, "msaa": 0},
           "enhanced": {"anisotropic": 16, "msaa": 0},   # (2x MSAA cost ~13 fps on an HD 4000 laptop)
           "high": {"anisotropic": 16, "msaa": 4}}
CUSTOM = "custom"
GRAPHICS_COMMENTS = {
    "anisotropic": "; anisotropic texture filtering: 0 (off, as the original), 2, 4, 8 or 16",
    "msaa": "; multisample anti-aliasing of the 3D: 0 (off, as the original), 2, 4 or 8 -- takes effect at the next start",
}


class ModernEngineError(Exception):
    pass


# ---- viperport.ini: read and edit in place ----------------------------------------------------------
# Section-aware and careful: an edit touches only the keys it sets, so comments, other sections, the
# order of lines, a BOM and the file's own line endings all survive.

def _ini_load(path: Path) -> tuple[list[str], str, bool, str]:
    """(lines, newline, whether it ends with one, BOM or '')."""
    text = path.read_bytes().decode("utf-8", errors="surrogateescape")
    bom = ""
    if text.startswith("﻿"):
        bom, text = "﻿", text[1:]
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.splitlines(), nl, text.endswith(("\n", "\r")), bom


def _ini_save(path: Path, lines: list[str], nl: str, trailing: bool, bom: str) -> None:
    text = bom + nl.join(lines) + (nl if trailing else "")
    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))


def _section_of(line: str) -> str | None:
    s = line.split(";", 1)[0].strip()
    return s[1:-1].strip().lower() if s.startswith("[") and s.endswith("]") else None


def _key_value(line: str) -> tuple[str, str] | None:
    s = line.split(";", 1)[0].strip()
    if "=" not in s or s.startswith("["):
        return None
    k, v = s.split("=", 1)
    return k.strip().lower(), v.strip()


def read_ini(path: str | Path) -> dict:
    """{section: {key: value}}, names lower-cased, comments dropped; keys before any section go under ""."""
    out: dict = {"": {}}
    sec = ""
    for line in _ini_load(Path(path))[0]:
        name = _section_of(line)
        if name is not None:
            sec = name
            out.setdefault(sec, {})
        elif (kv := _key_value(line)) is not None:
            out[sec][kv[0]] = kv[1]
    return out


def set_ini_keys(path: str | Path, section: str, values: dict, comments: dict | None = None) -> bool:
    """Set key=value for each of `values` in [section] of the ini at `path`, keeping every other line as
    it is. A key already there is rewritten in place (each copy of it in that section); a missing one is
    added at the end of the section, after its line from `comments` if there is one; a missing section is
    added at the end of the file. Returns whether the file changed."""
    path = Path(path)
    lines, nl, trailing, bom = _ini_load(path)
    sec, comments = section.lower(), comments or {}
    want = {k.lower(): str(v) for k, v in values.items()}
    new = list(lines)
    starts = [i for i, ln in enumerate(new) if _section_of(ln) == sec]
    start = starts[-1] if starts else None      # a section written twice: the last copy is the one read last
    seen = set()
    for s0 in starts[:-1]:                      # earlier copies: rewrite their keys too, add nothing
        for i in range(s0 + 1, len(new)):
            if _section_of(new[i]) is not None:
                break
            kv = _key_value(new[i])
            if kv and kv[0] in want and kv[1] != want[kv[0]]:
                new[i] = f"{new[i].split('=', 1)[0].rstrip()}={want[kv[0]]}"
    if start is None:
        while new and not new[-1].strip():
            new.pop()
        block = ([""] if new else []) + [f"[{section}]"]
        for k, v in values.items():
            block += ([comments[k]] if k in comments else []) + [f"{k}={v}"]
        new += block
        trailing = True
    else:
        end = next((i for i in range(start + 1, len(new)) if _section_of(new[i]) is not None), len(new))
        for i in range(start + 1, end):
            kv = _key_value(new[i])
            if kv and kv[0] in want:
                seen.add(kv[0])
                if kv[1] != want[kv[0]]:
                    new[i] = f"{new[i].split('=', 1)[0].rstrip()}={want[kv[0]]}"
        last = end
        while last > start + 1 and not new[last - 1].strip():
            last -= 1                    # after the section's last line, before the blank gap to the next
        add = []
        for k, v in values.items():
            if k.lower() not in seen:
                add += ([comments[k]] if k in comments else []) + [f"{k}={v}"]
        if add and last == len(new):
            trailing = True
        new[last:last] = add
    if new == lines:
        return False
    _ini_save(path, new, nl, trailing, bom)
    return True


_sha_cache: dict = {}


def _sha(p: Path) -> str:
    """sha256 of a file, remembered until it changes (status() asks often, and the Linux ELF is 7 MB)."""
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _sha_cache:
        if len(_sha_cache) > 64:
            _sha_cache.clear()
        _sha_cache[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return _sha_cache[key]


def _same(p: Path, bundled_copy: Path) -> bool:
    """Is `p` there, byte for byte the bundled file?"""
    try:
        return p.is_file() and bundled_copy.is_file() and _sha(p) == _sha(bundled_copy)
    except OSError:
        return False


def bundled() -> dict:
    """What vrmod ships for this platform: the viper-racing-port commit, whether the engine is there, and
    whether the standalone is in it (on Linux the engine IS the standalone)."""
    if IS_LINUX:
        avail = all((LINUX_ASSETS / n).is_file() for n in (ELF, SH, LIBSDL))
        info = {"available": avail, "standalone": avail, "commit": None, "platform": "linux"}
        prefix = "viper-racing-port linux commit "
    else:
        info = {"available": (ASSETS / DLL).is_file() and (ASSETS / SDL).is_file(),
                "standalone": (ASSETS / EXE).is_file(), "commit": None, "platform": "windows"}
        prefix = "viper-racing-port commit "
    src = ASSETS / "SOURCE.txt"
    if src.is_file():
        for line in src.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                info["commit"] = line[len(prefix):].split()[0][:7]
    return info


def is_ours(path: Path, bundled_copy: Path | None = None) -> bool:
    """dinput.dll / viperport.exe / the Linux viperport: viper-racing-port's (it carries the mark, or is
    the bundled file -- ASSETS/<its name> unless `bundled_copy` names another)."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if MARK in data:
        return True
    bundled_copy = bundled_copy or ASSETS / path.name
    return bundled_copy.is_file() and hashlib.sha256(data).hexdigest() == _sha(bundled_copy)


def race_exe_is_v10(data_dir: str | Path) -> bool:
    """Is there a v1.0 race.exe here -- the only build viperport.exe runs? Read from its PE header (the
    timestamp viperport.exe checks first), so a vrmod-patched v1.0 race.exe still counts. Any case
    (RACE.EXE off a CD, on Linux)."""
    race = casefold.find(data_dir, RACE_EXE)
    if race is None:
        return False
    try:
        with race.open("rb") as fh:
            head = fh.read(0x400)
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        if head[:2] != b"MZ" or head[pe:pe + 4] != b"PE\0\0":
            return False
        return struct.unpack_from("<I", head, pe + 8)[0] == V10_TIMESTAMP
    except (OSError, struct.error):
        return False


def game_options(data_dir: str | Path) -> Path | None:
    """The options.cfg the game reads with the modern engine installed, or None before the game has
    written one. On v1.0 the engine puts the user directory in <race.exe's folder>\\Config\\ -- the Data
    folder's own Config, and nothing else (a Config one level up belongs to some other copy). On the
    race.bin pressings it is the game's relative Config\\, found by the generic search
    (writepaths.options_file). options.def, the shipped default, is never returned, so never written."""
    d = Path(data_dir)
    if race_exe_is_v10(d):              # any case: the Linux engine makes Config, a CD copy may have CONFIG
        p = casefold.find(d, f"{writepaths.config_dirs(d)[0].name}/{writepaths.OPTIONS_CFG}")
    else:
        p = writepaths.options_file(d)
    return p if p is not None and p.name.lower() == writepaths.OPTIONS_CFG and p.is_file() else None


def _file_state(path: Path, bundled_copy: Path | None = None) -> str:
    bundled_copy = bundled_copy or ASSETS / path.name
    if not path.is_file():
        return ABSENT
    if not is_ours(path, bundled_copy):
        return FOREIGN
    if bundled_copy.is_file() and _sha(path) != _sha(bundled_copy):
        return OUTDATED
    return INSTALLED


def _linux_state(d: Path) -> str:
    """The Linux engine's state: the ELF's, and outdated too when its launcher or SDL2 isn't the bundle's."""
    state = _file_state(d / ELF, LINUX_ASSETS / ELF)
    if state == INSTALLED and not all(_same(d / n, LINUX_ASSETS / n) for n in (SH, LIBSDL)):
        state = OUTDATED
    return state


def status(data_dir: str | Path) -> dict:
    """{"state": absent | installed | outdated | foreign, "standalone": viperport.exe's state, or None
    where it doesn't apply (no v1.0 race.exe), "modtool": modtool.status() on v1.0 (the model
    editor's resource set), else None, "ini": {...} or None, "commit": bundled commit, "log": path or
    None, "graphics": graphics(), "platform": "windows" | "linux"}. outdated = ours, but not the build vrmod
    bundles -- including a v1.0 install whose engine predates the standalone (no viperport.exe yet), so
    Update brings it in. On Linux "state" is the native engine's (the viperport ELF, its launcher and
    SDL2), and "standalone" is that same state on v1.0 (the Linux engine is the standalone), else None."""
    d = Path(data_dir)
    if IS_LINUX:
        state = _linux_state(d)
        standalone = state if race_exe_is_v10(d) else None
    else:
        state = _file_state(d / DLL)
        standalone = _file_state(d / EXE) if race_exe_is_v10(d) else None
        if state == INSTALLED and bundled()["standalone"] and standalone in (ABSENT, OUTDATED):
            state = OUTDATED
    ini = None
    if (d / INI).is_file():
        ini = {}
        for line in (d / INI).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split(";", 1)[0].strip()
            if "=" in line:
                k, v = (s.strip() for s in line.split("=", 1))
                ini[k.lower()] = v.lower()
    return {"state": state, "standalone": standalone, "ini": ini, "commit": bundled()["commit"],
            "graphics": graphics(d),
            "modtool": modtool.status(d) if race_exe_is_v10(d) else None,
            "log": str(d / LOG) if (d / LOG).is_file() else None, "platform": platform()}


def active(data_dir: str | Path) -> dict:
    """Which parts are actually on: the DLL is ours and the ini switches them on."""
    st = status(data_dir)
    ours = st["state"] in (INSTALLED, OUTDATED)
    if IS_LINUX:                          # the native standalone is SDL, OpenGL and SDL audio, whatever the ini says
        return {"limits": ours, "sdl": ours, "gl": ours, "audio": ours}
    ini = st["ini"] or {}
    sdl = ours and ini.get("sdl") == "1"
    return {"limits": ours, "sdl": sdl, "gl": sdl and ini.get("renderer") == "gl",
            "audio": sdl and ini.get("audio") == "sdl"}


def install(data_dir: str | Path) -> str:
    """Put the bundled modern engine beside the game, everything on. Idempotent."""
    d = Path(data_dir)
    if not bundled()["available"]:
        raise ModernEngineError(f"the modern engine isn't bundled with this vrmod "
                                f"({LINUX_ASSETS if IS_LINUX else ASSETS} is missing)")
    if not d.is_dir():
        raise ModernEngineError(f"no folder {d}")
    if IS_LINUX:
        return _install_linux(d)
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
    if (d / INI).is_file():              # the player's own settings stay: only the platform switches are ours
        if set_ini_keys(d / INI, "platform", PLATFORM):
            notes.append(f"switched the {INI} platform settings back on (the rest of it is as it was)")
    else:
        (d / INI).write_text(INI_TEXT, encoding="utf-8")
    placed = [DLL, SDL, INI]
    exe = d / EXE
    if race_exe_is_v10(d) and bundled()["standalone"]:
        if exe.is_file() and not is_ours(exe):
            notes.append(f"a {EXE} that isn't the modern engine's is here and was left alone, so Play uses race.exe")
        else:
            shutil.copy2(ASSETS / EXE, exe)
            placed.append(EXE)
    elif exe.is_file() and is_ours(exe):
        exe.unlink()                     # the standalone runs v1.0 only: never leave it beside race.bin
        notes.append(f"took out a {EXE} -- the standalone runs v1.0's race.exe only")
    if race_exe_is_v10(d):
        notes.append(_install_modtool(d))
    commit = bundled()["commit"] or "unknown"
    return (f"Modern engine installed (viper-racing-port {commit}): {', '.join(placed[:-1])} and {placed[-1]} "
            "beside the game. Takes effect on the next launch; its log is viperport.log"
            + ("; " + "; ".join(notes) if notes else "") + ".")


def _not_v10_reason(d: Path) -> str:
    """Why a folder has no v1.0 race.exe, for the Linux messages."""
    if casefold.find(d, RACE_EXE) is not None:
        return "this race.exe isn't v1.0"
    if casefold.find(d, RACE_BIN) is not None:
        return "this install has race.bin (v1.1 / 1.2.x) and no race.exe"
    return f"there is no race.exe in {d}"


def _install_linux(d: Path) -> str:
    """Linux: the native standalone's files beside a v1.0 race.exe (and nowhere else), exec bits set."""
    if not race_exe_is_v10(d):
        raise ModernEngineError(f"{_not_v10_reason(d)} -- {V10_ONLY}")
    if (d / ELF).is_file() and not is_ours(d / ELF, LINUX_ASSETS / ELF):
        raise ModernEngineError(f"the {ELF} here isn't the modern engine's -- move it aside first")
    for rel in linux_files():
        dest = d / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and not os.access(dest, os.W_OK):
            dest.chmod(dest.stat().st_mode | 0o200)     # an earlier copy left read-only
        shutil.copy2(LINUX_ASSETS / rel, dest)
        if rel in (ELF, SH):
            dest.chmod(dest.stat().st_mode | 0o111)
    if not (d / INI).is_file():          # the player's own settings stay; [platform] doesn't matter here
        (d / INI).write_text(INI_TEXT, encoding="utf-8")
    note = _install_modtool(d)
    commit = bundled()["commit"] or "unknown"
    return (f"Modern engine installed (viper-racing-port {commit}, Linux): {ELF}, its launcher {SH} and SDL2 "
            f"({LIBSDL}) beside race.exe, with {INI}. Play starts it; its log is {LOG}; {note}.")


def graphics(data_dir: str | Path) -> dict:
    """The Graphics preset viperport.ini holds: {"preset": original | enhanced | high | custom,
    "anisotropic": int or None, "msaa": int or None} (None = a value that isn't a number). Missing keys,
    or no ini at all, mean 0: the original look. Plus game_filtering(): whether the game's own texture
    filtering and mipmaps are on, which the anisotropic filtering needs."""
    p = Path(data_dir) / INI
    raw = read_ini(p).get("graphics", {}) if p.is_file() else {}
    vals: dict = {}
    for k in ("anisotropic", "msaa"):
        try:
            vals[k] = int(raw.get(k) or "0")
        except ValueError:
            vals[k] = None
    name = next((n for n, v in PRESETS.items() if v == vals), CUSTOM)
    return dict(vals, preset=name, **game_filtering(data_dir))


# The game's own texture filtering: anisotropic filtering only applies where the game filters textures,
# and its Graphics options "filtering" and "mipmap" (options.cfg `filtering no` / `mipmap no`) start off.
# Enhanced and High switch both on; Original leaves them as they are.
GAME_FILTER_KEYS = ("filtering", "mipmap")


def game_filtering(data_dir: str | Path) -> dict:
    """{"options": options.cfg path or None, "filtering": True / False / None, "mipmap": ...} (None: no
    options.cfg yet, or no such line in it)."""
    p = game_options(data_dir)
    out: dict = {"options": str(p) if p else None}
    for k in GAME_FILTER_KEYS:
        v = drawdistance.get_line(p, k) if p else None
        out[k] = None if v is None else v.lower() == "yes"
    return out


def set_graphics(data_dir: str | Path, preset: str) -> str:
    """Write a Graphics preset into viperport.ini's [graphics] -- anisotropic= and msaa=, nothing else."""
    d = Path(data_dir)
    preset = (preset or "").strip().lower()
    if preset not in PRESETS:
        raise ModernEngineError(f"no graphics preset {preset!r} -- one of {', '.join(PRESETS)}")
    if status(d)["state"] not in (INSTALLED, OUTDATED):
        raise ModernEngineError("the modern engine isn't installed here -- install it first")
    if not (d / INI).is_file():
        (d / INI).write_text(INI_TEXT, encoding="utf-8")
    msaa_before = graphics(d)["msaa"]
    vals = PRESETS[preset]
    set_ini_keys(d / INI, "graphics", vals, GRAPHICS_COMMENTS)
    af = f"{vals['anisotropic']}x" if vals["anisotropic"] else "off"
    aa = f"{vals['msaa']}x" if vals["msaa"] else "off"
    msg = f"Graphics set to {preset.capitalize()} (anisotropic filtering {af}, anti-aliasing {aa})."
    if msaa_before != vals["msaa"]:
        msg += " The anti-aliasing change takes effect the next time the game starts."
    if preset != "original":                 # Original leaves the game's own filtering as it is
        msg += " " + _game_filtering_on(d)
    return msg


def _game_filtering_on(d: Path) -> str:
    """Enhanced / High: `filtering yes` and `mipmap yes` in the game's options.cfg. A note for the message."""
    p = game_options(d)
    if p is None:
        return ("The game hasn't written its options.cfg yet, so its texture filtering is still off: start the "
                "game once and choose the preset again, or switch on filtering and mipmap in the game's "
                "Graphics options.")
    try:
        changed = drawdistance.set_lines(p, {k: "yes" for k in GAME_FILTER_KEYS})
    except (drawdistance.SettingError, OSError) as e:
        return (f"The game's texture filtering wasn't switched on ({e}): switch on filtering and mipmap in "
                "the game's Graphics options.")
    return ("Switched on the game's texture filtering and mipmaps in its options.cfg (the game rewrites that "
            "file when it exits, so do this with the game closed)." if changed else
            "The game's texture filtering and mipmaps are already on.")


def _install_modtool(d: Path) -> str:
    """v1.0: the model editor's modtool.res, by modtool's rules (never over someone else's). A note."""
    before = modtool.status(d)["state"]
    if before == modtool.FOREIGN:
        return f"the {modtool.NAME} here isn't vrmod's, so it was left alone (vrmod modtool --force replaces it)"
    try:
        modtool.install(d)
    except (modtool.ModtoolError, OSError) as e:
        return f"{modtool.NAME} for the model editor wasn't written ({e})"
    kept = f", the community stand-in kept as {modtool.BACKUP}" if before == modtool.STANDIN else ""
    return f"{modtool.NAME} for the model editor (Ctrl+E on the main menu) written{kept}"


def remove(data_dir: str | Path) -> str:
    """Take the modern engine out again; puts back a dinput.dll it had set aside."""
    d = Path(data_dir)
    if IS_LINUX:
        return _remove_linux(d)
    gone = []
    for name in (DLL, EXE):
        if (d / name).is_file() and is_ours(d / name):
            (d / name).unlink()
            gone.append(name)
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
    if modtool.status(d)["state"] in (modtool.INSTALLED, modtool.OUTDATED):
        modtool.remove(d)
        gone.append(modtool.NAME)
        if (d / modtool.NAME).is_file():
            back += f"; the {modtool.NAME} it replaced is back in place"
    if not gone:
        return "The modern engine isn't installed here -- nothing to remove" + back + "."
    return f"Modern engine removed ({', '.join(gone)}){back}. The game runs stock on the next launch."


def _remove_linux(d: Path) -> str:
    """Linux: the ELF when it is ours; its launcher, SDL2, README and licences when the ELF was ours or
    they are the bundle's own; viperport.ini; then lib/ and LICENSES/ if that left them empty."""
    gone = []
    pkg = (d / ELF).is_file() and is_ours(d / ELF, LINUX_ASSETS / ELF)
    for rel in linux_files():
        p = d / rel
        if p.is_file() and (pkg if rel == ELF else pkg or _same(p, LINUX_ASSETS / rel)):
            p.unlink()
            gone.append(rel)
    for rel in LINUX_JUNK:
        if pkg and (d / rel).is_file():
            (d / rel).unlink()
    for sub in (str(PurePosixPath(LIBSDL).parent), LINUX_LICENSES):
        try:
            (d / sub).rmdir()                # only when empty
        except OSError:
            pass
    if (d / INI).is_file():
        (d / INI).unlink()
        gone.append(INI)
    back = ""
    if modtool.status(d)["state"] in (modtool.INSTALLED, modtool.OUTDATED):
        modtool.remove(d)
        gone.append(modtool.NAME)
        if (d / modtool.NAME).is_file():
            back += f"; the {modtool.NAME} it replaced is back in place"
    if not gone:
        return "The modern engine isn't installed here -- nothing to remove" + back + "."
    shown = [n for n in gone if not n.startswith(LINUX_LICENSES + "/") and n != LINUX_README]
    return f"Modern engine removed ({', '.join(shown)}){back}. Play needs it to start the game on Linux."


# ---- Play ------------------------------------------------------------------------------------------
# Routes: the standalone (viperport.exe), race.exe (v1.0; through the DLL when the engine is installed),
# or the launcher (the race.bin pressings: `Viper Racing.exe` starts race.bin). On Linux only the
# standalone: viperport.sh, the native engine's launcher -- never race.exe or the launcher.
STANDALONE, RACE, LAUNCH = "standalone", "race.exe", "launcher"
PROBE_TIMEOUT = 20      # seconds for `viperport.exe --probe` to answer
WATCH_SECONDS = 4       # without --probe: a viperport.exe that exits non-zero this soon refused

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             if sys.platform == "win32" else 0)


class PlayError(Exception):
    pass


def supports_probe(exe: Path) -> bool:
    """Does this viperport.exe / Linux viperport ELF know --probe? (Ask the ELF, not viperport.sh.)"""
    try:
        return PROBE_FLAG in Path(exe).read_bytes()
    except OSError:
        return False


def _run_probe(exe: Path, race: Path, cwd: Path) -> tuple[int, str]:
    """Run `viperport.exe --probe --race <race.exe>` (Linux: `viperport --probe <race.exe>`): (exit code,
    its stdout). Starts nothing."""
    args = ["--probe", str(race)] if IS_LINUX else ["--probe", "--race", str(race)]
    r = subprocess.run([str(exe), *args], cwd=str(cwd), capture_output=True, stdin=subprocess.DEVNULL,
                       text=True, errors="replace", timeout=PROBE_TIMEOUT, creationflags=_NO_WINDOW)
    return r.returncode, r.stdout or ""


def _spawn(exe: Path, cwd: Path) -> subprocess.Popen:
    """Start a game executable detached from vrmod, its own folder as the working directory. Detached
    the way each OS does it: creationflags on Windows, a new session on POSIX (each is the other's error)."""
    if sys.platform != "win32" and Path(exe).suffix.lower() in (".exe", ".bin"):
        raise PlayError(f"{Path(exe).name} is a Windows program -- vrmod doesn't start it here")
    detach = {"creationflags": _DETACHED} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen([str(exe)], cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True, **detach)


_probe_cache: dict = {}


def _stamp(*paths: Path) -> tuple:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(p), None, None))
    return tuple(out)


def probe(data_dir: str | Path) -> tuple[bool | None, str]:
    """Will viperport.exe (Linux: the viperport ELF) run this install's race.exe? (True / False, its one
    line saying why), or (None, ...) when the installed one predates --probe and can't be asked. Cached
    until the engine or race.exe changes."""
    d = Path(data_dir)
    exe, name = (d / ELF, ELF) if IS_LINUX else (d / EXE, EXE)
    race = casefold.path(d, RACE_EXE)
    key = _stamp(exe, d / (SH if IS_LINUX else DLL), race)
    if key in _probe_cache:
        return _probe_cache[key]
    if not supports_probe(exe):
        res = (None, f"this {name} predates --probe, so it can't be asked ahead of launch")
    else:
        try:
            code, out = _run_probe(exe, race, d)
            line = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
            for prefix in ("yes: ", "no: "):      # the probe's line starts with its answer; the exit code carries that
                if line.startswith(prefix):
                    line = line[len(prefix):]
            res = (code == 0, line or (f"{name} --probe said yes" if code == 0 else
                                       f"{name} --probe said no (exit code {code})"))
        except subprocess.TimeoutExpired:
            res = (False, f"{name} --probe didn't answer within {PROBE_TIMEOUT} s")
        except OSError as e:
            res = (False, f"{name} didn't start ({e})")
    _probe_cache.clear()                  # one install's answer at a time is all anything asks for
    _probe_cache[key] = res
    return res


def _launcher(d: Path) -> Path | None:
    # An installed v1.1 tree keeps it beside Data\; the disc layout has it inside Data\.
    for p in (casefold.find(d.parent, LAUNCHER), casefold.find(d, LAUNCHER)):
        if p is not None and p.is_file():
            return p
    return None


def play_route(data_dir: str | Path) -> dict:
    """How Play would start this install, without starting it:
    {"route": standalone | race.exe | launcher, "exe": path, "cwd": path, "engine": DLL installed,
     "probe": True / False / None, "why": why not viperport.exe (v1.0 with the engine only) or None,
     "label": what Play starts, for the UI}. Raises PlayError when there is nothing to start -- on Linux
    also when the engine isn't installed, or there is no v1.0 race.exe (the only Linux route is the
    native standalone)."""
    d = Path(data_dir)
    if not d.is_dir():
        raise PlayError(f"no folder {d}")
    st = status(d)
    engine = st["state"] in (INSTALLED, OUTDATED)
    if IS_LINUX:
        return _linux_route(d, st, engine)
    race = casefold.find(d, RACE_EXE)
    if race is not None and race.is_file():
        why, ok = None, None
        if engine and st["standalone"] in (INSTALLED, OUTDATED):
            ok, line = probe(d)
            if ok is not False:            # yes, or can't be asked (then play() watches it start)
                return {"route": STANDALONE, "exe": str(d / EXE), "cwd": str(d), "engine": True, "probe": ok,
                        "why": None, "label": STANDALONE_LABEL}
            why = line
        elif engine and st["standalone"] == FOREIGN:
            why = f"the {EXE} here isn't the modern engine's"
        elif engine and st["standalone"] == ABSENT and bundled()["standalone"]:
            why = f"{EXE} isn't installed yet -- Update the modern engine to add it"
        return {"route": RACE, "exe": str(race), "cwd": str(d), "engine": engine, "probe": ok, "why": why,
                "label": "race.exe with the modern engine" if engine else "race.exe"}
    launcher = _launcher(d)
    if launcher is None:
        if not casefold.exists(d, RACE_BIN):
            raise PlayError(f"no {RACE_EXE} or {RACE_BIN} in {d} -- is this the game's Data folder?")
        raise PlayError(f"no {LAUNCHER} beside {d} or in it -- race.bin is started by that launcher")
    return {"route": LAUNCH, "exe": str(launcher), "cwd": str(launcher.parent), "engine": engine, "probe": None,
            "why": None, "label": f"{LAUNCHER}, which starts race.bin" + (" with the modern engine" if engine else "")}


def _linux_route(d: Path, st: dict, engine: bool) -> dict:
    """Linux: viperport.sh from the Data folder, once the ELF says it will run this race.exe -- or a
    PlayError saying why there is no Linux route."""
    if not race_exe_is_v10(d):
        if casefold.find(d, RACE_EXE) is None and casefold.find(d, RACE_BIN) is None:
            raise PlayError(f"no {RACE_EXE} or {RACE_BIN} in {d} -- is this the game's Data folder?")
        raise PlayError(f"no Linux route: {V10_ONLY} ({_not_v10_reason(d)})")
    if not engine:
        raise PlayError("install the modern engine to play on Linux (race.exe is a Windows program; the "
                        "modern engine runs it natively)")
    if not (d / SH).is_file():
        raise PlayError(f"{SH} is missing -- Update the modern engine to put it back")
    ok, line = probe(d)
    if ok is False:
        raise PlayError(f"the modern engine won't run this race.exe: {line}")
    return {"route": STANDALONE, "exe": str(d / SH), "cwd": str(d), "engine": True, "probe": ok, "why": None,
            "label": LINUX_LABEL}


STANDALONE_LABEL = "viperport.exe: the game on the port's code alone"
LINUX_LABEL = "viperport: the game on the port's code alone, native on Linux"


def _started(r: dict) -> str:
    msg = f"Started {r['label']}."
    return msg + (f" Not {EXE}: {r['why']}." if r["why"] else "")


def play(data_dir: str | Path) -> dict:
    """Start the game, detached, by the route play_route() picks. Returns the route actually taken (as
    play_route) plus "message": what started, and on a fallback why it isn't viperport.exe. On Linux
    there is no fallback: a viperport that stops at start-up is a PlayError naming its log."""
    d = Path(data_dir)
    r = play_route(d)
    if r["route"] == STANDALONE:
        why = None
        try:
            proc = _spawn(Path(r["exe"]), d)
        except OSError as e:
            proc, why = None, f"it didn't start ({e})"
        if proc is not None:
            if r["probe"]:
                return dict(r, message=_started(r))
            try:                           # it can't be asked: watch it start instead
                code = proc.wait(timeout=WATCH_SECONDS)
            except subprocess.TimeoutExpired:
                code = None
            if not code:                   # still running (or a clean exit): it started
                return dict(r, message=_started(r))
            why = f"it stopped at start-up (exit code {code}) -- its message box or viperport.log says why"
        if IS_LINUX:
            raise PlayError(f"viperport {why.replace('its message box or ', '')}")
        r = dict(r, route=RACE, exe=str(casefold.path(d, RACE_EXE)), probe=False, why=why,
                 label="race.exe with the modern engine")
    _spawn(Path(r["exe"]), Path(r["cwd"]))
    return dict(r, message=_started(r))
