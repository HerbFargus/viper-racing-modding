"""Replace a file's contents without ever leaving it half-written.

WHY THIS EXISTS. Every module that patches the game rewrites the whole engine
binary -- two megabytes of race.exe or race.bin -- and `Path.write_bytes` opens
with "wb", which TRUNCATES ON OPEN. A failure after that point leaves a
truncated engine and nothing to run. The window is small but the loss is total,
and these modules are the ones least able to afford it.

AND IT IS NOT HYPOTHETICAL. Writing a .exe on Windows hands it to antivirus for
a moment, so the NEXT write to the same file can fail with PermissionError.
That was hit three times in one evening while porting the patch set to v1.0 --
once leaving `tablefix` applied and `needlefix` not, which is the benign half of
a pair that must move together. The other order reinstates a stack-smashing
crash, so relying on it landing the safe way round is not a plan.

WHAT THIS DOES. Writes a sibling temp file and renames it over the target.
`os.replace` is atomic within a volume, so the file is either wholly the old
contents or wholly the new, never a prefix of either. A locked target is retried
briefly, because that particular failure passes on its own.

WHY A SIBLING rather than the system temp directory: `os.replace` is only atomic
within one filesystem, and the game may well be installed on a different drive
from %TEMP%.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

SUFFIX = ".vrmod-tmp"
ATTEMPTS = 5


class SafeWriteError(OSError):
    """The target could not be replaced, after retrying a transient lock."""


def write_atomic(path: str | Path, data: bytes, attempts: int = ATTEMPTS) -> None:
    """Replace `path` with `data`, atomically, retrying a transient lock."""
    f = Path(path)
    tmp = f.with_name(f.name + SUFFIX)
    last: BaseException | None = None
    for i in range(attempts):
        try:
            tmp.write_bytes(data)
            os.replace(tmp, f)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.3 * (i + 1))
        except OSError:
            _discard(tmp)
            raise
        finally:
            if i == attempts - 1:
                _discard(tmp)
    _discard(tmp)
    raise SafeWriteError(
        f"could not write {f.name} after {attempts} attempts: {last}. Something "
        "is holding the file open -- close the game and the mod manager, and "
        "check whether antivirus is scanning it.")


def _discard(tmp: Path) -> None:
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
