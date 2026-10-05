"""Check how Play picks its route, and the standalone (viperport.exe) side of the modern engine.

Nothing is launched and no viper-racing-port binary runs: the bundle is a stand-in (a temp folder with
marked dinput.dll / viperport.exe / SDL2.dll), and modern_engine's two process calls -- _run_probe
(`viperport.exe --probe`) and _spawn (start a game executable) -- are replaced by recorders. Installs are
temp folders laid out like each pressing:

    v1.0   Data\\race.exe (a PE header with v1.0's timestamp) -- Data's contents ARE the game folder
    v1.1   Data\\race.bin, the `Viper Racing.exe` launcher one level up (or inside Data on the disc)

Covers: install puts viperport.exe beside a v1.0 race.exe only and remove takes it out; an engine from
before the standalone reads as outdated; a foreign viperport.exe is left alone; Play's route on each
layout; the probe's yes / no / can't-ask / no-answer; its cache; the launch-and-watch fallback; and the
doctor's standalone finding.

Run:  python scripts/check_play.py
"""

from __future__ import annotations

import struct
import subprocess
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


def pe_stub(timestamp: int) -> bytes:
    """Just enough of a 32-bit PE for race_exe_is_v10: MZ, e_lfanew, PE\\0\\0, machine, timestamp."""
    b = bytearray(0x200)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", b, 0x84, 0x14C, 1, timestamp)
    return bytes(b)


V10 = pe_stub(me.V10_TIMESTAMP)


class Recorder:
    """Stands in for _run_probe and _spawn."""

    def __init__(self):
        self.probes, self.spawns = [], []
        self.answer = (0, "yes: v1.0 race.exe (vrmod-patched), every function a rewrite\n")
        self.exit_code = None            # what a spawned viperport.exe does in the watch window

    def run_probe(self, exe, race, cwd):
        self.probes.append((Path(exe).name, Path(race).name, Path(cwd)))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    def spawn(self, exe, cwd):
        self.spawns.append((Path(exe).name, Path(cwd)))
        rec = self

        class Proc:
            def wait(self, timeout=None):
                if rec.exit_code is None:
                    raise subprocess.TimeoutExpired(str(exe), timeout)
                return rec.exit_code
        return Proc()


def titles(d: Path) -> list[str]:
    return [f.title for f in doctor.check(d).findings]


