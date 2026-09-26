"""Check installing and removing the modern engine, and what the doctor says about it.

Everything runs in temp folders: the modern engine is files beside the game, so a folder with a stand-in
race.exe is enough to exercise install, reinstall, remove, a foreign dinput.dll being set aside and put
back, an outdated build, and the doctor switching its startup-fix and audio advice off once the engine
covers them.

Run:  python scripts/check_modern_engine.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import doctor, modern_engine as me  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(name)
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))


def titles(d: Path) -> list[str]:
    return [f.title for f in doctor.check(d).findings]


def main() -> None:
    if not me.bundled()["available"]:
        print("  the modern engine isn't bundled (vrmod/assets/modern_engine) -- run scripts/update_modern_engine.py")
        sys.exit(1)
    print(f"bundled: viper-racing-port {me.bundled()['commit']}")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "race.exe").write_bytes(b"MZ" + b"\0" * 64)          # a stand-in: v1.0's layout

        print("absent")
        check("status is absent", me.status(d)["state"] == me.ABSENT)
        check("nothing active", not any(me.active(d).values()))
        check("the doctor offers it", any("Modern engine not installed" in t for t in titles(d)))
        check("the doctor still warns about the crackle", any("crackle" in t for t in titles(d)))

        print("install")
        msg = me.install(d)
        check("installed", me.status(d)["state"] == me.INSTALLED, msg)
        for f in (me.DLL, me.SDL, me.INI):
            check(f"{f} in place", (d / f).is_file())
        check("everything on", all(me.active(d).values()), str(me.active(d)))
        t = titles(d)
        check("the doctor reports it", "Modern engine installed" in t)
        check("no crackle warning with SDL audio", not any("crackle" in x for x in t))
        check("audio covered", "Audio: played by the modern engine" in t)
        check("startup covered", any("through the modern engine" in x for x in t))
        check("reinstall is idempotent", me.install(d) and me.status(d)["state"] == me.INSTALLED)

        print("outdated")
        (d / me.DLL).write_bytes(b"MZ older viperport build")
        check("an older build of ours is outdated", me.status(d)["state"] == me.OUTDATED)
        check("the doctor offers the update", any("newer build" in x for x in titles(d)))
        me.install(d)
        check("install updates it", me.status(d)["state"] == me.INSTALLED)

        print("remove")
        msg = me.remove(d)
        check("absent again", me.status(d)["state"] == me.ABSENT, msg)
        check("all three files gone", not any((d / f).exists() for f in (me.DLL, me.SDL, me.INI)))
        check("remove twice is harmless", "nothing to remove" in me.remove(d))

        print("someone else's dinput.dll")
        foreign = b"MZ another mod's dinput"
        (d / me.DLL).write_bytes(foreign)
        check("status is foreign", me.status(d)["state"] == me.FOREIGN)
        me.install(d)
        check("set aside on install", (d / me.FOREIGN_BACKUP).read_bytes() == foreign)
        check("ours in place", me.status(d)["state"] == me.INSTALLED)
        me.remove(d)
        check("put back on remove", (d / me.DLL).read_bytes() == foreign and not (d / me.FOREIGN_BACKUP).exists())

        print("an SDL2.dll that isn't ours")
        (d / me.DLL).unlink()
        me.install(d)
        (d / me.SDL).write_bytes(b"MZ someone's own SDL")
        me.remove(d)
        check("left alone on remove", (d / me.SDL).read_bytes() == b"MZ someone's own SDL")

    if FAILS:
        for f in FAILS:
            print(f"  FAILED: {f}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
