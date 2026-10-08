"""Check viperport.ini handling: install keeps the player's settings, and the Graphics preset.

Everything runs in temp folders. install() must create viperport.ini only when there is none, and
otherwise switch on just the three [platform] keys -- a [debug] section, comments and the file's line
endings stay as they were. set_graphics() writes exactly [graphics] anisotropic= and msaa=, and
graphics() reads them back (original / enhanced / high, or custom for anything else).

Run:  python scripts/check_graphics.py
"""

from __future__ import annotations

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


def main() -> None:
    if not me.bundled()["available"]:
        print("  the modern engine isn't bundled (vrmod/assets/modern_engine) -- run scripts/update_modern_engine.py")
        sys.exit(1)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)

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
            g = me.graphics(d)
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
        g = me.graphics(d)
        check("other values read as custom", g == {"anisotropic": 8, "msaa": 0, "preset": "custom"}, str(g))
        me.set_ini_keys(d / me.INI, "graphics", {"anisotropic": "lots"})
        check("a non-number is custom too", me.graphics(d)["preset"] == "custom")
        (d / me.INI).write_bytes(b"[graphics]\nanisotropic=16\n")
        check("a missing key is 0 (16, 0 is custom)", me.graphics(d) == {"anisotropic": 16, "msaa": 0, "preset": "custom"})
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