def main() -> None:
    rec = Recorder()
    me._run_probe, me._spawn = rec.run_probe, rec.spawn
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        assets = root / "assets"
        assets.mkdir()
        (assets / me.DLL).write_bytes(b"MZ viperport port dll, new build")
        (assets / me.SDL).write_bytes(b"MZ SDL2 stand-in")
        (assets / me.EXE).write_bytes(b"MZ viperport loader --probe --race --check")
        (assets / "SOURCE.txt").write_text("viper-racing-port commit 0123456789abcdef (2026-10-05)\n")
        me.ASSETS = assets

        print("bundle")
        check("the stand-in bundle has the standalone", me.bundled()["standalone"] and me.bundled()["available"])

        print("v1.0, no modern engine")
        d = root / "v10" / "Data"
        d.mkdir(parents=True)
        (d / "race.exe").write_bytes(V10)
        check("race.exe reads as v1.0", me.race_exe_is_v10(d))
        r = me.play_route(d)
        check("Play starts race.exe", r["route"] == me.RACE and r["label"] == "race.exe" and not r["why"], str(r))
        rec.spawns.clear()
        msg = me.play(d)["message"]
        check("race.exe spawned from the Data folder", rec.spawns == [("race.exe", d)], str(rec.spawns))
        check("message names it", msg == "Started race.exe.", msg)
        check("no probe without the engine", not rec.probes)

        print("v1.0, engine from before the standalone (no viperport.exe)")
        (d / me.DLL).write_bytes((assets / me.DLL).read_bytes())
        (d / me.SDL).write_bytes((assets / me.SDL).read_bytes())
        st = me.status(d)
        check("reads as outdated, standalone absent", st["state"] == me.OUTDATED and st["standalone"] == me.ABSENT, str(st))
        r = me.play_route(d)
        check("Play uses race.exe with the engine and says why",
              r["route"] == me.RACE and r["engine"] and "isn't installed yet" in (r["why"] or ""), str(r))
        check("the doctor offers the update, naming viperport.exe",
              any("newer build" in f.title and "viperport.exe" in f.detail for f in doctor.check(d).findings))

        print("v1.0, install")
        msg = me.install(d)
        check("viperport.exe in place", (d / me.EXE).read_bytes() == (assets / me.EXE).read_bytes(), msg)
        check("message lists it", me.EXE in msg, msg)
        st = me.status(d)
        check("installed, standalone installed", st["state"] == me.INSTALLED and st["standalone"] == me.INSTALLED, str(st))

        print("v1.0 + engine, the probe says yes")
        rec.probes.clear(); rec.spawns.clear()
        r = me.play_route(d)
        check("route is the standalone", r["route"] == me.STANDALONE and r["probe"] is True, str(r))
        check("probed with --race race.exe in the Data folder", rec.probes == [(me.EXE, "race.exe", d)], str(rec.probes))
        out = me.play(d)
        check("viperport.exe spawned, nothing else", rec.spawns == [(me.EXE, d)], str(rec.spawns))
        check("message", out["message"] == f"Started {me.STANDALONE_LABEL}.", out["message"])
        check("the answer is cached", len(rec.probes) == 1, str(rec.probes))
        check("the doctor: Play runs the standalone", "Play runs the standalone engine" in titles(d))

        print("v1.0 + engine, the probe says no")
        rec.answer = (3, "this race.exe has a patch the port doesn't know (at 0x4a1f30)\n")
        (d / "race.exe").write_bytes(V10 + b"patched")     # a change to race.exe drops the cached answer
        rec.probes.clear(); rec.spawns.clear()
        r = me.play_route(d)
        check("asked again after race.exe changed", len(rec.probes) == 1)
        check("route falls back to race.exe with the engine", r["route"] == me.RACE and r["engine"] and r["probe"] is False, str(r))
        check("why is the probe's own line", r["why"] == "this race.exe has a patch the port doesn't know (at 0x4a1f30)", str(r["why"]))
        out = me.play(d)
        check("only race.exe spawned", rec.spawns == [("race.exe", d)], str(rec.spawns))
        check("message says why", out["message"] == "Started race.exe with the modern engine. Not viperport.exe: "
              "this race.exe has a patch the port doesn't know (at 0x4a1f30).", out["message"])
        check("the doctor says Play uses race.exe",
              any(t.startswith("Play uses race.exe") for t in titles(d)))

        print("v1.0 + engine, the probe doesn't answer")
        rec.answer = subprocess.TimeoutExpired("viperport.exe", me.PROBE_TIMEOUT)
        (d / "race.exe").write_bytes(V10 + b"patched again")
        r = me.play_route(d)
        check("no answer is a no", r["route"] == me.RACE and "didn't answer" in (r["why"] or ""), str(r))

        print("v1.0 + engine, a viperport.exe from before --probe")
        rec.answer = (0, "")
        (d / me.EXE).write_bytes(b"MZ viperport loader, older (no probe option)")
        rec.probes.clear(); rec.spawns.clear()
        st = me.status(d)
        check("it is ours but outdated", st["standalone"] == me.OUTDATED and st["state"] == me.OUTDATED, str(st))
        r = me.play_route(d)
        check("route is the standalone, unprobed", r["route"] == me.STANDALONE and r["probe"] is None and not rec.probes, str(r))
        check("the doctor: not checked ahead of launch", any("not checked ahead of launch" in t for t in titles(d)))
        rec.exit_code = None                                # still running after the watch window
        out = me.play(d)
        check("still running: the standalone started", rec.spawns == [(me.EXE, d)] and out["route"] == me.STANDALONE, str(rec.spawns))
        rec.spawns.clear()
        rec.exit_code = 2                                   # refused at start-up
        out = me.play(d)
        check("a prompt non-zero exit falls back to race.exe",
              rec.spawns == [(me.EXE, d), ("race.exe", d)] and out["route"] == me.RACE, str(rec.spawns))
        check("message gives the exit code", "exit code 2" in out["message"] and out["message"].startswith(
              "Started race.exe with the modern engine. Not viperport.exe:"), out["message"])
        rec.exit_code = None

        print("v1.0, remove")
        me.install(d)
        check("install brings it up to date", me.status(d)["standalone"] == me.INSTALLED)
        msg = me.remove(d)
        check("viperport.exe gone", not (d / me.EXE).exists() and me.EXE in msg, msg)
        check("absent again", me.status(d)["state"] == me.ABSENT)

        print("v1.0, someone else's viperport.exe")
        (d / me.EXE).write_bytes(b"MZ some other program")
        msg = me.install(d)
        check("left alone on install", (d / me.EXE).read_bytes() == b"MZ some other program" and "left alone" in msg, msg)
        st = me.status(d)
        check("engine installed, standalone foreign", st["state"] == me.INSTALLED and st["standalone"] == me.FOREIGN, str(st))
        r = me.play_route(d)
        check("Play uses race.exe and says why", r["route"] == me.RACE and "isn't the modern engine's" in (r["why"] or ""), str(r))
        me.remove(d)
        check("left alone on remove", (d / me.EXE).read_bytes() == b"MZ some other program")
        (d / me.EXE).unlink()

        print("a race.exe that isn't v1.0")
        (d / "race.exe").write_bytes(pe_stub(0x12345678))
        me.install(d)
        check("no viperport.exe beside it", not (d / me.EXE).exists())
        check("standalone doesn't apply", me.status(d)["standalone"] is None)
        r = me.play_route(d)
        check("Play starts race.exe with the engine, no why", r["route"] == me.RACE and r["engine"] and not r["why"], str(r))
        me.remove(d)

        print("v1.1 installed (launcher beside Data)")
        g = root / "v11"
        d = g / "Data"
        d.mkdir(parents=True)
        (d / "race.bin").write_bytes(b"MZ race.bin stand-in")
        (g / "Viper Racing.exe").write_bytes(b"MZ launcher stand-in")
        r = me.play_route(d)
        check("Play starts the launcher from the game folder",
              r["route"] == me.LAUNCH and Path(r["exe"]).name == "Viper Racing.exe" and Path(r["cwd"]) == g, str(r))
        (d / me.EXE).write_bytes((assets / me.EXE).read_bytes())   # one of ours, put here by hand
        msg = me.install(d)
        check("install never leaves viperport.exe beside race.bin", not (d / me.EXE).exists(), msg)
        check("standalone doesn't apply", me.status(d)["standalone"] is None and me.status(d)["state"] == me.INSTALLED)
        rec.spawns.clear(); rec.probes.clear()
        out = me.play(d)
        check("launcher spawned in the game folder, no probe",
              rec.spawns == [("Viper Racing.exe", g)] and not rec.probes, str(rec.spawns))
        check("message", out["message"] == "Started Viper Racing.exe, which starts race.bin with the modern engine.",
              out["message"])
        check("no standalone finding on race.bin", not any("standalone" in t.lower() for t in titles(d)))

        print("v1.1 disc layout (launcher inside Data)")
        (g / "Viper Racing.exe").unlink()
        (d / "Viper Racing.exe").write_bytes(b"MZ launcher stand-in")
        r = me.play_route(d)
        check("the launcher inside Data", r["route"] == me.LAUNCH and Path(r["cwd"]) == d, str(r))

        print("nothing to start")
        (d / "Viper Racing.exe").unlink()
        try:
            me.play_route(d)
            check("no launcher is an error", False)
        except me.PlayError as e:
            check("no launcher is an error", "Viper Racing.exe" in str(e), str(e))

    if FAILS:
        for f in FAILS:
            print(f"  FAILED: {f}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
