"""Checks for the head-on panic patch.

Needs a race.bin to work against. Point it at one, or at a Data folder:

    python scripts/check_headon.py path/to/Data
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import headon  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    if src.is_dir():
        src = src / "race.bin"
    if not src.is_file():
        print(f"no race.bin at {src}")
        return 2

    print(f"head-on panic patch -- against {src}")
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        shutil.copy(src, data / "race.bin")
        original = (data / "race.bin").read_bytes()

        check("the function is found by signature, not by address",
              headon.status(data) == headon.ENABLED,
              f"AICar::headon_panic at {hex(headon.site(data))}")

        at = headon.apply(data)
        after = (data / "race.bin").read_bytes()
        changed = [i for i, (a, b) in enumerate(zip(original, after)) if a != b]

        # A one-byte patch is the whole point: the function is __thiscall, void,
        # no arguments, so returning before its `sub esp, 4` leaves the stack
        # exactly as it was found. Anything wider would mean the analysis is off.
        check("exactly one byte changes",
              len(changed) == 1 and changed[0] == at,
              f"{hex(at)}: {original[at]:#04x} -> {after[at]:#04x}")
        check("the byte written is a RET",
              after[at:at + 1] == headon.DISABLED, "0xc3")
        check("the file is otherwise untouched",
              len(after) == len(original), f"{len(after):,} bytes")
        check("status reports it disabled",
              headon.status(data) == headon.DISABLED_STATE, "disabled")

        backup = data / "race.bin.headon-backup"
        check("the original is backed up before writing",
              backup.is_file() and backup.read_bytes() == original,
              backup.name)

        # This writes into a game folder, so refusing to act twice and restoring
        # byte-for-byte both matter more than the patch itself.
        try:
            headon.apply(data)
        except headon.PatchError as e:
            check("re-applying is refused with a clear reason", "already" in str(e),
                  str(e))
        else:
            check("re-applying is refused with a clear reason", False, "it applied again")

        headon.revert(data)
        check("reverting restores the file byte for byte",
              (data / "race.bin").read_bytes() == original, "identical")
        check("status reports it enabled again",
              headon.status(data) == headon.ENABLED, "enabled")

        try:
            headon.revert(data)
        except headon.PatchError as e:
            check("reverting an unpatched build is refused", "not look patched" in str(e),
                  str(e))
        else:
            check("reverting an unpatched build is refused", False, "it reverted anyway")

        # A build the signature does not cover must be left alone rather than
        # written to at a guessed offset.
        blob = bytearray(original)
        blob[headon.site(data)] = 0x90
        (data / "race.bin").write_bytes(bytes(blob))
        check("an unrecognised build reports unknown, not enabled",
              headon.status(data) == headon.UNKNOWN, "unknown")
        try:
            headon.apply(data)
        except headon.PatchError:
            check("an unrecognised build is refused", True, "raises PatchError")
        else:
            check("an unrecognised build is refused", False, "it wrote anyway")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
