"""Double the triangle rasteriser's edge tables, so tall screens keep the needle.

THE LIMIT. The filled-triangle routine carves two scanline edge tables out of a
`0x2000` __chkstk frame. At four bytes per scanline that is **1024 entries each**,
and `needlefix` bounds both accesses by that number -- which is what makes tall
resolutions safe, but also means nothing below row 1024 is drawn. The tachometer
needle is geometry pivoted at `y = height - 0x50`, so above roughly 1104 screen
rows it disappears entirely: at 2048 x 1536 the dial renders and the pointer does
not.

THE FRAME. Once the prologue has run the stack looks like this, where `R` is the
slot holding the return address and `base` is esp after the four register pushes:

    base+0x0000   pushed ebp, edi, esi, ebx      16 bytes
    base+0x0010   edge table A                   4096 = 1024 entries
    base+0x1010   edge table B                   4096 = 1024 entries
    base+0x2010   R, the return address
    base+0x2014   arguments

so `0x2000` covers exactly the two tables. Doubling it to `0x4000` gives 2048
entries each -- enough for any screen the 2048-wide surface cap allows -- and
moves table B and every argument:

    mov eax, 0x2000   ->  0x4000      the __chkstk request
    add esp, 0x2000   ->  0x4000      the epilogue that unwinds it
    [esp + 0x1010]    ->  0x2010      table B's base, +0x1000
    [esp + 0x1028]    ->  0x2028      table B again, through a call's pushes
    [esp + 0x20xx]    ->  +0x2000     every argument reference

Table A stays at `[esp+0x10]`, so it is left alone.

HOW THE REFERENCES ARE FOUND -- and the trap in it. esp moves constantly here
(pushes before each call, `add esp` after), so a raw displacement means nothing on
its own, and tracking esp through the function does not work either because it
branches. What makes this tractable is that the displacements separate into two
bands with a 0xff8 gap: everything frame-local is at most `0x1028`, every argument
is at least `0x2020`. That is checked at patch time rather than assumed.

The operands encode as `opcode / modrm(mod=10, rm=100) / sib(base=100) / disp32`.
**The SIB's index field is whatever register the compiler picked and it differs
between builds** -- v1.2.5 indexes with edi (`sib=0x3c`), retail with ebp
(`sib=0x2c`) -- so only the base may be matched. Matching the whole SIB byte finds
20 of the 21 references on retail and produces a subtly broken binary; that is the
mistake this comment exists to prevent.

VALIDATION. Before a byte is written: exactly one prologue, an epilogue after it,
exactly 21 disp32 references whose multiset matches both known builds exactly, one
`mov eax, 0x2000`, one `add esp, 0x2000`, and the two bands separable. Any failure
refuses the patch. No instruction changes length -- every displacement that moves
is already disp32 -- so the function keeps its size and every branch inside it
stays correct.

COST. 8 KB more stack per call, on a default 1 MB stack.

PAIR THIS WITH `needlefix(entries=0x800)`. Growing the tables without raising the
bounds gains nothing; raising the bounds without growing the tables reinstates the
original stack-smashing crash.
"""
from __future__ import annotations

import collections
import re
import shutil
import struct
from pathlib import Path

from . import safewrite

RACE_BIN = "race.bin"

OLD_FRAME, NEW_FRAME = 0x2000, 0x4000
TABLE_B_SHIFT = 0x1000          # table B moves down by the growth of table A
ARG_SHIFT = 0x2000              # arguments move by the growth of both

# mov eax, 0x2000 / call __chkstk / push ebx / mov eax,[global] / push esi,edi,ebp
_PROLOGUE = re.compile(rb"\xb8\x00\x20\x00\x00\xe8(....)\x53\xa1(....)\x56\x57\x55", re.S)
_PROLOGUE_BIG = re.compile(rb"\xb8\x00\x40\x00\x00\xe8(....)\x53\xa1(....)\x56\x57\x55", re.S)
_EPILOGUE = bytes.fromhex("81c400200000c3")        # add esp, 0x2000 ; ret
_EPILOGUE_BIG = bytes.fromhex("81c400400000c3")

# every disp32 reference, as both builds have it
_EXPECTED = {0x1010: 2, 0x1028: 4, 0x2020: 2, 0x2024: 5,
             0x2028: 1, 0x202c: 2, 0x2034: 2, 0x203c: 3}

UNPATCHED, PATCHED, UNKNOWN, MISSING = "unpatched", "patched", "unknown", "missing"


class TableFixError(RuntimeError):
    """The rasteriser is not in a shape this patch recognises."""


