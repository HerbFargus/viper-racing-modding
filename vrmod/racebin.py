"""Install a race.bin the user supplies, safely.

The community's own instructions are "copy and paste this new race.bin into
your Viper Racing / Data folder overwriting the old one". That works, but it
backs nothing up and checks nothing -- overwrite the wrong file, or copy a
truncated download, and the game stops starting with no way back.

So this does the same job with the checks that are missing: confirm the file
really is a Viper Racing executable, read what version it claims, back up what
is there now, then install.

It deliberately does NOT ship any race.bin. The community build is someone
else's work, and it cannot be expressed as a patch to apply on the fly either:
diffing stock 1.1 against v1.2.5 2016 shows only 5.3% of bytes matching at the
same offset, divergence from 0x3c (the PE header), and 14,336 bytes of growth.
That is a rebuild, not an edit. The user brings the file; this handles it well.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import resolution, vrampatch

RACE_BIN = "race.bin"

# Markers every build of this executable carries. Checked together, because any
# one alone is weak: "MZ" is every Windows binary, and the resolution table is
# the strongest signal but would also match a hypothetical unrelated file.
MZ = b"MZ"
MARKERS = (b"Viper Racing", b"ghostcar", b"IdealLineRes")


class RaceBinError(RuntimeError):
    """The supplied file isn't a usable race.bin."""


@dataclass
class BinInfo:
    path: Path
    size: int
    sha256: str
    version: str | None          # e.g. "v1.2.5 2016"; None for the original release
    modes: list[tuple[int, int]] | None
    vram_fix: str                # vrampatch.PATCHED / UNPATCHED / UNKNOWN

    @property
    def describes(self) -> str:
        return self.version or "original release (no version marker)"


def inspect(path: str | Path) -> BinInfo:
    """Read what a race.bin claims to be. Raises if it isn't one."""
    p = Path(path)
    if not p.is_file():
        raise RaceBinError(f"{p} is not a file")
    blob = p.read_bytes()
    if len(blob) < 500_000:
        raise RaceBinError(
            f"{p.name} is only {len(blob):,} bytes -- far too small for race.bin "
            "(the real one is about 1.3 MB). A truncated download?")
    if not blob.startswith(MZ):
        raise RaceBinError(f"{p.name} is not a Windows executable")
    found = [m for m in MARKERS if m in blob]
    if not found:
        raise RaceBinError(
            f"{p.name} is an executable but carries none of Viper Racing's markers "
            f"({', '.join(m.decode() for m in MARKERS)}). Wrong file?")

    m = re.search(rb"v\d+\.\d+\.\d+[ -~]{0,12}", blob)
    version = m.group(0).decode("ascii", "replace").strip() if m else None

    try:
        modes = []
        start = resolution._table_offset(blob)
        for i in range(resolution.MODES):
            lm = resolution._LABEL.match(blob[start + i * resolution.SLOT:
                                              start + (i + 1) * resolution.SLOT])
            modes.append((int(lm.group(1)), int(lm.group(2))))
    except Exception:
        modes = None

    try:
        at = vrampatch._site(blob)
        chunk = blob[at:at + len(vrampatch.VRAM_ADD)]
        fix = (vrampatch.PATCHED if chunk == vrampatch.NOPS
               else vrampatch.UNPATCHED if chunk == vrampatch.VRAM_ADD
               else vrampatch.UNKNOWN)
    except Exception:
        fix = vrampatch.UNKNOWN

    return BinInfo(p, len(blob), hashlib.sha256(blob).hexdigest(), version, modes, fix)


def install(data_dir: str | Path, source: str | Path) -> tuple[BinInfo, BinInfo | None]:
    """Install `source` as the Data folder's race.bin.

    Returns (incoming, replaced) -- `replaced` is None if there was nothing
    there. The existing file is copied to race.bin.<version>-backup, or
    race.bin.replaced-backup when it carries no version, and an existing backup
    of that name is never overwritten.
    """
    data_dir = Path(data_dir)
    target = data_dir / RACE_BIN
    incoming = inspect(source)                    # raises before anything is touched

    replaced = None
    if target.is_file():
        try:
            replaced = inspect(target)
        except RaceBinError:
            replaced = None                       # unreadable, but still worth keeping
        if incoming.sha256 == (replaced.sha256 if replaced else None):
            raise RaceBinError("that is already the race.bin in this folder")
        tag = (replaced.version or "replaced").replace(" ", "-") if replaced else "replaced"
        backup = target.with_suffix(f"{target.suffix}.{tag}-backup")
        i = 2
        while backup.exists():
            backup = target.with_suffix(f"{target.suffix}.{tag}-backup{i}")
            i += 1
        shutil.copy2(target, backup)

    shutil.copy2(incoming.path, target)
    return incoming, replaced
