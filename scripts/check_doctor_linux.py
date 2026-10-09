"""Checks the doctor's platform gating: run it as if on Linux and as if on Windows.

On Linux the game runs only through the native engine (viperport; v1.0's race.exe only), so the
doctor must not report Windows-only findings there -- the startup fix, the patch set and the DPI
flag, dgVoodoo, DirectSound wrappers, the C:\\ log paths -- and must report the Linux ones: a
race.bin-only install has no Linux route, the engine's state, and the 32-bit runtime it needs.

Builds synthetic installs in a temp folder (upper-case file names, as copied off a CD), sets
doctor.PLATFORM, and stubs doctor.linux_runtime so both runtime outcomes are checked on any
machine. Needs no game files. On a real Linux it also prints what linux_runtime() finds.

    python scripts/check_doctor_linux.py
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, doctor, modern_engine  # noqa: E402
from vrmod.switcher_ui import is_data_folder  # noqa: E402

PASS = FAIL = 0

# Titles (substrings) that only make sense on Windows.
WINDOWS_ONLY = ("startup fix", "modern GPU", "race.bin is missing", "Unrecognised", "Patch set",
                "Modern-display enhancements", "Engine bug fixes", "DPI", "dgVoodoo", "Audio",
                "DirectSound", "root of C:", "stored outside this install", "Modern engine",
                "standalone engine", "Standalone engine", "dinput.dll")


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


_ONCE: set[str] = set()


def check_once(name: str, ok: bool) -> None:
    if name not in _ONCE or not ok:
        _ONCE.add(name)
        check(name, ok)


def fake_pe(timestamp: int) -> bytes:
    """Just enough of a 32-bit PE for the v1.0 test: MZ, e_lfanew, PE signature, timestamp."""
    head = bytearray(0x400)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", head, 0x84, 0x14C, 3, timestamp)
    return bytes(head)


def v10_install(root: Path) -> Path:
    """A v1.0-shaped Data folder in CD capitals, with Windows-only wrapper DLLs lying in it."""
    d = root / "DATA"
    (d / "CONFIG").mkdir(parents=True)
    (d / "RACE.EXE").write_bytes(fake_pe(modern_engine.V10_TIMESTAMP))
    (d / "DRIVERS.RES").write_bytes(archive.to_bytes([]))
    (d / "VIPER.CAR").write_bytes(b"car")
    (d / "DSOUND.DLL").write_bytes(b"MZ")
    (d / "DDRAW.DLL").write_bytes(b"MZ")
    (d / "CONFIG" / "OPTIONS.CFG").write_text("video_mode 2\n", encoding="ascii")
    return d


def racebin_install(root: Path) -> Path:
    d = root / "RB"
    d.mkdir(parents=True)
    (d / "RACE.BIN").write_bytes(fake_pe(0x12345678))
    (d / "DRIVERS.RES").write_bytes(archive.to_bytes([]))
    (d / "VIPER.CAR").write_bytes(b"car")
    return d


def run(data: Path, platform: str, runtime: dict | None = None):
    # modern_engine.IS_LINUX (where the engine module has it) makes status() answer for Linux;
    # doctor.PLATFORM left at None follows it, so flipping the engine's flag is enough.
    saved = doctor.PLATFORM, doctor.linux_runtime, getattr(modern_engine, "IS_LINUX", None)
    if hasattr(modern_engine, "IS_LINUX"):
        modern_engine.IS_LINUX = platform.startswith("linux")
    else:
        doctor.PLATFORM = platform
    if runtime is not None:
        doctor.linux_runtime = lambda: runtime
    try:
        check_once(f"doctor.on_linux() follows the platform ({platform})",
                   doctor.on_linux() == platform.startswith("linux"))
        return doctor.check(data).findings
    finally:
        doctor.PLATFORM, doctor.linux_runtime = saved[0], saved[1]
        if saved[2] is not None:
            modern_engine.IS_LINUX = saved[2]


def main() -> int:
    have = {"loader": "/lib/ld-linux.so.2", "libgl": "/usr/lib/i386-linux-gnu/libGL.so.1"}
    none = {"loader": None, "libgl": None}
    print("install doctor -- as if on Linux")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        d = v10_install(tmp)
        check("the upper-case v1.0 folder reads as a Data folder", is_data_folder(d))
        check("RACE.EXE reads as v1.0 (doctor.race_exe_is_v10)", doctor.race_exe_is_v10(d))

        found = run(d, "linux", have)
        ts = [f.title for f in found]
        leaked = [t for t in ts if any(w in t for w in WINDOWS_ONLY)]
        check("no Windows-only findings on Linux", not leaked, "; ".join(leaked) or "none")
        check("no DPI fix offered on Linux", all(f.action != "dpi" for f in found))
        check("no patch-set or startup-fix button on Linux",
              all(f.action not in ("patch", "vram", "wp_logs", "wp_userdir") for f in found))
        check("no 'No Linux route' for a v1.0 race.exe",
              not any("No Linux route" in t for t in ts))
        eng = [f for f in found if f.title.startswith("Linux engine")]
        check("the Linux engine's state is reported", len(eng) == 1, eng[0].title if eng else "none")
        st = modern_engine.status(d)["state"]
        if st == modern_engine.ABSENT and modern_engine.bundled()["available"]:
            check("...not installed: WARN with the install button",
                  eng and eng[0].level == doctor.WARN and eng[0].action == "modern_engine")
        rt = [f for f in found if "32-bit runtime" in f.title]
        check("runtime present: OK", len(rt) == 1 and rt[0].level == doctor.OK,
              rt[0].title if rt else "none")
        check("the drivers.res check still runs (platform-neutral, upper-case DRIVERS.RES)",
              any("drivers.res is empty" in t for t in ts))
        check("the options file is found (CONFIG/OPTIONS.CFG)",
              not any("No options file yet" in t for t in ts))
        check("the car count sees VIPER.CAR", any(t == "1 cars in the game" for t in ts))

        found = run(d, "linux", none)
        rt = [f for f in found if "32-bit runtime" in f.title]
        check("runtime missing: BAD with the apt line",
              len(rt) == 1 and rt[0].level == doctor.BAD and "dpkg --add-architecture i386" in (rt[0].fix or ""),
              rt[0].title if rt else "none")
        check("...naming both missing parts",
              bool(rt) and "ld-linux.so.2" in rt[0].detail and "libGL.so.1" in rt[0].detail)

        rb = racebin_install(tmp)
        found = run(rb, "linux", have)
        route = [f for f in found if "No Linux route" in f.title]
        check("a race.bin-only install: BAD 'No Linux route'",
              len(route) == 1 and route[0].level == doctor.BAD, route[0].title if route else "none")
        check("...which says the engine runs v1.0's race.exe only",
              bool(route) and "race.exe only" in route[0].detail)
        check("...and no engine-install offer for it", not any(f.title.startswith("Linux engine")
                                                              for f in found))

        print("\ninstall doctor -- the same folder as if on Windows (must be unchanged)")
        found = run(d, "win32")
        ts = [f.title for f in found]
        check("no Linux findings on Windows",
              not any("Linux" in t or "32-bit runtime" in t for t in ts))
        check("dgVoodoo is reported on Windows", any("dgVoodoo" in t for t in ts))
        check("audio is reported on Windows", any(t.startswith("Audio") for t in ts))
        check("the modern-engine finding is the Windows one on Windows",
              not modern_engine.bundled()["available"] or any("Modern engine" in t for t in ts))
        found = run(rb, "win32")
        check("a race.bin install raises no route complaint on Windows",
              not any("No Linux route" in f.title for f in found))

    if sys.platform.startswith("linux"):
        print(f"\nthis machine: linux_runtime() = {doctor.linux_runtime()}")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
