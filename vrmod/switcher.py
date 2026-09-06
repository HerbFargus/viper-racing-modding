"""Track slot management -- installing add-on .tra tracks into the game's
eight fixed slots, and restoring them.

This is a modern replacement for TrackMan (Frank P. Wolf, 2002), whose exact
on-disk contract was reverse-engineered from a real installed game and is
reproduced here so the two tools stay interoperable: a track installed by
TrackMan can be restored by this module and vice versa.

A full install touches THREE things, not just the track file:

    <slot>.trk    <- the .tra's bytes        backup: <slot>_AS_<name>.btr
    ui.res        <- <name>.stp as <slot>.stp  backup: <slot>.trm  (loose,
                                                "!IGM"-prefixed form)
    english.lng   <- the slot's display name    backup: english.trm

The language file stores keys like "Tracks:Bemidji:Name" followed by the
value. TrackMan rewrites the value IN PLACE, so english.lng never changes
size and the new name is truncated to the original field's width. We match
that behaviour rather than trying to grow the file, because the .lng string
table's length encoding isn't mapped and an in-place write is provably safe.

WHY THIS EXISTS (the bug worth fixing): TrackMan backs up whatever is
currently sitting in a slot, with no check that it's actually the stock
file. Install a second track over an already-modded slot and the real
original is silently destroyed -- observed on a live install, where
bemidji_AS_bemidji_edited.btr contained a modded track rather than stock
Bemidji. Every write here is therefore guarded by verify_slot(), which
checks the file against STOCK_TRACKS below before it will create a backup.
Use force=True to override, and expect to need the original disc after.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import archive, envelope

# sha256 + size of every stock .trk, taken from a clean retail install.
# verify_slot() uses these to tell "untouched stock" from "already modded",
# which is the check TrackMan is missing.
STOCK_TRACKS: dict[str, tuple[str, int]] = {
    "bemidji":  ("ae3cb0c9318c487f6cfe217edf65f2bbbe4b7b44de7f6bfea78e473552944464", 3355646),
    "dundas":   ("075737c9357324ab4984fcc5c157c2e0126c3ef05edb25583fb7b1673109f3c5", 3824751),
    "hastings": ("4aa9e5fae7098cb6f42bbbfd75411244a59f0968ea62f2e1d3f5fafdedf49eaa", 3890698),
    "heaven":   ("db19ca1046deb84d48b502060d022a075c08eccb3f2f6335537e2ef36843ce6a", 2734649),
    "kenyon":   ("48c0d4ce9f7a4cbf7dd52c6e2248371bf80b291075d2f06f137cde66c237825d", 3748929),
    "limbo":    ("d2f517d8362e13cf2d60ba0602d373e23926553ad9cf9d933ccdf10ef71a1d20", 3420070),
    "nfield":   ("cd37020edea0c26bf5e71b5ec9e7eee861a812c7e8a9c13365bb32d8c4a3b0ce", 4606262),
    "uptown":   ("4334fd3e4c5513bf4dd9ce3fbfdc0b2bf09450385064b7a2aa650f27b6133c7b", 3580612),
}

# In-game display names, as they appear in the menus and in TrackMan's UI.
# All eight are read from english.lng at runtime rather than hardcoded, so a
# slot renamed by an install reports its real current name. The full mapping
# is now confirmed -- hastings/limbo/uptown are Ridge Valley/Dayton/Silverdale
# -- cross-checked by matching each .lng name's computed track length against
# the mileages shown on the game's own Track Info screen: 8/8 agree to 0.1 mi.
LANG_FILE = "english.lng"
LANG_BACKUP = "english.trm"
UI_RES = "ui.res"
UI_BACKUP = "ui.trm"

MARKER = b"!IGM"


# Car roster. The game lists every .car it finds in the Data folder in its car
# selector, and there is no registry anywhere to edit instead: unlike track
# slots (which have Tracks:<slot>:Name entries in english.lng) cars appear in
# no config file -- options.def stores only car_no, the last-selected index. So
# presence in the folder is the only lever there is.
#
# Deactivating therefore means getting a file out of that folder, and we do it
# by MOVING it into a subfolder rather than renaming it in place. Confirmed by
# testing against the running game: a .car inside a subfolder of Data is not
# loaded, so the scan does not recurse.
#
# Why not rename, which is what CarMan does (.car -> .cat)? Two reasons.
# ".cat" is a registered Windows type (Security Catalog), so deactivated cars
# get a misleading icon, open the catalog viewer on a double-click, and draw
# the attention of security tooling. And a move leaves the filename completely
# untouched, which matters for a game that ties behaviour to a car's identity
# -- the archive's own members are <prefix>0.mod and friends, and renaming a
# car has already caused one real crash in this project. Extension-only
# renaming is safe in practice; not touching the name at all is safe by
# construction. Both operations are a same-volume rename, so neither costs
# anything.
CAR_EXT = ".car"
CARMAN_EXT = ".cat"          # recognised on read only -- see set_car_active()
DISABLED_DIR = "Disabled"


class SwitcherError(RuntimeError):
    """An operation would be unsafe or can't be completed."""


