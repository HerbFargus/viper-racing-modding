"""The one-instruction fix that lets the original game start on a modern GPU.

THE BUG. Before comparing the graphics card's memory against its own tiers, the
game adds 0x96000 to the figure DirectDraw reported:

    add  dword ptr [esp+4], 0x96000     81 44 24 04 00 60 09 00
    cmp  dword ptr [esp+4], 0x1e8480    81 7c 24 04 80 84 1e 00   ; 2 MB
    jae  ...                            73 04
    xor  eax, eax                       33 c0                     ; -> failure
    ...
    cmp  dword ptr [esp+4], 0x3d0900                              ; 4 MB

0x96000 is 614,400 -- exactly 640x480x2, one 16-bit framebuffer -- so this is
the game allowing for its own front buffer on top of what the driver reports.
Harmless in 1998. On a card reporting close to 4GB the add wraps past 2^32 to a
tiny value, the 2 MB comparison fails, and the game reports that the video card
returned an error and quits.

THE FIX, and it is the community's, not ours: replace those 8 bytes with NOPs.
Comparing the real figure works fine -- the comparisons are unsigned (`jae`),
so a 4GB card passes easily, and the framebuffer allowance the add provided is
meaningless when the card has gigabytes. This is exactly what the community
race.bin does; diffing stock 1.1 against v1.2.5 2016 shows those eight bytes
and nothing else at this site.

WHAT THIS DOES NOT DO. It fixes STARTUP only. The community build also raises
the polygon and vertex limits (95,000-polygon tracks, 20,000 vertices per
object) and fixes the spoiler and mirror display. A stock race.bin patched here
will run, but high-detail mods that rely on those limits still will not load.
Anyone wanting the full thing should install the community race.bin.

The site is located by PATTERN, never by offset -- it sits at 0x4e366 in stock
1.1, 0x4e026 in stock 1.0's race.bin and 0x54556 in its race.exe, and the
surrounding code moves between builds.

TWO LAYOUTS, TWO BINARIES. The retail pressings do not run the same file:

    v1.1   <install>\\Viper Racing.exe   the launcher: 388 KB, but only ~16 KB of
                                       it is code -- the rest is resources, and
                                       it imports no graphics DLLs at all. It runs
           <install>\\Data\\race.bin      <- the engine

    v1.0   <install>\\race.exe            <- the engine, and Data\\'s contents ARE
                                           the install directory, as distributed

and a v1.0 install ships BOTH: `race.exe` (890 KB of .text, importing DDRAW /
DSOUND / DINPUT) and a `race.bin` that is never loaded. Patching only race.bin
there changes nothing at all -- the game still refuses to start, and nothing
reports that the patch went to a dormant file. That silent no-op is the whole
reason this module looks at both. `race.exe` is the live binary whenever it is
present; each file carries its own copy of the check, so both get patched and
the install is correct whichever one the build actually loads.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import safewrite

# Engine binaries, LIVE ONE FIRST -- see "TWO LAYOUTS" above. Order is load-bearing:
# status() reports on the live binary, and apply() returns its offset.
TARGETS = ("race.exe", "race.bin")

RACE_BIN = "race.bin"   # retained: callers and older patch records name it

# The instruction being removed, and what replaces it.
VRAM_ADD = bytes.fromhex("8144240400600900")   # add dword [esp+4], 0x96000
NOPS = b"\x90" * len(VRAM_ADD)

# The instruction immediately AFTER it, used as the anchor. Anchoring on this
# rather than on the add itself means the same lookup answers both "can this be
# patched?" and "has it already been?" -- the eight bytes in front of the anchor
# are either the add or the NOPs that replaced it.
ANCHOR = bytes.fromhex("817c240480841e00")     # cmp dword [esp+4], 0x1e8480

UNPATCHED, PATCHED, UNKNOWN, MISSING = "unpatched", "patched", "unknown", "missing"


class PatchError(RuntimeError):
    """The patch site can't be found, or is not in a state we recognise."""


