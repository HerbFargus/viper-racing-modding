"""Give race.bin's crash handler symbol names, by appending a map to the binary.

WHY THIS WORKS. The crash handler prints raw addresses and the line
`No mapfile present`, and it looks for that map in an unusual place: it opens
its OWN module file (`GetModuleFileName` then `CreateFile`), memory-maps it,
walks the PE section headers to find where the last section ends, and treats
everything AFTER that as the map. Stock race.bin is exactly 1,300,480 bytes and
its last section ends at exactly 1,300,480 -- zero trailing bytes, hence the
message. Append text there and the handler starts using it.

THE FORMAT is an MSVC 4.0 .map public-symbols line, parsed with

    sscanf(line, " 0001:%x %s %x", &section_offset, name, &address)

requiring all three conversions to match. Parsing stops at a line containing
`FIXUPS`. For each address in the stack trace the handler keeps the symbol with
the largest address still below it -- the nearest preceding one -- and prints

    trace: byte 0x%x of "%s"

so a small byte offset means the address really is inside that function, and a
huge one means the address landed in a region this map does not cover.

WHAT WE CAN NAME. There is no symbol table to recover, so function starts are
inferred: every target of a direct `call rel32` inside .text is an entry point.
That finds the great majority of real functions and never invents one that is
not called. They are named `sub_<va>`; a handful whose purpose was established
by reverse engineering are given real names, located BY PATTERN so they work on
both the retail and community builds, whose layouts differ.

SAFETY. Appending changes the file size but touches no byte of the image, so
the loader, every section, and every patch site are unaffected. `remove()`
truncates back to the end of the last section, which is exactly the original
file. A backup is written the first time regardless.
"""
from __future__ import annotations

import re
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

RACE_BIN = "race.bin"
TEXT_SECTION = 1                 # .text is section 1 in every build seen
END_MARKER = "FIXUPS"            # the handler stops parsing here


class MapError(RuntimeError):
    """The binary can't be read, or already carries trailing data."""


@dataclass
class Layout:
    image_base: int
    text_va: int                 # virtual address of .text
    text_raw: int                # file offset of .text
    text_size: int
    image_end: int               # file offset one past the last section

    def f2va(self, off: int) -> int:
        return self.text_va + (off - self.text_raw)


def _layout(blob: bytes) -> Layout:
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    nsec = struct.unpack_from("<H", blob, pe + 6)[0]
    optsz = struct.unpack_from("<H", blob, pe + 20)[0]
    base = struct.unpack_from("<I", blob, pe + 24 + 28)[0]
    off = pe + 24 + optsz
    text = None
    end = 0
    for i in range(nsec):
        s = blob[off + i * 40: off + (i + 1) * 40]
        name = s[:8].rstrip(b"\x00").decode("ascii", "replace")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", s, 8)
        end = max(end, rawptr + rawsize)
        if name == ".text":
            text = (base + vaddr, rawptr, min(vsize, rawsize))
    if text is None:
        raise MapError("no .text section -- not a race.bin")
    return Layout(base, text[0], text[1], text[2], end)


# --------------------------------------------------------------------------
# naming what we actually understand
# --------------------------------------------------------------------------

# Patterns that identify a specific routine in any build. Each maps a regex over
# the whole file to the offset (within the match) of the function's first byte,
# so the same table works on retail 1.1 and the community v1.2.5 despite their
# different layouts. Keep these anchored on instruction sequences that are
# distinctive, not on addresses.
_KNOWN: list[tuple[str, re.Pattern, int]] = [
    # add dword [esp+4], 0x96000 / cmp dword [esp+4], 0x1e8480 -- the VRAM check
    ("vram_check_tier", re.compile(rb"(?:\x81\x44\x24\x04\x00\x60\x09\x00|\x90{8})\x81\x7c\x24\x04\x80\x84\x1e\x00", re.S), 0),
    # the stamp draw's tacho call site: push 0/mov eax,[h]/push 0/sub eax,imm/push eax/mov ecx,[rpm]/push 0x10
    ("hud_draw_tacho_site", re.compile(rb"\x6a\x00\xa1....\x6a\x00\x2d....\x50\x8b\x0d....\x6a\x10\x51\xe8", re.S), 0),
    # clip-rect reset: [ecx+0x14]=0, [ecx+0x18]=0, [ecx+0x1c]=[ecx+8], [ecx+0x20]=[ecx+0xc]
    ("surface_reset_clip", re.compile(rb"\x8b\x4c\x24\x04\x33\xc0\x8b\x51\x08\x89\x41\x14\x89\x41\x18\x89\x51\x1c", re.S), 0),
    # set_viewport: stores left/top/width/height then halves each for the projection centre
    ("set_viewport", re.compile(rb"\x8b\x4c\x24\x04\x53\x56\x89\x0d....\x8b\x74\x24\x10", re.S), 0),
]


