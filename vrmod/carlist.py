"""Move and resize the Vehicle list on the Hacks options screen.

THE PROBLEM. The car list on that screen starts halfway down the window and is
only as tall as the space below it, so once an install carries more than a
handful of cars the entries run off the bottom of the screen and become
unreachable. Nothing scrolls far enough to save you; the box simply ends.

WHERE IT LIVES. `Added@HackOptionsControl` builds the screen as a table of
`UIDialogItem` descriptors and hands them to `_UIAddItems`. The constructor is a
plain 14-dword field copy (`?0UIDialogItem`: this[0..0x34] = args, ret 0x38), so
the geometry is four literal immediates at one call site:

    push h          field +0x14
    push w          field +0x10   (imm8 -- see the width note below)
    push y          field +0x0c
    push x          field +0x08
    push 0                        the string list, index field, etc. follow
    push 0x14                     item type
    call ?0UIDialogItem

`_UIAddItems` confirms which is which: it places the list's bottom scroll button
at `y + [+0x14] - 0x12` and its top one at `(x, y)`, so +0x0c is the top edge and
+0x14 is the height.

THE COMMUNITY ALREADY FIXED THIS, ON THE OTHER BINARY. Diffing every build we
hold, the earliest carrying the change is the **v1.2.4 BETA that shipped inside
the VRgt Demo, installer dated 6 January 2005**, and every later community build
inherits it unchanged:

    build                     x     y     w     h      list spans
    v1.0 retail race.bin    300   200   100   200      200 -> 400
    v1.0 RC   race.exe      300   200   100   200      200 -> 400
    1.2.4 beta (2005)       390   124   111   255      124 -> 379
    1.2.5 (2016)            390   124   111   255
    1.2.6 (2017)            390   124   111   255

76 pixels higher and 55 taller. The 0x50 bytes of descriptor either side are
byte-identical between retail and 1.2.4 -- including the neighbouring 0x122,
0x82 and 0x0b fields -- so the whole fix is those four numbers and nothing
structural.

WHY THIS MODULE EXISTS ANYWAY. The community only ever patched `race.bin`. The
v1.0 pressing runs `race.exe`, which no community build touches, so a v1.0
install has never had this fix -- the same gap as the horn ball and the module
assertion. Applying it by pattern gets it onto either engine.

THE WIDTH IS CONSTRAINED, THE REST ARE NOT. x, y and h are pushed as `push
imm32` (5 bytes) and can hold anything. The width is `push imm8` (2 bytes)
because both 100 and the community's 111 fit in a byte, and there is no room to grow
that instruction without moving everything after it -- so w is capped at 127.
That has never been the limiting dimension; car names are short.

HOW MANY ROWS THAT BUYS -- SOLVED, in game. `?0ListBox` computes it:

    push 0xa / call UIStyleHeight / add eax, 2
    mov  [this+0x23c], eax          ; ROW PITCH = font height + 2
    mov  eax, <box height>
    idiv dword [this+0x23c]
    mov  [this+0x238], eax          ; VISIBLE ROWS = h / pitch

Confirmed against a real screen: the community's h=255 renders exactly 17
entries, so the pitch is 15 and UIStyleHeight returns 13. **Rows scale directly
with h** -- an earlier guess here that the unchanged `0x0b` field might cap them
was wrong, and is retracted.

SO THE ROW COUNT IS NOT THE WALL -- SELECTABILITY IS. `?0ListBox` takes a scroll
object and, when it gets one, publishes the entry count and visible count to it:

    test ecx, ecx / je ...          ; no scroll object -> no notification
    mov [ecx], <entry count>
    mov [ecx+4], [this+0x238]

The Vehicle descriptor passes 0, so this list has no scrollbar and `Draw@ListBox`
starts at a scroll offset that is always zero. Entries past the visible count are
not merely off-screen, they are UNREACHABLE -- and `sort_carlist` qsorts the
names with `stricmp`, so with a large collection everything late in the alphabet
is simply unselectable. Observed in game: with 40+ cars installed the selected
`viper` could not be reached.

Raising h is therefore a real but bounded fix -- it buys `h/15` rows and nothing
more, and the community's 255 already fills the dialog panel it sits in, so even
that is spent.

AND THAT IS WHERE THIS DELIBERATELY STOPS. A genuine fix for a large collection
means giving the list a scroll object: `_UIAddItems` dispatches type 0x12 to a
ScrollBar plus two ScrollButtons and type 0x14 to this bare ListBox, so a
scrolling list is TWO descriptor entries sharing a scroll object. But
`Added@HackOptionsControl` builds its descriptor table inline on the stack
(`sub esp, 0x1c0`, fixed entries, type-0 terminated), so adding one means
growing that frame, writing 14 more dwords, allocating the scroll object and
wiring both entries to it -- injected x86, not an immediate.

It is not attempted, and not planned. The screen only ever needs to show a
working SET of cars; managing a library of hundreds is what this toolkit's own
switcher and gallery are for, and solving it there costs nothing and risks
nothing. Raising h past what the panel holds would also just overdraw the
dialog frame. If someone does want it later, everything needed to start is
above.
"""
from __future__ import annotations

import re
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from . import backups, safewrite

RACE_BIN = "race.bin"

