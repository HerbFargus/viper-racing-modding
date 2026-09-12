"""Fix the stack overflow, and the red streaks, in the filled-triangle rasteriser.

THE BUG. The filled-triangle rasteriser (`0x44A280` retail) allocates its two
edge tables on the stack -- `mov eax, 0x2000` then __chkstk, carved as two 4096
byte tables at `[esp+0x10]` and `[esp+0x1010]`. Four bytes per scanline means
each holds exactly **1024 entries**. Two separate places then index them by
scanline, and BOTH bound the index against the render surface's height instead
of against the table:

  1. the edge walker (`0x44A420`), which RECORDS one x per scanline:

        test ebx, ebx                 ; y >= 0 ?
        jl   skip
        mov  eax, [render_target]
        cmp  dword [eax+0xC], ebx     ; y < SURFACE HEIGHT ?
        jle  skip
        mov  dword [edi + ebx*4], eax ; <-- indexes a 1024-entry table

  2. the fill loop (`0x44A3C7`), which READS one x from each table per scanline:

        test edi, edi                 ; y*4 >= 0 ?
        jl   next
        mov  eax, [render_target]
        cmp  dword [eax+0xC], esi     ; y < SURFACE HEIGHT ?
        jle  next
        mov  ecx, [esp + edi + 0x10]     ; <-- table A[y]
        mov  eax, [esp + edi + 0x1010]   ; <-- table B[y]

Every mode the game shipped with was at most 768 tall, so neither ever mattered.
Above 1024 rows they diverge from the tables in different ways.

Overflowing the WRITE runs off the stack frame and destroys saved registers and
return addresses; execution then jumps through the wreckage, which is why the
crash reports an EIP like `0x4E` -- a garbage value that changes between runs
and is not an address in the program at all.

Overflowing the READ is harmless to memory but not to the picture: at y >= 1024
table A's index reaches past its own 4096 bytes into table B, so the span is
built from two unrelated x values and the row is filled edge to edge. The
symptom is long horizontal streaks in the triangle's colour across the whole
screen.

WHAT TRIGGERS IT. The tachometer needle is drawn as geometry rather than as a
stamp, centred at `y = height - 0x50` with radius `0x32`, so it reaches about
`height - 30`. At 1920x1080 that is row 1050: past 1024, so the game dies on
entering a race, and once the write is fixed the same rows streak red instead.
Confirmed by prediction: with the pivot forced to 960 the needle reaches 1010
and the game runs clean; at 980 it reaches 1030 and it crashes.

THE FIX. Bound both sites by the table as well as by the surface.

The edge walker has no room for a second test, so its surface check is replaced
outright:

    cmp  <scanline>, <entries>    ; the register varies between builds
    jge  skip

That is safe because it can only ever REFUSE to record an edge, and drawing is
clipped independently -- `0x449A00` tests every pixel against all four clip-rect
fields and the plot routines honour it -- so nothing is drawn out of bounds just
because an edge was not recorded.

The fill loop is different: dropping its surface check would let it hand rows
past the bottom of a short surface to the span drawer, which is a wider bet than
this patch needs to make. So its ten bytes become a jump to a stub in .text
slack that keeps BOTH tests:

    cmp  <scanline>, <entries> / jge skip
    mov  eax, [render_target] / cmp [eax+0xC], <scanline> / jle skip
    jmp  continue
    skip: jmp next

Rows past the bound therefore contribute no edges and are not filled. At 1920x1080
with the stock tables that costs the bottom ~26 rows of the needle at idle, where
it hangs below the dial; everywhere the game shipped, nothing changes at all.

THE BOUND IS A PARAMETER, and it must match the tables the binary actually has.
`tablefix` doubles the frame to `0x4000`, giving 2048 entries each, at which point
this takes `entries=0x800` and tall screens keep their needle. The two go together:
bigger tables with the old bound gains nothing, and a bigger bound with the old
tables reinstates the stack smash.

VERIFIED ON HARDWARE: 1920x1080 crashed on every attempt before the first patch
and races with a full HUD after it.

Both sites are found by PATTERN and without assuming any register, so this works
on the retail and community builds despite their different layouts AND their
different register allocation -- see the comment on the guard patterns, which is
the subtler of the two and silently broke retail until it was found.
"""
from __future__ import annotations

import re
import shutil
import struct
from pathlib import Path

RACE_BIN = "race.bin"
TABLE_ENTRIES = 0x400            # 4096-byte table / 4 bytes per scanline