def _known_names(blob: bytes, lay: Layout) -> dict[int, str]:
    out: dict[int, str] = {}
    for name, pat, delta in _KNOWN:
        hits = [m.start() + delta for m in pat.finditer(blob)]
        if len(hits) == 1:
            off = hits[0]
            if lay.text_raw <= off < lay.text_raw + lay.text_size:
                out[lay.f2va(off)] = name
    return out


def entry_points(blob: bytes, lay: Layout) -> set[int]:
    """Every target of a direct `call rel32` that lands inside .text.

    Call targets are function starts by construction, which is why this is used
    instead of scanning for prologues: it cannot invent a function that nothing
    calls, and it does not care what the prologue looks like.
    """
    out: set[int] = set()
    lo, hi = lay.text_raw, lay.text_raw + lay.text_size
    for i in range(lo, hi - 5):
        if blob[i] != 0xE8:
            continue
        rel = struct.unpack_from("<i", blob, i + 1)[0]
        target = lay.f2va(i) + 5 + rel
        if lay.text_va <= target < lay.text_va + lay.text_size:
            out.add(target)
    return out


def build(blob: bytes) -> str:
    """The map text for a race.bin image."""
    lay = _layout(blob)
    named = _known_names(blob, lay)
    addrs = sorted(entry_points(blob, lay) | set(named))
    lines = [
        " race.bin",
        "",
        f" Preferred load address is {lay.image_base:08x}",
        "",
        "  Address         Publics by Value              Rva+Base",
        "",
    ]
    for va in addrs:
        name = named.get(va) or f"sub_{va:08x}"
        lines.append(f" 0001:{va - lay.text_va:08x}       {name:<34} {va:08x}")
    lines += ["", f" {END_MARKER}", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# install / remove
# --------------------------------------------------------------------------

def _race_bin(data_dir: str | Path) -> Path:
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        raise MapError(f"no {RACE_BIN} in {data_dir}")
    return f


def status(data_dir: str | Path) -> tuple[int, int, int]:
    """(file size, end of last section, trailing bytes)."""
    f = _race_bin(data_dir)
    blob = f.read_bytes()
    lay = _layout(blob)
    return len(blob), lay.image_end, len(blob) - lay.image_end


def install(data_dir: str | Path) -> tuple[int, int]:
    """Append a generated map. Returns (symbol count, bytes appended).

    Refuses if the file already has trailing data, so a second run cannot
    append a second map after the first -- the parser would read both and the
    result would be meaningless.
    """
    f = _race_bin(data_dir)
    blob = f.read_bytes()
    lay = _layout(blob)
    trailing = len(blob) - lay.image_end
    if trailing:
        raise MapError(
            f"{f.name} already has {trailing:,} trailing bytes; refusing to append "
            "a second map. Run remove() first.")

    text = build(blob)
    backup = f.with_suffix(f.suffix + ".map-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    f.write_bytes(blob + text.encode("ascii"))
    return text.count("\n 0001:"), len(text)


def remove(data_dir: str | Path) -> int:
    """Truncate back to the end of the last section. Returns bytes removed."""
    f = _race_bin(data_dir)
    blob = f.read_bytes()
    lay = _layout(blob)
    trailing = len(blob) - lay.image_end
    if trailing:
        f.write_bytes(blob[:lay.image_end])
    return trailing


def lookup(blob_or_dir, address: int) -> tuple[str, int] | None:
    """Resolve an address the way the game does: nearest preceding symbol.

    Useful for reading a crash log without restarting the game.
    """
    p = Path(blob_or_dir)
    blob = (p / RACE_BIN).read_bytes() if p.is_dir() else p.read_bytes()
    lay = _layout(blob)
    named = _known_names(blob, lay)
    best = None
    for va in entry_points(blob, lay) | set(named):
        if va <= address and (best is None or va > best):
            best = va
    if best is None:
        return None
    return named.get(best) or f"sub_{best:08x}", address - best