# Engine binaries, live one first. The v1.0 pressing runs race.exe; growing the
# tables in the race.bin sitting beside it changes a file nothing loads, and the
# game still smashes its stack above row 1024. The rasteriser is the SAME 409-byte
# function in all three builds -- same prologue, same 21 disp32 references, same
# multiset -- so this is only a question of which file to open.
ENGINE_NAMES = ("race.exe", RACE_BIN)


def _race_bin(data_dir: str | Path) -> Path:
    """The engine binary whose rasteriser the game actually runs."""
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise TableFixError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def _refs(body: bytes) -> list[tuple[int, int]]:
    """(offset of the disp32, value) for every esp-relative disp32 operand.

    Matches `mod=10, rm=100` with a SIB whose BASE is esp. The index and scale
    fields are deliberately not constrained -- see the module docstring.
    """
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(body) - 7:
        if body[i] in (0x8B, 0x8D) and (body[i + 1] & 0xC7) == 0x84 \
                and (body[i + 2] & 0x07) == 0x04:
            out.append((i + 3, struct.unpack_from("<I", body, i + 3)[0]))
            i += 7
        else:
            i += 1
    return out


def _locate(blob: bytes) -> tuple[int, int]:
    """(start, end) file offsets of the rasteriser, unpatched."""
    hits = list(_PROLOGUE.finditer(blob))
    if len(hits) != 1:
        raise TableFixError(
            f"expected exactly one rasteriser prologue, found {len(hits)}")
    start = hits[0].start()
    end = blob.find(_EPILOGUE, start)
    if end < 0:
        raise TableFixError("no `add esp, 0x2000 / ret` epilogue after the prologue")
    return start, end + len(_EPILOGUE)


def status(data_dir: str | Path) -> str:
    try:
        f = _race_bin(data_dir)
    except TableFixError:
        return MISSING
    blob = f.read_bytes()
    if len(_PROLOGUE.findall(blob)) == 1 and _EPILOGUE in blob:
        return UNPATCHED
    if len(_PROLOGUE_BIG.findall(blob)) == 1 and _EPILOGUE_BIG in blob:
        return PATCHED
    return UNKNOWN


def entries(data_dir: str | Path) -> int:
    """Scanlines each edge table can hold in the binary as it stands."""
    return 0x800 if status(data_dir) == PATCHED else 0x400


def apply(data_dir: str | Path) -> dict[str, object]:
    """Grow both edge tables to 2048 entries. Returns what was changed."""
    f = _race_bin(data_dir)
    blob = bytearray(f.read_bytes())

    if status(data_dir) == PATCHED:
        return {"result": "already patched"}
    start, end = _locate(bytes(blob))
    body = bytes(blob[start:end])

    refs = _refs(body)
    got = collections.Counter(d for _, d in refs)
    if dict(got) != _EXPECTED:
        raise TableFixError(
            f"the rasteriser's stack references are not what this patch expects.\n"
            f"  found    {dict(sorted(got.items()))}\n"
            f"  expected {dict(sorted(_EXPECTED.items()))}\n"
            f"Refusing to guess -- a mis-relocated reference fails exactly like the "
            f"crash this whole area is about.")

    local = [d for _, d in refs if d < OLD_FRAME]
    args = [d for _, d in refs if d >= OLD_FRAME]
    if not (local and args and max(local) < OLD_FRAME <= min(args)):
        raise TableFixError("frame-local and argument displacements are not separable")
    if body.count(b"\xb8\x00\x20\x00\x00") != 1:
        raise TableFixError("expected exactly one `mov eax, 0x2000` in the function")
    if body.count(_EPILOGUE[:6]) != 1:
        raise TableFixError("expected exactly one `add esp, 0x2000` in the function")

    out = bytearray(body)
    moved = {"table_b": 0, "args": 0}
    for off, d in refs:
        new = d + (ARG_SHIFT if d >= OLD_FRAME else TABLE_B_SHIFT)
        struct.pack_into("<I", out, off, new)
        moved["args" if d >= OLD_FRAME else "table_b"] += 1

    out[:5] = b"\xb8" + struct.pack("<I", NEW_FRAME)            # mov eax, 0x4000
    ep = out.rfind(_EPILOGUE[:6])
    out[ep:ep + 6] = b"\x81\xc4" + struct.pack("<I", NEW_FRAME)  # add esp, 0x4000

    if len(out) != len(body):
        raise TableFixError("internal error: the function changed size")
    blob[start:end] = out

    backup = f.with_suffix(f.suffix + ".table-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    safewrite.write_atomic(f, bytes(blob))
    return {"result": "patched", "at": start, "bytes": len(body),
            "table_b_refs": moved["table_b"], "arg_refs": moved["args"],
            "entries": 0x800}
