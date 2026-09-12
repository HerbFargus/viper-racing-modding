"""Read and change the game's screen resolutions.

The game offers four modes. Each is identified internally by a MENU INDEX 1-4,
and that index -- not the text in the menu -- is what carries the dimensions:

    index 1 = 512x384    index 2 = 640x480    index 3 = 800x600    index 4 = 1024x768

Those numbers are compiled in as immediate operands at four separate sites, so
a resolution is only really changed when all four agree:

  1. THE ENUMERATION WHITELIST, inside the DirectDraw mode-enumeration callback
     (0x44f140 in the retail build). For every mode the driver reports it
     compares against five hardcoded width/height pairs and, on a match, sets a
     byte in the availability array at 0x50af94:

         cmp ecx, 0x400            ; width  == 1024
         jne next
         cmp dword [eax+8], 0x300  ; height ==  768
         jne next
         mov byte [0x50af98], 1    ; flags[4] = available

     A mode that matches none of the five is silently discarded, however
     willing the driver was to provide it.

  2. THE DIMENSION GETTER (0x44e960), a jump table on the index that loads the
     mode into eax/ecx:  mov eax, 0x400 / mov ecx, 0x300.

  3 and 4. TWO GLOBALS CHAINS (0x447d74 and 0x447e97), each writing the same
     pair into the width and height globals.

  and finally the LABEL, a NUL-padded 12-byte string, which is only what the
  menu prints. The four labels sit in DESCENDING order, so the label slot for a
  menu index is `MODES - index`.

WHY THIS MODULE USED TO BE WRONG. It patched the label alone, on the inference
that the game parsed it for the dimensions. It does not. The symptom was
subtle: relabelling the 640x480 entry to "1920 x 1080" produced a menu that
offered 1920x1080, accepted it, and then rendered 640x480, because index 2
still meant 640x480 everywhere that mattered. Every mode that appeared to
"work" during testing was a stock entry that had not been edited at all.

WHICH INDEX TO REPURPOSE. Prefer index 4. Index 2's availability flag doubles
as the startup gate -- `cmp byte [0x50af96], 0` is what prints "video card
cannot do 640x480x16!" and exits -- so pointing index 2 at a mode the driver
does not offer stops the game booting. Index 4 has no such role: an unavailable
mode simply drops out of the menu. `set_mode` refuses index 2 unless asked
twice, via allow_boot_gate.

WHAT THIS STILL CANNOT PROMISE. Patching makes the game WILLING to use a mode.
The availability flag is only set if DirectDraw actually enumerates that exact
width and height at the depth the game asks for. If the patched mode never
appears in the menu, that is the driver declining, not this patch failing --
and the game still runs on its other modes.

Every site is found by PATTERN, never by offset: the retail build and the
community v1.2.5 one place them differently (the label table alone moves from
0xde9a4 to 0xe2520), so an offset would break on the next build someone makes.

There is a pre-existing tool for the label alone, ResolutionChanger.exe (2008).
Its own dialog warns "This Application does not backup your current race.bin!!!"
-- this module always does.
"""
from __future__ import annotations

import re
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from . import safewrite

RACE_BIN = "race.bin"
SLOT = 12                    # bytes per label, including the NUL padding
MODES = 4
MAX_LABEL = SLOT - 1         # 11 characters, leaving room for the terminator
BOOT_GATE_INDEX = 2          # the index whose flag gates startup

# What a label slot must look like: "W x H", ASCII, then NUL padding.
_LABEL = re.compile(rb"^(\d{3,4}) x (\d{3,4})\x00*$")

# The dimension getter's four blocks:
#   b8 <w32>            mov eax, width
#   b9 <h32>            mov ecx, height
#   c6 05 <addr32> 04   mov byte [flags], 4
# They appear in ascending index order, which is how an index is assigned.
_DIMS = re.compile(rb"\xb8(....)\xb9(....)\xc6\x05....\x04", re.S)


