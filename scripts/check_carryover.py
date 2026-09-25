"""Checks that a patch-set rebuild does not silently throw away other patches.

THE BUG. apply() restores the pristine snapshot before replaying its steps --
that is what makes it idempotent and its output a function of its arguments.
The cost went unnoticed: everything ELSE anyone applied to the engine lives in
the same binary and is reverted too. Pressing "apply this resolution" in the
desktop app put the player's logs back under C:\\, un-silenced the module
assertion, re-enabled the head-on panic and reset the horn-ball tuning -- and
said nothing at all.

Found the hard way: this repo's own test bed was rebuilt twice during unrelated
work and lost all four without a word.

THE FIX, AND WHY IT IS NOT JUST "DON'T RESTORE". Layering instead would give up
the property that makes apply() worth having. So the four are captured BEFORE
the snapshot goes back and re-applied after, each one named in the Report --
explicit carry-over rather than accidental inheritance. `carry_over=False` still
gives the bare rebuild, and then says what it dropped.

Needs a real engine with a baseline, so it takes a Data folder:

    python scripts/check_carryover.py [path/to/Data]
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import (headon, hornball, modassert, patchset,  # noqa: E402
                   writepaths)

DEFAULT = (Path.home() / "Desktop" / "claude-code" / "game-files"
           / "installs" / "v1.0-RC")

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def state(d: Path) -> dict:
    wp = writepaths.status(d).get("race.exe", {})
    t = hornball.read(d)
    return {"logs": wp.get("logs"), "userdir": wp.get("userdir"),
            "headon": headon.status(d), "modassert": modassert.status(d),
            "hornball": (round(t.speed_mult, 3), round(t.cooldown, 4), round(t.mass_mult or 1.0, 3))}


def fresh(tmp: Path, name: str, src: Path) -> Path:
    """A bare install: the engine at its pristine bytes, plus the snapshot."""
    d = tmp / name
    d.mkdir()
    shutil.copy2(src / "race.exe.vrmod-original", d / "race.exe")
    shutil.copy2(src / "race.exe.vrmod-original", d / "race.exe.vrmod-original")
    return d


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not (src / "race.exe.vrmod-original").is_file():
        print(f"  needs a v1.0 Data folder carrying a baseline snapshot: {src}")
        return 1
    print(f"source: {src}\n")

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        # --- nothing else applied: nothing to carry -------------------------
        d = fresh(tmp, "bare", src)
        rep = patchset.apply(d, mode=(1920, 1080))
        check("a bare install reports no carry-over",
              not [x for n, x in rep.steps if n == "carried"])

        # --- all four applied, then rebuilt ---------------------------------
        d = fresh(tmp, "full", src)
        patchset.apply(d, mode=(1920, 1080))
        writepaths.apply(d, writepaths.LOGS_KIND, migrate=False)
        writepaths.apply(d, writepaths.USER_DIR_KIND, migrate=False)
        modassert.apply(d)
        headon.apply(d)
        hornball.apply(d, speed_mult=6.25, cooldown=0.1, mass_mult=2.0)
        before = state(d)
        want = {"logs": "patched", "userdir": "patched", "headon": "disabled",
                "modassert": "patched", "hornball": (6.25, 0.1, 2.0)}
        check("the fixture really has all four applied", before == want, str(before))

        rep = patchset.apply(d, mode=(1600, 900))
        carried = [x for n, x in rep.steps if n == "carried"]
        check("the rebuild reports carrying each one", len(carried) == 5,
              f"{len(carried)} carried")
        after = state(d)
        for k in want:
            check(f"  {k} survives the rebuild", after[k] == want[k],
                  f"{after[k]!r}")

        # --- and the set's own step really did change --------------------
        check("the rebuild still applied its own arguments",
              patchset.resolution.read(d)[0] == (1600, 900),
              str(patchset.resolution.read(d)[0]))

        # --- determinism is not lost ---------------------------------------
        # Carry-over must not make the output depend on history: the same
        # arguments, from the same state, must still give the same bytes.
        h1 = sha(d / "race.exe")
        patchset.apply(d, mode=(1600, 900))
        check("carrying over is still idempotent", sha(d / "race.exe") == h1,
              h1[:16])

        d2 = fresh(tmp, "rebuilt", src)
        patchset.apply(d2, mode=(1600, 900))
        writepaths.apply(d2, writepaths.LOGS_KIND, migrate=False)
        writepaths.apply(d2, writepaths.USER_DIR_KIND, migrate=False)
        modassert.apply(d2)
        headon.apply(d2)
        hornball.apply(d2, speed_mult=6.25, cooldown=0.1, mass_mult=2.0)
        check("a carried rebuild equals applying the same patches by hand",
              sha(d2 / "race.exe") == h1, sha(d2 / "race.exe")[:16])

        # --- opting out still works, and says so ----------------------------
        d = fresh(tmp, "optout", src)
        patchset.apply(d, mode=(1920, 1080))
        writepaths.apply(d, writepaths.LOGS_KIND, migrate=False)
        modassert.apply(d)
        rep = patchset.apply(d, mode=(1920, 1080), carry_over=False)
        check("carry_over=False does NOT put them back",
              state(d)["logs"] != "patched"
              and state(d)["modassert"] != "patched")
        dropped = [n for n in rep.notes if "NOT back" in n]
        check("carry_over=False names what it dropped", bool(dropped))
        check("  ...including the write paths",
              bool(dropped) and "write paths" in dropped[0])
        check("  ...including the module assertion",
              bool(dropped) and "module assertion" in dropped[0])

        # --- the resolution TABLE, not just one entry -----------------------
        # Resolution is one of the set's own steps, but it only ever wrote ONE
        # index, so any other slot the player had repointed went back to stock
        # on the next rebuild. Index 1 is where that bites: its stock 512x384 is
        # not enumerated on modern hardware, so it is the free slot.
        d = fresh(tmp, "table", src)
        patchset.apply(d, mode=(1920, 1080))
        patchset.resolution.set_mode(d, 1, 2048, 1536)
        patchset.resolution.set_mode(d, 3, 1280, 720)
        before = patchset.resolution.read(d)
        rep = patchset.apply(d, mode=(1920, 1080))
        check("slots set by hand survive a rebuild that did not mention them",
              patchset.resolution.read(d) == before, str(patchset.resolution.read(d)))
        marked = [x for n, x in rep.steps if n == "resolution" and "(carried)" in x]
        check("  and each is reported as carried, not silently kept",
              len(marked) == 2, f"{len(marked)} marked")

        # an explicit request must WIN over the carried value
        rep = patchset.apply(d, mode=(1920, 1080), modes={1: (1600, 900)})
        check("an explicit mode overrides the carried one",
              patchset.resolution.read(d)[3] == (1600, 900),
              str(patchset.resolution.read(d)))

        # --- the whole table in one reproducible call -----------------------
        d = fresh(tmp, "decl", src)
        patchset.apply(d, mode=(1920, 1080),
                       modes={1: (2048, 1536), 3: (1280, 720)})
        want = [(1920, 1080), (1280, 720), (640, 480), (2048, 1536)]
        check("modes= sets the whole table in one call",
              patchset.resolution.read(d) == want,
              str(patchset.resolution.read(d)))

        d2 = fresh(tmp, "decl2", src)
        patchset.apply(d2, mode=(1920, 1080),
                       modes={3: (1280, 720), 1: (2048, 1536)})
        check("the table does not depend on the order given",
              sha(d2 / "race.exe") == sha(d / "race.exe"))

        # mode=None means "only what modes says"
        d = fresh(tmp, "noprimary", src)
        patchset.apply(d, mode=None, modes={1: (1600, 900)})
        t = patchset.resolution.read(d)
        check("mode=None leaves the primary slot stock",
              t[0] == (1024, 768) and t[3] == (1600, 900), str(t))

        # --- the boot gate is refused, and nothing is written ---------------
        d = fresh(tmp, "gate", src)
        patchset.apply(d, mode=(1920, 1080))
        before = sha(d / "race.exe")
        for bad, why in (({2: (1280, 720)}, "the startup gate"),
                         ({0: (1280, 720)}, "index 0"),
                         ({5: (1280, 720)}, "index 5"),
                         ({1: (10, 10)}, "a nonsense size")):
            try:
                patchset.apply(d, modes=bad)
                check(f"{why} is refused", False)
            except patchset.PatchSetError:
                check(f"{why} is refused", True)
        check("  a refused request leaves the binary untouched",
              sha(d / "race.exe") == before, before[:16])

        # --- opting out drops the table too, and says so --------------------
        d = fresh(tmp, "tabledrop", src)
        patchset.apply(d, mode=(1920, 1080), modes={1: (2048, 1536)})
        rep = patchset.apply(d, mode=(1920, 1080), carry_over=False)
        check("carry_over=False returns the un-named slots to stock",
              patchset.resolution.read(d)[3] == (512, 384),
              str(patchset.resolution.read(d)))
        check("  ...and says which index it dropped",
              any("menu index 1" in n for n in rep.notes))

        # --- a stock horn ball is not 'carried' as if it were a setting -----
        d = fresh(tmp, "stockhorn", src)
        patchset.apply(d, mode=(1920, 1080))
        modassert.apply(d)
        rep = patchset.apply(d, mode=(1920, 1080))
        carried = [x for n, x in rep.steps if n == "carried"]
        check("stock horn-ball tuning is not reported as carried",
              not any("horn ball" in c for c in carried), str(carried))

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
