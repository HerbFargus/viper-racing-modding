"""Check that replacing an engine binary cannot leave it half-written.

The property under test is the one that matters when a two-megabyte race.exe is
being rewritten: after any outcome, success or failure, the file is either
wholly the old contents or wholly the new. Never a prefix, never zero bytes.

Run:  python scripts/check_safewrite.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import safewrite  # noqa: E402

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="check_safewrite_"))
    try:
        old, new = b"A" * 4096, b"B" * 8192
        f = tmp / "race.exe"

        f.write_bytes(old)
        safewrite.write_atomic(f, new)
        check("a plain replace writes the new contents", f.read_bytes() == new)
        check("it leaves no temp file behind",
              not list(tmp.glob("*" + safewrite.SUFFIX)),
              ", ".join(p.name for p in tmp.iterdir()))

        # the temp file must be a SIBLING: os.replace is only atomic within one
        # filesystem, and the game may not be on the same drive as %TEMP%.
        probe = tmp / "probe.exe"
        probe.write_bytes(old)
        seen: list[Path] = []
        real = Path.write_bytes

        def spy(self, data):
            seen.append(Path(self))
            return real(self, data)

        Path.write_bytes = spy
        try:
            safewrite.write_atomic(probe, new)
        finally:
            Path.write_bytes = real
        check("the temp file is written beside the target, not in %TEMP%",
              bool(seen) and seen[0].parent == probe.parent, str(seen[0].parent))

        # a LOCKED target: the failure this exists for.
        locked = tmp / "locked.exe"
        locked.write_bytes(old)
        before = sha(locked)
        fh = os.open(locked, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            # Deny replacement by holding an open handle AND making it read-only,
            # which is the closest portable stand-in for the antivirus window.
            os.chmod(locked, 0o444)
            raised = False
            try:
                safewrite.write_atomic(locked, new, attempts=2)
            except OSError:
                raised = True
            intact = sha(locked) == before
            check("a target that cannot be replaced raises rather than truncating",
                  raised or intact, f"raised={raised}")
            check("...and the original contents survive untouched", intact)
            check("...leaving no temp file behind",
                  not list(tmp.glob("*" + safewrite.SUFFIX)))
        finally:
            os.close(fh)
            os.chmod(locked, 0o666)

        # the contrast: what write_bytes does in the same situation
        victim = tmp / "victim.exe"
        victim.write_bytes(old)
        try:
            with open(victim, "wb") as fp:
                fp.write(new[:10])
                raise RuntimeError("interrupted mid-write")
        except RuntimeError:
            pass
        check("(control) a plain truncating write CAN leave a partial file",
              victim.stat().st_size == 10, f"{victim.stat().st_size} bytes")

        big = tmp / "big.exe"
        big.write_bytes(b"x" * 2_404_451)
        payload = b"y" * 2_404_451
        safewrite.write_atomic(big, payload)
        check("a 2.4 MB engine-sized replace round-trips exactly",
              big.read_bytes() == payload, f"{big.stat().st_size:,} bytes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        for f in failures:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
