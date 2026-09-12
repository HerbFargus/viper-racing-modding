"""Stop the game writing outside its own folder.

Viper Racing writes four kinds of file to places that have nothing to do with
where it is installed, because the paths are absolute string literals compiled
into the engine:

    c:\\log.log          the run log (TWO separate literals, two code paths)
    c:\\except.log       the crash dump the SEH handler writes
    c:\\timer.log        timing diagnostics
    c:\\career.log       career progress log -- RC build only
    C:\\Program Files\\MGI\\Viper98\\    the USER directory: options.cfg, *.sco
                                     records, ghostcar\\, paint*.tex

Two consequences. Logs land at the root of C: (or, without admin rights, in
%LOCALAPPDATA%\\VirtualStore\\ via UAC file virtualisation, which is why they
sometimes seem to vanish). And every install on the machine shares ONE user
directory -- so two builds share one options.cfg, and deleting an install
resets nothing.

WHAT THIS DOES. Rewrites those literals to relative paths, in place:

    c:\\log.log        ->  log\\log.log
    c:\\except.log     ->  log\\except.log
    c:\\timer.log      ->  log\\timer.log
    c:\\career.log     ->  log\\career.log
    C:\\Program Files\\MGI\\Viper98\\  ->  Config\\

Each literal is NUL-terminated and measured with an inlined `strlen` at run
time (`mov edi,<addr>; xor eax,eax; repne scasb`), so there is no compiled-in
length to keep in step -- a shorter string simply measures shorter. Every one
of them has exactly ONE reference in the image, so nothing else can be reading
the bytes we overwrite.

WHO NEEDS WHICH. The two patches are independent because their coverage is:

    build                     log paths   user directory
    v1.0 race.exe  (the RC)   5 literals  hardcoded  <- needs both
    v1.0 race.bin  (release)  4 literals  already relative (\\Config\\)
    v1.2.5 / v1.2.6 community 4 literals  already relative

MGI made the user directory relative between the RC and the release, but NOBODY
ever fixed the log paths -- not the release, not the 2016 community build. So
the log patch applies to every build there is, including the one most people
run, while the user-directory patch is RC-only.

RELATIVE TO WHAT. Win32 resolves a relative path against the process's CURRENT
WORKING DIRECTORY, not the directory the .exe lives in. Those match when you
double-click the game in its own folder, or use a shortcut whose "Start in" is
that folder. They do NOT match if the shortcut's "Start in" is blank or points
elsewhere, and then the game writes into whatever directory it was started
from. `fopen` does not create directories, so in that case the log opens fail
SILENTLY -- no log.log, no except.log, exactly when a crash log matters most.
apply() therefore creates the folders in the install directory, which is the
case we can control; `where()` reports what a given build actually uses.

This is "portable across installs", not "portable anywhere". A real portable
build would derive the path from GetModuleFileName at run time, which is a code
change, not a 29-byte string swap.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import safewrite

# Engine binaries, live one first -- same ordering rule as vrampatch: a v1.0
# install ships both, and only race.exe is ever loaded.
TARGETS = ("race.exe", "race.bin")

# The hardcoded user directory, and what replaces it.
#
# NOTE the replacement has NO leading backslash. The release build's own literal
# is "\Config\", but that is APPENDED to a base directory it computes; standing
# alone, a leading backslash means the ROOT OF THE DRIVE -- C:\Config\ -- which
# is not an improvement on what we are fixing.
USER_DIR = b"C:\\Program Files\\MGI\\Viper98\\"
USER_DIR_NEW = b"Config\\"

# The log literals. `log.log` appears TWICE, in two different code paths; patch
# one and not the other and the run log splits between two locations depending
# on which path wrote it, which is worse than leaving both alone.
#
# NOTE the folder is "log", not "logs". `log\log.log` is 11 bytes, which is
# exactly the budget available at the `c:\log.log` sites (10 bytes + its NUL +
# ONE byte of padding). `logs\log.log` is 12 and would run into the "\r\n"
# literal that follows it. The obvious name does not fit.
LOG_DIR = "log"
LOG_MAP = {
    b"c:\\log.log":    b"log\\log.log",
    b"c:\\except.log": b"log\\except.log",
    b"c:\\timer.log":  b"log\\timer.log",
    b"c:\\career.log": b"log\\career.log",
}

# Folders the engine expects to find under the user directory, from its own
# string table: "setups\" + "<track>.csu" for per-track car setups, and
# "ghostcar" for saved ghost laps.
USER_SUBDIRS = ("setups", "ghostcar")

USER_DIR_KIND, LOGS_KIND = "userdir", "logs"

UNPATCHED, PATCHED, MIXED, ABSENT = "unpatched", "patched", "mixed", "absent"

# How far past a literal's NUL we are willing to treat trailing zero bytes as
# usable padding. The real gaps here are 1-6 bytes; a cap keeps us from walking
# into a genuinely empty data structure that happens to follow.
_MAX_SLACK = 8


class PatchError(RuntimeError):
    """The patch site is missing, ambiguous, or in a state we do not recognise."""


def _sites(blob: bytes, literal: bytes) -> list[int]:
    """Offsets of a WHOLE NUL-terminated string-table entry equal to `literal`.

    Both ends are anchored, and both anchors earn their place. The trailing NUL
    stops a longer string that merely starts with this one from matching. The
    LEADING NUL stops the reverse: the release build's user-directory literal is
    "\\Config\\", which ends with our replacement "Config\\", so a suffix match
    would report an unpatched release build as already patched. Every literal we
    touch begins a string-table entry, so requiring the preceding NUL is safe.
    """
    out = []
    for m in re.finditer(re.escape(literal) + b"\x00", blob):
        if m.start() == 0 or blob[m.start() - 1] == 0:
            out.append(m.start())
    return out


def _budget(blob: bytes, off: int, orig_len: int, max_slack: int = _MAX_SLACK) -> int:
    """Bytes usable at `off`: the literal, its NUL, and any NUL padding after.

    `max_slack` is conservative when APPLYING -- we only ever shorten, so there
    is no reason to reach far past a literal. Reverting is the opposite case:
    the field was zero-filled by our own apply(), the original is longer than
    what sits there now, and the run of NULs we need back is exactly the field
    we cleared. So revert passes a larger bound and relies on the scan stopping
    at the next real byte.
    """
    end = off + orig_len + 1
    slack = 0
    while slack < max_slack and end + slack < len(blob) and blob[end + slack] == 0:
        slack += 1
    return orig_len + 1 + slack


def _pairs(kind: str) -> list[tuple[bytes, bytes]]:
    if kind == USER_DIR_KIND:
        return [(USER_DIR, USER_DIR_NEW)]
    if kind == LOGS_KIND:
        return list(LOG_MAP.items())
    raise PatchError(f"unknown patch kind {kind!r}")


def _present(data_dir: str | Path) -> list[Path]:
    d = Path(data_dir)
    return [d / n for n in TARGETS if (d / n).is_file()]


def _state_of(blob: bytes, kind: str) -> str:
    old = sum(len(_sites(blob, a)) for a, _ in _pairs(kind))
    new = sum(len(_sites(blob, b)) for _, b in _pairs(kind))
    if old and not new:
        return UNPATCHED
    if new and not old:
        return PATCHED
    if not old and not new:
        return ABSENT          # this build never had these literals
    return MIXED               # half-done, or something else edited it


def status(data_dir: str | Path) -> dict[str, dict[str, str]]:
    """Per binary, the state of each patch: {"race.exe": {"logs": "unpatched", ...}}."""
    return {f.name: {k: _state_of(f.read_bytes(), k)
                     for k in (LOGS_KIND, USER_DIR_KIND)}
            for f in _present(data_dir)}


def where(data_dir: str | Path) -> dict[str, str]:
    """Where the LIVE binary writes its logs and its user data, as it stands.

    Reported as the literal the binary holds, so a relative answer is relative
    to the working directory the game is started from -- see the module notes.
    """
    files = _present(data_dir)
    if not files:
        return {}
    blob = files[0].read_bytes()
    out = {"binary": files[0].name}
    for kind, label in ((LOGS_KIND, "logs"), (USER_DIR_KIND, "user_data")):
        found = []
        for a, b in _pairs(kind):
            for lit in (b, a):                      # patched form first
                if _sites(blob, lit):
                    found.append(lit.decode("ascii", "replace"))
                    break
        out[label] = ", ".join(found) if found else "not present in this build"
    return out


def _apply_to(f: Path, kind: str) -> list[tuple[str, str]]:
    """Rewrite one binary's literals. Returns [(old, new), ...] actually changed."""
    blob = bytearray(f.read_bytes())
    state = _state_of(bytes(blob), kind)
    if state == PATCHED:
        return []
    if state == ABSENT:
        return []
    if state == MIXED:
        raise PatchError(
            f"{f.name}: {kind} is half-patched -- some literals are relative and "
            "some are not. Refusing to guess; revert first.")

    # Budget-check everything BEFORE writing anything, so a failure cannot leave
    # the file half-rewritten.
    plan = []
    for old, new in _pairs(kind):
        for off in _sites(bytes(blob), old):
            budget = _budget(bytes(blob), off, len(old))
            if len(new) + 1 > budget:
                raise PatchError(
                    f"{f.name}: {new.decode()} needs {len(new) + 1} bytes but only "
                    f"{budget} are free at 0x{off:x}; refusing to overrun the "
                    "next literal")
            plan.append((off, budget, old, new))

    for off, budget, old, new in plan:
        blob[off:off + budget] = new + b"\x00" * (budget - len(new))

    backup = f.with_suffix(f.suffix + ".writepaths-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    safewrite.write_atomic(f, bytes(blob))
    return [(o.decode(), n.decode()) for _, _, o, n in plan]


def apply(data_dir: str | Path, kind: str = LOGS_KIND, *,
          migrate: bool = True) -> dict[str, object]:
    """Make one family of paths relative, in every engine binary present.

    Also creates the folder the patched paths point at. `fopen` does not create
    directories, and a missing log folder fails silently -- so creating it here
    is not a convenience, it is the difference between having a crash log and
    not noticing you don't.

    migrate: for the user directory, copy the existing contents of the old
    hardcoded folder into the new one, so settings, lap records and ghosts
    survive the move rather than appearing to have been wiped.
    """
    d = Path(data_dir)
    files = _present(d)
    if not files:
        raise PatchError(f"no {' or '.join(TARGETS)} in {d}")

    changed: dict[str, list[tuple[str, str]]] = {}
    for f in files:
        done = _apply_to(f, kind)
        if done:
            changed[f.name] = done

    folder = d / (LOG_DIR if kind == LOGS_KIND else USER_DIR_NEW.decode().rstrip("\\"))
    folder.mkdir(exist_ok=True)
    if kind == USER_DIR_KIND:
        # Subfolders the engine looks for underneath the user directory. It
        # creates ghostcar\ itself, but `setups\` has never appeared on its own
        # -- loading a car setup logs "Can't open Config\setups\<track>.csu
        # --using default" and falls back harmlessly, while SAVING one reports
        # "Can't create setup file". fopen creates no directories, so making
        # them here costs nothing and removes the question.
        for sub in USER_SUBDIRS:
            (folder / sub).mkdir(exist_ok=True)

    migrated = []
    if kind == USER_DIR_KIND and migrate:
        old = Path(USER_DIR.decode())
        if old.is_dir():
            for p in sorted(old.iterdir()):
                dst = folder / p.name
                if dst.exists():
                    continue
                if p.is_dir():
                    shutil.copytree(p, dst)
                else:
                    shutil.copy2(p, dst)
                migrated.append(p.name)

    return {"kind": kind, "changed": changed, "folder": str(folder),
            "migrated": migrated}


def revert(data_dir: str | Path, kind: str = LOGS_KIND) -> dict[str, list[str]]:
    """Put the absolute paths back. The created folders are left alone -- they
    may hold logs or settings, and deleting user data to undo a code patch is
    not this function's call."""
    out: dict[str, list[str]] = {}
    for f in _present(data_dir):
        blob = bytearray(f.read_bytes())
        if _state_of(bytes(blob), kind) != PATCHED:
            continue
        restored = []
        for old, new in _pairs(kind):
            for off in _sites(bytes(blob), new):
                # Generous bound: we are restoring into the field our own apply()
                # zero-filled, which is longer than what currently occupies it.
                budget = _budget(bytes(blob), off, len(new), max_slack=len(old) + 8)
                if len(old) + 1 > budget:
                    raise PatchError(
                        f"{f.name}: cannot restore {old.decode()} at 0x{off:x} -- "
                        f"needs {len(old) + 1} bytes, {budget} free. The field has "
                        "been written by something other than this patch.")
                blob[off:off + budget] = old + b"\x00" * (budget - len(old))
                restored.append(old.decode())
        safewrite.write_atomic(f, bytes(blob))
        out[f.name] = restored
    return out


# ---------------------------------------------------------------------------
# Where the user data this patch redirects actually lands.
#
# `Config\` is relative, and Win32 resolves it against the process's CURRENT
# WORKING DIRECTORY -- which, for someone starting the game normally, is the
# folder holding the executable they started. The two pressings put that folder
# in DIFFERENT places relative to the Data folder:
#
#     v1.0   race.exe IS in the Data folder, so the game root IS data_dir
#     v1.1   "Viper Racing.exe" sits one level up, so the root is data_dir.parent
#
# Assuming only the v1.1 shape is a live bug, not a cosmetic one: on a v1.0
# install `data_dir.parent` is whatever folder happens to contain the install,
# so a Config there belongs to a DIFFERENT copy of the game -- and when there
# is none, the search falls through to options.def and silently reports the
# SHIPPED DEFAULT as if it were the player's current setting. That is exactly
# what doctor did before this helper existed: it told someone racing at
# 1920x1080 that they were at 640x480, because options.def still said so.
#
# So: check data_dir's own layout first, and exhaust every .cfg before trying
# any .def.

OPTIONS_CFG = "options.cfg"
OPTIONS_DEF = "options.def"


def config_dirs(data_dir: str | Path) -> list[Path]:
    """Candidate Config folders, most-likely first. See the note above."""
    d = Path(data_dir)
    return [d / USER_DIR_NEW.decode().rstrip("\\"),
            d.parent / USER_DIR_NEW.decode().rstrip("\\")]


def config_dir(data_dir: str | Path, *, containing: str | None = None) -> Path | None:
    """The install's live Config folder, or None if it has none yet.

    `containing` narrows it to a folder that actually holds that file, for
    callers that want a specific artefact (paint0.tex, options.cfg) rather than
    just any Config directory -- an empty Config beside the wrong pressing
    should not win over a populated one.
    """
    for c in config_dirs(data_dir):
        if c.is_dir() and (containing is None or (c / containing).is_file()):
            return c
    return None


def options_file(data_dir: str | Path) -> Path | None:
    """The options file the game actually reads, or None if there is none.

    options.cfg is what the game writes and re-reads; options.def is only the
    shipped default, so every .cfg candidate is tried before any .def. Returns
    the path rather than the contents so callers can say WHICH file they read.
    """
    d = Path(data_dir)
    for name in (OPTIONS_CFG, OPTIONS_DEF):
        for c in [r / name for r in config_dirs(d)] + [d / name]:
            if c.is_file():
                return c
    return None
