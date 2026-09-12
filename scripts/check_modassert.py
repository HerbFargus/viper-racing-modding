"""Check the module-assertion patch, and the claim that justifies it.

The patch disables a development-only assertion, and the argument for doing that
is that the SHIPPED game does not make the check at all. That is not a matter of
taste, it is checkable: the panic string should be present in the v1.0 RC's
race.exe and absent from every build MGI or the community released. The suite
asserts it, so the justification cannot quietly rot.

Run:  python scripts/check_modassert.py [Data-folder]
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import mapfile, modassert, pe  # noqa: E402

DEFAULT_DATA = (Path.home() / "Desktop" / "claude-code" / "game-files"
                / "installs" / "v1.0-RC")
PANIC = b'"%s" called module %s owned by "%s"'

# Builds that shipped. None should carry the assertion.
RELEASED = [
    Path.home() / "Desktop" / "claude-code" / "reference-files" / "executables"
    / "engine-builds" / n
    for n in ("race.bin-v1.2.5-2016-community.bin", "race.bin-v1.2.6-2017-community.bin")
]

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    exe = src / "race.exe"
    if not exe.is_file():
        print(f"  no race.exe in {src} -- this patch only applies to the v1.0 RC")
        sys.exit(1)
    print(f"source: {src}\n")

    # --- the justification ---------------------------------------------
    check("the RC carries the assertion", PANIC in exe.read_bytes())
    rb = src / "race.bin"
    if rb.is_file():
        check("v1.0's own race.bin -- the release build -- does NOT",
              PANIC not in rb.read_bytes())
    for p in RELEASED:
        if p.is_file():
            check(f"{p.name[:34]} does NOT", PANIC not in p.read_bytes())
        else:
            print(f"  --    {p.name} not present, skipped")

    tmp = Path(tempfile.mkdtemp(prefix="check_modassert_"))
    try:
        shutil.copy2(exe, tmp / "race.exe")
        f = tmp / "race.exe"
        # The source is a real install and may already be patched -- this is a
        # fix someone applies and keeps. Normalise the COPY so the assertions
        # below have a known baseline.
        if modassert.status(tmp) == modassert.PATCHED:
            modassert.revert(tmp)
        original = f.read_bytes()

        # --- what the patch targets ------------------------------------
        off = modassert._site(original)
        va = pe.offset_to_va(original, off)
        hit = mapfile.lookup(f, va)
        check("the site resolves to unsafe_check in the RC's own symbol map",
              bool(hit) and mapfile.pretty(hit[0]) == "unsafe_check" and hit[1] == 0,
              f"{mapfile.pretty(hit[0])}+0x{hit[1]:x} @ {va:#x}" if hit else "unresolved")
        check("a stock RC reports unpatched", modassert.status(tmp) == modassert.UNPATCHED)

        at = modassert.apply(tmp)
        now = f.read_bytes()
        check("apply() reports the same offset the site lookup gave", at == off,
              f"{at:#x}")
        check("exactly one byte changed",
              sum(1 for a, b in zip(original, now) if a != b) == 1)
        check("and that byte is a RET", now[at:at + 1] == modassert.RET,
              now[at:at + 1].hex())
        check("the file keeps its size", len(now) == len(original))
        check("status is now patched", modassert.status(tmp) == modassert.PATCHED)
        check("the embedded symbol map still parses",
              len(mapfile.symbols(f)[0]) > 10000,
              f"{len(mapfile.symbols(f)[0]):,} symbols")

        try:
            modassert.apply(tmp)
            check("a second apply is refused", False)
        except modassert.ModAssertError:
            check("a second apply is refused", True)

        modassert.revert(tmp)
        check("revert restores the binary byte-for-byte", f.read_bytes() == original)
        check("status returns to unpatched", modassert.status(tmp) == modassert.UNPATCHED)

        # a build without the subsystem must report absent, not fail
        bare = tmp / "bare"
        bare.mkdir()
        if rb.is_file():
            shutil.copy2(rb, bare / "race.bin")
            check("a release build reports ABSENT rather than erroring",
                  modassert.status(bare) == modassert.ABSENT,
                  modassert.status(bare))
            try:
                modassert.apply(bare)
                check("...and refuses to patch one", False)
            except modassert.ModAssertError:
                check("...and refuses to patch one", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        for f in failures:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
