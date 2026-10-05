"""Check vrmod's modtool.res: what v1.0's model editor loads, and the install / remove rules.

The editor (Ctrl+E on v1.0's main menu) loads modtool.res, which no disc shipped. This builds vrmod's
and checks it the way the game reads it: the archive parses and round-trips, every name the editor
loads is there (and nothing it gets from common.res / ui.res is duplicated), each button stamp is
the uncompressed two-frame kind at the size its place in the editor's layout leaves room for, with
the two frames visibly different, the background is the 3D view's 300 x 256, point.mod names its
texture, and the textures are 8.3 names, power-of-two, at most 256 and free of black (which some
cards key out). Then the background's sources: a dark catalog.stp in ui.res is cropped in its own
palette; a missing, bright or unreadable one falls back to the generated panel. Then the rules, in
temp folders with a stand-in v1.0 race.exe: missing -> written; the community stand-in (by sha256)
-> replaced and kept as the backup; anyone else's -> left alone unless --force; an older one of ours
-> outdated; remove puts back what it replaced; the modern engine's install / remove carry it; the
doctor's finding for each state. Nothing is launched and nothing under game-files is written.

Run:  python scripts/check_modtool.py
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, doctor, envelope, mod, modern_engine as me, modtool as mt, stp, tex  # noqa: E402

FAILS: list[str] = []
STANDIN_COPY = (Path(__file__).resolve().parents[2] / "game-files" / "installs" / "v1.0-RC" / "modtool.res")

# What ModTool loads (viper-racing-port hook/edit_tool.cpp, edit_view.cpp; race_v10.exe's strings),
# with where each comes from.
EDITOR_LOADS = ["carback.stp", "point.mod", "wire_f.tex", "wedge.tex",
                "tview.stp", "ttri.stp", "tvert.stp", "tedge.stp", "tgeom.stp",
                "tnewp.stp", "tmovp.stp", "ttrans.stp", "tscale.stp",
                "tulock.stp", "tvlock.stp", "tuvsnap.stp", "tnlock.stp",
                "tplane.stp", "t3pput.stp", "capture.stp", "zoom.stp",
                "newsurf.stp", "surfprop.stp", "browse.stp", "mktmplt.stp"]
FROM_OTHER_SETS = ["ok.stp", "cancel.stp", "lscroll.stp", "rscroll.stp", "cross.stp",   # common.res
                   "prev.stp", "next.stp", "dialog1.stp"]                                 # ui.res
RADIO_BUTTONS = {"tview", "ttri", "tvert", "tedge", "tgeom", "tnewp", "tmovp", "ttrans", "tscale",
                 "tulock", "tvlock", "tuvsnap", "tnlock"}

# Each button's top-left in the editor (ModTool's and set_texture_cb's item lists) and the room it has.
LAYOUT = {   # name: (x, y, max width, max height)
    "tview": (20, 360, 24, 30), "ttri": (44, 360, 24, 30), "tvert": (68, 360, 24, 30),
    "tedge": (92, 360, 22, 30), "tgeom": (114, 360, 26, 30),
    "tnewp": (340, 360, 24, 30), "tmovp": (364, 360, 24, 30), "ttrans": (388, 360, 24, 30),
    "tscale": (412, 360, 28, 30), "tulock": (440, 360, 24, 30), "tvlock": (464, 360, 24, 30),
    "tuvsnap": (488, 360, 24, 30), "tnlock": (512, 360, 28, 30), "tplane": (540, 360, 24, 30),
    "t3pput": (564, 360, 76, 30),
    "capture": (500, 341, 20, 19),             # between lscroll (480 + 18) and rscroll (520); radio row at 360
    "zoom": (597, 317, 43, 18),                # the scroll bars' corner; the coordinates text at y 335
    "newsurf": (480, 390, 70, 50), "surfprop": (550, 390, 90, 50),   # prev / next row; Import row at 440
    "browse": (220, 19, 100, 21),              # Surface Properties (320 x 200); Material row at y 40
    "mktmplt": (90, 163, 158, 37),             # between ok (8 + 64) and cancel (248)
}


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(name)
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))


def v10_race_exe() -> bytes:
    """A stand-in v1.0 race.exe: just the PE header, with v1.0's timestamp."""
    b = bytearray(0x200)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", b, 0x84, 0x14C, 1, me.V10_TIMESTAMP)
    return bytes(b)


def titles(d: Path) -> list[str]:
    return [f.title for f in doctor.check(d).findings]


def model_findings(d: Path):
    return [f for f in doctor.check(d).findings if "odel editor" in f.title]


