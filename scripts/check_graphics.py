"""Check viperport.ini handling: install keeps the player's settings, and the Graphics preset.

Everything runs in temp folders. install() must create viperport.ini only when there is none, and
otherwise switch on just the three [platform] keys -- a [debug] section, comments and the file's line
endings stay as they were. set_graphics() writes exactly [graphics] anisotropic= and msaa=, and
graphics() reads them back (original / enhanced / high, or custom for anything else).

Run:  python scripts/check_graphics.py
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import modern_engine as me  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(name)
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))


def lines_changed(before: str, after: str) -> tuple[list[str], list[str]]:
    """(lines gone, lines added), as sets of lines -- order-insensitive, enough for these checks."""
    b, a = before.splitlines(), after.splitlines()
    return [x for x in b if x not in a], [x for x in a if x not in b]


def gv(d: Path) -> dict:
    """graphics() without the game-filtering fields."""
    g = me.graphics(d)
    return {k: g[k] for k in ("anisotropic", "msaa", "preset")}


def v10_race_exe() -> bytes:
    """A stand-in v1.0 race.exe: just the PE header, with v1.0's timestamp."""
    b = bytearray(0x200)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", b, 0x84, 0x14C, 1, me.V10_TIMESTAMP)
    return bytes(b)


# Shaped like the game's own options.cfg: CRLF, `key value`, the two keys far apart, sections repeated.
GAME_OPTIONS = "\r\n".join([
    "version 1", "[GX]", "filtering no", "sky_texture no", "[SOUND]", "channels 8",
    "[GX]", "mirror 0", "shadow 0", "skids 2", "mipmap no", "fog no", "lighting no",
    "[GAME]", "draw_distance 0.500000", ""])


def options_case(root: Path) -> None:
    """The game's options.cfg: Enhanced / High switch filtering and mipmap on, Original leaves them."""
    print("the game's options.cfg (v1.0: <Data>\\Config)")
    d = root / "v10" / "Data"
    d.mkdir(parents=True)
    (d / "race.exe").write_bytes(v10_race_exe())
    me.install(d)
    stray = d.parent / "Config"                   # one level up: some other copy's, never ours on v1.0
    stray.mkdir()
    (stray / "options.cfg").write_bytes(GAME_OPTIONS.encode())
    msg = me.set_graphics(d, "enhanced")
    check("no options.cfg yet: the ini is still written", gv(d)["preset"] == "enhanced")
    check("no options.cfg yet: the message says what to do", "start the game once" in msg, msg)
    check("no options.cfg yet: none created", not (d / "Config").exists())
    check("the Config one level up is left alone", (stray / "options.cfg").read_bytes() == GAME_OPTIONS.encode())
    g = me.graphics(d)
    check("graphics reports no game filtering", g["options"] is None and g["filtering"] is None, str(g))

    cfg = d / "Config" / "options.cfg"
    cfg.parent.mkdir()
    cfg.write_bytes(GAME_OPTIONS.encode())
    g = me.graphics(d)
    check("graphics reads the game's filtering off", (g["filtering"], g["mipmap"]) == (False, False), str(g))
    check("graphics names the file", g["options"] == str(cfg))
    me.set_graphics(d, "original")
    check("Original leaves options.cfg alone", cfg.read_bytes() == GAME_OPTIONS.encode())
    for name in ("enhanced", "high"):
        cfg.write_bytes(GAME_OPTIONS.encode())
        msg = me.set_graphics(d, name)
        want = GAME_OPTIONS.replace("filtering no", "filtering yes").replace("mipmap no", "mipmap yes").encode()
        check(f"{name}: filtering and mipmap yes, every other byte the same (CRLF kept)",
              cfg.read_bytes() == want, repr(cfg.read_bytes()[:60]))
        check(f"{name}: the message says so", "texture filtering and mipmaps" in msg, msg)
        g = me.graphics(d)
        check(f"{name}: graphics reports them on", g["filtering"] and g["mipmap"], str(g))
    check("again: already on, file untouched", "already on" in me.set_graphics(d, "high"))
    me.set_graphics(d, "original")
    check("Original after High doesn't switch them off", me.graphics(d)["filtering"] is True)
    lf = GAME_OPTIONS.replace("\r\n", "\n").replace("filtering no", "filtering   no").encode()
    cfg.write_bytes(lf)
    me.set_graphics(d, "enhanced")
    check("an LF file with odd spacing keeps both", cfg.read_bytes() == lf.replace(b"filtering   no", b"filtering   yes")
          .replace(b"mipmap no", b"mipmap yes"), repr(cfg.read_bytes()[:40]))
    cfg.write_bytes(GAME_OPTIONS.replace("mipmap no\r\n", "").encode())
    msg = me.set_graphics(d, "high")
    check("a missing line: nothing half-written, and said", cfg.read_bytes() == GAME_OPTIONS.replace("mipmap no\r\n", "").encode()
          and "wasn't switched on" in msg, msg)

    print("the game's options.cfg (race.bin pressings: Config beside the launcher)")
    d = root / "v11" / "Data"
    d.mkdir(parents=True)
    me.install(d)
    cfg = d.parent / "Config" / "options.cfg"
    cfg.parent.mkdir()
    cfg.write_bytes(GAME_OPTIONS.encode())
    (d / "options.def").write_bytes(GAME_OPTIONS.encode())
    me.set_graphics(d, "high")
    check("the Config one level up is the one set", b"filtering yes" in cfg.read_bytes())
    check("options.def is never written", (d / "options.def").read_bytes() == GAME_OPTIONS.encode())
    cfg.unlink()
    msg = me.set_graphics(d, "enhanced")
    check("only options.def: treated as no options.cfg yet", "start the game once" in msg
          and (d / "options.def").read_bytes() == GAME_OPTIONS.encode(), msg)


