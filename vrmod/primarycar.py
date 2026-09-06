"""Make a mod car the PRIMARY car, so the whole AI field drives it.

WHY. Viper Racing has no in-game way to choose the AI's car: The Pack auto-fills
every slot with the primary car, which the engine loads from `viper.car` by its
"viper" member-name prefix (`viper.cf`, `viper0..7.mod`, ...). Confirmed in game --
give `viper.car` a different body and every AI inherits it; a car with the wrong
internal names panics with `Couldn't find viper.cf`. So to put a mod car under the
AI you must repackage it onto viper's identity. (This is the trick modders used by
hand: keep the internal names "viper" and the AI race your car.)

HOW (the "overlay", validated in game with Mario). Start from a pristine viper.car
so every member the engine requires exists, then:
  * for each viper member `viper<suffix>`, swap in the mod's `<modprefix><suffix>`
    content under viper's name (body LODs, sub-parts, .cf/.ccs, sounds, tables);
  * for shared fixed names (cockpit.tab, ball.mod, Needle.mod, horn.sfx) take the
    mod's version;
  * keep viper's own copy of anything the mod lacks (vipers.mod, viper.ugs, and the
    Viperd* paint textures -- the mod's meshes carry their own textures instead, so
    those paints go unused, which is why the AI cars are identical rather than
    per-slot colours);
  * carry every remaining mod asset (its textures, wheels, .tir, ...) as-is, so the
    swapped meshes' material references resolve.

The mod's own texture names win, so all AI cars share the mod's single skin.

NOTE. This only sets appearance/parts; the mod's meshes still have to fit the
engine's per-object vertex buffer (see `vertexbuffer`) -- a high-poly mod needs
`vrmod patch --max-verts` first or it overflows. This checks and warns.
"""
from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from . import archive, vertexbuffer

TARGET = "viper.car"                       # the primary car the AI always load
TARGET_PREFIX = "viper"
PAINT_SLOT = "VIPER.tex"                    # body material the engine swaps Viperd<N>.tex into
BODY_LODS = tuple(f"viper{i}.mod" for i in range(8))   # the meshes that carry the paint
BACKUP = "viper.car.primarycar-backup"     # the pristine base identity, captured once


class PrimaryCarError(RuntimeError):
    """The mod car can't be identified, or the base viper.car is missing."""


def detect_prefix(entries) -> str:
    """The car's internal member prefix -- the stem shared by <p>0.mod / <p>.cf."""
    names = {e.name.lower() for e in entries}
    for e in entries:
        nl = e.name.lower()
        if nl.endswith("0.mod") and (nl[:-5] + ".cf") in names:
            return e.name[:-5]
    # fall back to the prefix of <x>0.mod
    for e in entries:
        if e.name.lower().endswith("0.mod"):
            return e.name[:-5]
    raise PrimaryCarError("can't find a <prefix>0.mod body mesh -- is this a car .car?")


def overlay(base_entries, mod_entries, mod_prefix: str):
    """Return viper-identity entries carrying the mod's content. Pure; no I/O."""
    mp = mod_prefix.lower()
    mod_by_name = {e.name.lower(): e for e in mod_entries}
    mod_by_suffix = {e.name[len(mp):].lower(): e
                     for e in mod_entries if e.name.lower().startswith(mp)}
    out, consumed = [], set()
    for e in base_entries:
        nl = e.name.lower()
        src = (mod_by_suffix.get(nl[len(TARGET_PREFIX):])
               if nl.startswith(TARGET_PREFIX) else mod_by_name.get(nl))
        if src is not None:
            out.append(dataclasses.replace(src, name=e.name))   # viper name, mod content
            consumed.add(id(src))
        else:
            out.append(e)                                        # gap -> keep viper's
    present = {o.name.lower() for o in out}
    for m in mod_entries:                                        # carry the rest as-is
        if id(m) not in consumed and m.name.lower() not in present:
            out.append(m)
    return out