def catalog_res(rgb: tuple[int, int, int]) -> bytes:
    """A ui.res holding only a 640 x 480 uncompressed catalog.stp: one colour, a lighter stripe at
    the crop's corner so the crop's position can be checked."""
    px = bytearray(bytes(rgb) * (640 * 480))
    x0, y0 = mt.BG_SOURCE[2], mt.BG_SOURCE[3]
    for x in range(x0, x0 + 5):
        o = (y0 * 640 + x) * 3
        px[o:o + 3] = bytes(min(c + 40, 255) for c in rgb)
    st = stp.build_from_rgb(bytes(px), 640, 480)
    env = envelope.parse(st)
    return archive.to_bytes([archive.ArchiveEntry("catalog.stp", env.tag, env.version, env.payload)])


def check_archive(data: bytes, label: str) -> None:
    print(f"the archive ({label})")
    entries = archive.read_bytes(data)
    by = {e.name.lower(): e for e in entries}
    check("parses and round-trips byte for byte", archive.to_bytes(entries) == data)
    check("every name the editor loads is there", all(n in by for n in EDITOR_LOADS),
          ", ".join(n for n in EDITOR_LOADS if n not in by))
    check("null.tex (point.mod's texture) is there", "null.tex" in by)
    check("nothing beyond what's loaded", set(by) == set(EDITOR_LOADS) | {"null.tex"},
          ", ".join(sorted(set(by) - set(EDITOR_LOADS) - {"null.tex"})))
    check("nothing common.res / ui.res already provide", not any(n in by for n in FROM_OTHER_SETS))
    check("names fit 8.3", all(len(n.split(".")[0]) <= 8 and len(n) <= 12 for n in by))
    for name in EDITOR_LOADS:
        if not name.endswith(".stp") or name == "carback.stp":
            continue
        base = name[:-4]
        e = by[name]
        try:
            s = stp.parse_payload(e.payload)
        except ValueError as ex:
            check(f"{name}: the uncompressed stamp", False, str(ex))
            continue
        x, y, mw, mh = LAYOUT[base]
        f0 = s.pixels[:len(s.pixels) // 2]
        f1 = s.pixels[len(s.pixels) // 2:]
        ok = (e.version == 3 and s.frames == 2 and s.hotspot == (0, 0) and s.width <= mw and s.height <= mh
              and f0 != f1)
        kind = "unselected / selected" if base in RADIO_BUTTONS else "up / pressed"
        check(f"{name}: {s.width}x{s.height}, 2 frames ({kind}), fits at ({x}, {y})", ok,
              f"{s.width}x{s.height} f{s.frames} room {mw}x{mh}")
    bg = stp.parse_payload(by["carback.stp"].payload)
    check("carback.stp is the 3D view's 300 x 256, one frame", (bg.width, bg.height, bg.frames) == (300, 256, 1))
    m = mod.parse(by["point.mod"].to_standalone_bytes())
    check("point.mod: one material, null.tex, covering every face",
          [x.name for x in m.materials] == ["null.tex"] and m.materials[0].face_end == len(m.faces) > 0)
    check("point.mod's marker meets at the origin (the picked vertex)",
          min(abs(v.x) + abs(v.y) + abs(v.z) for v in m.vertices) < 1e-6)
    for name in ("null.tex", "wire_f.tex", "wedge.tex"):
        info = tex.parse(by[name].to_standalone_bytes())
        raw = info.pixel_data[-(info.size * info.size * 2):]
        texels = struct.unpack(f"<{info.size * info.size}H", raw)
        black = sum(1 for t in texels if t in (0x0000, 0x0020))
        check(f"{name}: opaque, {info.size}x{info.size}, no black texels",
              info.flags == 0 and info.size <= 256 and info.size & (info.size - 1) == 0 and black == 0,
              f"flags {info.flags}, {black} black")


def main() -> None:
    data, source = mt.build(None)
    check_archive(data, "no install: the generated background")
    check("the background is generated with no install to compose from", source == "generated")
    check("the build is deterministic", mt.build(None)[0] == data)

    if STANDIN_COPY.is_file():
        print("the community stand-in")
        sha = hashlib.sha256(STANDIN_COPY.read_bytes()).hexdigest()
        check("STANDIN_SHA256 is the install's copy", sha == mt.STANDIN_SHA256, sha)
        names = {e.name.lower() for e in archive.read(STANDIN_COPY)}
        check("it lacks wedge.tex (edge mode's texture), which ours has", "wedge.tex" not in names)
        payloads = [e.payload for e in archive.read(STANDIN_COPY) if e.name.endswith(".stp") and e.name != "carback.stp"]
        same = max(payloads.count(p) for p in payloads)
        check("18 of its 21 tool buttons are one placeholder", len(payloads) == 21 and same == 18, f"{same}")
    else:
        print(f"(no stand-in copy at {STANDIN_COPY}: its checks skipped)")

    print("the background's sources")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        bg, src = mt.compose_background(d)
        check("no ui.res: generated", src == "generated")
        (d / "ui.res").write_bytes(catalog_res((20, 22, 30)))
        bg, src = mt.compose_background(d)
        s = stp.parse(bg)
        check("a dark catalog.stp: cropped from it", src == "ui.res catalog.stp", src)
        check("the crop starts at the panel corner", s.pixels[0:3] != s.pixels[3 * 6:3 * 6 + 3]
              and (s.width, s.height) == (300, 256))
        (d / "ui.res").write_bytes(catalog_res((200, 200, 200)))
        check("a bright catalog.stp: generated instead", mt.compose_background(d)[1] == "generated")
        (d / "ui.res").write_bytes(b"0TSR garbage")
        check("an unreadable ui.res: generated", mt.compose_background(d)[1] == "generated")

    print("install / remove")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        try:
            mt.install(d)
            check("refuses without a v1.0 race.exe", False)
        except mt.ModtoolError:
            check("refuses without a v1.0 race.exe", True)
        check("no finding without a v1.0 race.exe", not model_findings(d))
        (d / "race.exe").write_bytes(v10_race_exe())

        check("absent", mt.status(d)["state"] == mt.ABSENT)
        check("the doctor says why the editor won't open", "Model editor not set up: no modtool.res" in titles(d))
        msg = mt.install(d)
        check("written", mt.status(d)["state"] == mt.INSTALLED, msg)
        check_archive((d / mt.NAME).read_bytes(), "installed")
        check("the record names the generator", json.loads((d / mt.RECORD).read_text())["generator"] == mt.GENERATOR)
        check("the doctor says it's ready", "Model editor ready" in titles(d))
        check("reinstall keeps it installed", mt.install(d) and mt.status(d)["state"] == mt.INSTALLED)

        rec = json.loads((d / mt.RECORD).read_text())
        rec["generator"] = mt.GENERATOR - 1
        (d / mt.RECORD).write_text(json.dumps(rec))
        check("an older one of ours is outdated", mt.status(d)["state"] == mt.OUTDATED)
        check("the doctor offers the update", any(f.action == "modtool" for f in model_findings(d)))
        mt.install(d)
        check("install updates it", mt.status(d)["state"] == mt.INSTALLED)

        msg = mt.remove(d)
        check("remove takes ours out", not (d / mt.NAME).exists() and not (d / mt.RECORD).exists(), msg)
        check("remove twice is harmless", "nothing to remove" in mt.remove(d))

        print("the community stand-in (matched by sha256)")
        fake = b"0TSR a stand-in modtool.res"
        real_sha = mt.STANDIN_SHA256
        mt.STANDIN_SHA256 = hashlib.sha256(fake).hexdigest()
        try:
            (d / mt.NAME).write_bytes(fake)
            check("recognised", mt.status(d)["state"] == mt.STANDIN)
            check("the doctor offers to replace it", any(f.action == "modtool" and "stand-in" in f.title
                                                         for f in model_findings(d)))
            msg = mt.install(d)
            check("replaced", mt.status(d)["state"] == mt.INSTALLED, msg)
            check("kept as the backup", (d / mt.BACKUP).read_bytes() == fake)
            mt.remove(d)
            check("remove puts it back", (d / mt.NAME).read_bytes() == fake and not (d / mt.BACKUP).exists())

            print("the modern engine carries it (v1.0)")
            if me.bundled()["available"]:
                me._run_probe = lambda exe, race, cwd: (0, "stand-in: yes")
                msg = me.install(d)
                check("engine install writes it", mt.status(d)["state"] == mt.INSTALLED, msg)
                check("engine status reports it", me.status(d)["modtool"]["state"] == mt.INSTALLED)
                msg = me.remove(d)
                check("engine remove takes it out and puts the stand-in back",
                      (d / mt.NAME).read_bytes() == fake and not (d / mt.BACKUP).exists(), msg)
            else:
                print("  (the modern engine isn't bundled: skipped)")
        finally:
            mt.STANDIN_SHA256 = real_sha

        print("someone else's modtool.res")
        theirs = b"0TSR someone's own modtool.res"
        (d / mt.NAME).write_bytes(theirs)
        check("foreign", mt.status(d)["state"] == mt.FOREIGN)
        msg = mt.install(d)
        check("left alone without --force", (d / mt.NAME).read_bytes() == theirs and "left" in msg.lower(), msg)
        check("the doctor says it's left alone", any("didn't write" in f.title for f in model_findings(d)))
        if me.bundled()["available"]:
            msg = me.install(d)
            check("the engine's install leaves it alone too", (d / mt.NAME).read_bytes() == theirs, msg)
            me.remove(d)
            check("and the engine's remove", (d / mt.NAME).read_bytes() == theirs)
        mt.install(d, force=True)
        check("--force replaces it", mt.status(d)["state"] == mt.INSTALLED)
        check("--force keeps it as the backup", (d / mt.BACKUP).read_bytes() == theirs)
        mt.remove(d)
        check("remove puts it back", (d / mt.NAME).read_bytes() == theirs and not (d / mt.BACKUP).exists())
        check("remove leaves someone else's alone", "left alone" in mt.remove(d)
              and (d / mt.NAME).read_bytes() == theirs)

    if FAILS:
        for f in FAILS:
            print(f"  FAILED: {f}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