def disabled_dir(data_dir: Path | str) -> Path:
    return Path(data_dir) / DISABLED_DIR


def car_paths(data_dir: Path | str) -> list[tuple[Path, bool]]:
    """Every car in the folder as (path, active), actives first.

    A .cat alongside is reported as inactive too. That is not CarMan support --
    nothing here ever writes one -- it just means a folder someone previously
    managed with CarMan shows all its cars instead of silently hiding them,
    and activating one converts it to the scheme used here.
    """
    d = Path(data_dir)
    out = [(p, True) for p in sorted(d.glob(f"*{CAR_EXT}"), key=lambda f: f.stem.lower())]
    out += [(p, False) for p in sorted(d.glob(f"*{CARMAN_EXT}"), key=lambda f: f.stem.lower())]
    dd = disabled_dir(d)
    if dd.is_dir():
        out += [(p, False) for p in sorted(dd.glob(f"*{CAR_EXT}"), key=lambda f: f.stem.lower())]
    return out


def find_car(data_dir: Path | str, name: str) -> Path | None:
    """Locate a car by filename in either the active folder or Disabled/.

    Callers hand back a bare filename that came from car_paths(), so this also
    serves as the containment check: anything that doesn't land in one of the
    two known directories returns None.
    """
    d = Path(data_dir)
    for candidate in (d / name, disabled_dir(d) / name):
        if candidate.is_file() and candidate.parent.resolve() in (
            d.resolve(), disabled_dir(d).resolve()
        ):
            return candidate
    return None


def car_companions(car: Path) -> list[Path]:
    """Files that belong with a car and should travel with it.

    The <name>.jpg + <name>-readme.txt pairing is a COMMUNITY DISTRIBUTION
    convention, not something the game reads -- it comes from a modder (Val)
    who used them for the gallery on his site, and add-on cars have shipped
    that way since. So moving them is about keeping a downloaded mod intact
    rather than about whether the game works: deactivating a car would
    otherwise strand its picture and its documentation in the folder it left,
    and they would not come back with it.

    Matching is on the exact stem plus a "<stem>-" prefix, never a bare
    prefix -- otherwise viper.car would claim viper_original.car.
    """
    stem = car.stem.lower()
    out = []
    for p in car.parent.iterdir():
        if not p.is_file() or p == car:
            continue
        n = p.name.lower()
        if p.suffix.lower() in (CAR_EXT, CARMAN_EXT):
            continue                       # another car is never a companion
        if p.stem.lower() == stem or n.startswith(stem + "-"):
            out.append(p)
    return out


