"""Check installing and removing the modern engine, and what the doctor says about it.

Everything runs in temp folders: the modern engine is files beside the game, so a folder with a stand-in
v1.0 race.exe (just its PE header) is enough to exercise install, reinstall, remove, the bundled
viperport.exe going in beside it and out again, a foreign dinput.dll being set aside and put back, an
outdated build, and the doctor switching its startup-fix and audio advice off once the engine covers
them. Nothing is launched: `viperport.exe --probe` is answered by a stand-in. Play's route choice has
its own checks, in check_play.py. The Linux engine (viperport, viperport.sh, SDL2 beside a v1.0
race.exe) is checked too, on any OS, by forcing modern_engine.IS_LINUX.

Run:  python scripts/check_modern_engine.py
"""

from __future__ import annotations

import os
import struct
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


def v10_race_exe() -> bytes:
    """A stand-in v1.0 race.exe: just the PE header, with v1.0's timestamp."""
    b = bytearray(0x200)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", b, 0x84, 0x14C, 1, me.V10_TIMESTAMP)
    return bytes(b)


def linux_checks() -> None:
    """The Linux engine, forced on any OS (me.IS_LINUX): the bundled native standalone installed beside a
    v1.0 race.exe (upper-case, as off a CD), status / outdated / foreign, remove, and the refusals."""
    me.IS_LINUX = True
    try:
        print("Linux (forced): the bundle")
        b = me.bundled()
        check("the Linux engine is bundled (vrmod/assets/modern_engine/linux)", b["available"] and b["standalone"])
        check("SOURCE.txt names its commit", bool(b["commit"]), str(b["commit"]))
        check("the bundled ELF is an ELF with the mark", (me.LINUX_ASSETS / me.ELF).read_bytes()[:4] == b"\x7fELF"
              and me.is_ours(me.LINUX_ASSETS / me.ELF, me.LINUX_ASSETS / me.ELF))
        check("the bundled viperport.sh has LF line endings", b"\r\n" not in (me.LINUX_ASSETS / me.SH).read_bytes())
        files = me.linux_files()
        check("licences listed", any(f.startswith("LICENSES/") for f in files), str(files))
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "Data"
            d.mkdir()
            (d / "RACE.EXE").write_bytes(v10_race_exe())

            print("Linux: absent")
            st = me.status(d)
            check("absent, platform linux", st["state"] == me.ABSENT and st["platform"] == "linux", str(st))
            check("standalone absent on v1.0", st["standalone"] == me.ABSENT)
            check("nothing active", not any(me.active(d).values()))

            print("Linux: install")
            msg = me.install(d)
            st = me.status(d)
            check("installed", st["state"] == me.INSTALLED and st["standalone"] == me.INSTALLED, msg)
            for f in files + [me.INI]:
                check(f"{f} in place", (d / f).is_file())
            check("no Windows files", not any((d / f).exists() for f in (me.DLL, me.SDL, me.EXE)))
            if os.name == "posix":
                for f in (me.ELF, me.SH):
                    check(f"{f} executable", os.access(d / f, os.X_OK))
            check("the ini is the bundled text", (d / me.INI).read_text(encoding="utf-8") == me.INI_TEXT)
            check("everything on", all(me.active(d).values()), str(me.active(d)))
            check("message names the Linux files", me.SH in msg and "Linux" in msg, msg)
            check("reinstall is idempotent", me.install(d) and me.status(d)["state"] == me.INSTALLED)

            print("Linux: outdated")
            (d / me.SH).write_bytes(b"#!/bin/sh\n# an older viperport.sh\n")
            check("an older launcher is outdated", me.status(d)["state"] == me.OUTDATED)
            me.install(d)
            check("install updates it", me.status(d)["state"] == me.INSTALLED)
            (d / me.ELF).write_bytes(b"\x7fELF older viperport build")
            check("an older ELF of ours is outdated", me.status(d)["state"] == me.OUTDATED)
            me.install(d)
            check("install updates the ELF", me.status(d)["state"] == me.INSTALLED)

            print("Linux: remove")
            (d / "viperport.log").write_text("log")
            (d / "viperport-probe.txt").write_text("yes: v1.0 race.exe")
            msg = me.remove(d)
            check("absent again", me.status(d)["state"] == me.ABSENT, msg)
            check("every engine file gone", not any((d / f).exists() for f in files + [me.INI]))
            check("lib/ and LICENSES/ gone once empty", not (d / "lib").exists() and not (d / "LICENSES").exists())
            check("the probe's report gone, the log kept", not (d / "viperport-probe.txt").exists()
                  and (d / "viperport.log").exists())
            check("race.exe untouched", (d / "RACE.EXE").read_bytes() == v10_race_exe())
            check("remove twice is harmless", "nothing to remove" in me.remove(d))
            (d / "lib").mkdir()
            (d / "lib" / "libother.so").write_bytes(b"\x7fELF someone's")
            me.install(d)
            me.remove(d)
            check("a lib/ with someone else's file stays", (d / "lib" / "libother.so").is_file())

            print("Linux: someone else's viperport")
            (d / me.ELF).write_bytes(b"\x7fELF some other program")
            check("status is foreign", me.status(d)["state"] == me.FOREIGN)
            try:
                me.install(d)
                check("install refuses over it", False)
            except me.ModernEngineError as e:
                check("install refuses over it", "isn't the modern engine's" in str(e), str(e))
            me.remove(d)
            check("left alone on remove", (d / me.ELF).read_bytes() == b"\x7fELF some other program")
            (d / me.ELF).unlink()

        print("Linux: no v1.0 race.exe")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "race.bin").write_bytes(b"MZ race.bin stand-in")
            st = me.status(d)
            check("race.bin only: absent, no standalone", st["state"] == me.ABSENT and st["standalone"] is None, str(st))
            try:
                me.install(d)
                check("race.bin only: install refused", False)
            except me.ModernEngineError as e:
                check("race.bin only: install refused", me.V10_ONLY in str(e) and "race.bin" in str(e), str(e))
            check("nothing written", sorted(p.name for p in d.iterdir()) == ["race.bin"])
            b = bytearray(v10_race_exe())
            struct.pack_into("<I", b, 0x88, 0x12345678)              # another build's timestamp
            (d / "race.exe").write_bytes(bytes(b))
            try:
                me.install(d)
                check("a race.exe that isn't v1.0: install refused", False)
            except me.ModernEngineError as e:
                check("a race.exe that isn't v1.0: install refused", "isn't v1.0" in str(e), str(e))
    finally:
        me.IS_LINUX = False


