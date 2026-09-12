"""Checks for moving the Vehicle list on the Hacks options screen.

WHAT IS BEING PATCHED. `Added@HackOptionsControl` builds the screen as a table of
`UIDialogItem` descriptors; the Vehicle list's geometry is four literal
immediates at one call site. `?0UIDialogItem` is a plain 14-dword field copy, and
`_UIAddItems` places the list's bottom scroll button at `y + [+0x14] - 0x12`, so
+0x0c is the top edge and +0x14 the height.

THE VALUES ARE NOT INVENTED. Every build we hold was diffed, and the change first
appears in the v1.2.4 BETA from the VRgt Demo (installer dated 2005-01-06):

    v1.0 retail race.bin   300 200 100 200
    v1.0 RC   race.exe     300 200 100 200
    1.2.4 beta (2005)      390 124 111 255
    1.2.5 (2016)           390 124 111 255
    1.2.6 (2017)           390 124 111 255

The suite asserts that against the real binaries, so the module's STOCK and
COMMUNITY constants cannot drift from what the builds actually contain.

THE WIDTH IS THE ONE CONSTRAINT. It is `push imm8`, two bytes; x, y and h are
`push imm32`, five. Widening past 127 would need a longer instruction and
relocate everything after it, so it is refused rather than silently truncated.

Run:  python scripts/check_carlist.py [Data-folder]
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import carlist, patchset  # noqa: E402

DEFAULT_DATA = (Path.home() / "Desktop" / "claude-code" / "game-files"
                / "installs" / "v1.0-RC")
BUILDS = (Path.home() / "Desktop" / "claude-code" / "reference-files"
          / "executables" / "engine-builds")

# What each build must actually contain, read off the binaries themselves.
EXPECTED = {
    "race.bin-v1.0-RETAIL-redump61183.bin": (carlist.STOCK_GEOMETRY, "retail v1.0"),
    "race.bin-v124beta-from-VRgtDemo-2005.bin": (carlist.COMMUNITY_GEOMETRY,
                                                 "v1.2.4 BETA, VRgt Demo 2005"),
    "race.bin-v1.2.5-2016-community.bin": (carlist.COMMUNITY_GEOMETRY, "1.2.5 2016"),
    "race.bin-v1.2.6-2017-community.bin": (carlist.COMMUNITY_GEOMETRY, "1.2.6 2017"),
}

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def as_install(tmp: Path, name: str, src: Path, engine: str) -> Path:
    d = tmp / name
    d.mkdir()
    shutil.copy2(src, d / engine)
    return d


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    exe = src / "race.exe"
    if not exe.is_file():
        print(f"  no race.exe in {src}")
        return 1
    print(f"source: {src}\n")

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        # --- the constants match the real builds ----------------------------
        print("the shipped geometry, read off each build\n")
        for fname, (want, label) in EXPECTED.items():
            f = BUILDS / fname
            if not f.is_file():
                check(f"{label}: build present", False, "missing")
                continue
            d = as_install(tmp, fname.replace(".", "_"), f, "race.bin")
            got = carlist.read(d)
            check(f"{label} is {want.x},{want.y},{want.w},{want.h}",
                  got == want, str(got))

        # The source is a live install and this is a fix someone applies and
        # keeps, so its race.exe may already carry it. Prefer the pristine
        # snapshot; failing that, normalise the COPY. (Getting this wrong is
        # what made this suite fail the moment the fix was applied to the bed.)
        snap = src / "race.exe.vrmod-original"
        d = as_install(tmp, "rc", snap if snap.is_file() else exe, "race.exe")
        if not snap.is_file() and carlist.status(d) != carlist.STOCK:
            carlist.revert(d)
        check("an untouched v1.0 race.exe has the retail geometry",
              carlist.read(d) == carlist.STOCK_GEOMETRY,
              f"{carlist.read(d)} from "
              f"{'the snapshot' if snap.is_file() else 'a normalised copy'}")
        check("  ...which is the point: no community build ever patched race.exe",
              carlist.status(d) == carlist.STOCK)

        print("\napply / revert\n")
        original = (d / "race.exe").read_bytes()

        check("a stock build reports STOCK", carlist.status(d) == carlist.STOCK)
        g = carlist.apply(d)
        check("apply() defaults to the community geometry",
              g == carlist.COMMUNITY_GEOMETRY, str(g))
        now = (d / "race.exe").read_bytes()
        check("the file keeps its size", len(now) == len(original))
        check("exactly four bytes changed",
              sum(1 for a, b in zip(original, now) if a != b) == 4,
              str(sum(1 for a, b in zip(original, now) if a != b)))
        check("status is now COMMUNITY", carlist.status(d) == carlist.COMMUNITY)

        carlist.apply(d, y=90, h=320)
        check("individual fields can be set, leaving the rest",
              carlist.read(d) == carlist.Geometry(390, 90, 111, 320),
              str(carlist.read(d)))
        check("status is CUSTOM for anything else",
              carlist.status(d) == carlist.CUSTOM)

        carlist.revert(d)
        check("revert restores the retail geometry",
              carlist.read(d) == carlist.STOCK_GEOMETRY)
        check("  and the binary is byte-for-byte the original",
              (d / "race.exe").read_bytes() == original)

        print("\nwhat it refuses\n")
        for kwargs, why in (
                (dict(w=128), "a width of 128 -- one past the imm8 it is encoded in"),
                (dict(w=0), "a zero width"),
                (dict(h=4), "a height with no room for an entry"),
                (dict(x=-1), "a negative coordinate"),
                (dict(y=70000), "a coordinate past 65535")):
            try:
                carlist.apply(d, **kwargs)
                check(f"refuses {why}", False, "accepted it")
            except carlist.CarListError:
                check(f"refuses {why}", True)
        check("  and a refusal leaves the file untouched",
              (d / "race.exe").read_bytes() == original)
        check("127 is accepted -- the boundary is off by one in the right direction",
              carlist.apply(d, w=127).w == 127)
        carlist.revert(d)

        # --- a build without the descriptor ---------------------------------
        bare = tmp / "bare"
        bare.mkdir()
        (bare / "race.bin").write_bytes(b"MZ" + b"\x00" * 4096)
        check("a build with no such descriptor reports ABSENT",
              carlist.status(bare) == carlist.ABSENT)
        check("  ...and available() says so rather than raising",
              carlist.available(bare) is False)
        try:
            carlist.apply(bare)
            check("  ...and apply() refuses it", False)
        except carlist.CarListError:
            check("  ...and apply() refuses it", True)

        # --- the patch set must carry it ------------------------------------
        # A rebuild restores the pristine snapshot, which would silently undo
        # this exactly as it used to undo the write paths and the horn ball.
        print("\nsurviving a patch-set rebuild\n")
        snap = src / "race.exe.vrmod-original"
        if snap.is_file():
            d2 = tmp / "rebuild"
            d2.mkdir()
            shutil.copy2(snap, d2 / "race.exe")
            shutil.copy2(snap, d2 / "race.exe.vrmod-original")
            patchset.apply(d2, mode=(1920, 1080))
            carlist.apply(d2, y=90, h=320)
            want = carlist.read(d2)
            rep = patchset.apply(d2, mode=(1920, 1080))
            check("the geometry survives a rebuild", carlist.read(d2) == want,
                  str(carlist.read(d2)))
            check("  and the rebuild says it carried it",
                  any("car list" in x for n, x in rep.steps if n == "carried"))
            rep = patchset.apply(d2, mode=(1920, 1080), carry_over=False)
            check("carry_over=False returns it to stock",
                  carlist.read(d2) == carlist.STOCK_GEOMETRY)
            check("  and names it among what it dropped",
                  any("car list" in n for n in rep.notes))
        else:
            print(f"  (no {snap.name} -- skipping the rebuild checks)")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
