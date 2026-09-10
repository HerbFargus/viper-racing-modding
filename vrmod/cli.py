"""Command-line interface for unpacking/repacking Viper Racing .trk/.car/.res archives."""
from __future__ import annotations

import argparse
import base64
import functools
import http.server
import json
import re
import shutil
import sys
import webbrowser
from pathlib import Path

from . import aifield, archive, aspectfix, bpp as bppmod, car, carshot, catalog as catalog_mod, cf, cockpit_tab, doctor, envelope, hornball, mod, patchset, primarycar, racebin, resolution, sfx, sky, switcher_ui, tex, track, trackmap, viewer, vrampatch

COMMIT_PATH = "/__vrmod_commit__"


def _unique_path(path: Path) -> Path:
    """path if it doesn't already exist, else path with _2/_3/... inserted before
    the suffix -- same collision-avoidance viewer.build_gallery() already uses, so
    a commit never silently clobbers an existing file (a same-named prior commit,
    or anything else already sitting there)."""
    if not path.exists():
        return path
    stem, suffix, i = path.stem, path.suffix, 2
    while True:
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _tex_mode(info: tex.TexInfo) -> str:
    if info.has_alpha:
        return "alpha"
    if info.has_colorkey:
        return "colorkey"
    return "opaque"


def _fit_to_original(pixels: bytes, w: int, h: int, orig_info, name: str,
                     resized: list) -> tuple[bytes, int]:
    """Resample an imported texture to the size the original was.

    The game's textures are square powers of two, and much of the hardware it
    shipped for capped them at 256 -- so an import that is larger than what a
    texture already was is a real risk, not just wasted memory: an unpatched
    game may refuse to load it. Rather than write whatever size arrived, fit it
    to the original and record the change so the caller can say so.

    `sky.py` takes the same line, and offers `--tile-size` as the deliberate
    way to change resolution. There is no equivalent here yet, because the
    drawers have nowhere to ask.
    """
    target = orig_info.size
    if w == target and h == target:
        return pixels, target
    # Always 4: read_tga_bytes returns RGBA regardless, because the drawers
    # only ever produce 32-bit TGAs (see viewer.py's encodeTga). Any drop to
    # RGB happens after this, per the original's mode.
    fitted = tex.resize_nearest(pixels, w, h, target, target, 4)
    resized.append(f"{name} {w}x{h} -> {target}x{target}")
    return fitted, target


def _nearest_pow2(n: int) -> int:
    """Nearest power of two to n (ties round down)."""
    if n < 1:
        return 1
    lo = 1 << (n.bit_length() - 1)
    hi = lo << 1
    return lo if (n - lo) <= (hi - n) else hi


def _fit_new_texture(pixels: bytes, w: int, h: int, name: str,
                     resized: list, cap: int = 512) -> tuple[bytes, int]:
    """Fit a brand-new texture -- one with no original .tex in the car or the
    shared archives to match a size against -- to a valid .tex size.

    encode_to_tex() requires a square power of two >= 8, but a skin imported
    alongside a foreign body (via the shell's OBJ+.mtl import) is routinely
    non-square or not-power-of-two, so resample rather than reject. The target
    is the nearest power of two to the larger side, floored at 8 and capped at
    `cap` (512 by default -- large enough to stay crisp, small enough to load on
    the unpatched game and its 256/512-capped hardware without a warning). Any
    change is recorded in `resized` so the UI can say the artwork was refit.
    """
    target = max(8, min(cap, _nearest_pow2(max(w, h))))
    if w == target and h == target:
        return pixels, target
    fitted = tex.resize_nearest(pixels, w, h, target, target, 4)
    resized.append(f"{name} {w}x{h} -> {target}x{target}")
    return fitted, target


def _new_tex_mode_wrap(pixels: bytes) -> tuple[str, int]:
    """Mode/wrap for a brand-new material's texture -- one with no original .tex
    to copy those from. Opaque unless the imported image actually carries
    transparency (an opaque skin forced to alpha is just wasteful); wrap=1, a
    valid stock value. The game panics with "tmap: unknown texture format" on
    wrap=0 -- no stock .tex uses it, every one is wrap=1 (tileable) or 2 (decal).
    `pixels` is RGBA here (read_tga_bytes always returns 4 channels)."""
    has_alpha = any(pixels[i] < 255 for i in range(3, len(pixels), 4))
    return ("alpha" if has_alpha else "opaque"), 1


def find_original_backup(car_path: Path) -> Path | None:
    """The earliest _apply_commit backup for this car -- its pristine pre-tool
    state. The first Save writes `<stem>_original<suffix>.bak` (no collision
    suffix); later Saves get `..._2.bak`, etc. Prefer the un-suffixed one; else
    the oldest by mtime (copy2 preserves the source car's mtime, so oldest =
    most original)."""
    car_path = Path(car_path)
    primary = car_path.with_name(f"{car_path.stem}_original{car_path.suffix}.bak")
    if primary.exists():
        return primary
    cands = sorted(car_path.parent.glob(f"{car_path.stem}_original*{car_path.suffix}*.bak"),
                   key=lambda p: p.stat().st_mtime)
    return cands[0] if cands else None


def _restore_original(car_path: Path) -> Path:
    """Copy the pristine backup back over the car. Returns the backup used;
    raises FileNotFoundError if there's nothing to restore from. Backups are
    left in place (restore is repeatable / non-destructive of history)."""
    car_path = Path(car_path)
    backup = find_original_backup(car_path)
    if backup is None:
        raise FileNotFoundError(
            "no original backup found for this car (nothing has been saved yet, "
            "so there's no pre-edit copy to restore)")
    shutil.copy2(backup, car_path)
    return backup