def set_car_active(data_dir: Path | str, name: str, active: bool) -> str:
    """Move one car between the Data folder and Data/Disabled/.

    The car's companion files (its .jpg preview, its readme) move with it --
    see car_companions(). Returns the resulting filename. Refuses rather than
    overwrites if the destination is taken -- two files with the same name
    would otherwise let a move silently destroy one of them. A .cat picked up
    from an older CarMan setup is converted to a plain .car on activation.
    """
    d = Path(data_dir)
    src = find_car(d, name)
    if src is None:
        raise SwitcherError(f"{name} not found in the Data folder or {DISABLED_DIR}/")
    if src.suffix.lower() not in (CAR_EXT, CARMAN_EXT):
        raise SwitcherError(f"{name} is not a car file")

    dst_dir = d if active else disabled_dir(d)
    dst = dst_dir / (src.stem + CAR_EXT)
    if dst == src:
        return src.name
    if dst.exists():
        where = "the Data folder" if active else f"{DISABLED_DIR}/"
        raise SwitcherError(
            f"can't move {src.name} into {where}: {dst.name} is already there. "
            "Move or remove one of them first."
        )
    # Collect companions BEFORE moving the car, since the scan is directory-based.
    companions = car_companions(src)
    dst_dir.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    for c in companions:
        target = dst_dir / c.name
        if not target.exists():
            c.rename(target)
        # If something of that name is already there, leave the companion put
        # rather than clobber it. The car itself has moved either way, which is
        # the part that decides whether the game loads it.
    return dst.name


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class SlotStatus:
    slot: str
    display_name: str
    present: bool
    is_stock: bool
    size: int
    # Name of the .tra currently installed, recovered from the backup
    # filename TrackMan-style installs leave behind.
    occupied_by: str | None = None
    backup: Path | None = None


@dataclass
class InstallPlan:
    """What an install would do. Produced by plan_install() so the UI can
    show it and the caller can confirm before anything is written."""
    slot: str
    tra: Path
    display_name: str
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    screenshot: Path | None = None
    backup_track: Path | None = None
    blocked: str | None = None


def _lang_key(slot: str) -> bytes:
    return f"Tracks:{slot.capitalize()}:Name".encode("ascii")


def read_display_name(data_dir: Path | str, slot: str) -> str:
    """Read a slot's current in-game name out of english.lng.

    The table stores the key immediately followed by a one-byte separator
    and then the value, terminated by the next separator -- so the value's
    extent is found by scanning, not by a length field (which isn't mapped).
    """
    lang = Path(data_dir) / LANG_FILE
    if not lang.exists():
        return slot.capitalize()
    blob = lang.read_bytes()
    key = _lang_key(slot)
    i = blob.find(key)
    if i < 0:
        return slot.capitalize()
    start = i + len(key) + 1
    m = re.compile(rb"[ -~]*").match(blob, start)
    return (m.group(0) if m else b"").decode("ascii", errors="replace") or slot.capitalize()


def _write_display_name(data_dir: Path, slot: str, name: str) -> tuple[str, str] | None:
    """Overwrite a slot's name in place. Returns (old, new) or None if the
    key isn't present. The value is truncated (and space-padded) to the
    original field width so the file's size never changes -- see module
    docstring for why growing it isn't safe."""
    lang = data_dir / LANG_FILE
    blob = bytearray(lang.read_bytes())
    key = _lang_key(slot)
    i = blob.find(key)
    if i < 0:
        return None
    start = i + len(key) + 1
    m = re.compile(rb"[ -~]*").match(bytes(blob), start)
    old = m.group(0)
    width = len(old)
    new = name.encode("ascii", errors="replace")[:width].ljust(width, b" ")
    blob[start:start + width] = new
    lang.write_bytes(bytes(blob))
    return old.decode("ascii", "replace"), new.decode("ascii", "replace").rstrip()


def verify_slot(data_dir: Path | str, slot: str) -> tuple[bool, str]:
    """Is this slot holding the untouched stock track? Returns (is_stock, detail)."""
    p = Path(data_dir) / f"{slot}.trk"
    if not p.exists():
        return False, "missing"
    data = p.read_bytes()
    want_hash, want_size = STOCK_TRACKS[slot]
    if len(data) != want_size:
        return False, f"size {len(data):,} != stock {want_size:,}"
    if _sha(data) != want_hash:
        return False, "same size but different contents"
    return True, "stock"