# --- both guards, matched WITHOUT assuming which registers the compiler used --
#
#     test rA,rA / jl rel8 / mov eax,[global] / cmp [eax+0xC],rB / jle rel8
#
# The two sites have the same shape and are told apart by whether rA and rB are
# the same register:
#
#   rA == rB  ->  the EDGE WALKER. It tests the scanline and guards recording it.
#   rA != rB  ->  the FILL LOOP. rA is the byte index (y*4), rB the scanline.
#
# Matching the registers literally is what broke this on retail: the fill loop
# indexes with edi on v1.2.5 and with ebp on retail, so a hardcoded `test edi,edi`
# finds the site on one build and nothing on the other. Register allocation is
# exactly the thing that differs between two independent compiles of the same
# source, so no pattern here may depend on it.
_TEST_RR = bytes(0xC0 + 9 * r for r in range(8))       # test rX,rX  (modrm 11 r r)
_CMP_M8 = bytes(0x40 + 8 * r for r in range(8))        # cmp [eax+disp8], rX
_GUARD_RE = (rb"\x85([" + re.escape(_TEST_RR) + rb"])\x7c(.)"
             rb"\xa1(....)\x39([" + re.escape(_CMP_M8) + rb"])\x0c\x7e(.)")
_GUARD = re.compile(_GUARD_RE, re.S)

# the same two sites once patched
_EDGE_FIXED = re.compile(
    rb"\x85([" + re.escape(_TEST_RR) + rb"])\x7c(.)\x81([\xf8-\xff])(....)"
    rb"\x90\x90\x7d(.)", re.S)
_FILL_FIXED = re.compile(
    rb"\x85([" + re.escape(_TEST_RR) + rb"])\x7c(.)\xe9(....)\x90{5}", re.S)


def _test_reg(b: int) -> int:
    return (b - 0xC0) // 9


def _cmp_reg(b: int) -> int:
    return (b - 0x40) // 8


def _guards(blob: bytes) -> dict[str, re.Match]:
    """Locate the edge walker and the fill loop, whatever registers they use."""
    found: dict[str, list[re.Match]] = {"edge_walker": [], "fill_loop": []}
    for m in _GUARD.finditer(blob):
        same = _test_reg(m.group(1)[0]) == _cmp_reg(m.group(4)[0])
        found["edge_walker" if same else "fill_loop"].append(m)
    out = {}
    for site, hits in found.items():
        if len(hits) == 1:
            out[site] = hits[0]
        elif hits:
            raise NeedleFixError(
                f"expected one {site} guard, found {len(hits)} -- refusing to guess")
    return out

_GUARD_LEN = 10                  # bytes replaced at site 2: mov/cmp/jle
_REG = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")

UNPATCHED, PATCHED, PARTIAL, UNKNOWN, MISSING = (
    "unpatched", "patched", "partial", "unknown", "missing")


class NeedleFixError(RuntimeError):
    """A patch site can't be found, or isn't in a state we recognise."""


# Engine binaries, live one first. The v1.0 pressing runs race.exe, and raising
# the rasteriser bounds in the race.bin beside it changes a file nothing loads.
# The guard sites are found by pattern and those patterns match all three builds.
ENGINE_NAMES = ("race.exe", RACE_BIN)


def _race_bin(data_dir: str | Path) -> Path:
    """The engine binary whose rasteriser the game actually runs."""
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise NeedleFixError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def _sections(blob: bytes):
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    nsec = struct.unpack_from("<H", blob, pe + 6)[0]
    optsz = struct.unpack_from("<H", blob, pe + 20)[0]
    base = struct.unpack_from("<I", blob, pe + 24 + 28)[0]
    off = pe + 24 + optsz
    out = []
    for i in range(nsec):
        s = blob[off + i * 40: off + (i + 1) * 40]
        name = s[:8].rstrip(b"\x00").decode("ascii", "replace")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", s, 8)
        out.append((name, base + vaddr, vsize, rawptr, rawsize))
    return out


def _text(blob: bytes):
    for s in _sections(blob):
        if s[0] == ".text":
            return s
    raise NeedleFixError("no .text section -- not a race.bin")


def _f2va(blob: bytes, off: int) -> int:
    _, va, _, rawptr, _ = _text(blob)
    return va + (off - rawptr)


def _slack(blob: bytearray, size: int) -> tuple[int, int]:
    """(file offset, VA) of `size` free bytes in .text's mapped slack.

    The slack is the gap between the section's virtual size and its larger raw
    size, which the loader maps because the raw size already equals the
    section-aligned virtual size. It is zero in both builds and belongs to no
    code, so a stub placed there needs no new section and shifts nothing.
    """
    _, va, vsize, rawptr, rawsize = _text(blob)
    start, end = (rawptr + vsize + 15) & ~15, rawptr + rawsize
    for off in range(start, end - size, 16):
        if not any(blob[off:off + size]):
            return off, va + (off - rawptr)
    raise NeedleFixError("no free .text slack for the fill-loop stub")