# Engine binaries, live one first -- the v1.0 pressing runs race.exe and ships a
# race.bin beside it that nothing loads. Same rule as every other patch here.
ENGINE_NAMES = ("race.exe", RACE_BIN)

# The Vehicle item's construction, wildcarded at the four geometry immediates.
# Anchored on the trailing `push 0` / `push 0x14` (the item type), which is what
# makes it unique -- the four pushes alone are not.
SIGNATURE = re.compile(
    rb"\x68(....)"      # push h    -> field +0x14
    rb"\x6a(.)"         # push w    -> field +0x10   (imm8)
    rb"\x68(....)"      # push y    -> field +0x0c
    rb"\x68(....)"      # push x    -> field +0x08
    rb"\x51"            # push ecx  (0)
    rb"\x6a\x14",       # push 0x14 (item type)
    re.S)

MAX_WIDTH = 0x7F        # the width is an imm8; widening it would relocate code

STOCK, COMMUNITY, CUSTOM, ABSENT = "stock", "community", "custom", "absent"


class CarListError(RuntimeError):
    """The Vehicle list isn't where this patch expects, or the build has none."""


@dataclass(frozen=True)
class Geometry:
    x: int
    y: int
    w: int
    h: int

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def __str__(self) -> str:
        return f"x={self.x} y={self.y} w={self.w} h={self.h} (spans {self.y}-{self.bottom})"


# What the retail builds ship, and what the community builds changed it to.
STOCK_GEOMETRY = Geometry(300, 200, 100, 200)
COMMUNITY_GEOMETRY = Geometry(390, 124, 111, 255)


def _engine(data_dir: str | Path) -> Path:
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise CarListError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def _site(blob: bytes) -> tuple[int, Geometry]:
    """Offset of the `push h` and the geometry there. Raises unless exactly one."""
    hits = list(SIGNATURE.finditer(blob))
    if len(hits) != 1:
        raise CarListError(
            f"expected exactly one Vehicle list descriptor, found {len(hits)}")
    m = hits[0]
    h = struct.unpack("<I", m.group(1))[0]
    w = m.group(2)[0]
    y = struct.unpack("<I", m.group(3))[0]
    x = struct.unpack("<I", m.group(4))[0]
    return m.start(), Geometry(x, y, w, h)


def available(data_dir: str | Path) -> bool:
    """Whether this build carries a descriptor this can move."""
    try:
        _site(_engine(data_dir).read_bytes())
        return True
    except CarListError:
        return False


def read(data_dir: str | Path) -> Geometry:
    """The Vehicle list's current geometry."""
    return _site(_engine(data_dir).read_bytes())[1]


def site(data_dir: str | Path) -> int:
    """File offset of the descriptor, for reporting."""
    return _site(_engine(data_dir).read_bytes())[0]


def status(data_dir: str | Path) -> str:
    """STOCK, COMMUNITY (the community builds' values), CUSTOM or ABSENT."""
    try:
        g = read(data_dir)
    except CarListError:
        return ABSENT
    if g == STOCK_GEOMETRY:
        return STOCK
    if g == COMMUNITY_GEOMETRY:
        return COMMUNITY
    return CUSTOM


def apply(data_dir: str | Path, geometry: Geometry | None = None, *,
          x: int | None = None, y: int | None = None,
          w: int | None = None, h: int | None = None) -> Geometry:
    """Move/resize the list. Defaults to the community geometry.

    Pass a Geometry, or any of x/y/w/h to change only those. Returns what is now
    in the file. Backs the engine up once as `<engine>.carlist-backup`.
    """
    f = _engine(data_dir)
    blob = bytearray(f.read_bytes())
    at, current = _site(bytes(blob))

    if geometry is None:
        base = current if any(v is not None for v in (x, y, w, h)) else COMMUNITY_GEOMETRY
        geometry = Geometry(base.x if x is None else x,
                            base.y if y is None else y,
                            base.w if w is None else w,
                            base.h if h is None else h)

    if not 1 <= geometry.w <= MAX_WIDTH:
        raise CarListError(
            f"width must be 1-{MAX_WIDTH}: it is encoded as a one-byte immediate, "
            f"and a wider one would need a longer instruction and relocate "
            f"everything after it. Got {geometry.w}.")
    for name, v in (("x", geometry.x), ("y", geometry.y), ("h", geometry.h)):
        if not 0 <= v <= 0xFFFF:
            raise CarListError(f"{name} must be 0-65535, got {v}")
    if geometry.h < 16:
        raise CarListError(f"height {geometry.h} leaves no room for any entry")

    blob[at:at + 17] = (b"\x68" + struct.pack("<I", geometry.h)
                        + b"\x6a" + bytes([geometry.w])
                        + b"\x68" + struct.pack("<I", geometry.y)
                        + b"\x68" + struct.pack("<I", geometry.x))
    # Folder first, then beside the file: an install patched before
    # backups moved has its only pristine copy loose in Data/, and
    # missing it here would take a fresh "backup" of a patched binary.
    backup = backups.locate(f, ".carlist-backup") or backups.path_for(f, ".carlist-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    safewrite.write_atomic(f, bytes(blob))
    return geometry


def revert(data_dir: str | Path) -> Geometry:
    """Put the retail geometry back."""
    return apply(data_dir, STOCK_GEOMETRY)