def status(data_dir: Path | str) -> list[SlotStatus]:
    data_dir = Path(data_dir)
    out = []
    for slot in STOCK_TRACKS:
        p = data_dir / f"{slot}.trk"
        is_stock, _ = verify_slot(data_dir, slot)
        backups = sorted(data_dir.glob(f"{slot}_AS_*.btr"))
        occupied = None
        if backups and not is_stock:
            occupied = backups[-1].stem[len(slot) + 4:]
        out.append(SlotStatus(
            slot=slot,
            display_name=read_display_name(data_dir, slot),
            present=p.exists(),
            is_stock=is_stock,
            size=p.stat().st_size if p.exists() else 0,
            occupied_by=occupied,
            backup=backups[-1] if backups else None,
        ))
    return out


def available_tracks(data_dir: Path | str) -> list[Path]:
    return sorted(Path(data_dir).glob("*.tra"))


def plan_install(data_dir: Path | str, tra: Path | str, slot: str) -> InstallPlan:
    """Work out exactly what installing `tra` into `slot` would do, without
    writing anything."""
    data_dir, tra = Path(data_dir), Path(tra)
    if slot not in STOCK_TRACKS:
        raise SwitcherError(f"unknown slot {slot!r}; expected one of {', '.join(STOCK_TRACKS)}")
    name = tra.stem
    plan = InstallPlan(slot=slot, tra=tra, display_name=name)

    if not tra.exists():
        plan.blocked = f"{tra.name} does not exist"
        return plan

    # Validate it really is a track bundle before touching the install.
    try:
        from . import track as track_mod
        entries = archive.read_bytes(tra.read_bytes())
        names = {e.name.lower() for e in entries}
        missing = [m for m in track_mod.REQUIRED_MEMBERS if m not in names]
        if missing:
            plan.blocked = f"not a usable track: missing {', '.join(missing)}"
            return plan
    except Exception as ex:
        plan.blocked = f"unreadable archive: {type(ex).__name__}: {ex}"
        return plan

    is_stock, detail = verify_slot(data_dir, slot)
    backup = data_dir / f"{slot}_AS_{name}.btr"
    plan.backup_track = backup
    if is_stock:
        plan.steps.append(f"back up stock {slot}.trk -> {backup.name}")
    else:
        plan.warnings.append(
            f"{slot}.trk is NOT the stock file ({detail}). Backing it up would save a "
            f"modified track as if it were the original. Restore this slot first, or "
            f"pass force=True to overwrite anyway."
        )
    plan.steps.append(f"write {tra.name} -> {slot}.trk")

    stp = data_dir / f"{name}.stp"
    if stp.exists():
        plan.screenshot = stp
        plan.steps.append(f"swap {stp.name} into {UI_RES} as {slot}.stp (backup {slot}.trm)")
    else:
        plan.warnings.append(f"no {name}.stp alongside the track -- the menu screenshot will stay as-is")

    old = read_display_name(data_dir, slot)
    width = len(old)
    shown = name[:width]
    plan.steps.append(f"rename in {LANG_FILE}: {old!r} -> {shown!r}")
    if len(name) > width:
        plan.warnings.append(
            f"display name truncated to {width} chars ({name!r} -> {shown!r}); the .lng "
            f"string table is edited in place so names can't grow"
        )
    return plan


def install(data_dir: Path | str, tra: Path | str, slot: str, *,
            force: bool = False, dry_run: bool = False) -> InstallPlan:
    """Install a .tra into a slot, backing up everything it replaces."""
    data_dir, tra = Path(data_dir), Path(tra)
    plan = plan_install(data_dir, tra, slot)
    if plan.blocked:
        raise SwitcherError(plan.blocked)
    if plan.warnings and not force:
        blocking = [w for w in plan.warnings if "NOT the stock file" in w]
        if blocking:
            raise SwitcherError(blocking[0])
    if dry_run:
        return plan

    name = tra.stem
    # 1. track file
    backup = data_dir / f"{slot}_AS_{name}.btr"
    slot_file = data_dir / f"{slot}.trk"
    if slot_file.exists() and not backup.exists():
        shutil.copy2(slot_file, backup)
    shutil.copy2(tra, slot_file)

    # 2. menu screenshot, swapped into ui.res
    stp = data_dir / f"{name}.stp"
    if stp.exists():
        _install_screenshot(data_dir, slot, stp)

    # 3. display name
    lang_backup = data_dir / LANG_BACKUP
    if not lang_backup.exists() and (data_dir / LANG_FILE).exists():
        shutil.copy2(data_dir / LANG_FILE, lang_backup)
    _write_display_name(data_dir, slot, name)
    return plan