def _retag_body_to_paint_slot(entries):
    """Rename each body LOD's dominant material to the paint slot, so the engine
    applies its per-slot Viperd<N>.tex paints (per-AI colours) instead of the mod's
    single fixed skin. Caveat: those paints are UV-mapped for the viper body.
    Returns (entries, retagged_count)."""
    import dataclasses as dc
    from . import mod as modmod
    out, n = [], 0
    for e in entries:
        if e.name.lower() in BODY_LODS:
            try:
                m = modmod.parse(e.to_standalone_bytes())
                if m.materials:
                    dom = max(range(len(m.materials)),
                              key=lambda i: m.materials[i].face_end - m.materials[i].face_start)
                    if m.materials[dom].name != PAINT_SLOT:
                        m.materials[dom] = dc.replace(m.materials[dom], name=PAINT_SLOT)
                        std = modmod.build(m)
                        from . import envelope
                        env = envelope.parse(std)
                        e = dc.replace(e, payload=env.payload)
                        n += 1
            except Exception:
                pass
        out.append(e)
    return out, n


def _base_and_backup(data_dir: Path) -> tuple[Path, Path]:
    d = Path(data_dir)
    target = d / TARGET
    backup = d / BACKUP
    if not backup.exists():
        if not target.exists():
            raise PrimaryCarError(f"no {TARGET} in {data_dir} to use as the base")
        shutil.copy2(target, backup)        # capture the pristine identity once
    return target, backup


def install(data_dir: str | Path, mod_car: str | Path, *, paint_slots: bool = False) -> dict:
    """Repackage `mod_car` onto viper's identity and write it as viper.car.

    Rebuilds from the captured backup every time (idempotent, re-runnable with a
    different mod). With `paint_slots`, retags the body to viper's paint slot so the
    AI get per-slot colours (see the caveat on `_retag_body_to_paint_slot`). Returns
    a report dict.
    """
    d = Path(data_dir)
    mod_path = Path(mod_car)
    if not mod_path.is_file():
        raise PrimaryCarError(f"no such mod car: {mod_path}")
    target, backup = _base_and_backup(d)

    base = archive.read(backup)
    mod = archive.read(mod_path)
    prefix = detect_prefix(mod)
    out = overlay(base, mod, prefix)
    retagged = 0
    if paint_slots:
        out, retagged = _retag_body_to_paint_slot(out)

    layout = archive.read_layout(backup.read_bytes())
    target.write_bytes(archive.to_bytes(out, partitioned=layout.partitioned))

    # vertex-buffer sanity: the mod's heaviest mesh must fit race.bin's buffer
    warn = None
    try:
        from . import mod as modmod, envelope
        worst = 0
        for e in mod:
            if e.name.lower().endswith(".mod"):
                try:
                    worst = max(worst, len(modmod.parse(
                        envelope.build(e.tag, e.version, e.payload)).vertices))
                except Exception:
                    pass
        cap = vertexbuffer.buffer_verts(d)
        if worst > cap:
            warn = (f"heaviest mesh is {worst:,} verts but race.bin's buffer holds "
                    f"{cap:,}; it will crash on load. Raise it first: "
                    f"vrmod patch <Data> --max-verts {min(32768, max(worst + 100, 1000))}")
    except Exception:
        pass
    return {"target": target, "mod": mod_path.name, "prefix": prefix,
            "members": len(out), "vertex_warning": warn,
            "paint_slots": retagged if paint_slots else None}


def status(data_dir: str | Path) -> str:
    d = Path(data_dir)
    if not (d / TARGET).exists():
        return "no viper.car"
    if not (d / BACKUP).exists():
        return "stock (never overlaid)"
    return "overlaid (a mod car is installed as the primary; --revert to restore)"


def revert(data_dir: str | Path) -> str:
    d = Path(data_dir)
    backup = d / BACKUP
    if not backup.exists():
        raise PrimaryCarError(f"no {BACKUP} to restore from")
    shutil.copy2(backup, d / TARGET)
    backup.unlink()
    return f"restored {TARGET} from {BACKUP}"