class ResolutionError(RuntimeError):
    """The resolution table can't be read or safely changed."""


@dataclass
class Mode:
    index: int                   # menu index, 1-4
    width: int
    height: int
    label: tuple[int, int]       # what the menu prints, which may disagree
    sites: int                   # code sites found for this mode (want 4)

    @property
    def slot(self) -> int:
        """Position in the label table; the labels run in descending order."""
        return MODES - self.index

    @property
    def consistent(self) -> bool:
        return self.label == (self.width, self.height) and self.sites == 4


# Engine binaries, live one first. The v1.0 pressing runs race.exe and ships a
# race.bin beside it that nothing loads, so writing the mode table into
# "race.bin" on that install changes a file the game never opens -- the menu
# still tops out at 1024x768 and nothing says why. The four sites are found by
# PATTERN, and those patterns match race.exe unmodified, so this is only a
# question of which file to open. Same rule as vrampatch, mapfile and doctor.
ENGINE_NAMES = ("race.exe", RACE_BIN)


def _race_bin(data_dir: Path) -> Path:
    """The engine binary whose mode table the game actually reads."""
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise ResolutionError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


# --------------------------------------------------------------------------
# locating the five sites
# --------------------------------------------------------------------------

def _u32(v: int) -> bytes:
    return re.escape(struct.pack("<I", v))


def _whitelist(w: int, h: int) -> re.Pattern:
    """cmp ecx, w / jne / cmp dword [eax+8], h / jne -- in the enum callback."""
    return re.compile(rb"\x81\xf9" + _u32(w) + rb"\x75." +
                      rb"\x81\x78\x08" + _u32(h) + rb"\x75.", re.S)


def _globals(w: int, h: int) -> re.Pattern:
    """mov dword [width], w / mov dword [height], h -- two chains do this."""
    return re.compile(rb"\xc7\x05...." + _u32(w) + rb"\xc7\x05...." + _u32(h), re.S)


def _dims(w: int, h: int) -> re.Pattern:
    return re.compile(rb"\xb8" + _u32(w) + rb"\xb9" + _u32(h) + rb"\xc6\x05....\x04", re.S)


def _table_offset(blob: bytes) -> int:
    """Find the four-slot label run. Anchored on all four slots parsing, so a
    stray "1024 x 768" elsewhere in the binary can't be mistaken for it."""
    for m in re.finditer(rb"\d{3,4} x \d{3,4}\x00", blob):
        start = m.start()
        if all(_LABEL.match(blob[start + i * SLOT: start + (i + 1) * SLOT])
               for i in range(MODES)):
            return start
    raise ResolutionError("couldn't find the resolution label table in race.bin")


def _code_modes(blob: bytes) -> list[tuple[int, int]]:
    """The four (width, height) pairs from the dimension getter, in index order.

    This -- not the label -- is what the game actually renders at, so it is the
    authority everywhere below. A binary whose label was edited by an older
    version of this module (or by ResolutionChanger) will disagree, and reading
    the label instead would then look for code that does not exist.
    """
    hits = _DIMS.findall(blob)
    if len(hits) != MODES:
        raise ResolutionError(
            f"expected {MODES} resolution blocks in the dimension getter, found "
            f"{len(hits)}. This race.bin is not a build this patch understands.")
    return [(struct.unpack("<I", w)[0], struct.unpack("<I", h)[0]) for w, h in hits]


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def modes(data_dir: str | Path) -> list[Mode]:
    """Everything known about the four modes, including any label/code mismatch."""
    blob = _race_bin(Path(data_dir)).read_bytes()
    start = _table_offset(blob)
    labels = []
    for i in range(MODES):
        m = _LABEL.match(blob[start + i * SLOT: start + (i + 1) * SLOT])
        labels.append((int(m.group(1)), int(m.group(2))))

    out = []
    for k, (w, h) in enumerate(_code_modes(blob)):
        index = k + 1
        sites = (len(_whitelist(w, h).findall(blob))
                 + len(_dims(w, h).findall(blob))
                 + len(_globals(w, h).findall(blob)))
        out.append(Mode(index, w, h, labels[MODES - index], sites))
    return out


