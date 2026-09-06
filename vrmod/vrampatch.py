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
1.1 and the surrounding code moves between builds.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

RACE_BIN = "race.bin"

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


def status(data_dir: str | Path) -> str:
    """UNPATCHED, PATCHED, UNKNOWN or MISSING for a Data folder's race.bin."""
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        return MISSING
    try:
        blob = f.read_bytes()
        at = _site(blob)
    except PatchError:
        return UNKNOWN
    chunk = blob[at:at + len(VRAM_ADD)]
    return UNPATCHED if chunk == VRAM_ADD else PATCHED if chunk == NOPS else UNKNOWN


def apply(data_dir: str | Path) -> int:
    """Apply the fix. Returns the offset patched.

    Refuses unless the site currently holds exactly the expected instruction --
    so it cannot be applied twice, and cannot damage a build it does not
    recognise. race.bin is copied to race.bin.vram-backup first.
    """
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        raise PatchError(f"no {RACE_BIN} in {data_dir}")
    blob = bytearray(f.read_bytes())
    at = _site(bytes(blob))
    chunk = bytes(blob[at:at + len(VRAM_ADD)])
    if chunk == NOPS:
        raise PatchError("already patched -- nothing to do")
    if chunk != VRAM_ADD:
        raise PatchError(
            f"unexpected bytes at the patch site ({chunk.hex(' ')}); refusing to write")

    blob[at:at + len(VRAM_ADD)] = NOPS
    backup = f.with_suffix(f.suffix + ".vram-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    f.write_bytes(bytes(blob))
    return at


def revert(data_dir: str | Path) -> int:
    """Put the original instruction back. Returns the offset restored."""
    f = Path(data_dir) / RACE_BIN
    blob = bytearray(f.read_bytes())
    at = _site(bytes(blob))
    if bytes(blob[at:at + len(VRAM_ADD)]) != NOPS:
        raise PatchError("the patch site does not hold this patch")
    blob[at:at + len(VRAM_ADD)] = VRAM_ADD
    f.write_bytes(bytes(blob))
    return at