def _site(blob: bytes) -> int:
    """Offset of the 8 bytes to patch. Raises if not exactly one anchor."""
    hits = [m.start() for m in re.finditer(re.escape(ANCHOR), blob)]
    if len(hits) != 1:
        raise PatchError(
            f"expected exactly one video-memory check, found {len(hits)}. "
            "This race.bin is not a build this patch understands.")
    return hits[0] - len(VRAM_ADD)


def _present(data_dir: str | Path) -> list[Path]:
    """Every engine binary in the folder, the live one first."""
    d = Path(data_dir)
    return [d / n for n in TARGETS if (d / n).is_file()]


def _status_of(f: Path) -> str:
    try:
        blob = f.read_bytes()
        at = _site(blob)
    except PatchError:
        return UNKNOWN
    chunk = blob[at:at + len(VRAM_ADD)]
    return UNPATCHED if chunk == VRAM_ADD else PATCHED if chunk == NOPS else UNKNOWN


def report(data_dir: str | Path) -> dict[str, str]:
    """Per-binary status, e.g. {"race.exe": "unpatched", "race.bin": "patched"}.

    status() collapses this to the live binary; use this when the difference
    matters -- diagnosing a v1.0 install where only the dormant race.bin got
    patched, for instance.
    """
    return {f.name: _status_of(f) for f in _present(data_dir)}


def status(data_dir: str | Path) -> str:
    """UNPATCHED, PATCHED, UNKNOWN or MISSING for the binary the game actually runs.

    On a v1.0 install that is race.exe, not race.bin -- reporting on race.bin
    there would say "patched" about a file the game never loads.
    """
    files = _present(data_dir)
    if not files:
        return MISSING
    return _status_of(files[0])


def _patch_file(f: Path) -> int | None:
    """NOP the site in one binary. Returns the offset, or None if already patched."""
    blob = bytearray(f.read_bytes())
    at = _site(bytes(blob))
    chunk = bytes(blob[at:at + len(VRAM_ADD)])
    if chunk == NOPS:
        return None
    if chunk != VRAM_ADD:
        raise PatchError(
            f"unexpected bytes at the patch site in {f.name} ({chunk.hex(' ')}); "
            "refusing to write")
    blob[at:at + len(VRAM_ADD)] = NOPS
    backup = f.with_suffix(f.suffix + ".vram-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    safewrite.write_atomic(f, bytes(blob))
    return at


def apply(data_dir: str | Path) -> int:
    """Apply the fix to EVERY engine binary present. Returns the live one's offset.

    Refuses unless the site holds exactly the expected instruction -- so it cannot
    be applied twice, and cannot damage a build it does not recognise. Each file is
    copied to <name>.vram-backup first.

    Both binaries are patched on a v1.0 install because the dormant one costs
    nothing to fix and leaves the tree correct if the other is ever made live. A
    sibling that is already patched, or that this patch does not recognise, is
    skipped rather than aborting the run -- only a failure on the LIVE binary is
    fatal, since that is the one that decides whether the game starts.
    """
    files = _present(data_dir)
    if not files:
        raise PatchError(f"no {' or '.join(TARGETS)} in {data_dir}")
    if _status_of(files[0]) == PATCHED:
        raise PatchError("already patched -- nothing to do")

    live_at = None
    for f in files:
        try:
            at = _patch_file(f)
        except PatchError:
            if f is files[0]:
                raise
            continue
        if f is files[0]:
            live_at = at
    return live_at


def revert(data_dir: str | Path) -> int:
    """Put the original instruction back in every binary. Returns the live offset."""
    files = _present(data_dir)
    if not files:
        raise PatchError(f"no {' or '.join(TARGETS)} in {data_dir}")
    live_at = None
    for f in files:
        blob = bytearray(f.read_bytes())
        try:
            at = _site(bytes(blob))
        except PatchError:
            if f is files[0]:
                raise
            continue
        if bytes(blob[at:at + len(VRAM_ADD)]) != NOPS:
            if f is files[0]:
                raise PatchError("the patch site does not hold this patch")
            continue
        blob[at:at + len(VRAM_ADD)] = VRAM_ADD
        safewrite.write_atomic(f, bytes(blob))
        if f is files[0]:
            live_at = at
    return live_at