def read(data_dir: str | Path) -> list[tuple[int, int]]:
    """The four real modes as (width, height), in label-table order.

    Kept for callers that just want the list the menu is built from.
    """
    by_slot = {m.slot: (m.width, m.height) for m in modes(data_dir)}
    return [by_slot[s] for s in range(MODES)]


# The mode selector in options.cfg, stored as a MENU INDEX (1-4).
# `slot = MODES - index`, so index 4 is slot 0, the first table entry (where
# set_mode puts the modern mode). Setting only the table makes a resolution
# AVAILABLE; this selects it, so the game boots straight into it instead of the
# player picking it in the menu.
#
# This is the ONLY video key. An options file also carries a line reading
# `video mode N`, which was previously documented here as a separate frontend
# key holding a slot 0-3. It is not a key at all: load_options splits each line
# at the FIRST space, so that line parses as an option named `video` with the
# string value "mode N", and no code anywhere reads an option called `video`.
# See doctor.video_mode for the full trace.
RACE_MODE_KEY = "video_mode"


def select_race_mode(data_dir: str | Path, index: int) -> Path | None:
    """Point the RACE view at menu `index` (1-4) in the live options.cfg.

    Returns the file written, or None if no options file exists yet (game never
    run) or there's nowhere to add the key. The `(?m)^video_mode` anchor matters:
    the junk `video mode N` line sits earlier in the file and an unanchored
    `video[ _]mode` would rewrite that instead, leaving the real key untouched.
    """
    if not 1 <= index <= MODES:
        raise ResolutionError(f"menu index must be 1-{MODES}, got {index}")
    from . import aifield                    # its options_path finds Config/options.cfg
    f = aifield.options_path(data_dir)
    if f is None:
        return None
    t = f.read_text(encoding="utf-8", errors="replace")
    pat = rf"(?m)^({RACE_MODE_KEY})\s+-?\d+"     # underscore only; 'video mode' won't match
    if re.search(pat, t):
        t = re.sub(pat, rf"\g<1> {index}", t)
    else:
        m = re.search(r"(?m)^\[GAME\]\s*$", t)
        if not m:
            return None                          # nowhere sensible to add it -- skip, don't fail
        t = t[:m.end()] + f"\n{RACE_MODE_KEY} {index}" + t[m.end():]
    f.write_text(t, encoding="utf-8")
    return f


def label_for(width: int, height: int) -> bytes:
    """The stored form of a mode, padded to its slot.

    Raises rather than truncating: a silently shortened label would leave the
    menu printing something other than what was asked for.
    """
    text = f"{width} x {height}".encode("ascii")
    if len(text) > MAX_LABEL:
        raise ResolutionError(
            f"{width} x {height} needs {len(text)} characters but a slot holds "
            f"{MAX_LABEL}. Five-digit dimensions will not fit.")
    return text.ljust(SLOT, b"\x00")


# --------------------------------------------------------------------------
# patching
# --------------------------------------------------------------------------