def _install_screenshot(data_dir: Path, slot: str, stp: Path) -> None:
    """Replace <slot>.stp inside ui.res, saving the original as <slot>.trm
    in the loose "!IGM"-prefixed form TrackMan uses."""
    ui = data_dir / UI_RES
    entries = archive.read_bytes(ui.read_bytes())
    target = f"{slot}.stp"
    existing = next((e for e in entries if e.name.lower() == target), None)
    if existing is None:
        raise SwitcherError(f"{UI_RES} has no {target} to replace")

    trm = data_dir / f"{slot}.trm"
    if not trm.exists():
        trm.write_bytes(MARKER + existing.payload)
    if not (data_dir / UI_BACKUP).exists():
        shutil.copy2(ui, data_dir / UI_BACKUP)

    raw = stp.read_bytes()
    # Loose .stp files ship truncated to start at "!IGM"; rebuild a full
    # envelope so replace_entry() sees a normal standalone resource.
    if raw[:4] == MARKER:
        standalone = envelope.build(existing.tag, existing.version, raw[4:])
    else:
        standalone = raw
    layout = archive.read_layout(ui.read_bytes())
    new_entries = archive.replace_entry(entries, existing.name, standalone)
    ui.write_bytes(archive.to_bytes(new_entries, partitioned=layout.partitioned))


def restore(data_dir: Path | str, slot: str) -> list[str]:
    """Put a slot back to whatever its backup holds. Returns what was done."""
    data_dir = Path(data_dir)
    done = []
    backups = sorted(data_dir.glob(f"{slot}_AS_*.btr"))
    if backups:
        src = backups[-1]
        shutil.copy2(src, data_dir / f"{slot}.trk")
        done.append(f"restored {slot}.trk from {src.name}")
        for b in backups:
            b.unlink()
    trm = data_dir / f"{slot}.trm"
    if trm.exists():
        _install_screenshot_raw(data_dir, slot, trm.read_bytes())
        trm.unlink()
        done.append(f"restored {slot}.stp in {UI_RES}")
    lang_backup = data_dir / LANG_BACKUP
    if lang_backup.exists():
        original = read_display_name_from(lang_backup.read_bytes(), slot)
        if original:
            _write_display_name(data_dir, slot, original)
            done.append(f"restored name {original!r}")
    if not done:
        done.append(f"{slot}: nothing to restore")
    return done


def read_display_name_from(blob: bytes, slot: str) -> str | None:
    key = _lang_key(slot)
    i = blob.find(key)
    if i < 0:
        return None
    start = i + len(key) + 1
    m = re.compile(rb"[ -~]*").match(blob, start)
    return (m.group(0) if m else b"").decode("ascii", "replace").rstrip() or None


def _install_screenshot_raw(data_dir: Path, slot: str, raw: bytes) -> None:
    ui = data_dir / UI_RES
    blob = ui.read_bytes()
    entries = archive.read_bytes(blob)
    existing = next((e for e in entries if e.name.lower() == f"{slot}.stp"), None)
    if existing is None:
        return
    payload = raw[4:] if raw[:4] == MARKER else envelope.parse(raw).payload
    standalone = envelope.build(existing.tag, existing.version, payload)
    layout = archive.read_layout(blob)
    ui.write_bytes(archive.to_bytes(
        archive.replace_entry(entries, existing.name, standalone),
        partitioned=layout.partitioned,
    ))


def restore_all(data_dir: Path | str) -> list[str]:
    out = []
    for slot in STOCK_TRACKS:
        out.extend(restore(data_dir, slot))
    return out