def _apply_commit(body: dict) -> tuple[Path, Path]:
    """Turn the shell's "Save" payload into a real, edited .car file -- written
    back to the car's OWN original path/filename (backed up first, never
    blindly overwritten -- see the comment near the end of this function for why
    keeping the car's real identity intact, rather than renaming, is deliberate).
    Returns (edited_path, backup_path) -- edited_path always equals the input
    car_path. Handles stats (.cf, via cf.build()), cockpit (cockpit.tab, via
    cockpit_tab.build() -- only the records actually present in the payload are
    touched, same partial-patch behavior as cf.build()), parts (.mod, via
    mod.from_obj()+mod.build(), upserted since a part may be a shared default the
    car doesn't own yet), textures (.tex, via tex.encode_to_tex(), see below for
    mode handling, also upserted), and sounds (.sfx, via sfx.from_wav_bytes()+
    sfx.build(), also upserted for the same shared-default reason).

    Texture mode (opaque/alpha/colorkey) isn't something the browser can know --
    it only ever sees decoded RGBA pixels, with no memory of the original .tex's
    own flags (same caveat as the Textures drawer's TGA export). This runs
    server-side with the real original file still on disk, though, so it reads
    that file's actual mode and re-encodes the new pixels the same way, rather
    than guessing.
    """
    # Restore: copy the pristine backup back over the car OR track (undoes all
    # tool edits). Handled before the track/car split so both use it.
    if body.get("action") == "restore":
        target = Path(body.get("track_path") or body["car_path"])
        backup = _restore_original(target)
        return target, backup, [], [], None
    # Generate the LOD chain from the body mesh (decimate <prefix>0.mod into
    # <prefix>1..7.mod, carrying its textures) so the car stays itself at every
    # distance. Standalone action -- operates on the saved car, then the shell
    # reloads. Backs up first, like every other write.
    if body.get("action") == "genlods":
        car_path = Path(body["car_path"])
        entries = archive.read(car_path)
        out_entries, made = car.build_lod_chain(entries)
        backup = _unique_path(
            car_path.with_name(f"{car_path.stem}_original{car_path.suffix}.bak"))
        shutil.copy2(car_path, backup)
        archive.write(out_entries, car_path)
        return car_path, backup, [], [f"Generated {len(made)} LOD level(s): "
                                      + ", ".join(f"{n} ({v}v)" for n, v in made)], None
    if "track_path" in body:
        return _apply_track_commit(body)
    car_path = Path(body["car_path"])
    entries = archive.read(car_path)

    stats = body.get("stats") or {}
    if stats:
        prefix = car._find_prefix(entries)
        cf_name = next(e.name for e in entries if e.name.lower() == f"{prefix}.cf".lower())
        cf_raw = car._entry_bytes(entries, cf_name)
        new_cf = cf.build(cf_raw, {k: float(v) for k, v in stats.items()})
        entries = archive.replace_entry(entries, cf_name, new_cf)

    cockpit_records = body.get("cockpit") or {}
    if cockpit_records:
        cockpit_tab_name = next(e.name for e in entries if e.name.lower() == "cockpit.tab")
        cockpit_raw = car._entry_bytes(entries, cockpit_tab_name)
        new_cockpit = cockpit_tab.build(
            cockpit_raw, {name: tuple(float(v) for v in vals) for name, vals in cockpit_records.items()}
        )
        entries = archive.replace_entry(entries, cockpit_tab_name, new_cockpit)

    warnings: list[str] = []
    limit, why = doctor.vertex_budget(car_path.parent)
    for name, obj_text in (body.get("parts") or {}).items():
        # upsert_entry, not replace_entry: a Parts-drawer row may be a shared
        # default the car doesn't own yet (currently just ball.mod, the horn
        # ball -- see viewer.py's build_shell_html and SHARED_PART_NAMES), same
        # situation as an unowned texture. replace_entry would raise (nothing to
        # replace); upsert_entry adds it as a real new per-car override instead.
        mesh = mod.from_obj(obj_text)
        # Warn, never decimate. The right ceiling depends on which race.bin is
        # installed, and someone may have deliberately built for a patched one;
        # quietly reducing their geometry would destroy that intent. The count
        # and the limit are enough for them to decide -- `obj2mod --patch` and
        # `moddecimate` are there when reducing IS what they want.
        if limit is not None and len(mesh.vertices) > limit:
            warnings.append(
                f"{name} has {len(mesh.vertices):,} vertices, over the {limit:,} "
                f"that {why} allows -- the game may fail to load this car")
        entries = archive.upsert_entry(entries, name, mod.build(mesh))

    # Deletions: optional sub-parts/interior pieces removed in the slot map, or a
    # per-car override reverted to its shared default. Applied after the part
    # upserts above so a remove of a name that a part edit also touched (shouldn't
    # happen -- the UI stages one or the other) resolves as "gone". Silently skip
    # a name that isn't actually in the archive (already absent = already the
    # desired state), rather than failing the whole save.
    for name in (body.get("remove") or []):
        try:
            entries = archive.remove_entry(entries, name)
        except KeyError:
            pass

    resized: list[str] = []
    for name, tga_b64 in (body.get("textures") or {}).items():
        pixels, w, h = tex.read_tga_bytes(base64.b64decode(tga_b64))
        # find_shared, not _entry_bytes: a material shown in the Textures drawer
        # may not be owned by this car yet (still inherited from a shared .res --
        # same situation as an unowned ball.mod/wheel). Checking the shared
        # archives too means an unowned texture still gets its real original
        # mode/wrap preserved, not just a guess, even though upsert_entry below
        # is about to turn it into a real per-car override.
        orig_raw = car.find_shared(car_path, entries, name)
        if orig_raw is not None:
            orig_info = tex.parse(orig_raw)
            mode, wrap = _tex_mode(orig_info), orig_info.wrap
            # Fit BEFORE any channel conversion: pixels are still RGBA here, and
            # h is still the real height. Doing it after the opaque branch below
            # would resample 3-channel data as though it were 4.
            pixels, w = _fit_to_original(pixels, w, h, orig_info, name, resized)
        else:
            # No original to match (a brand-new material -- e.g. a foreign body's
            # own skin arriving via the shell's OBJ+.mtl import): pick mode/wrap
            # from the image itself (opaque unless it has alpha, a valid wrap),
            # and fit to a valid .tex size ourselves, since encode_to_tex demands
            # a square power of two >= 8 and an imported skin often isn't one.
            mode, wrap = _new_tex_mode_wrap(pixels)
            pixels, w = _fit_new_texture(pixels, w, h, name, resized)
        if mode == "opaque":
            # read_tga_bytes always returns RGBA (our TGAs are always 32-bit --
            # see viewer.py's encodeTga), but encode_to_tex's "opaque" mode wants
            # plain RGB888 -- strip the alpha byte rather than pass 4-channel data
            # to a 3-channel-expecting mode.
            rgb = bytearray(len(pixels) // 4 * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = pixels[0::4], pixels[1::4], pixels[2::4]
            pixels = bytes(rgb)
        new_tex = tex.encode_to_tex(pixels, w, mode=mode, wrap=wrap)
        entries = archive.upsert_entry(entries, name, new_tex)

    for name, wav_b64 in (body.get("sounds") or {}).items():
        # upsert_entry, not replace_entry: a Sound-drawer row may be one of
        # race.res's shared defaults the car doesn't own yet (horn.sfx/
        # shift1.sfx/squeal.sfx -- see viewer.py's SHARED_SFX_ROLES), same
        # situation as an unowned ball.mod or texture.
        info = sfx.from_wav_bytes(base64.b64decode(wav_b64))
        entries = archive.upsert_entry(entries, name, sfx.build(info))

    # Display name: the <prefix>1.tab "Name" field (an in-place, fixed-width
    # rewrite -- this is the shown label only, NOT the car's filename identity).
    new_name = body.get("car_name")
    if new_name is not None and new_name.strip():
        entries = car.set_car_name(entries, new_name)

    # Write edits back under the car's OWN original filename, not a renamed
    # copy -- deliberate, not an oversight. The game ties several things to a
    # car's exact identity beyond just its own <prefix>0.mod-style archive
    # members, confirmed the hard way, one real bug at a time: a real crash log
    # from renaming to "viper_edited.car" while the archive's own members stayed
    # "Viper0.mod" etc. (ResourceGet("viper_edited0.mod") returning NULL); the
    # body's paint-slot material name, itself <prefix>-based (viper.car's own is
    # literally "VIPER.tex", exotic.car's "Exotic.tex"), rendering as a flat
    # fallback color once mismatched; and paintkit.res having a dedicated
    # exotic.cvs/sedan.cvs/sports.cvs canvas for every OTHER car but no
    # viper.cvs at all -- "viper" is clearly hardcoded as the primary car,
    # working through paintN.cvs directly, and a renamed car falls out of that
    # special case with no canvas of its own to fall back to (confirmed
    # in-game: renamed car's Paint Kit shows solid black). Only ball.mod-style
    # SHARED_PART_NAMES/SHARED_SFX_ROLES overrides get created as real new
    # per-car entries (upsert_entry, above) -- everything else keeps its
    # existing name, so none of this identity-tied machinery is ever at risk.
    # Never overwriting car_path blindly, though: back it up first, collision-
    # safe via the same _unique_path() scheme the old renamed-output approach
    # used, so the pre-edit state is always recoverable. The backup gets a
    # trailing ".bak" so it is NOT a loadable ".car": the game scans Data/ and
    # loads every *.car, deriving each one's member names from its filename, so a
    # "viper_original.car" backup would make it look for "viper_original0.mod" and
    # panic (the exact filename<->members crash from the format reference).
    # Save As a NEW standalone car: fork the just-edited entries to a new filename
    # prefix (fork_car re-prefixes every internal member and texture reference --
    # a plain file rename crashes the game, see fork_car and the format reference).
    # The ORIGINAL car is never touched, so there is nothing to back up. Any display
    # name and pending edits are already baked into `entries` above, so the fork is
    # the user's current edited state under a genuinely separate identity.
    if body.get("action") == "saveas":
        new_prefix = (body.get("new_prefix") or "").strip()
        # Cap at 9, not the format's raw 10: the 16-byte member-name field must fit
        # <prefix> + the longest suffix (6, e.g. "d1.tex"). At 10 the longest member
        # (jeepd1.tex) is exactly 16 bytes with NO null terminator; 9 guarantees a
        # terminator on every member, matching how every shipped name behaves.
        if not re.fullmatch(r"[A-Za-z0-9_]{1,9}", new_prefix):
            raise ValueError("new car name must be 1-9 letters, digits or underscores "
                             "(it becomes the car's internal file prefix, e.g. 'jeep')")
        forked = car.fork_car(entries, new_prefix)
        # destination "elsewhere": hand the BYTES back instead of writing. This
        # endpoint only ever writes inside the Data folder it was pointed at -- a
        # save outside it goes through the OS folder dialog in the desktop bridge
        # (or a browser download), so the location is the user's explicit choice
        # rather than a path this server accepted and wrote to. The display name
        # and every staged edit are already baked into `entries`, so both
        # destinations produce the identical car.
        if body.get("destination") == "elsewhere":
            data = base64.b64encode(archive.to_bytes(forked)).decode("ascii")
            return Path(f"{new_prefix}.car"), None, resized, warnings, data
        out_path = car_path.with_name(f"{new_prefix}.car")
        if out_path.exists():
            raise ValueError(f"{out_path.name} already exists in the Data folder -- pick another name")
        archive.write(forked, out_path)
        return out_path, None, resized, warnings, None

    backup_path = _unique_path(car_path.with_name(f"{car_path.stem}_original{car_path.suffix}.bak"))
    shutil.copy2(car_path, backup_path)
    archive.write(entries, car_path)
    return car_path, backup_path, resized, warnings, None


def _apply_track_commit(body: dict) -> tuple[Path, Path]:
    """Track-shell counterpart to _apply_commit() -- currently textures only
    (viewer.py's track viewer has no write path for the mesh itself yet, see
    grf.py's docstring). Simpler than the car version's texture handling:
    a track's textures always live in its own .trk, so the "shared archive"
    lookup car.find_shared() does isn't needed -- replace_entry (not
    upsert_entry) is correct too, since a texture only shows in the drawer
    at all if it's already a real entry in this exact archive."""
    track_path = Path(body["track_path"])
    entries = archive.read(track_path)

    resized: list[str] = []
    for name, tga_b64 in (body.get("textures") or {}).items():
        pixels, w, h = tex.read_tga_bytes(base64.b64decode(tga_b64))
        orig_entry = next((e for e in entries if e.name.lower() == name.lower()), None)
        if orig_entry is not None:
            orig_info = tex.parse(envelope.build(orig_entry.tag, orig_entry.version, orig_entry.payload))
            mode, wrap = _tex_mode(orig_info), orig_info.wrap
            # Before the channel conversion below -- see the note in _apply_commit.
            pixels, w = _fit_to_original(pixels, w, h, orig_info, name, resized)
        else:
            mode, wrap = _new_tex_mode_wrap(pixels)
        if mode == "opaque":
            rgb = bytearray(len(pixels) // 4 * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = pixels[0::4], pixels[1::4], pixels[2::4]
            pixels = bytes(rgb)
        new_tex = tex.encode_to_tex(pixels, w, mode=mode, wrap=wrap)
        entries = archive.replace_entry(entries, name, new_tex)

    # The sky arrives as ONE panoramic TGA and is split back into the four
    # sky*.tex tiles here (see sky.py). It is not a material, so it cannot ride
    # along in the textures dict -- the drawer sends it under its own key.
    sky_b64 = body.get("sky")
    if sky_b64:
        pixels, w, h = tex.read_tga_bytes(base64.b64decode(sky_b64))
        if len(pixels) == w * h * 4:                    # skies are opaque
            rgb = bytearray(w * h * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = pixels[0::4], pixels[1::4], pixels[2::4]
            pixels = bytes(rgb)
        first = next(e for e in entries if e.name.lower() == sky.TILES[0])
        info = tex.parse(envelope.build(first.tag, first.version, first.payload))
        mode = "alpha" if info.has_alpha else "colorkey" if info.has_colorkey else "opaque"
        # Keep the track's existing tile size: the drawer has no way to ask for
        # a different one, and silently upgrading to 512 because someone edited
        # the exported strip at 2x could produce a track the stock game refuses
        # to load. `skyimport --tile-size` is the deliberate route.
        tiles = sky.build_tiles(pixels, w, h, info.size, mode, info.wrap)
        for name, raw in zip(sky.TILES, tiles):
            real = next(e.name for e in entries if e.name.lower() == name)
            entries = archive.replace_entry(entries, real, raw)

    # Export as .tra: write the edited track out as a portable, INSTALLABLE track
    # file instead of overwriting the slot's .trk. This is the track counterpart
    # to the car's "Save as new car", but deliberately NOT a new editing target:
    # a track isn't identified by its filename (its members are fixed-named --
    # track.grf, track.bpp, ... -- and the game loads whatever sits in its eight
    # fixed slots), so a differently-named .trk would simply never be loaded. The
    # distributable unit is a .tra, which the switcher installs INTO a slot
    # (handling the backup, the ui.res thumbnail and the english.lng name). The
    # original .trk is left untouched, so there is nothing to back up.
    if body.get("action") == "exporttra":
        name = (body.get("tra_name") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
            raise ValueError("track file name must be 1-32 letters, digits, dashes or "
                             "underscores (it becomes <name>.tra)")
        out_path = track_path.with_name(f"{name}.tra")
        # Only a Data-folder write can collide here; an "elsewhere" save is
        # checked by the OS dialog (and the bridge) at the folder the user picks.
        if body.get("destination") != "elsewhere" and out_path.exists():
            raise ValueError(f"{out_path.name} already exists in the Data folder -- pick another name")
        warnings: list[str] = []
        names = {e.name.lower() for e in entries}
        missing = [m for m in track.REQUIRED_MEMBERS if m not in names]
        if missing:
            warnings.append(f"missing {len(missing)} member(s) every known track carries: "
                            f"{', '.join(missing)}")
        # A .ccs named for a DIFFERENT slot rides along fine (track lookups aren't
        # filename-bound) but is worth flagging -- same warning `trk2tra` gives.
        stem = track_path.stem.lower()
        slot_specific = sorted(
            e.name for e in entries
            if e.name.lower().endswith(".ccs") and e.name.lower() != "aidef.ccs"
            and e.name.lower()[:-4] in track.SLOTS and e.name.lower()[:-4] != stem)
        if slot_specific:
            warnings.append(f"carries another slot's zone file(s): {', '.join(slot_specific)}")
        # "flat" -- the header convention every existing .tra uses (track.export_tra).
        blob = archive.to_bytes(entries, partitioned=False)
        # Same rule as the car fork: "elsewhere" returns the bytes for the OS
        # dialog rather than having this endpoint write outside the Data folder.
        if body.get("destination") == "elsewhere":
            return (Path(f"{name}.tra"), None, resized, warnings,
                    base64.b64encode(blob).decode("ascii"))
        out_path.write_bytes(blob)
        return out_path, None, resized, warnings, None

    # ".bak" so the backup isn't a loadable ".trk" (same reasoning as the car
    # backup in _apply_commit -- keep stray copies out of the game's scan).
    backup_path = _unique_path(track_path.with_name(f"{track_path.stem}_original{track_path.suffix}.bak"))
    shutil.copy2(track_path, backup_path)
    archive.write(entries, track_path)
    return track_path, backup_path, resized, [], None


class _CommitHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler plus one POST route (COMMIT_PATH) that applies a
    shell's pending edits and writes a new .car -- see _apply_commit(). Every
    other request (every GET, and any POST elsewhere) behaves exactly like the
    plain handler this replaces."""

    def do_POST(self):
        if self.path != COMMIT_PATH:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
            out_path, backup_path, notes, warnings, data = _apply_commit(body)
            response = {"ok": True, "out_path": str(out_path),
                        "backup_path": str(backup_path) if backup_path else None,
                        "resized": notes, "warnings": warnings}
            # "elsewhere": nothing was written -- the page saves these bytes via
            # the OS dialog, so send the filename and payload instead of a path.
            if data is not None:
                response["filename"] = out_path.name
                response["data"] = data
        except Exception as e:
            response = {"ok": False, "error": str(e)}
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve_and_open(html_path: Path, port: int = 0) -> None:
    """Serve html_path's directory over local HTTP and open it in the default browser.

    Opening a generated viewer file directly (file://) can silently fail to run its
    scripts at all in some browsers/security setups -- no error, just a blank page --
    while serving the exact same file over http:// reliably works. Blocks serving
    requests until interrupted (Ctrl+C), same as `python -m http.server`.

    Uses _CommitHandler (not the plain SimpleHTTPRequestHandler) unconditionally --
    harmless for pages that never call COMMIT_PATH (gallery pages, view-only
    shells), and it's what lets a shell's "Save" button work when opened this way
    specifically (see build_shell_html's docstring: that button only works
    through this server, not a generic http.server or file://).
    """
    handler = functools.partial(_CommitHandler, directory=str(html_path.parent))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/{html_path.name}"
    print(f"serving {html_path.parent} at {url} (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _parse_record_edits(parser: argparse.ArgumentParser, pairs: list[str]) -> dict[str, tuple[float, float, float]]:
    """Parse "name=x,y,z" strings (cockpitset/cockpitpatch's --set-style args) into
    a {name: (x, y, z)} dict, same shape cockpit_tab.build() expects."""
    edits: dict[str, tuple[float, float, float]] = {}
    for pair in pairs:
        if "=" not in pair:
            parser.error(f"expected name=x,y,z, got {pair!r}")
        name, value = pair.split("=", 1)
        parts = value.split(",")
        if len(parts) != 3:
            parser.error(f"expected 3 comma-separated numbers for {name!r}, got {value!r}")
        edits[name] = tuple(float(p) for p in parts)
    return edits


def _parse_field_edits(parser: argparse.ArgumentParser, pairs: list[str]) -> dict[str, float]:
    """Parse "field=value" strings (cfset/cfpatch's --set-style args) into a
    {field: value} dict, same shape cf.build() expects."""
    edits: dict[str, float] = {}
    for pair in pairs:
        if "=" not in pair:
            parser.error(f"expected field=value, got {pair!r}")
        name, value = pair.split("=", 1)
        edits[name] = float(value)
    return edits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vrmod", description="Viper Racing archive unpack/repack tool"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_unpack = sub.add_parser("unpack", help="Unpack a .trk/.car/.res archive into loose files")
    p_unpack.add_argument("archive", type=Path)
    p_unpack.add_argument("out_dir", type=Path)

    p_pack = sub.add_parser("pack", help="Pack a directory of loose files back into an archive")
    p_pack.add_argument("in_dir", type=Path)
    p_pack.add_argument("archive", type=Path)

    p_switcher = sub.add_parser(
        "switcher",
        help="Open the Data folder UI: Tracks (install/restore .tra into the 8 game slots) "
             "and Cars (open any .car in the mod-tool shell)",
    )
    p_switcher.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_switcher.add_argument("--port", type=int, default=8770)
    p_switcher.add_argument("--no-browser", action="store_true")

    p_aifield = sub.add_parser(
        "aifield",
        help="Show or set the AI opponent count (field size). Max 15 AI (16-car grid); "
             "the in-game selector caps at 7. Do NOT touch the in-game selector after setting",
    )
    p_aifield.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_aifield.add_argument("count", type=int, nargs="?", default=None,
                           help=f"AI opponents to set (0-{aifield.MAX_AI}); omit to show current")
    p_aifield.add_argument("--revert", action="store_true",
                           help="restore options.cfg from the backup taken on first set")

    p_primary = sub.add_parser(
        "primarycar",
        help="Install a mod car as the PRIMARY car (viper.car) so the whole AI field "
             "drives it. Repackages the mod onto viper's internal names; backs up the "
             "original. High-poly mods need 'vrmod patch --max-verts' first",
    )
    p_primary.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_primary.add_argument("mod_car", type=Path, nargs="?", default=None,
                           help="the mod .car to install as the AI/primary car")
    p_primary.add_argument("--paint-slots", action="store_true",
                           help="retag the body to viper's paint slot so the AI drivers get "
                                "DIFFERENT colours (tells them apart on track). The paints are "
                                "UV-mapped for the viper body, so they look off on a mod -- "
                                "differentiation, not accuracy")
    p_primary.add_argument("--status", action="store_true",
                           help="report whether a mod car is installed as primary")
    p_primary.add_argument("--revert", action="store_true",
                           help="restore the original viper.car from the backup")

    p_trackmap = sub.add_parser(
        "trackmap",
        help="Generate a track's Track Info map image from its centre line (track.ild)",
    )
    p_trackmap.add_argument("trk_file", type=Path)
    p_trackmap.add_argument("out_file", type=Path, nargs="?",
                            help="write a .png preview here (omit with --install)")
    p_trackmap.add_argument("--install", action="store_true",
                            help="write the map into the track as Trackmap.stp (backs up first)")
    p_trackmap.add_argument("--markers", type=int, default=None,
                            help="number of numbered markers (default: about 3 per mile)")
    p_trackmap.add_argument("--line-width", type=int, default=trackmap.LINE_WIDTH)

    p_carshot = sub.add_parser(
        "carshot",
        help="Render a car's body mesh to a small flat-shaded PNG thumbnail",
    )
    p_carshot.add_argument("car_file", type=Path)
    p_carshot.add_argument("out_file", type=Path)
    p_carshot.add_argument("--width", type=int, default=carshot.WIDTH)
    p_carshot.add_argument("--height", type=int, default=carshot.HEIGHT)
    p_carshot.add_argument("--yaw", type=float, default=carshot.YAW,
                           help="rotation about the vertical axis, degrees")
    p_carshot.add_argument("--pitch", type=float, default=carshot.PITCH,
                           help="downward tilt, degrees")
    p_carshot.add_argument("--no-wheels", action="store_true",
                           help="draw the body only -- about twice as fast")
    p_carshot.add_argument("--style", choices=("wire", "shaded", "textured"), default="wire",
                           help="hidden-line wireframe (default), flat-shaded solid, or UV-textured")
    p_carshot.add_argument("--paint", type=Path, default=None,
                           help="a paint texture (Config/paint0.tex) for the runtime paint slot")

    p_doctor = sub.add_parser(
        "doctor",
        help="Check an install: race.bin version, modern-GPU compatibility, resolution, "
             "what is installed, leftover backups",
    )
    p_doctor.add_argument("data_dir", type=Path, help="the game's Data folder")

    p_rb = sub.add_parser(
        "racebin",
        help="Inspect, or install, a race.bin you have downloaded (verifies it and backs "
             "up the current one first)",
    )
    p_rb.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_rb.add_argument("--install", type=Path, default=None, metavar="FILE",
                      help="install this race.bin, replacing the one in the Data folder")

    p_trackgen = sub.add_parser(
        "trackgen",
        help="Generate a track's MKWORLD source set (fooland*.txt + swept meshes) "
             "from a centreline -- the driving half of the track pipeline",
    )
    p_trackgen.add_argument("centreline", type=Path,
                            help="a .ase/.obj centreline, or a .mod road surface "
                                 "(or directory of them) to recover one from")
    p_trackgen.add_argument("out_dir", type=Path, help="directory to write into")
    p_trackgen.add_argument("--spacing", type=float, default=10.0,
                            help="resample the centreline to this station spacing (m)")
    p_trackgen.add_argument("--road-width", type=float, default=12.0,
                            help="full road width in metres (default 12)")
    p_trackgen.add_argument("--open", action="store_true",
                            help="treat the centreline as open rather than a closed loop")
    p_trackgen.add_argument("--checkpoints", type=int, default=3,
                            help="timing gates around the lap (minimum 2; the engine "
                                 "panics with 'Couldn't find any checkpoints!' below that)")
    p_trackgen.add_argument("--grid", type=int, default=8,
                            help="starting-grid slots (default 8)")

    p_bppinfo = sub.add_parser(
        "bppinfo",
        help="Summarise a track's collision BSP (.bpp): triangle and node counts, "
             "surface flags, and how much of the tree is reachable",
    )
    p_bppinfo.add_argument("trk_file", type=Path, help="a .trk/.tra archive, or a loose .bpp")

    p_bpp2obj = sub.add_parser(
        "bpp2obj",
        help="Export a track's COLLISION mesh as OBJ. Compare it against the render "
             "mesh (trk2tra/trackview) to find geometry you can hit but cannot see",
    )
    p_bpp2obj.add_argument("trk_file", type=Path, help="a .trk/.tra archive, or a loose .bpp")
    p_bpp2obj.add_argument("obj_file", type=Path)

    p_retag = sub.add_parser(
        "bppsurface",
        help="Show or change a track's per-triangle surface codes in .bpp "
             "(0=asphalt 10=grass 14=water 16=rumble 20=dirt). Backs the track up first",
    )
    p_retag.add_argument("track", type=Path, help="a .trk/.tra archive")
    p_retag.add_argument("--set", nargs="+", default=None, metavar="OLD=NEW",
                         help="remap codes, e.g. --set 10=20 (grass->dirt). Repeatable")
    p_retag.add_argument("--region", nargs=4, type=float, default=None,
                         metavar=("MINX", "MINZ", "MAXX", "MAXZ"),
                         help="only retag triangles whose centroid is in this XZ box")
    p_retag.add_argument("--out", type=Path, default=None,
                         help="write here instead of rewriting the track in place")

    p_cc = sub.add_parser(
        "collisioncheck",
        help="Find where a track's collision (.bpp) and render (.grf) meshes disagree "
             "-- invisible walls and drive-through props. Diff two tracks to catch an "
             "edit of any size",
    )
    p_cc.add_argument("track", type=Path, help="a .trk/.tra archive")
    p_cc.add_argument("--against", type=Path, default=None, metavar="ORIGINAL",
                      help="diff TRACK (edited) against this ORIGINAL and report only what "
                           "the edit changed -- the reliable check for a broken-collision mod")

    p_patch = sub.add_parser(
        "patch",
        help="Apply the whole race.bin patch set in one reproducible step: startup fix, "
             "rasteriser bounds, widescreen field of view, resolution, symbol map",
    )
    p_patch.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_patch.add_argument("--mode", default="1920x1080", metavar="WIDTHxHEIGHT",
                         help="resolution to install (default: 1920x1080)")
    p_patch.add_argument("--index", type=int, default=patchset.DEFAULT_INDEX,
                         help="menu index to replace, 1/3/4 (default: 4). Index 2 is the "
                              "startup gate -- repointing it stops the game booting")
    p_patch.add_argument("--fov", type=float, default=aspectfix.RATIO_ORIGINAL,
                         help="vertical half-field to preserve (default: 0.65, the original)")
    p_patch.add_argument("--small-tables", action="store_true",
                         help="leave the rasteriser's edge tables at 1024 scanlines. "
                              "The default doubles them so screens taller than ~1104 "
                              "rows keep the tachometer needle")
    p_patch.add_argument("--no-map", action="store_true",
                         help="skip the appended symbol map used by the crash handler")
    p_patch.add_argument("--max-verts", type=int, default=None, metavar="N",
                         help="raise the per-object vertex buffer to hold N vertices "
                              "(opt-in; stock is 1,000 on retail 1.1, 30,000 on v1.2.5; "
                              "32768 is the int16 format ceiling). Only helps high-poly mods")
    p_patch.add_argument("--dpi-aware", action="store_true",
                         help="also mark the launcher DPI-aware for the current user. "
                              "Required on a scaled desktop, and a Windows setting rather "
                              "than a change to any game file -- so it is opt-in")
    p_patch.add_argument("--status", action="store_true",
                         help="report what is installed and exit, changing nothing")
    p_patch.add_argument("--revert", action="store_true",
                         help="restore the pristine snapshot taken on the first run")
    p_patch.add_argument("--force-baseline", action="store_true",
                         help="snapshot the current race.bin as the baseline even if it "
                              "already carries patches")

    p_vram = sub.add_parser(
        "patch-vram",
        help="Let an original race.bin start on a modern GPU (removes the video-memory "
             "addition that overflows on 4GB+ cards). Startup fix only",
    )
    p_vram.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_vram.add_argument("--revert", action="store_true", help="put the original instruction back")

    p_res = sub.add_parser(
        "resolution",
        help="List or change the four screen resolutions stored in race.bin",
    )
    p_res.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_res.add_argument("--set", nargs=2, metavar=("INDEX", "WIDTHxHEIGHT"), default=None,
                       help="replace one mode, e.g. --set 0 1920x1080 (backs race.bin up first)")

    p_hb = sub.add_parser(
        "hornball",
        help="Tune the hidden horn-ball hack: throw speed and re-fire cooldown "
             "(reads current values; --speed/--cooldown to change, --reset for stock)",
    )
    p_hb.add_argument("data_dir", type=Path, help="the game's Data folder")
    p_hb.add_argument("--speed", type=float, default=None, metavar="MULT",
                      help=f"throw speed as a multiplier of stock ({hornball.SPEED_MIN}"
                           f"-{hornball.SPEED_MAX}x; 1.0 = stock)")
    p_hb.add_argument("--cooldown", type=float, default=None, metavar="SECONDS",
                      help=f"seconds between throws ({hornball.COOLDOWN_MIN}"
                           f"-{hornball.COOLDOWN_MAX}; stock 2.0)")
    p_hb.add_argument("--reset", action="store_true", help="restore stock (1.0x, 2.0s)")

    p_carfork = sub.add_parser(
        "carfork",
        help="Fork a car to a NEW filename prefix so it becomes a standalone vehicle "
             "(distinct from the one it was forked from). Re-prefixes every internal "
             "member and texture reference -- a plain file rename crashes the game",
    )
    p_carfork.add_argument("car_file", type=Path, help="the source .car")
    p_carfork.add_argument("new_prefix",
                           help="new prefix, e.g. 'jeep' -> writes jeep.car with jeep0.mod, "
                                "jeep.cf, jeepL.tab, ...")
    p_carfork.add_argument("--out", type=Path, default=None,
                           help="output path (default: <new_prefix>.car beside the source)")
    p_carfork.add_argument("--name", default=None,
                           help="also set the in-game display name (the car-select label)")

    p_skyexport = sub.add_parser(
        "skyexport",
        help="Export a track's sky (sky1-4.tex) as one editable panoramic TGA",
    )
    p_skyexport.add_argument("trk_file", type=Path)
    p_skyexport.add_argument("tga_file", type=Path)

    p_skyimport = sub.add_parser(
        "skyimport",
        help="Replace a track's sky from a panoramic TGA (backs up the track first)",
    )
    p_skyimport.add_argument("trk_file", type=Path)
    p_skyimport.add_argument("tga_file", type=Path)
    p_skyimport.add_argument("--out", type=Path, default=None,
                             help="write to this file instead of rewriting the track in place")
    p_skyimport.add_argument("--tile-size", type=int, default=None,
                             help="write different-sized tiles (default: keep the track's "
                                  "existing size). 256 is the stock maximum -- larger reportedly "
                                  "needs a patched game and may not load on an unpatched one")

    p_list = sub.add_parser("list", help="List an archive's contents without extracting")
    p_list.add_argument("archive", type=Path)

    p_trk2tra = sub.add_parser(
        "trk2tra",
        help="Repack a track (.trk or .tra) as a .tra for slot-swapping with trackman",
    )
    p_trk2tra.add_argument("track_file", type=Path)
    p_trk2tra.add_argument("tra_file", type=Path)
    p_trk2tra.add_argument(
        "--layout",
        choices=track.LAYOUTS,
        default="flat",
        help="Container header convention: 'flat' (what existing .tra files use, default), "
             "'partitioned' (what retail .trk use), or 'preserve' (keep the source's)",
    )
    p_trk2tra.add_argument(
        "--allow-missing",
        action="store_true",
        help="Export even if members every known track carries are absent",
    )

    p_tex2tga = sub.add_parser(
        "tex2tga", help="Convert a .tex texture's base level to a .tga (opaque, alpha, or colorkey)"
    )
    p_tex2tga.add_argument("tex_file", type=Path)
    p_tex2tga.add_argument("tga_file", type=Path)

    p_sfx2wav = sub.add_parser(
        "sfx2wav", help="Convert a .sfx sound to a standard playable .wav (PCM only for now, see sfx.py)"
    )
    p_sfx2wav.add_argument("sfx_file", type=Path)
    p_sfx2wav.add_argument("wav_file", type=Path)

    p_wav2sfx = sub.add_parser(
        "wav2sfx", help="Convert a 16-bit mono PCM .wav to a .sfx sound (see sfx.py)"
    )
    p_wav2sfx.add_argument("wav_file", type=Path)
    p_wav2sfx.add_argument("sfx_file", type=Path)

    p_tga2tex = sub.add_parser(
        "tga2tex", help="Encode a .tga image into a .tex texture"
    )
    p_tga2tex.add_argument("tga_file", type=Path)
    p_tga2tex.add_argument("tex_file", type=Path)
    p_tga2tex.add_argument(
        "--mode", choices=("opaque", "alpha", "colorkey"), default=None,
        help="pixel format (default: alpha for a 32-bit source, opaque for 24-bit; "
             "pass explicitly for colorkey, which also needs a 32-bit source)",
    )
    p_tga2tex.add_argument(
        "--wrap", type=int, default=0, choices=(0, 1),
        help="1 for a tileable surface, 0 for a unique decal (default 0)",
    )

    p_cfdump = sub.add_parser("cfdump", help="Dump a .cf car physics config as name/value text")
    p_cfdump.add_argument("cf_file", type=Path)
    p_cfdump.add_argument(
        "txt_file", type=Path, nargs="?", default=None,
        help="write to this file instead of stdout",
    )

    p_txt2cf = sub.add_parser(
        "txt2cf",
        help="Build a .cf from name/value text (as produced by cfdump), applied onto a base .cf",
    )
    p_txt2cf.add_argument("txt_file", type=Path)
    p_txt2cf.add_argument(
        "base_cf", type=Path,
        help="a real .cf file to inherit unnamed/reserved bytes from",
    )
    p_txt2cf.add_argument("out_file", type=Path)

    p_cfset = sub.add_parser(
        "cfset", help="Edit named fields of a .cf file, writing a new .cf with everything else unchanged"
    )
    p_cfset.add_argument("in_file", type=Path)
    p_cfset.add_argument("out_file", type=Path)
    p_cfset.add_argument(
        "set", nargs="+", metavar="field=value",
        help="one or more field=value pairs, e.g. power_max=500 num_gears=5",
    )

    p_cockpitdump = sub.add_parser(
        "cockpitdump", help="Dump a cockpit.tab (camera/wheel/gauge positions) as name/value text"
    )
    p_cockpitdump.add_argument("tab_file", type=Path)
    p_cockpitdump.add_argument(
        "txt_file", type=Path, nargs="?", default=None,
        help="write to this file instead of stdout",
    )

    p_txt2cockpit = sub.add_parser(
        "txt2cockpit",
        help="Build a cockpit.tab from name/value text (as produced by cockpitdump), applied onto a base cockpit.tab",
    )
    p_txt2cockpit.add_argument("txt_file", type=Path)
    p_txt2cockpit.add_argument(
        "base_tab", type=Path,
        help="a real cockpit.tab file to inherit unnamed/reserved bytes from",
    )
    p_txt2cockpit.add_argument("out_file", type=Path)

    p_cockpitset = sub.add_parser(
        "cockpitset",
        help="Edit named records of a cockpit.tab file, writing a new one with everything else unchanged",
    )
    p_cockpitset.add_argument("in_file", type=Path)
    p_cockpitset.add_argument("out_file", type=Path)
    p_cockpitset.add_argument(
        "set", nargs="+", metavar="name=x,y,z",
        help="one or more record edits, e.g. \"wheel=-.491,.625,-.150\" \"rpm dat=-196,70,7000\"",
    )

    p_cockpitpatch = sub.add_parser(
        "cockpitpatch",
        help="Edit a car's cockpit.tab in place inside its .car archive, writing a new .car",
    )
    p_cockpitpatch.add_argument("car_file", type=Path)
    p_cockpitpatch.add_argument("out_file", type=Path)
    p_cockpitpatch.add_argument(
        "set", nargs="+", metavar="name=x,y,z",
        help="one or more record edits, e.g. \"wheel=-.491,.625,-.150\" \"rpm dat=-196,70,7000\"",
    )

    p_cfpatch = sub.add_parser(
        "cfpatch",
        help="Edit a car's <prefix>.cf physics config in place inside its .car archive, writing a new .car",
    )
    p_cfpatch.add_argument("car_file", type=Path)
    p_cfpatch.add_argument("out_file", type=Path)
    p_cfpatch.add_argument(
        "set", nargs="+", metavar="field=value",
        help="one or more field=value pairs, e.g. power_max=500 num_gears=5",
    )

    p_modinfo = sub.add_parser("modinfo", help="List a .mod's vertex/face counts and materials")
    p_modinfo.add_argument("mod_file", type=Path)

    p_mod2obj = sub.add_parser("mod2obj", help="Convert a .mod mesh to OBJ+MTL for viewing")
    p_mod2obj.add_argument("mod_file", type=Path)
    p_mod2obj.add_argument("obj_file", type=Path)

    p_obj2mod = sub.add_parser(
        "obj2mod", help="Build a .mod from a triangulated OBJ (with usemtl groups)"
    )
    p_obj2mod.add_argument("obj_file", type=Path)
    p_obj2mod.add_argument("mod_file", type=Path)
    p_obj2mod.add_argument(
        "--budget", type=int, default=None,
        help="decimate to at most this many vertices if the imported mesh exceeds it",
    )
    p_obj2mod.add_argument(
        "--patch", choices=tuple(mod.VERTEX_BUDGETS), default=None,
        help=f"use a known patch's vertex ceiling instead of --budget: {mod.VERTEX_BUDGETS}",
    )

    p_moddecimate = sub.add_parser(
        "moddecimate", help="Decimate an existing .mod down to a target vertex count"
    )
    p_moddecimate.add_argument("in_file", type=Path)
    p_moddecimate.add_argument("out_file", type=Path)
    p_moddecimate.add_argument(
        "--budget", type=int, default=None, help="target vertex count"
    )
    p_moddecimate.add_argument(
        "--patch", choices=tuple(mod.VERTEX_BUDGETS), default=None,
        help=f"use a known patch's vertex ceiling instead of --budget: {mod.VERTEX_BUDGETS}",
    )

    p_carview = sub.add_parser(
        "carview", help="Assemble a .car (body+wheels+substats) into a viewable HTML page"
    )
    p_carview.add_argument("car_file", type=Path)
    p_carview.add_argument("html_file", type=Path)
    p_carview.add_argument(
        "--z-offset", type=float, default=0.0,
        help="shift the wheel axle Z position (meters) -- tune by eye against a reference photo",
    )
    p_carview.add_argument(
        "--wheel-radius", type=float, default=None,
        help="override the wheel Y-height (meters); default uses a matching .tir file or a fallback",
    )
    p_carview.add_argument(
        "--paint", type=Path, default=None,
        help="a paintN.tex (from a live install's Config/ folder) to use for the main body "
             "paint, which isn't in the static archives -- see resolve_textures()",
    )
    p_carview.add_argument(
        "--serve", action="store_true",
        help="serve the output over a local HTTP server and open it in the default browser, "
             "instead of just writing the file -- opening the file directly (file://) can "
             "silently fail to run its scripts in some browsers/security setups, where "
             "serving it over http:// reliably works",
    )

    p_catalog = sub.add_parser(
        "catalog",
        help="Catalogue a folder of cars (loose .car or one-zip-per-car) into "
             "catalog.json/.csv plus a browsable index.html",
    )
    p_catalog.add_argument("cars_dir", type=Path,
                           help="folder to walk; the first directory below it becomes each car's 'collection'")
    p_catalog.add_argument("out_dir", type=Path)
    p_catalog.add_argument("--shots", action="store_true",
                           help="render every car ourselves (one consistent camera) instead of using "
                                "the zips' own screenshots -- about 0.5s per car")
    p_catalog.add_argument("--data-dir", type=Path, default=None,
                           help="a game Data folder, so shared materials (wheels, glass, effects, which "
                                "live in race.res) resolve while rendering")
    p_catalog.add_argument("--paint", type=Path, default=None,
                           help="a paint texture (Config/paint0.tex) to fill the runtime paint slot")

    p_gallery = sub.add_parser(
        "gallery",
        help="Scan a folder (recursively, any layout) for .car files and build a browsable index + one shell.html each",
    )
    p_gallery.add_argument("data_dir", type=Path)
    p_gallery.add_argument("out_dir", type=Path)
    p_gallery.add_argument(
        "--paint-dir", type=Path, default=None,
        help="directory with paint0.tex (a game install's Config/ folder) -- used as a stand-in body color for every car",
    )
    p_gallery.add_argument("--serve", action="store_true")

    p_shell = sub.add_parser(
        "shell", help="Integrated car view: Car/Cockpit/Horn Ball tabs, Stats and Textures drawers, View/Mod it! toggle"
    )
    p_shell.add_argument("car_file", type=Path)
    p_shell.add_argument("html_file", type=Path)
    p_shell.add_argument(
        "--paint-dir", type=Path, default=None,
        help="directory with paint0.tex (a game install's Config/ folder) -- used as a stand-in body color",
    )
    p_shell.add_argument("--serve", action="store_true")

    p_trackview = sub.add_parser(
        "trackview",
        help="View a track's scenery mesh (track.grf, read-only -- see grf.py) with a Textures drawer",
    )
    p_trackview.add_argument("trk_file", type=Path)
    p_trackview.add_argument("html_file", type=Path)
    p_trackview.add_argument("--serve", action="store_true")

    p_cockpitview = sub.add_parser(
        "cockpitview", help="View a car's dashboard+steering wheel (real cockpit.tab position), free-orbit"
    )
    p_cockpitview.add_argument("car_file", type=Path)
    p_cockpitview.add_argument("html_file", type=Path)
    p_cockpitview.add_argument("--serve", action="store_true")

    p_partview = sub.add_parser(
        "partview", help="View a single shared .mod (e.g. ball.mod, the horn ball) with its real texture"
    )
    p_partview.add_argument("data_dir", type=Path, help="the game's Data/ folder (searches its shared archives)")
    p_partview.add_argument("mod_name", help="e.g. ball.mod")
    p_partview.add_argument("html_file", type=Path)
    p_partview.add_argument("--serve", action="store_true")

    p_modretex = sub.add_parser(
        "modretex", help="Swap the texture filename a .mod material references"
    )
    p_modretex.add_argument("in_file", type=Path)
    p_modretex.add_argument("out_file", type=Path)
    p_modretex.add_argument("index", type=int, help="material index (see modinfo)")
    p_modretex.add_argument("new_texture", help="new texture filename, e.g. MYTEXTURE.tex")

    p_modlod = sub.add_parser(
        "modlod",
        help="Generate a car's LOD chain (<prefix>1.mod..7.mod) by decimating its body, "
             "carrying the body's textures -- so the car stays itself (not a viper) and "
             "stays textured at every distance (roster, replays, distant traffic)",
    )
    p_modlod.add_argument("car_file", type=Path, help="the .car to add LODs to")
    p_modlod.add_argument("--out", type=Path, default=None,
                          help="write here instead of rewriting the car in place")
    p_modlod.add_argument("--levels", type=int, default=7,
                          help="how many LODs to generate, 1..7 (default 7 = full chain)")
    p_modlod.add_argument("--targets", default=None, metavar="N,N,...",
                          help="explicit per-level vertex counts (LOD1 first), overriding the "
                               "default geometric falloff")
    p_modlod.add_argument("--keep-existing", action="store_true",
                          help="don't overwrite LOD meshes that already exist (only fill missing) "
                               "-- preserves hand-authored LODs")

    p_modpatch = sub.add_parser(
        "modpatch",
        help="Swap one or more already-edited standalone .mod files into a .car archive by entry name",
    )
    p_modpatch.add_argument("car_file", type=Path)
    p_modpatch.add_argument("out_file", type=Path)
    p_modpatch.add_argument(
        "set", nargs="+", metavar="entry_name=local_mod_file",
        help="one or more entry replacements, e.g. \"viperc.mod=my_dash.mod\" -- entry_name must "
             "already exist in the archive (see 'list'); local_mod_file is a standalone .mod, e.g. "
             "from obj2mod, moddecimate, or modretex",
    )

    args = parser.parse_args(argv)

    if args.command == "unpack":
        names = archive.unpack(args.archive, args.out_dir)
        print(f"unpacked {len(names)} member(s) to {args.out_dir}")
    elif args.command == "pack":
        archive.pack(args.in_dir, args.archive)
        print(f"packed {args.archive}")
    elif args.command == "trk2tra":
        try:
            res = track.export_tra(
                args.track_file, args.tra_file,
                layout=args.layout, require_members=not args.allow_missing,
            )
        except track.TrackExportError as ex:
            raise SystemExit(f"error: {ex}")
        note = " (byte-identical to source)" if res.byte_identical else ""
        print(f"wrote {res.dest} -- {res.member_count} members, {res.layout} layout{note}")
        if res.missing:
            print(f"  warning: missing {len(res.missing)} usual member(s): {', '.join(res.missing)}")
        if res.slot_specific:
            print(
                f"  note: carries slot-specific config {', '.join(res.slot_specific)} -- "
                "harmless, but it names a different slot than this file does"
            )
    elif args.command == "switcher":
        switcher_ui.serve(args.data_dir, port=args.port, open_browser=not args.no_browser)
    elif args.command == "aifield":
        try:
            if args.revert:
                print(aifield.revert(args.data_dir))
            elif args.count is None:
                st = aifield.status(args.data_dir)
                if st["file"] is None:
                    print("no options.cfg/options.def yet -- run the game once first")
                else:
                    print(f"{st['file']}")
                    print(f"  ai_car_count {st['ai_car_count']}  ai_cars {st['ai_cars']}  "
                          f"car_count {st['car_count']}  ->  {st['total']} cars "
                          f"({st['ai_car_count']} AI + player)")
                    print(f"  max settable: {aifield.MAX_AI} AI ({aifield.MAX_AI + 1}-car grid)")
            else:
                r = aifield.set_count(args.data_dir, args.count)
                print(f"set {r['file'].name}: {r['ai_car_count']} AI + player = {r['total']} cars")
                print("  NOTE: takes effect next launch. Do NOT touch the in-game AI selector "
                      "(it clamps to 7 and overwrites this).")
        except aifield.AiFieldError as e:
            raise SystemExit(f"error: {e}")
    elif args.command == "primarycar":
        try:
            if args.revert:
                print(primarycar.revert(args.data_dir))
            elif args.status or args.mod_car is None:
                print(f"primary car: {primarycar.status(args.data_dir)}")
            else:
                r = primarycar.install(args.data_dir, args.mod_car,
                                       paint_slots=args.paint_slots)
                print(f"installed {r['mod']} (prefix '{r['prefix']}') as {r['target'].name} "
                      f"-- {r['members']} members; the whole AI field will drive it")
                if r["paint_slots"] is not None:
                    print(f"  paint-slots: retagged {r['paint_slots']} body LOD(s) -> per-AI "
                          f"colours (viper paint UVs, so expect a rough look)")
                if r["vertex_warning"]:
                    print(f"\n  WARNING: {r['vertex_warning']}")
                print("  revert with: vrmod primarycar <Data> --revert")
        except primarycar.PrimaryCarError as e:
            raise SystemExit(f"error: {e}")
    elif args.command == "trackgen":
        from . import trackgen as _tg
        line = _tg.read_centreline(args.centreline)
        raw = len(line)
        # A .ase flagged *SHAPE_CLOSED is a circuit even though its knots stop
        # short of closing -- path10.ASE leaves a 201 m gap. Honour the flag
        # unless told otherwise, and resample across the seam so the ring is
        # continuous; sweeping it as open leaves a hole in the track.
        if str(args.centreline).lower().endswith(".ase"):
            closed = _tg.ase_is_closed(args.centreline)
        else:
            # No flag to consult, so ask the geometry: a centreline recovered
            # from a circuit comes back with its ends a station apart, not a lap
            # apart. Anything within a few spacings is a ring.
            import math as _math
            gap = _math.dist(line[0][:2], line[-1][:2])
            step = (sum(_math.dist(a[:2], b[:2]) for a, b in zip(line, line[1:]))
                    / max(len(line) - 1, 1))
            closed = gap < max(step * 4.0, args.spacing * 4.0)
        if args.open:
            closed = False
        if args.spacing > 0:
            line = _tg.resample(line, args.spacing, closed=closed)
        scene = _tg.sweep(
            line,
            road_half_width=args.road_width / 2.0,
            closed=closed,
        )
        _tg.add_checkpoints(scene, args.checkpoints, half_width=args.road_width / 2.0)
        _tg.add_grid(scene, args.grid)
        written = _tg.write_scene(scene, args.out_dir)
        print(f"{args.centreline.name}: {raw:,} points -> {len(scene.centreline):,} stations"
              f"{' (closed circuit)' if closed else ' (open)'}")
        for w in written:
            print(f"  {w.stat().st_size:>9,}  {w.name}")
        print()
        print(f"{len(scene.driveables)} driveable objects, written identically "
              f"to both scene files.")
        print(f"Next: run make-track.bat in {args.out_dir} to compile.")

    elif args.command == "trackmap":
        opts = {"line_width": args.line_width}
        if args.markers is not None:
            opts["markers"] = args.markers
        if args.install:
            out, w, h = trackmap.install(args.trk_file, **opts)
            print(f"wrote {w}x{h} Trackmap.stp into {out}")
        else:
            if args.out_file is None:
                raise SystemExit("error: give an output .png path, or pass --install")
            pixels, w, h = trackmap.render(args.trk_file, **opts)
            args.out_file.write_bytes(viewer._rgb_png(w, h, [bytearray(pixels[y*w*3:(y+1)*w*3]) for y in range(h)]))
            print(f"wrote {args.out_file} ({w}x{h})")
    elif args.command == "racebin":
        def show(tag, i):
            print(f"{tag}: {i.describes}")
            print(f"    {i.size:,} bytes, sha256 {i.sha256[:16]}")
            print(f"    modern-GPU startup fix: {i.vram_fix}")
            if i.modes:
                print(f"    resolutions: {', '.join(f'{w}x{h}' for w, h in i.modes)}")
        if args.install:
            incoming, replaced = racebin.install(args.data_dir, args.install)
            if replaced:
                show("replaced", replaced)
            show("installed", incoming)
            print("  the previous race.bin was backed up alongside it")
        else:
            show("current", racebin.inspect(args.data_dir / racebin.RACE_BIN))
    elif args.command == "bppsurface":
        from . import bpp as _bpp
        NAMES = {0: "asphalt", 10: "grass", 14: "water", 16: "rumble/apron", 20: "dirt?"}
        entries = archive.read(args.track)
        bpp_name = next((e.name for e in entries if e.name.lower().endswith(".bpp")), None)
        if bpp_name is None:
            raise SystemExit(f"no .bpp inside {args.track.name}")
        b = _bpp.parse(next(e.payload for e in entries if e.name == bpp_name))

        if not args.set:
            print(f"{args.track.name}: surface codes")
            for code, n in _bpp.surface_histogram(b).items():
                print(f"  {code:>3} {NAMES.get(code,''):<12} {n:>6,} triangles")
        else:
            mapping = {}
            for pair in args.set:
                old, new = pair.split("=")
                mapping[int(old)] = int(new)
            region = tuple(args.region) if args.region else None
            n = _bpp.retag(b, mapping, region=region)
            print(f"retagged {n:,} triangles: "
                  + ", ".join(f"{o}->{v}" for o, v in mapping.items())
                  + (f"  within XZ {region}" if region else ""))
            if n:
                new_std = envelope.build(b"TPPB", 2, _bpp.build(b))
                entries = archive.replace_entry(entries, bpp_name, new_std)
                out = args.out or args.track
                if out == args.track:
                    backup = out.with_suffix(out.suffix + ".surface-backup")
                    if not backup.exists():
                        shutil.copy2(out, backup)
                        print(f"  backed up original -> {backup.name}")
                archive.write(entries, out)
                print(f"  wrote {out}")
            else:
                print("  nothing matched; no file written")
    elif args.command == "collisioncheck":
        from . import collisioncheck as _cc
        if args.against:
            d = _cc.diff(args.against, args.track)
            print(f"diff  {args.against.name}  ->  {args.track.name}")
            print(f"  new invisible walls (collision left without render): "
                  f"{len(d.lost_render)} cluster(s)")
            for c in d.lost_render:
                print(f"     {c.count:>3} tris @ ({c.cx:8.1f},{c.cy:6.1f},{c.cz:8.1f})  "
                      f"footprint {c.xz_radius:.1f}m, height {c.y_extent:.1f}m")
            print(f"  new drive-through (render left without collision): "
                  f"{len(d.lost_collision)} cluster(s)")
            for c in d.lost_collision:
                print(f"     {c.count:>3} tris @ ({c.cx:8.1f},{c.cy:6.1f},{c.cz:8.1f})")
            if not d.lost_render and not d.lost_collision:
                print("  the edit changed no collision/render correspondence.")
        else:
            r = _cc.check(args.track)
            print(f"{args.track.name}:  {r.grf_triangles:,} render tris, "
                  f"{r.bpp_triangles:,} collision tris")
            print(f"  collision without nearby geometry: {r.collision_without_geometry:,} "
                  f"(mostly off-track terrain -- expected)")
            print(f"  geometry without nearby collision: {r.geometry_without_collision:,} "
                  f"(cosmetic detail -- expected)")
            s = r.suspects
            print(f"  PROP SUSPECTS (compact, standing, orphaned collision): {len(s)}")
            for c in s:
                print(f"     {c.count:>3} tris @ ({c.cx:8.1f},{c.cy:6.1f},{c.cz:8.1f})  "
                      f"footprint {c.xz_radius:.1f}m, height {c.y_extent:.1f}m")
            if not s:
                print("     none -- no invisible-wall-shaped clusters.")
            print("  NOTE: a tiny deleted prop can hide in the terrain baseline; "
                  "use --against <original> to catch an edit of any size.")
    elif args.command in ("bppinfo", "bpp2obj"):
        raw = args.trk_file.read_bytes()
        # Three shapes reach here, distinguished by magic rather than extension:
        # a track archive (0TSR -- .trk retail or .tra repacked) carrying the
        # .bpp as one member; a loose member still in its envelope (0SER), which
        # is what the MKWORLD toolchain writes into out/; and a bare payload.
        if raw[:4] == archive.MAGIC:
            entry = next((e for e in archive.read_bytes(raw)
                          if e.name.lower().endswith(".bpp")), None)
            if entry is None:
                raise SystemExit(f"no .bpp inside {args.trk_file.name}")
            raw = entry.payload
        elif raw[:4] == envelope.MAGIC:
            raw = envelope.parse(raw).payload
        b = bppmod.parse(raw)
        if args.command == "bpp2obj":
            args.obj_file.write_text(bppmod.to_obj(b, args.trk_file.stem))
            print(f"{len(b.triangles):,} collision triangles -> {args.obj_file}")
        else:
            reached = sum(1 for _ in bppmod.walk(b))
            flags = {}
            flat = 0
            for t in b.triangles:
                flags[t.flag] = flags.get(t.flag, 0) + 1
                if t.normal[1] > 0.99:
                    flat += 1
            ys = [v[1] for t in b.triangles for v in t.v]
            print(f"  triangles     {len(b.triangles):,}")
            print(f"  nodes         {len(b.nodes):,}  (root {b.root:,}; "
                  f"{reached:,} reachable, {reached/max(1,len(b.nodes))*100:.1f}%)")
            print(f"  height range  {min(ys):.1f} .. {max(ys):.1f}")
            print(f"  flat-and-up   {flat:,} ({flat/max(1,len(b.triangles))*100:.1f}%) "
                  f"-- the drivable surface; the rest are walls, kerbs and objects")
            print("  surface flags " + ", ".join(
                f"{k}={v:,}" for k, v in sorted(flags.items())))
            print(f"  payload       {b.size:,} bytes"
                  f"{'' if b.size == len(raw) else '  MISMATCH vs ' + str(len(raw))}")
    elif args.command == "patch":
        if args.status:
            for k, v in patchset.status(args.data_dir).items():
                print(f"  {k:<11} {v}")
            scaled = patchset.scaling_active()
            print(f"  {'dpi':<11} launcher marked aware: "
                  f"{patchset.dpi_aware(args.data_dir)}"
                  f"{'; desktop IS scaled' if scaled else ''}")
        elif args.revert:
            print(patchset.revert(args.data_dir))
        else:
            w, h = (int(v) for v in args.mode.lower().split("x"))
            rep = patchset.apply(args.data_dir, mode=(w, h), index=args.index,
                                 with_map=not args.no_map, ratio=args.fov,
                                 big_tables=not args.small_tables,
                                 max_verts=args.max_verts,
                                 force_baseline=args.force_baseline)
            print(f"rebuilt from {rep.baseline}")
            for name, detail in rep.steps:
                print(f"  {name:<22} {detail}")
            if args.dpi_aware:
                print(f"  {'dpi':<22} {patchset.set_dpi_aware(args.data_dir)}")
            for note in rep.notes:
                print(f"\n  NOTE: {note}")
            print("\n  Re-run this command any time -- it rebuilds from the snapshot "
                  "rather than layering,\n  so the same arguments always give the same bytes. "
                  "--revert restores the original.")
    elif args.command == "patch-vram":
        state = vrampatch.status(args.data_dir)
        if args.revert:
            at = vrampatch.revert(args.data_dir)
            print(f"restored the original instruction at {hex(at)}")
        elif state == vrampatch.PATCHED:
            print("already patched -- nothing to do")
        else:
            at = vrampatch.apply(args.data_dir)
            print(f"patched race.bin at {hex(at)} (8 bytes)")
            print("  original backed up as race.bin.vram-backup")
            print("  This is the STARTUP fix only. The community race.bin (v1.2.5) also")
            print("  raises the polygon and vertex limits, which high-detail mods need.")
    elif args.command == "resolution":
        if args.set:
            idx = int(args.set[0])
            w, h = (int(v) for v in args.set[1].lower().split("x"))
            was = resolution.set_mode(args.data_dir, idx, w, h)
            print(f"mode {idx}: {was[0]} x {was[1]} -> {w} x {h}")
            print(f"  race.bin backed up as race.bin.res-backup")
            print("  NOTE: that the game reads dimensions from these labels is inferred, "
                  "not proven -- start the game and check before relying on it.")
        for i, (w, h) in enumerate(resolution.read(args.data_dir)):
            print(f"  mode {i}: {w} x {h}")
        m = doctor.video_mode(args.data_dir)
        if m is not None:
            print(f"  (the game is currently set to mode {m})")
    elif args.command == "hornball":
        if not hornball.available(args.data_dir):
            print("This race.bin doesn't carry the horn-ball launch code this can tune.")
            return 1
        if args.reset:
            hornball.reset(args.data_dir)
        elif args.speed is not None or args.cooldown is not None:
            hornball.apply(args.data_dir, speed_mult=args.speed, cooldown=args.cooldown)
        t = hornball.read(args.data_dir)
        print(f"horn-ball: speed {t.speed_mult:.2f}x (stock 1.0), "
              f"cooldown {t.cooldown:.2f}s (stock 2.0)"
              + ("  [stock]" if t.is_stock else ""))
        if args.speed is None and args.cooldown is None and not args.reset:
            print("  --speed MULT / --cooldown SECONDS to change, --reset for stock. "
                  "Enable the hack in-game from the hidden hacks menu.")
    elif args.command == "carfork":
        entries = archive.read(args.car_file)
        old = car.body_prefix(entries)
        forked = car.fork_car(entries, args.new_prefix)
        if args.name:
            forked = car.set_car_name(forked, args.name)
        out = args.out or (args.car_file.parent / f"{args.new_prefix}.car")
        if out.exists():
            print(f"refusing to overwrite existing {out}")
            return 1
        archive.write(forked, out)
        print(f"forked {args.car_file.name} -> {out.name}  (prefix '{old}' -> '{args.new_prefix}', "
              f"{len(forked)} members)")
        print("  Put it in the Data folder: it appears in Options -> Hacks -> Vehicle, and can be "
              "driven while the AI field keeps its own car.")
    elif args.command == "doctor":
        rep = doctor.check(args.data_dir)
        marks = {doctor.BAD: "!!", doctor.WARN: " !", doctor.OK: " *", doctor.INFO: "  "}
        print(rep.game_root)
        print()
        for f in rep.findings:
            print(f"{marks[f.level]} {f.title}")
            print(f"     {f.detail}")
            if f.fix:
                print(f"     -> {f.fix}")
            print()
        print({doctor.BAD: "Something here will stop the game working.",
               doctor.WARN: "Worth acting on, but the game should still run.",
               doctor.INFO: "Nothing wrong.",
               doctor.OK: "Nothing wrong."}[rep.worst])
    elif args.command == "skyexport":
        w, h = sky.export_tga(args.trk_file, args.tga_file)
        print(f"wrote {args.tga_file} ({w}x{h})")
        print(f"  this strip is ONE QUARTER of the horizon -- the game repeats it "
              f"{sky.REPEATS} times around, so it must tile seamlessly left-to-right, "
              f"and anything unique in it appears {sky.REPEATS} times in game.")
    elif args.command == "skyimport":
        out, size, was = sky.install_tga(args.trk_file, args.tga_file, args.out, args.tile_size)
        print(f"wrote {len(sky.TILES)} x {size}x{size} sky tiles into {out}")
        if size != was:
            print(f"  NOTE: tile size changed {was} -> {size}")
            if size > 256:
                print("  256 is the stock maximum -- larger tiles need a patched game "
                      "and may not load on an unpatched one.")
        if args.out is None:
            print(f"  original backed up as {args.trk_file.name}.sky-backup")
    elif args.command == "carshot":
        args.out_file.write_bytes(carshot.to_png(
            args.car_file, style=args.style, wheels=not args.no_wheels,
            width=args.width, height=args.height,
            yaw=args.yaw, pitch=args.pitch, paint_texture=args.paint,
        ))
        print(f"wrote {args.out_file} ({args.width}x{args.height})")
    elif args.command == "list":
        entries = archive.read(args.archive)
        for e in entries:
            print(
                f"{e.name:20s} {e.mnemonic:6s} v{e.version:<3d} {e.payload_size:>10,d} bytes"
            )
        print(f"\n{len(entries)} entries")
    elif args.command == "tex2tga":
        tex.tex_to_tga(args.tex_file, args.tga_file)
        print(f"wrote {args.tga_file}")
    elif args.command == "sfx2wav":
        sfx.sfx_to_wav(args.sfx_file, args.wav_file)
        print(f"wrote {args.wav_file}")
    elif args.command == "wav2sfx":
        sfx.wav_to_sfx(args.wav_file, args.sfx_file)
        print(f"wrote {args.sfx_file}")
    elif args.command == "tga2tex":
        kwargs = {"wrap": args.wrap}
        if args.mode is not None:
            kwargs["mode"] = args.mode
        tex.tga_to_tex(args.tga_file, args.tex_file, **kwargs)
        print(f"wrote {args.tex_file}")
    elif args.command == "cfdump":
        values = cf.parse_file(args.cf_file)
        text = cf.to_text(values)
        if args.txt_file is not None:
            args.txt_file.write_text(text)
            print(f"wrote {args.txt_file}")
        else:
            print(text, end="")
    elif args.command == "txt2cf":
        values = cf.parse_text(args.txt_file.read_text())
        base_raw = args.base_cf.read_bytes()
        new_raw = cf.build(base_raw, values)
        args.out_file.write_bytes(new_raw)
        print(f"wrote {args.out_file} ({len(values)} field(s) from {args.txt_file})")
    elif args.command == "cockpitdump":
        records = cockpit_tab.parse_file(args.tab_file)
        text = cockpit_tab.to_text(records)
        if args.txt_file is not None:
            args.txt_file.write_text(text)
            print(f"wrote {args.txt_file}")
        else:
            print(text, end="")
    elif args.command == "txt2cockpit":
        records = cockpit_tab.parse_text(args.txt_file.read_text())
        base_raw = args.base_tab.read_bytes()
        new_raw = cockpit_tab.build(base_raw, records)
        args.out_file.write_bytes(new_raw)
        print(f"wrote {args.out_file} ({len(records)} record(s) from {args.txt_file})")
    elif args.command == "cockpitset":
        raw = args.in_file.read_bytes()
        edits = _parse_record_edits(parser, args.set)
        new_raw = cockpit_tab.build(raw, edits)
        args.out_file.write_bytes(new_raw)
        print(f"wrote {args.out_file} ({len(edits)} record(s) changed)")
    elif args.command == "cockpitpatch":
        entries = archive.read(args.car_file)
        base_raw = car._entry_bytes(entries, "cockpit.tab")
        if base_raw is None:
            parser.error(f"{args.car_file} has no cockpit.tab entry")
        edits = _parse_record_edits(parser, args.set)
        new_raw = cockpit_tab.build(base_raw, edits)
        new_entries = archive.replace_entry(entries, "cockpit.tab", new_raw)
        archive.write(new_entries, args.out_file)
        print(f"wrote {args.out_file} ({len(edits)} cockpit.tab record(s) changed)")
    elif args.command == "modinfo":
        mesh = mod.parse_file(args.mod_file)
        print(f"vertices={len(mesh.vertices)} faces={len(mesh.faces)} materials={len(mesh.materials)}")
        for i, m in enumerate(mesh.materials):
            print(
                f"  [{i}] {m.name:20s} verts[{m.vertex_start}:{m.vertex_end}) "
                f"faces[{m.face_start}:{m.face_end})"
            )
    elif args.command == "mod2obj":
        mesh = mod.parse_file(args.mod_file)
        mod.write_obj(mesh, args.obj_file)
        print(f"wrote {args.obj_file}")
    elif args.command == "obj2mod":
        if args.budget is not None and args.patch is not None:
            parser.error("pass either --budget or --patch, not both")
        budget = args.budget if args.budget is not None else (
            mod.VERTEX_BUDGETS[args.patch] if args.patch else None
        )
        mesh = mod.read_obj(args.obj_file)
        before = len(mesh.vertices)
        if budget is not None and before > budget:
            mesh = mod.decimate(mesh, budget)
            print(f"decimated {before} -> {len(mesh.vertices)} vertices (budget {budget})")
        elif budget is None:
            biggest = mod.VERTEX_BUDGETS["hd"]
            if before > biggest:
                print(f"warning: {before:,} vertices exceeds every known ceiling "
                      f"({mod.VERTEX_BUDGETS}); no game build will load this")
            elif before > mod.VERTEX_BUDGETS["original"]:
                print(f"note: {before:,} vertices is over the original game's "
                      f"{mod.VERTEX_BUDGETS['original']:,} per object -- needs a patched "
                      f"race.bin. Pass --patch to decimate instead.")
        new_raw = mod.build(mesh)
        args.mod_file.write_bytes(new_raw)
        print(
            f"wrote {args.mod_file} "
            f"(vertices={len(mesh.vertices)} faces={len(mesh.faces)} materials={len(mesh.materials)})"
        )
    elif args.command == "moddecimate":
        if args.budget is not None and args.patch is not None:
            parser.error("pass either --budget or --patch, not both")
        if args.budget is None and args.patch is None:
            parser.error("pass --budget or --patch")
        budget = args.budget if args.budget is not None else mod.VERTEX_BUDGETS[args.patch]
        mesh = mod.parse_file(args.in_file)
        before = len(mesh.vertices)
        mesh = mod.decimate(mesh, budget)
        args.out_file.write_bytes(mod.build(mesh))
        print(f"wrote {args.out_file}: {before} -> {len(mesh.vertices)} vertices (budget {budget})")
    elif args.command == "carview":
        viewer.write_viewer_html(
            args.car_file, args.html_file, z_offset=args.z_offset, wheel_radius=args.wheel_radius,
            paint_texture=args.paint,
        )
        print(f"wrote {args.html_file}")
        if args.serve:
            serve_and_open(args.html_file)
    elif args.command == "partview":
        viewer.write_part_viewer_html(args.data_dir, args.mod_name, args.html_file)
        print(f"wrote {args.html_file}")
        if args.serve:
            serve_and_open(args.html_file)
    elif args.command == "catalog":
        records = catalog_mod.catalog(args.cars_dir)
        ok = sum(1 for r in records if not r.error)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "catalog.json").write_text(catalog_mod.to_json(records), encoding="utf-8")
        (args.out_dir / "catalog.csv").write_text(catalog_mod.to_csv(records), encoding="utf-8")
        if args.shots:
            n = catalog_mod.render_shots(records, args.cars_dir, args.out_dir,
                                         paint_texture=args.paint, shared_from=args.data_dir)
            print(f"rendered {n} car shot(s)")
        else:
            n = catalog_mod.extract_thumbnails(records, args.cars_dir, args.out_dir)
            print(f"extracted {n} bundled screenshot(s)")
        page = catalog_mod.build_page(records, args.out_dir)
        print(f"wrote {page} ({ok}/{len(records)} car(s) read)")
        missing = [r.filename for r in records if r.error]
        if missing:
            print(f"  {len(missing)} unreadable: {', '.join(missing[:5])}"
                  + (" ..." if len(missing) > 5 else ""))

    elif args.command == "gallery":
        result = viewer.build_gallery(args.data_dir, args.out_dir, paint_dir=args.paint_dir)
        ok = sum(1 for c in result.cars if c.error is None)
        track_ok = sum(1 for t in result.tracks if t.error is None)
        print(
            f"wrote {args.out_dir / 'index.html'} "
            f"({ok}/{len(result.cars)} car(s) rendered, "
            f"{track_ok}/{len(result.tracks)} track(s) rendered, "
            f"{result.resource_archive_count} resource archive(s) found)"
        )
        for c in result.cars:
            if c.error is not None:
                print(f"  FAILED: {c.car_path} -- {c.error}")
        for t in result.tracks:
            if t.error is not None:
                print(f"  FAILED: {t.track_path} -- {t.error}")
        if args.serve:
            serve_and_open(args.out_dir / "index.html")
    elif args.command == "shell":
        viewer.write_shell_html(args.car_file, args.html_file, paint_dir=args.paint_dir)
        print(f"wrote {args.html_file}")
        if args.serve:
            serve_and_open(args.html_file)
    elif args.command == "trackview":
        viewer.write_track_viewer_html(args.trk_file, args.html_file)
        print(f"wrote {args.html_file}")
        if args.serve:
            serve_and_open(args.html_file)
    elif args.command == "cockpitview":
        viewer.write_cockpit_viewer_html(args.car_file, args.html_file)
        print(f"wrote {args.html_file}")
        if args.serve:
            serve_and_open(args.html_file)
    elif args.command == "modretex":
        raw = args.in_file.read_bytes()
        new_raw = mod.set_material_texture(raw, args.index, args.new_texture)
        args.out_file.write_bytes(new_raw)
        print(f"wrote {args.out_file} (material {args.index} -> {args.new_texture})")
    elif args.command == "cfset":
        raw = args.in_file.read_bytes()
        edits = _parse_field_edits(parser, args.set)
        new_raw = cf.build(raw, edits)
        args.out_file.write_bytes(new_raw)
        print(f"wrote {args.out_file} ({len(edits)} field(s) changed)")
    elif args.command == "cfpatch":
        entries = archive.read(args.car_file)
        prefix = car._find_prefix(entries)
        cf_name = f"{prefix}.cf"
        base_raw = car._entry_bytes(entries, cf_name)
        if base_raw is None:
            parser.error(f"{args.car_file} has no {cf_name} entry")
        edits = _parse_field_edits(parser, args.set)
        new_raw = cf.build(base_raw, edits)
        new_entries = archive.replace_entry(entries, cf_name, new_raw)
        archive.write(new_entries, args.out_file)
        print(f"wrote {args.out_file} ({len(edits)} {cf_name} field(s) changed)")
    elif args.command == "modlod":
        entries = archive.read(args.car_file)
        targets = None
        if args.targets:
            targets = [int(x) for x in args.targets.replace(" ", "").split(",") if x]
        out_entries, made = car.build_lod_chain(
            entries, targets=targets, levels=args.levels, keep_existing=args.keep_existing)
        out = args.out or args.car_file
        if out == args.car_file:                       # in place -> keep a pristine backup
            backup = _unique_path(
                args.car_file.with_name(f"{args.car_file.stem}_original{args.car_file.suffix}.bak"))
            shutil.copy2(args.car_file, backup)
            print(f"backed up -> {backup.name}")
        archive.write(out_entries, out)
        print(f"wrote {out}")
        for name, vc in made:
            print(f"  {name}: {vc} verts")
        if not made:
            print("  (nothing generated -- all levels already present and --keep-existing set)")
    elif args.command == "modpatch":
        entries = archive.read(args.car_file)
        edits = {}
        for pair in args.set:
            if "=" not in pair:
                parser.error(f"expected entry_name=local_mod_file, got {pair!r}")
            entry_name, local_path = pair.split("=", 1)
            edits[entry_name] = Path(local_path).read_bytes()
        for entry_name, raw in edits.items():
            entries = archive.replace_entry(entries, entry_name, raw)
        archive.write(entries, args.out_file)
        print(f"wrote {args.out_file} ({len(edits)} .mod entry/entries replaced)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
