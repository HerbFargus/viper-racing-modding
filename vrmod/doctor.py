"""Check a Viper Racing install and explain what it finds.

This deliberately DIAGNOSES rather than patches. The hard compatibility problem
-- the game refusing to start on modern GPUs -- is already solved twice over by
people who understand the binary better than this project does:

  * the community `race.bin` (v1.2.5, 2016; lineage Sucahyo 2007 -> Charlie
    Ward -> Val Novak), which also raises the polygon and vertex limits, and
  * dgVoodoo2, by dropping DDraw.dll and D3DImm.dll into Data/.

The underlying fault is an integer overflow in the video-memory check: the game
reads the DirectDraw-reported VRAM into a signed 32-bit integer, so a card with
4GB or more wraps negative, fails the minimum-memory test, and the game reports
that the video card returned an error. Nothing about that is worth
re-implementing badly when a maintained fix exists.

What IS missing is knowing whether a given install is actually in good shape,
because the fixes are scattered across forum posts and dead links. So: detect,
explain, and only ever apply changes that are plain-text and reversible.

Note `race.bin` is the real executable -- "Viper Racing.exe" in the parent
folder is only a launcher, which is why every compatibility fix targets a file
inside Data/.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import patchset, resolution, switcher, vrampatch

# Severity, worst first. "bad" means the game probably will not run or work
# right; "warn" is worth acting on; "info" is context, not a problem.
BAD, WARN, OK, INFO = "bad", "warn", "ok", "info"

RACE_BIN = "race.bin"
DRIVERS_RES = "drivers.res"
DGVOODOO_DLLS = ("ddraw.dll", "d3dimm.dll")
OPTIONS = "options.def"

# The four modes stock race.bin ships with, in its own order. `video mode` in
# options.def indexes this list. Anything else means a resolution patcher has
# rewritten the table -- see resolution.py.
STOCK_MODES = [(1024, 768), (800, 600), (640, 480), (512, 384)]

# Files this toolchain and its predecessors leave behind. Not junk exactly --
# they are the undo history -- but worth surfacing, because they accumulate and
# each one is a full copy of a multi-megabyte archive.
LEFTOVER_GLOBS = (
    "*.bak", "*.quarantine", "*_original.*", "*.sky-backup", "*.map-backup",
    "*_AS_*.btr", "*.trm",
)

# Retail disc-check components. Viper Racing shipped on CD and checks for the
# disc at launch; these are the files a retail-derived install carries. We only
# DETECT them (so a user knows whether to expect the "insert the CD" prompt) --
# analysing or defeating the protection is out of scope, see disc_check().
DISC_LAUNCHER = "Viper Racing.exe"   # the launcher, in the game root (Data's parent)
DISC_HELPER = "findviper.exe"        # the disc-locator helper, ships in Data


@dataclass
class Finding:
    level: str
    title: str
    detail: str
    fix: str | None = None       # what the user could do, in plain words
    action: str | None = None    # an id the UI can offer as a button, if we can do it
    link: str | None = None      # a URL the UI can render (e.g. a download page)


@dataclass
class Report:
    game_root: Path
    data_dir: Path
    findings: list[Finding] = field(default_factory=list)

    @property
    def worst(self) -> str:
        for level in (BAD, WARN, INFO, OK):
            if any(f.level == level for f in self.findings):
                return level
        return OK


def race_bin_version(data_dir: Path) -> str | None:
    """The version string the game shows in Options, read straight out of the
    binary. Stock 1.1 has no such marker; the community builds embed one."""
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        return None
    blob = f.read_bytes()
    m = re.search(rb"v\d+\.\d+\.\d+[ -~]{0,12}", blob)
    return m.group(0).decode("ascii", "replace").strip() if m else None


def drivers_res_lines(data_dir: Path) -> int | None:
    """How many baked AI racing lines `drivers.res` holds, or None if absent.

    The shipped file carries 524 `.ilg` lines -- one per AI skill tier per track
    section -- keyed to the STOCK track in each slot. Install a different track
    into that slot and the AI keeps following the old track's line: it swerves
    off the road at the start, or the game crashes outright on some layouts.

    The community answer, circulated by Sucahyo from 2009, is a `drivers.res`
    containing nothing at all. With no baked line to prefer, the AI falls back to
    the track's own `default.ili`/`track.ild`, which is what an add-on ships.

    Counting `.ilg` members rather than bytes because that is the thing that
    causes the fault -- the `.dnt` driver tunings alongside them are harmless.
    """
    from . import archive

    f = Path(data_dir) / DRIVERS_RES
    if not f.is_file():
        return None
    try:
        return sum(1 for e in archive.read(f) if e.name.lower().endswith(".ilg"))
    except Exception:
        return None


def empty_drivers_res(data_dir: str | Path) -> tuple[Path, Path | None]:
    """Replace `drivers.res` with an empty archive, backing up the original.

    Returns (written, backup). Reversible: the backup is a plain copy and the
    file we write is the same 16 bytes the community fix ships.
    """
    from . import archive

    data_dir = Path(data_dir)
    target = data_dir / DRIVERS_RES
    backup = None
    if target.is_file():
        backup = target.with_suffix(".res.bak")
        n = 1
        while backup.exists():
            n += 1
            backup = target.with_suffix(f".res.bak{n}")
        backup.write_bytes(target.read_bytes())
    target.write_bytes(archive.to_bytes([]))
    return target, backup


def disc_check(data_dir: Path) -> list[Path]:
    """Retail disc-check components present in this install, if any.

    Viper Racing was released on CD and checks for the disc at launch. This
    reports which retail disc-check files are present -- purely so a user knows
    whether to expect the "insert the CD" prompt. It deliberately does NOT read,
    analyse, or defeat the protection: whether a given install still requires the
    disc can only be confirmed by launching without it (a no-CD patch, which this
    toolkit neither makes nor detects, would change that).
    """
    data_dir = Path(data_dir)
    # The launcher sits in the game root for an installed copy, but inside Data on
    # the CD layout, so check both; the disc helper ships in Data. Dedupe by name.
    found: dict[str, Path] = {}
    for p in (data_dir.parent / DISC_LAUNCHER, data_dir / DISC_LAUNCHER, data_dir / DISC_HELPER):
        if p.is_file():
            found.setdefault(p.name, p)
    return list(found.values())


def video_mode(data_dir: Path) -> int | None:
    """The video mode index currently in force, or None.

    Config/options.cfg is what the game WRITES and reads at runtime;
    Data/options.def is only the shipped default. Checking the live file first
    matters as soon as anyone changes resolution in the menus -- otherwise this
    reports the factory setting forever.
    """
    root = Path(data_dir).parent
    for candidate in (root / "Config" / "options.cfg",
                      Path(data_dir) / "options.cfg",
                      root / "Config" / OPTIONS,
                      Path(data_dir) / OPTIONS):
        if candidate.is_file():
            m = re.search(rb"video[ _]mode\s+(\d+)", candidate.read_bytes())
            if m:
                return int(m.group(1))
    return None


def race_video_slot(data_dir: Path) -> int | None:
    """The label-table SLOT used for RACING, which is not the one used for menus.

    The game keeps two independent video modes (see the reference, §5.2.2), and
    options.cfg records them in two different numbering schemes -- a trap worth
    knowing about:

        video mode  1      <- the frontend, as a label-table SLOT (0-3)
        video_mode  4      <- the race view, as a MENU INDEX (1-4)

    They are related by `slot = 4 - index`, so `video_mode 4` is slot 0, the first
    entry in the table. Reading the underscore key as a slot points at the wrong
    resolution, and reading it with the space-key regex (`video[ _]mode`) matches
    whichever line comes first. This returns the race mode already converted to a
    slot, so it can be indexed into `resolution.read()` like the frontend one.
    """
    root = Path(data_dir).parent
    for candidate in (root / "Config" / "options.cfg",
                      Path(data_dir) / "options.cfg",
                      root / "Config" / OPTIONS,
                      Path(data_dir) / OPTIONS):
        if candidate.is_file():
            m = re.search(rb"video_mode\s+(\d+)", candidate.read_bytes())
            if m:
                index = int(m.group(1))
                return resolution.MODES - index if 1 <= index <= resolution.MODES else None
    return None


def vertex_budget(data_dir: str | Path) -> tuple[int | None, str]:
    """The per-object vertex ceiling this install can actually load.

    Returns (limit, why). `limit` is None when we genuinely do not know, which
    is better than guessing: warning someone off a model their build handles
    fine is its own kind of wrong.

    The ceiling is a property of race.bin, not of the car -- see
    mod.VERTEX_BUDGETS. The original release allows 1,200; the three confirmed
    community builds -- Sucahyo's v1.2.4 BETA (2007) and Val Novak's v1.2.5 2016
    and v1.2.6 2017 -- all document 20,000 (their readmes/changelogs state the
    same figure; see MODDING_HISTORY.md's race.bin version table). Any other
    version marker reports None rather than guess.
    """
    from . import mod as mod_mod

    data_dir = Path(data_dir)
    if not (data_dir / RACE_BIN).is_file():
        return None, "no race.bin here"
    version = race_bin_version(data_dir)
    if version is None:
        return mod_mod.VERTEX_BUDGETS["original"], "the original release"
    if any(v in version for v in ("1.2.4", "1.2.5", "1.2.6")):
        return mod_mod.VERTEX_BUDGETS["hd"], f"race.bin {version}"
    return None, f"race.bin {version}, whose limit this tool has not confirmed"


def leftovers(data_dir: Path) -> list[Path]:
    """Backup files safe to delete.

    The patch set's pristine snapshot is deliberately excluded: it matches the
    leftover patterns but it is the baseline every rebuild and every revert works
    from, so advising anyone to delete it would be actively harmful.
    """
    d = Path(data_dir)
    out: list[Path] = []
    for pattern in LEFTOVER_GLOBS:
        out.extend(p for p in d.glob(pattern) if p.is_file())
    return sorted(set(out) - {d / patchset.SNAPSHOT})


def check(data_dir: str | Path) -> Report:
    """Inspect an install. data_dir is the game's Data folder."""
    data_dir = Path(data_dir)
    root = data_dir.parent
    rep = Report(game_root=root, data_dir=data_dir)
    add = rep.findings.append

    # ---- the compatibility fix ------------------------------------------
    version = race_bin_version(data_dir)
    if not (data_dir / RACE_BIN).is_file():
        add(Finding(BAD, "race.bin is missing",
                    "race.bin IS the game -- the .exe beside it is only a launcher. "
                    "Without this file nothing will start.",
                    "Reinstall, or restore race.bin from a backup."))
    elif version is None:
        state = vrampatch.status(data_dir)
        if state == vrampatch.UNPATCHED:
            add(Finding(WARN, "This is the original race.bin, and it will not start on a modern GPU",
                        "Before checking the graphics card's memory the game adds 0x96000 to the "
                        "figure the driver reports. On a card with about 4GB or more that addition "
                        "wraps around, the check fails, and the game says the video card returned "
                        "an error. Removing the addition fixes it -- that is exactly what the "
                        "community race.bin does.",
                        "Apply the startup fix here, or install the community race.bin (v1.2.5), "
                        "which also raises the polygon and vertex limits.",
                        action="vram"))
        elif state == vrampatch.PATCHED:
            add(Finding(OK, "race.bin has the modern-GPU startup fix",
                        "The video-memory addition has been removed, so the card's real memory is "
                        "compared directly and the game starts. Note this is the startup fix only: "
                        "the community race.bin also raises the polygon and vertex limits, so "
                        "high-detail mods may still not load on this build."))
        else:
            add(Finding(WARN, "Unrecognised race.bin",
                        "No version marker, and the video-memory check is not where this tool "
                        "expects it, so its state cannot be determined.",
                        "If the game will not start, install the community race.bin (v1.2.5) "
                        "or use dgVoodoo2."))
    else:
        add(Finding(OK, f"race.bin is {version}",
                    "A community build. These fix the video-memory overflow that stops the "
                    "original running on modern graphics cards, and raise the polygon and "
                    "vertex limits (v1.2.5 allows 95,000-polygon tracks and 20,000 vertices "
                    "per object)."))

    # ---- the retail CD check (informational only) -----------------------
    # Viper Racing shipped on CD and checks for the disc at launch. We report
    # whether this looks like a retail-derived install so people know to expect
    # the "insert the CD" prompt; we do NOT analyse or bypass the protection --
    # no-CD patching is circumvention and out of scope. The definitive test for
    # any given install is launching with no disc in the drive.
    present = [p.name for p in disc_check(data_dir)]
    if present:
        add(Finding(INFO, "Retail disc check: the game CD is normally required",
                    "Viper Racing was released on CD and checks for the disc at launch. This "
                    "install carries the retail disc-check components (" + ", ".join(present) +
                    "), so expect an \"insert the CD\" prompt unless you have an official "
                    "release that doesn't need it. Note the community race.bin (v1.2.5) patches "
                    "the graphics-card check and the polygon/vertex limits -- NOT the disc "
                    "check -- so a patched race.bin still needs the CD. The reliable way to "
                    "know for THIS install: start the game with no disc in the drive; if it "
                    "runs, you don't need it.",
                    fix="Keep the Viper Racing CD in the drive to play, or use an official "
                        "release that doesn't require the disc."))
    else:
        add(Finding(INFO, "Retail disc check: components not found beside this folder",
                    "The retail launcher/disc helper weren't found next to this Data folder, so "
                    "this may be a repackaged or partial copy. Viper Racing's retail release "
                    "checks for the CD at launch; the reliable way to know whether this install "
                    "needs the disc is to start it with no disc in the drive."))

    # ---- the vrmod patch set --------------------------------------------
    try:
        ps = patchset.status(data_dir)
        applied = [n for n in ("needle", "aspect")
                   if ps[n] == "patched"] + (["mapfile"] if "appended" in ps["mapfile"] else [])
        partial = [n for n in ("needle", "aspect") if ps[n] in ("partial", "old-patch")]
        snap = not ps["baseline"].startswith("none")

        if partial:
            add(Finding(WARN, f"Patch set is half-applied: {', '.join(partial)}",
                        "One of the race.bin patches is in an intermediate or superseded "
                        "state. The patch set is meant to be rebuilt as a unit, not layered.",
                        "Run: vrmod patch <Data> --mode 1920x1080"))
        elif applied:
            add(Finding(OK, f"Patch set applied: {', '.join(applied)}",
                        f"Rebuildable from {ps['baseline']}." if snap else
                        "Applied, but there is no pristine snapshot, so this binary cannot "
                        "be rebuilt or reverted by the tool.",
                        None if snap else
                        "Put an untouched race.bin in place and run: vrmod patch <Data>"))
        else:
            add(Finding(INFO, "Modern-display enhancements not applied",
                        "A bundle of race.bin fixes that make the game look right on a modern "
                        "monitor, applied together as one reversible step: the startup fix (so "
                        "it runs on 4GB+ GPUs), a widescreen field of view, and the "
                        "tall-resolution fixes that keep the HUD and tachometer intact -- plus "
                        "it adds a modern mode (1920x1080 by default) to the game's resolution "
                        "table and appends a crash-symbol map. This is NOT the same as the "
                        "'Resolution' item below: the game ships four FIXED resolutions topping "
                        "out at 1024x768, and its in-game menu only picks one of those four. This "
                        "changes what is IN that table, so a modern resolution becomes available "
                        "to pick.",
                        "Apply it (reversible: vrmod patch <Data> --revert). Power users can "
                        "choose a different resolution with vrmod patch <Data> --mode WIDTHxHEIGHT.",
                        action="patch"))

        # the display-scaling trap -- invisible unless you go looking for it.
        # Positively confirm the good case too, so a "verify install" run shows
        # DPI was checked rather than staying silent. Note the flag is read at
        # process start, so it only takes effect on the NEXT launch after setting.
        scaled = patchset.scaling_active()
        if scaled and not patchset.dpi_aware(data_dir):
            add(Finding(WARN, "The desktop is scaled and the game is not marked DPI-aware",
                        "A DPI-unaware process is handed a virtualised desktop smaller than "
                        "the real one, so the game draws for the mode it asked for but only "
                        "part of that lands on screen: the view sits right of centre and "
                        "bottom-anchored HUD elements vanish. Both look like game bugs and "
                        "are not.",
                        "Run: vrmod patch <Data> --dpi-aware, or set it by hand -- right-click "
                        "race.bin OR Viper Racing.exe -> Properties -> Compatibility -> Override "
                        "high DPI scaling behavior -> Application (either one works). Takes effect "
                        "on the next launch, not the current one.", action="dpi"))
        elif scaled:
            add(Finding(OK, "The desktop is scaled, and the game is marked DPI-aware",
                        "A DPI-unaware process would be handed a virtualised, smaller desktop and "
                        "draw partly off-screen; the HIGHDPIAWARE compatibility flag (set on "
                        "race.bin or its launcher) prevents that."))
    except Exception as e:
        add(Finding(INFO, "Could not read the patch-set state", f"{type(e).__name__}: {e}"))

    # ---- dgVoodoo2, the other route -------------------------------------
    present = [n for n in DGVOODOO_DLLS if (data_dir / n).is_file()]
    if present:
        add(Finding(INFO, "dgVoodoo2 is installed",
                    f"Found {', '.join(present)} in the Data folder. dgVoodoo2 translates the "
                    "game's DirectDraw/Direct3D calls, which fixes the same startup problem "
                    "and generally renders more accurately."))
    elif version:
        add(Finding(INFO, "dgVoodoo2 is not installed",
                    "Not a problem -- the patched race.bin already covers startup. Worth "
                    "knowing about if you hit rendering glitches, since it replaces the "
                    "ancient DirectDraw path entirely.",
                    "Optional: put dgVoodoo2's DDraw.dll and D3DImm.dll in the Data folder."))

    # ---- audio: the retail 1.1 DirectSound crackle ----------------------
    # Retail 1.1 streams its .sfx effects through DirectSound, which Windows has
    # only emulated since Vista; on modern Windows it crackles constantly, at
    # every resolution (so it is NOT the pitch-tracks-framerate effect). v1.2.5
    # fixed this in its own mixer code. The general, non-invasive fix is a
    # drop-in dsound.dll wrapper: DSOUND.dll is a static import, and Windows
    # resolves static imports app-directory-first, so a local dsound.dll shadows
    # the system one. dsoal ships dsound.dll + dsoal-aldrv.dll (use the 32-bit
    # build -- the game is a 32-bit process). Confirmed to fix retail 1.1.
    wrapper = (data_dir / "dsound.dll").is_file()
    is_dsoal = (data_dir / "dsoal-aldrv.dll").is_file()
    if version is None:                                # retail 1.1 -- the affected build
        if wrapper:
            which = "dsoal" if is_dsoal else "a DirectSound wrapper (local dsound.dll)"
            add(Finding(OK, "Audio: DirectSound wrapper present",
                        f"Found {which} in the Data folder. Retail 1.1's DirectSound sound "
                        "effects crackle on modern Windows (Vista+), where legacy DirectSound is "
                        "emulated; a local dsound.dll shadows the system one and reimplements it "
                        "cleanly, which fixes the crackle."))
        else:
            add(Finding(WARN, "Audio will crackle: retail 1.1 on modern Windows",
                        "Retail 1.1 streams its sound effects through DirectSound, which has been "
                        "emulated since Windows Vista and crackles constantly here -- at every "
                        "resolution, so it is not a performance problem. The community v1.2.5 "
                        "build fixed this in its own audio code.",
                        "Use the community race.bin (v1.2.5), OR drop a DirectSound wrapper (dsoal) "
                        "into this Data folder: dsound.dll + dsoal-aldrv.dll. Viper Racing is a "
                        "32-BIT game, so download the 32-bit (Win32 / x86) build -- NOT the 64-bit "
                        "one. Non-invasive and reversible (delete the two DLLs to undo).",
                        link="https://github.com/ThreeDeeJay/dsoal/releases"))
    elif wrapper:
        add(Finding(INFO, "Audio: DirectSound wrapper present (not needed on this build)",
                    "A local dsound.dll is in the Data folder. Harmless, but this community build "
                    "already fixes the DirectSound crackle in its own code, so the wrapper is not "
                    "required here."))

    # ---- resolution ------------------------------------------------------
    try:
        modes = resolution.read(data_dir)
    except Exception:
        modes = None
    mode = video_mode(data_dir)
    if modes and modes != STOCK_MODES:
        listed = ", ".join(f"{w}x{h}" for w, h in modes)
        stock = ", ".join(f"{w}x{h}" for w, h in STOCK_MODES)
        add(Finding(INFO, "race.bin's resolution table has been edited",
                    f"The four modes are now {listed}, where stock is {stock}. Expected if "
                    "you have used a resolution changer."))
    if mode is None:
        add(Finding(INFO, "No video mode recorded yet",
                    "options.def has no video mode line, which usually just means the game "
                    "has not been run and saved settings yet."))
    elif modes and 0 <= mode < len(modes):
        w, h = modes[mode]
        race_slot = race_video_slot(data_dir)
        detail = (f"race.bin defines {', '.join(f'{a}x{b}' for a, b in modes)}.")
        if race_slot is not None and race_slot != mode and 0 <= race_slot < len(modes):
            rw, rh = modes[race_slot]
            add(Finding(OK, f"Resolution: {rw} x {rh} racing, {w} x {h} in the menus",
                        detail + " The game keeps TWO independent video modes, and "
                        "options.cfg records them in DIFFERENT numbering: `video mode` is "
                        f"the frontend as a slot 0-3 (here {mode}), `video_mode` is the race "
                        f"view as a menu index 1-4 (here {len(modes) - race_slot}, i.e. slot "
                        f"{race_slot}). The menu resolution is not what you race at."))
        else:
            add(Finding(OK, f"Resolution: {w} x {h}",
                        f"Video mode {mode} of the four. " + detail))
    else:
        add(Finding(INFO, f"Resolution: video mode {mode}",
                    "Could not read race.bin's resolution table to say what that means."))

    # ---- what is installed ----------------------------------------------
    try:
        slots = switcher.status(data_dir)
        modded = [s for s in slots if not s.is_stock]
        if modded:
            names = ", ".join(f"{s.slot} ({s.occupied_by})" if s.occupied_by else s.slot
                              for s in modded)
            add(Finding(INFO, f"{len(modded)} of {len(slots)} track slots hold add-ons",
                        names + ". Restore returns any of them to the stock track."))
        else:
            add(Finding(OK, "All 8 track slots are stock", "Nothing installed over them."))

        # ---- drivers.res, which only matters once a slot holds an add-on ----
        lines = drivers_res_lines(data_dir)
        if lines is None:
            add(Finding(WARN, "drivers.res is missing or unreadable",
                        "The game reads its AI driver data from this file. An empty one is fine "
                        "and is what add-on tracks want, but it should exist."))
        elif lines and modded:
            add(Finding(WARN, "The AI will drive the wrong line on your add-on tracks",
                        f"drivers.res holds {lines} baked AI racing lines, one per skill tier per "
                        f"section of each STOCK track. A slot holding a different track keeps "
                        f"following the old track's line: the AI swerves off the road within "
                        f"seconds of the start, and on some layouts the game crashes outright. "
                        f"Nothing else gives it away -- the geometry, collision, timing and your "
                        f"own car are all fine.",
                        "Empty drivers.res. With no baked line to prefer, the AI follows each "
                        "track's own racing line, which is what an add-on ships. The original is "
                        "backed up first, and stock tracks are unaffected -- they carry their own "
                        "lines too.",
                        action="drivers"))
        elif lines:
            add(Finding(OK, f"drivers.res holds {lines} baked AI lines",
                        "Correct for an all-stock install. If you install an add-on track, this "
                        "file has to be emptied or the AI will follow the stock track's line."))
        else:
            add(Finding(OK, "drivers.res is empty, which add-on tracks need",
                        "The AI takes its line from each track's own default.ili, so add-ons and "
                        "stock tracks both drive correctly."))
    except Exception as e:
        add(Finding(WARN, "Could not read the track slots", f"{type(e).__name__}: {e}"))

    cars = switcher.car_paths(data_dir)
    active = [p for p, on in cars if on]
    aside = len(cars) - len(active)
    add(Finding(OK, f"{len(active)} cars in the game",
                f"Every .car in the Data folder loads."
                + (f" {aside} set aside in Disabled/." if aside else "")))

    # ---- housekeeping ----------------------------------------------------
    junk = leftovers(data_dir)
    if junk:
        mb = sum(p.stat().st_size for p in junk) / 1048576
        add(Finding(INFO, f"{len(junk)} backup files, {mb:.0f} MB",
                    "Left by this tool and by TrackMan -- your undo history, so they are not "
                    "junk exactly, but each is a full copy of an archive and they add up.",
                    "Delete any you no longer need; the newest of each is the one to keep."))
    return rep
