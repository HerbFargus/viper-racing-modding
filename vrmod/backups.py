"""One place that knows where a car's or track's backup lives.

Every edit this toolkit makes to a `.car` or `.trk` copies the original first,
and until now each copy landed beside its file. That is fine for one edit and
untenable as a habit: a real install had **112 files in its Data root, 56 of
them backups** -- outnumbering the actual game assets more than two to one --
and a single whole-install sweep accounts for 21 of those on its own.

So archive backups now live in a `Backups/` folder inside the Data directory.
Safe, for the same reason `Disabled/` is: the engine scans Data/ for `*.car`
and `*.trk` but does not recurse, so a copy in a subfolder is invisible to it.

WHAT IS AND IS NOT MOVED. Archive backups are -- the `<stem>_original<ext>.bak`
copies an edit leaves, and the `.dekey-backup` copies a sweep leaves. Those are
45 of the 56 files and 96 of the 119 MB, through two code paths.

BINARY patch backups move too: `.vram-backup`, `.aspect-backup`,
`.carlist-backup`, `.headon-backup`, `.modassert-backup`, `.needle-backup`,
`.aifield-backup`, `.surface-backup`, `.map-backup`, `.res-backup`. Nine modules
write them and each checks "have I already backed this up?" by looking beside
the file, so all of those lookups go through locate() instead.

The one that needed real care is `patchset.find_pristine_backup`, which hunts
for an UNPATCHED engine among the copies the toolkit has already taken -- it
globs beside race.bin. Left alone it would have found nothing and told the user
to go and find their disc while holding a perfectly good copy of their own, and
it would have done that silently. It searches both locations now.

READING IS BACKWARD-COMPATIBLE and has to be: anyone who used the tool before
this has loose backups already. Every lookup checks the folder first and then
falls back to the old location, so an existing install keeps working untouched
and `migrate()` is an offer rather than a requirement.
"""
from __future__ import annotations

import shutil
from pathlib import Path

DIR_NAME = "Backups"

# What an edit leaves behind, and what a sweep leaves behind. Both are whole
# copies of an archive, which is why they are the ones worth relocating.
EDIT_SUFFIX = ".bak"
SWEEP_SUFFIX = ".dekey-backup"

# What the binary patchers leave beside race.bin / race.exe. Each is written by
# a different module, and each of those modules uses "does my backup already
# exist?" as its write-once guard -- so every one of them has to ask through
# locate(), or it will take a second backup of an already-patched binary and
# quietly destroy the only pristine copy.
BINARY_SUFFIXES = (
    ".vram-backup", ".aspect-backup", ".carlist-backup", ".headon-backup",
    ".modassert-backup", ".needle-backup", ".aifield-backup",
    ".surface-backup", ".map-backup", ".sky-backup", ".res-backup",
    ".table-backup",
    ".writepaths-backup",
)


def folder(data_dir: Path, create: bool = False) -> Path:
    d = Path(data_dir) / DIR_NAME
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def is_archive_backup(path: Path) -> bool:
    """A whole-archive copy, as opposed to a patched binary's backup."""
    n = path.name.lower()
    if n.endswith(SWEEP_SUFFIX):
        return True
    return n.endswith(EDIT_SUFFIX) and "_original" in n


def is_binary_backup(path: Path) -> bool:
    n = path.name.lower()
    return any(n.endswith(sfx) for sfx in BINARY_SUFFIXES)


def is_backup(path: Path) -> bool:
    return is_archive_backup(path) or is_binary_backup(path)


def locate(original: Path, suffix: str, data_dir: Path | None = None) -> Path | None:
    """An existing backup of `original` with this suffix, or None.

    Folder first, then beside the file. The fallback is not politeness: every
    binary patcher uses this as its write-once guard, and an install patched
    before this change has its only pristine engine sitting loose in Data/.
    Missing it means taking a fresh "backup" of an already-patched binary.
    """
    original = Path(original)
    data_dir = Path(data_dir) if data_dir else original.parent
    for cand in (folder(data_dir) / (original.name + suffix),
                 original.with_name(original.name + suffix)):
        if cand.is_file():
            return cand
    return None


def path_for(original: Path, suffix: str, data_dir: Path | None = None) -> Path:
    """Where a NEW backup of `original` should be written (folder created)."""
    original = Path(original)
    data_dir = Path(data_dir) if data_dir else original.parent
    return folder(data_dir, create=True) / (original.name + suffix)


def store(source: Path, suffix: str, data_dir: Path | None = None) -> Path:
    """Copy `source` into the Backups folder and return where it landed.

    The name keeps its suffix even inside the folder. That is deliberate
    belt-and-braces: if the file is ever moved back into Data/ by hand, the
    suffix is still what stops the engine loading `viper_original.car` and
    panicking for a `viper_original0.mod` it cannot find.
    """
    source = Path(source)
    data_dir = Path(data_dir) if data_dir else source.parent
    dest = _unique(folder(data_dir, create=True) / (source.name + suffix))
    shutil.copy2(source, dest)
    return dest


def store_as(source: Path, name: str, data_dir: Path | None = None) -> Path:
    """Copy `source` into the folder under an explicit name.

    The edit path keeps its historical `<stem>_original<ext>.bak` shape rather
    than gaining a second convention: the name is what `find_original_backup`
    matches on, and an install will hold both old loose copies and new foldered
    ones for a long time.
    """
    source = Path(source)
    data_dir = Path(data_dir) if data_dir else source.parent
    dest = _unique(folder(data_dir, create=True) / name)
    shutil.copy2(source, dest)
    return dest


def find(data_dir: Path, suffix: str | None = None) -> list[Path]:
    """Archive backups, in the folder AND loose in Data/ (old installs)."""
    data_dir = Path(data_dir)
    out: list[Path] = []
    for d in (folder(data_dir), data_dir):
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or not is_archive_backup(p):
                continue
            if suffix and not p.name.lower().endswith(suffix.lower()):
                continue
            out.append(p)
    return out


def target_of(backup: Path, data_dir: Path | None = None) -> Path:
    """The live file a backup restores to.

    Handles both shapes, because both exist on disk after an upgrade:
    `viper.car.dekey-backup` -> `viper.car`, and the older
    `viper_original.car.bak` -> `viper.car`.
    """
    backup = Path(backup)
    data_dir = Path(data_dir) if data_dir else (
        backup.parent.parent if backup.parent.name == DIR_NAME else backup.parent)
    name = backup.name
    if name.lower().endswith(SWEEP_SUFFIX):
        name = name[:-len(SWEEP_SUFFIX)]
    elif name.lower().endswith(EDIT_SUFFIX):
        name = name[:-len(EDIT_SUFFIX)]
        # strip the collision counter an older _unique_path may have added,
        # then the "_original" marker itself
        stem = Path(name).stem
        ext = Path(name).suffix
        for cut in ("_original",):
            if cut in stem:
                stem = stem.split(cut)[0]
        name = stem + ext
    return Path(data_dir) / name


def migrate(data_dir: Path, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """Move loose archive backups into the folder. Returns [(from, to)]."""
    data_dir = Path(data_dir)
    moved = []
    for p in sorted(data_dir.iterdir()):
        if not p.is_file() or not is_backup(p):
            continue
        dest = _unique(folder(data_dir, create=not dry_run) / p.name)
        if not dry_run:
            shutil.move(str(p), str(dest))
        moved.append((p, dest))
    return moved


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1