def main() -> None:
    me.IS_LINUX = False                    # the Windows engine first (and the doctor); linux_checks() after
    if not me.bundled()["available"]:
        print("  the modern engine isn't bundled (vrmod/assets/modern_engine) -- run scripts/update_modern_engine.py")
        sys.exit(1)
    print(f"bundled: viper-racing-port {me.bundled()['commit']}")
    check("the bundle includes viperport.exe (else run scripts/update_modern_engine.py)", me.bundled()["standalone"])
    me._run_probe = lambda exe, race, cwd: (0, "stand-in: yes")   # never run the real viperport.exe here
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "race.exe").write_bytes(v10_race_exe())             # a stand-in: v1.0's layout

        print("absent")
        check("status is absent", me.status(d)["state"] == me.ABSENT)
        check("nothing active", not any(me.active(d).values()))
        check("the doctor offers it", any("Modern engine not installed" in t for t in titles(d)))
        check("the doctor still warns about the crackle", any("crackle" in t for t in titles(d)))

        print("install")
        msg = me.install(d)
        check("installed", me.status(d)["state"] == me.INSTALLED, msg)
        for f in (me.DLL, me.SDL, me.INI, me.EXE):
            check(f"{f} in place", (d / f).is_file())
        check("viperport.exe is the bundled one", me.status(d)["standalone"] == me.INSTALLED)
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
        check("all four files gone", not any((d / f).exists() for f in (me.DLL, me.SDL, me.INI, me.EXE)))
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

    linux_checks()

    if FAILS:
        for f in FAILS:
            print(f"  FAILED: {f}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
