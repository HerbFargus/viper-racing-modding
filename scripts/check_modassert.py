"""Check the module-assertion patch, and the claim that justifies it.

The patch disables a development-only assertion, and the argument for doing that
is that the SHIPPED builds do not perform this check. That has to be stated
precisely, because a loose version of it was wrong: the module-safety subsystem
is NOT absent from the releases. They keep its strings, and they keep a FATAL
panic on the safe-module path -- `_MultiEnter` pushes

    Task "%s" called module "%s" after module ended.

straight into LogPanic, in every build. This patch does not touch that.

What the releases compile away is the SINGLE-ENTRY guard. The function
MouseQueueEvent calls is the real check in the RC and a bare RET everywhere
else:

    v1.0 race.exe (RC)   _SingleEnter -> unsafe_check -> checks
    v1.0 race.bin        c3
    v1.2.5 / v1.2.6      c3

So the suite asserts both halves -- no ownership assertion in a release, but the
safe-module panic still present, and the single-entry guard a bare RET -- and
the argument cannot quietly rot into the wrong one again.

Run:  python scripts/check_modassert.py [Data-folder]
"""

from __future__ import annotations

import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import mapfile, modassert, pe  # noqa: E402

DEFAULT_DATA = (Path.home() / "Desktop" / "claude-code" / "game-files"
                / "installs" / "v1.0-RC")

PANIC = b'"%s" called module %s owned by "%s"'
MULTI = b'Task "%s" called module "%s" after module ended.'

RELEASED = [
    Path.home() / "Desktop" / "claude-code" / "reference-files" / "executables"
    / "engine-builds" / n
    for n in ("race.bin-v1.2.5-2016-community.bin", "race.bin-v1.2.6-2017-community.bin")
]

# MouseQueueEvent's prologue, the same shape in every build:
#   sub esp,0x10 / mov eax,[handle] / push esi / push 0 / push 0 / push eax / call
_MQE = re.compile(
    b"\x83\xec\x10\xa1(....)\x56\x6a\x00\x6a\x00\x50\xe8(....)", re.S)

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def single_enter(blob: bytes) -> int | None:
    """File offset of the single-entry guard MouseQueueEvent calls."""
    m = _MQE.search(blob)
    if not m:
        return None
    site = m.start() + 14
    va = pe.offset_to_va(blob, site) + 5 + struct.unpack_from("<i", blob, site + 1)[0]
    return pe.va_to_offset(blob, va)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    exe = src / "race.exe"
    if not exe.is_file():
        print(f"  no race.exe in {src} -- this patch only applies to the v1.0 RC")
        sys.exit(1)
    print(f"source: {src}\n")

    # --- the justification, both halves --------------------------------
    rc = exe.read_bytes()
    check("the RC carries the ownership assertion", PANIC in rc)
    ent = single_enter(rc)
    check("the RC's single-entry guard is real code, not a RET",
          ent is not None and rc[ent] != 0xC3,
          f"@0x{ent:x} = {rc[ent]:#04x}" if ent is not None else "not located")

    rb = src / "race.bin"
    builds = ([("v1.0 race.bin", rb)] if rb.is_file() else []) + \
             [(p.name[:28], p) for p in RELEASED if p.is_file()]
    for label, p in builds:
        b = p.read_bytes()
        check(f"{label}: has NO ownership assertion", PANIC not in b)
        check(f"{label}: DOES keep the safe-module panic, which we leave alone",
              MULTI in b)
        e = single_enter(b)
        check(f"{label}: its single-entry guard is a bare RET",
              e is not None and b[e] == 0xC3,
              f"@0x{e:x} = {b[e]:#04x}" if e is not None else "not located")

    # --- apply / revert -------------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="check_modassert_"))
    try:
        shutil.copy2(exe, tmp / "race.exe")
        f = tmp / "race.exe"
        # The source is a real install and may already be patched -- this is a
        # fix someone applies and keeps. Normalise the COPY for a known baseline.
        if modassert.status(tmp) == modassert.PATCHED:
            modassert.revert(tmp)
        original = f.read_bytes()

        off = modassert._site(original)
        va = pe.offset_to_va(original, off)
        hit = mapfile.lookup(f, va)
        check("the site resolves to unsafe_check in the RC's own symbol map",
              bool(hit) and mapfile.pretty(hit[0]) == "unsafe_check" and hit[1] == 0,
              f"{mapfile.pretty(hit[0])}+0x{hit[1]:x} @ {va:#x}" if hit else "unresolved")

        check("a stock RC reports unpatched",
              modassert.status(tmp) == modassert.UNPATCHED)
        at = modassert.apply(tmp)
        now = f.read_bytes()
        check("apply() reports the same offset the site lookup gave", at == off, f"{at:#x}")
        check("exactly one byte changed",
              sum(1 for a, b in zip(original, now) if a != b) == 1)
        check("and that byte is a RET", now[at:at + 1] == modassert.RET,
              now[at:at + 1].hex())
        check("the file keeps its size", len(now) == len(original))
        check("status is now patched", modassert.status(tmp) == modassert.PATCHED)
        check("the safe-module panic is still present -- we did not touch it",
              MULTI in now)
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
        check("status returns to unpatched",
              modassert.status(tmp) == modassert.UNPATCHED)

        bare = tmp / "bare"
        bare.mkdir()
        if rb.is_file():
            shutil.copy2(rb, bare / "race.bin")
            check("a release build reports ABSENT rather than erroring",
                  modassert.status(bare) == modassert.ABSENT, modassert.status(bare))
            try:
                modassert.apply(bare)
                check("...and refuses to patch one", False)
            except modassert.ModAssertError:
                check("...and refuses to patch one", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        for name in failures:
            print(f"  FAILED: {name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