def set_mode(data_dir: str | Path, index: int, width: int, height: int,
             *, allow_boot_gate: bool = False) -> tuple[int, int]:
    """Repoint one menu index at a new resolution. Returns what it was.

    `index` is the MENU index 1-4, not a label-table slot. All four code sites
    and the label are rewritten together, or nothing is written at all.

    Backs race.bin up as race.bin.res-backup the first time. Every edit is a
    same-length immediate replacement, so the file size never changes.
    """
    if not 1 <= index <= MODES:
        raise ResolutionError(f"menu index must be 1-{MODES}, got {index}")
    if width < 100 or height < 100:
        raise ResolutionError("width and height must be at least 100")
    if index == BOOT_GATE_INDEX and not allow_boot_gate:
        raise ResolutionError(
            f"index {BOOT_GATE_INDEX} is the startup gate: its availability flag is "
            "what the game checks before it will start at all, so pointing it at a "
            "mode the driver does not offer stops the game booting. Use index 4, or "
            "pass allow_boot_gate=True if that is really what you want.")

    f = _race_bin(Path(data_dir))
    blob = bytearray(f.read_bytes())
    current = _code_modes(bytes(blob))
    old_w, old_h = current[index - 1]

    if (width, height) == (old_w, old_h):
        raise ResolutionError(f"index {index} is already {width} x {height}")
    if current.count((old_w, old_h)) > 1:
        raise ResolutionError(
            f"{old_w} x {old_h} is configured on more than one index, so its code "
            "sites can't be told apart. Reinstall race.bin from a backup first.")
    if (width, height) in current:
        raise ResolutionError(
            f"{width} x {height} is already on index {current.index((width, height)) + 1}; "
            "two indices sharing a resolution would make future edits ambiguous.")

    label = label_for(width, height)          # raises before anything is written

    # Rewrite each site, asserting the expected number of hits. A count that is
    # off means the pattern found something other than what it was aimed at, and
    # writing then would corrupt unrelated code.
    plan = ((_whitelist(old_w, old_h), _whitelist_repl(width, height), 1, "enumeration whitelist"),
            (_dims(old_w, old_h), _dims_repl(width, height), 1, "dimension getter"),
            (_globals(old_w, old_h), _globals_repl(width, height), 2, "globals chains"))

    out = bytes(blob)
    for pattern, repl, want, what in plan:
        out, n = pattern.subn(repl, out)
        if n != want:
            raise ResolutionError(
                f"expected {want} match(es) for the {what} of {old_w} x {old_h}, "
                f"found {n}; refusing to write a partial patch.")

    blob = bytearray(out)
    start = _table_offset(bytes(blob))
    at = start + (MODES - index) * SLOT
    blob[at:at + SLOT] = label

    backup = f.with_suffix(f.suffix + ".res-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    safewrite.write_atomic(f, bytes(blob))
    return old_w, old_h


def _same_length(sub):
    """Guard every replacement against changing the instruction's size.

    These are immediate-operand edits inside live code: a replacement even one
    byte short shifts everything after it and turns the rest of the function
    into garbage. Checking here means a slicing mistake raises instead of
    producing a binary that looks patched and crashes.
    """
    def checked(m: re.Match) -> bytes:
        out = sub(m)
        if len(out) != len(m.group(0)):
            raise ResolutionError(
                f"internal error: replacement is {len(out)} bytes for a "
                f"{len(m.group(0))}-byte match; refusing to shift the code")
        return out
    return checked


def _whitelist_repl(w: int, h: int):
    """Replacement preserving both jne displacements, which are not ours to change."""
    @_same_length
    def sub(m: re.Match) -> bytes:
        b = m.group(0)
        return (b"\x81\xf9" + struct.pack("<I", w) + b[6:8] +
                b"\x81\x78\x08" + struct.pack("<I", h) + b[15:17])
    return sub


def _dims_repl(w: int, h: int):
    """mov eax, w / mov ecx, h -- the immediates end at byte 10, then the
    `mov byte [flags], 4` tail is carried through untouched."""
    @_same_length
    def sub(m: re.Match) -> bytes:
        return (b"\xb8" + struct.pack("<I", w) +
                b"\xb9" + struct.pack("<I", h) + m.group(0)[10:])
    return sub


def _globals_repl(w: int, h: int):
    """Replacement preserving both global addresses, which differ per build."""
    @_same_length
    def sub(m: re.Match) -> bytes:
        b = m.group(0)
        return (b"\xc7\x05" + b[2:6] + struct.pack("<I", w) +
                b"\xc7\x05" + b[12:16] + struct.pack("<I", h))
    return sub