PLAYER_INI = """; my own notes about this install
[platform]
; I turned SDL off once
sdl=0
renderer=ddraw
audio=sdl

[debug]
; frame times in the log
perf=1
"""


def linux_case(root: Path) -> None:
    """Linux (forced, on any OS): the native engine's ini is created once and then left alone ([platform]
    doesn't matter to it), and the presets work, an all-upper-case CONFIG/OPTIONS.CFG included."""
    print("Linux: viperport.ini and the presets (an upper-case CD copy)")
    me.IS_LINUX = True
    try:
        if not me.bundled()["available"]:
            check("the Linux engine is bundled (vrmod/assets/modern_engine/linux)", False)
            return
        d = root / "linux" / "Data"
        (d / "CONFIG").mkdir(parents=True)
        (d / "RACE.EXE").write_bytes(v10_race_exe())
        (d / "CONFIG" / "OPTIONS.CFG").write_bytes(GAME_OPTIONS.encode())
        me.install(d)
        check("the bundled ini, as is", (d / me.INI).read_text(encoding="utf-8") == me.INI_TEXT)
        (d / me.INI).write_bytes(b"; mine\n[graphics]\nmsaa=2\n")
        me.install(d)
        check("reinstall leaves the player's ini alone (no [platform] added)",
              (d / me.INI).read_bytes() == b"; mine\n[graphics]\nmsaa=2\n")
        check("options.cfg found in CONFIG", (me.graphics(d)["options"] or "").lower() == str(d / "CONFIG" / "OPTIONS.CFG").lower(),
              str(me.graphics(d)["options"]))
        msg = me.set_graphics(d, "enhanced")
        check("Enhanced written", gv(d) == {"anisotropic": 16, "msaa": 0, "preset": "enhanced"}, msg)
        g = me.graphics(d)
        check("the game's filtering and mipmaps switched on", g["filtering"] is True and g["mipmap"] is True, msg)
        check("status carries the preset", me.status(d)["graphics"]["preset"] == "enhanced")
        me.remove(d)
        try:
            me.set_graphics(d, "high")
            check("set_graphics refused once removed", False)
        except me.ModernEngineError as e:
            check("set_graphics refused once removed", True, str(e))
    finally:
        me.IS_LINUX = False