def status(data_dir: str | Path) -> str:
    try:
        f = _race_bin(data_dir)
    except NeedleFixError:
        return MISSING
    blob = f.read_bytes()
    try:
        open_sites = _guards(blob)
    except NeedleFixError:
        return UNKNOWN
    edge_done = len(_EDGE_FIXED.findall(blob)) == 1
    fill_done = len(_FILL_FIXED.findall(blob)) == 1
    if "edge_walker" in open_sites and "fill_loop" in open_sites:
        return UNPATCHED
    if edge_done and fill_done and not open_sites:
        return PATCHED
    if edge_done or fill_done:
        return PARTIAL
    return UNKNOWN


def apply(data_dir: str | Path, entries: int = TABLE_ENTRIES) -> dict[str, str]:
    """Bound both table accesses by the table size.

    Each site is patched only if it is still open, so this can be run against a
    binary that already carries the earlier, edge-walker-only version of the fix.

    `entries` must match the tables the binary actually has: 0x400 for the stock
    frame, 0x800 after `tablefix` has doubled it. Too high reinstates the stack
    smash; too low silently throws away scanlines that would now be safe.
    Returns what was done to each site.
    """
    f = _race_bin(data_dir)
    blob = bytearray(f.read_bytes())
    done: dict[str, str] = {}
    backup = f.with_suffix(f.suffix + ".needle-backup")
    if not backup.exists():
        shutil.copy2(f, backup)

    sites = _guards(bytes(blob))
    if not sites and status(data_dir) == PATCHED:
        return {"edge_walker": "already patched", "fill_loop": "already patched"}

    # ---- site 1: the edge walker -----------------------------------------
    m = sites.get("edge_walker")
    if m is not None:
        reg = _test_reg(m.group(1)[0])           # the scanline register
        at = m.start() + 4                       # the mov/cmp pair
        blob[at:at + 8] = (bytes([0x81, 0xF8 | reg])     # cmp <reg>, <entries>
                           + entries.to_bytes(4, "little") + b"\x90\x90")
        blob[at + 8] = 0x7D                      # jle -> jge
        done["edge_walker"] = (f"patched at {_f2va(blob, at):#x}, "
                               f"bound {entries:#x} on {_REG[reg]}")
    elif _EDGE_FIXED.search(bytes(blob)):
        done["edge_walker"] = "already patched"
    else:
        raise NeedleFixError(
            "no edge-walker guard found. This race.bin is not a build this "
            "patch understands.")

    # ---- site 2: the fill loop -------------------------------------------
    m = sites.get("fill_loop")
    if m is not None:
        reg = _cmp_reg(m.group(4)[0])            # the scanline register
        at = m.start() + 4                       # the mov/cmp/jle triple
        rt = m.group(3)                          # render-target global
        skip_rel = m.group(5)[0]
        skip_rel -= 256 if skip_rel > 127 else 0
        cont_va = _f2va(blob, at + _GUARD_LEN)
        skip_va = cont_va + skip_rel

        soff, sva = _slack(blob, 32)
        stub = (bytes([0x81, 0xF8 | reg])                   # cmp <reg>, <entries>
                + entries.to_bytes(4, "little")
                + b"\x7d\x0f"                               # jge skip
                + b"\xa1" + rt                              # mov eax,[rt]
                + bytes([0x39, 0x40 | (reg << 3), 0x0C])    # cmp [eax+0xC],<reg>
                + b"\x7e\x05")                              # jle skip
        stub += b"\xe9" + struct.pack("<i", cont_va - (sva + len(stub) + 5))
        stub += b"\xe9" + struct.pack("<i", skip_va - (sva + len(stub) + 5))
        blob[soff:soff + len(stub)] = stub

        jmp = b"\xe9" + struct.pack("<i", sva - (_f2va(blob, at) + 5))
        blob[at:at + _GUARD_LEN] = jmp + b"\x90" * (_GUARD_LEN - len(jmp))
        done["fill_loop"] = (f"patched at {_f2va(blob, at):#x}, stub at {sva:#x}, "
                             f"bound {entries:#x} on {_REG[reg]}")
    elif _FILL_FIXED.search(bytes(blob)):
        done["fill_loop"] = "already patched"
    else:
        raise NeedleFixError(
            "no fill-loop guard found. This race.bin is not a build this "
            "patch understands.")

    if len(blob) != backup.stat().st_size and not backup.exists():
        raise NeedleFixError("internal error: patch changed the file size")
    f.write_bytes(bytes(blob))
    return done


def revert(data_dir: str | Path) -> None:
    """Both patches overwrite the render-target address they would need to undo
    themselves, so reverting means restoring the backup."""
    raise NeedleFixError(
        "revert needs the original render-target operands, which the patch "
        "overwrote -- restore race.bin.needle-backup instead")
