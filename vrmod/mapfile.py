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

from . import safewrite

RACE_BIN = "race.bin"
TEXT_SECTION = 1                 # .text is section 1 in every build seen
END_MARKER = "FIXUPS"            # the handler stops parsing here

# Engine binaries, live one first -- the v1.0 pressing runs race.exe and ships a
# race.bin beside it that nothing loads, so a Data folder alone does not say
# which binary a crash came from. Same rule as vrampatch and doctor.
ENGINE_NAMES = ("race.exe", "race.bin")

# A public-symbols line in the MSVC 4.0 map the handler parses:
#     0001:000113a0       ?check_for_canary_launch@@YAEXZ 004123a0 f kernel:win32.obj
# Section offset, name, then the loaded address -- the third field is the one to
# resolve against, matching the handler's own sscanf.
_MAP_LINE = re.compile(r"\s*0001:([0-9a-fA-F]+)\s+(\S+)\s+([0-9a-fA-F]+)")


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
    """The engine binary this install runs -- see engine()."""
    return engine(data_dir)


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
    safewrite.write_atomic(f, blob + text.encode("ascii"))
    return text.count("\n 0001:"), len(text)


def remove(data_dir: str | Path) -> int:
    """Truncate OUR map back off. Returns bytes removed.

    Refuses to touch a map the build shipped with. The v1.0 race.exe carries its
    own linker map in exactly this position, and truncating there would throw
    away 10,000-odd real symbol names -- the thing that makes that build's crash
    logs readable -- to undo a patch we never applied.
    """
    f = _race_bin(data_dir)
    blob = f.read_bytes()
    lay = _layout(blob)
    trailing = len(blob) - lay.image_end
    if not trailing:
        return 0
    if not is_generated(blob):
        raise MapError(
            f"{f.name} carries {trailing:,} bytes of a map this tool did not "
            "append -- it shipped that way. Refusing to truncate it.")
    safewrite.write_atomic(f, blob[:lay.image_end])
    return trailing


def engine(data_dir: str | Path) -> Path:
    """The engine binary in a Data folder, preferring the one that actually runs."""
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise MapError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def read_map(blob: bytes) -> dict[int, str]:
    """Symbols from a map ALREADY present after the last section, {address: name}.

    Empty when the binary carries none. This is the real thing where it exists
    and is far better than what build() can reconstruct: the v1.0 `race.exe` is
    a Release Candidate that shipped with its own linker map appended -- 10,465
    genuine symbol names, against the `sub_<va>` placeholders inference gives.
    Parsed exactly as the handler does, stopping at FIXUPS.
    """
    lay = _layout(blob)
    tail = blob[lay.image_end:]
    if not tail:
        return {}
    out: dict[int, str] = {}
    for line in tail.decode("ascii", "replace").splitlines():
        if END_MARKER in line:
            break
        m = _MAP_LINE.match(line)
        if m:
            out[int(m.group(3), 16)] = m.group(2)
    return out


def is_generated(blob: bytes) -> bool:
    """Did WE append this map, or did the build ship with one?

    It matters because "has trailing data" is otherwise read as "we patched
    this". The v1.0 race.exe is a Release Candidate that shipped with its own
    linker map already appended, so a caller checking for trailing bytes
    concludes the binary is dirty and refuses to snapshot a perfectly untouched
    file.

    The discriminator is the naming. build() can only infer function starts from
    call targets, so almost every symbol it emits is `sub_<va>`; a real linker
    map names them. One `sub_` line is therefore ours, and a shipped map has
    none.
    """
    lay = _layout(blob)
    tail = blob[lay.image_end:]
    return b" sub_" in tail[:65536] if tail else False


def pretty(name: str) -> str:
    """A readable form of an MSVC-decorated name. NOT a demangler.

    `?my_handler@@YGJPAU_EXCEPTION_POINTERS@@@Z` -> `my_handler`. Just the
    identifier between the leading `?` and the first `@@`; anything that does
    not look decorated is returned unchanged, so `_WinMain@16` and `sub_004...`
    pass straight through.
    """
    if name.startswith("?") and "@@" in name:
        return name[1:name.index("@@")]
    return name


def symbols(blob_or_dir) -> tuple[dict[int, str], str]:
    """({address: name}, source). Prefers a real embedded map over inference."""
    p = Path(blob_or_dir)
    blob = engine(p).read_bytes() if p.is_dir() else p.read_bytes()
    real = read_map(blob)
    if real:
        return real, "embedded map"
    lay = _layout(blob)
    named = _known_names(blob, lay)
    out = {va: named.get(va) or f"sub_{va:08x}"
           for va in entry_points(blob, lay) | set(named)}
    return out, "inferred from call targets"


def lookup(blob_or_dir, address: int) -> tuple[str, int] | None:
    """Resolve an address the way the game does: nearest preceding symbol.

    Useful for reading a crash log without restarting the game. A binary that
    carries its own map is resolved against that; otherwise names are inferred.
    """
    syms, _ = symbols(blob_or_dir)
    best = None
    for va in syms:
        if va <= address and (best is None or va > best):
            best = va
    if best is None:
        return None
    return syms[best], address - best


# The handler's own dump format, e.g.
#     ( 00416049 , EXCEPTION_ACCESS_VIOLATION , ? )
#     ( 00411407, call-stack , ? )
_FRAME = re.compile(r"\(\s*([0-9a-fA-F]{6,8})\s*,\s*([^,]*?)\s*,")


def resolve_trace(text: str, blob_or_dir) -> list[tuple[int, str, str, int]]:
    """Symbolise an except.log. Returns [(address, kind, name, byte offset), ...].

    The handler writes `?` for every frame when the running binary has no map
    appended -- which is every build except the v1.0 RC. Reading the addresses
    back against the binary that produced them recovers the names it could not
    print at the time.

    A large byte offset means the address is not really inside the named
    function, so the map does not cover that region and the name is the nearest
    thing below rather than the truth.
    """
    syms, _ = symbols(blob_or_dir)
    ordered = sorted(syms)
    out = []
    for m in _FRAME.finditer(text):
        addr = int(m.group(1), 16)
        best = None
        for va in ordered:
            if va <= addr:
                best = va
            else:
                break
        if best is None:
            out.append((addr, m.group(2), "?", 0))
        else:
            out.append((addr, m.group(2), syms[best], addr - best))
    return out