def main() -> None:
    me.IS_LINUX = False                    # the Windows engine's ini handling; linux_case() covers Linux
    if not me.bundled()["available"]:
        print("  the modern engine isn't bundled (vrmod/assets/modern_engine) -- run scripts/update_modern_engine.py")
        sys.exit(1)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "Data"             # a race.bin-style folder: no v1.0 race.exe here
        d.mkdir()

        print("fresh install")
        me.install(d)
        ini = me.read_ini(d / me.INI)
        check("platform keys written", ini.get("platform") == me.PLATFORM, str(ini.get("platform")))
        check("the bundled text, as is", (d / me.INI).read_text(encoding="utf-8") == me.INI_TEXT)
        check("graphics reads original with no [graphics]", me.graphics(d)["preset"] == "original")
        check("status carries the preset", me.status(d)["graphics"]["preset"] == "original")

        print("install over the player's own ini")
        (d / me.INI).write_bytes(PLAYER_INI.encode())
        msg = me.install(d)
        after = (d / me.INI).read_bytes().decode()
        ini = me.read_ini(d / me.INI)
        check("platform switched back on", ini["platform"] == me.PLATFORM, str(ini["platform"]))
        check("[debug] perf=1 kept", ini.get("debug") == {"perf": "1"})
        check("comments kept", all(c in after for c in ("; my own notes about this install", "; I turned SDL off once",
                                                          "; frame times in the log")))
        gone, added = lines_changed(PLAYER_INI, after)
        check("only the two wrong platform lines changed", sorted(gone) == ["renderer=ddraw", "sdl=0"]
              and sorted(added) == ["renderer=gl", "sdl=1"], f"{gone} -> {added}")
        check("the install message says so", "platform settings" in msg, msg)
        check("an ini already right is left byte for byte", not me.set_ini_keys(d / me.INI, "platform", me.PLATFORM))

        print("a missing platform key is added inside [platform]")
        (d / me.INI).write_bytes(b"[platform]\nsdl=1\n\n[debug]\nperf=1\n")
        me.install(d)
        text = (d / me.INI).read_text()
        check("added before [debug]", text == "[platform]\nsdl=1\nrenderer=gl\naudio=sdl\n\n[debug]\nperf=1\n", repr(text))

        print("graphics presets")
        (d / me.INI).write_bytes(PLAYER_INI.encode())
        me.install(d)
        base = (d / me.INI).read_text()
        for name, vals in me.PRESETS.items():
            msg = me.set_graphics(d, name)
            g = gv(d)
            check(f"{name} round-trips", g == dict(vals, preset=name), f"{g} / {msg}")
            ini = me.read_ini(d / me.INI)
            check(f"{name}: [graphics] holds exactly the two keys",
                  ini.get("graphics") == {k: str(v) for k, v in vals.items()}, str(ini.get("graphics")))
            now = (d / me.INI).read_text()
            check(f"{name}: everything else unchanged", now.startswith(base), repr(now[:len(base)]))
        text = (d / me.INI).read_text()
        check("the section's comments are written once", text.count(me.GRAPHICS_COMMENTS["msaa"]) == 1
              and text.count("[graphics]") == 1)
        check("status carries it", me.status(d)["graphics"]["preset"] == "high")
        check("the anti-aliasing note when msaa changes", "next time" in me.set_graphics(d, "enhanced"))
        check("no note when it doesn't", "next time" not in me.set_graphics(d, "enhanced"))

        print("custom")
        me.set_ini_keys(d / me.INI, "graphics", {"anisotropic": 8, "msaa": 0})
        g = gv(d)
        check("other values read as custom", g == {"anisotropic": 8, "msaa": 0, "preset": "custom"}, str(g))
        me.set_ini_keys(d / me.INI, "graphics", {"anisotropic": "lots"})
        check("a non-number is custom too", me.graphics(d)["preset"] == "custom")
        (d / me.INI).write_bytes(b"[graphics]\nanisotropic=4\n")
        check("a missing key is 0 (4, 0 is custom)", gv(d) == {"anisotropic": 4, "msaa": 0, "preset": "custom"})
        (d / me.INI).write_bytes(b"[graphics]\nanisotropic=16\n")
        check("16x anisotropic alone reads as Enhanced", gv(d) == {"anisotropic": 16, "msaa": 0, "preset": "enhanced"})
        (d / me.INI).write_bytes(b"[graphics]\nanisotropic=0\nmsaa=0\n")
        check("zeros read as original", me.graphics(d)["preset"] == "original")

        (d / me.INI).write_bytes(b"[graphics]\nanisotropic=16\nmsaa=2\n\n[graphics]\nanisotropic=8\n")
        me.set_graphics(d, "high")
        check("a [graphics] written twice: both copies set", me.graphics(d)["preset"] == "high"
              and (d / me.INI).read_bytes() == b"[graphics]\nanisotropic=16\nmsaa=4\n\n[graphics]\nanisotropic=16\n"
              + me.GRAPHICS_COMMENTS["msaa"].encode() + b"\nmsaa=4\n", repr((d / me.INI).read_bytes()))

        print("refusals")
        try:
            me.set_graphics(d, "ultra")
            check("an unknown preset is refused", False)
        except me.ModernEngineError as e:
            check("an unknown preset is refused", True, str(e))
        before = (d / me.INI).read_bytes()
        check("and the ini is untouched", (d / me.INI).read_bytes() == before)

        print("CRLF")
        crlf = PLAYER_INI.replace("\n", "\r\n").encode()
        (d / me.INI).write_bytes(crlf)
        me.install(d)
        me.set_graphics(d, "high")
        raw = (d / me.INI).read_bytes()
        check("stays CRLF throughout", raw.count(b"\n") == raw.count(b"\r\n") and b"\r\n" in raw)
        check("ends with CRLF", raw.endswith(b"msaa=4\r\n"), repr(raw[-20:]))
        check("[debug] still there", me.read_ini(d / me.INI)["debug"] == {"perf": "1"})
        lf = PLAYER_INI.encode()
        (d / me.INI).write_bytes(lf)
        me.set_graphics(d, "enhanced")
        check("an LF file stays LF", b"\r" not in (d / me.INI).read_bytes())

        options_case(Path(tmp) / "opts")
        linux_case(Path(tmp) / "lin")

        print("remove, then the engine is gone")
        me.remove(d)
        check("remove still takes the ini out", not (d / me.INI).exists())
        try:
            me.set_graphics(d, "enhanced")
            check("set_graphics refused without the engine", False)
        except me.ModernEngineError as e:
            check("set_graphics refused without the engine", True, str(e))
        check("no ini written by the refusal", not (d / me.INI).exists())

    if FAILS:
        for f in FAILS:
            print(f"  FAILED: {f}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
