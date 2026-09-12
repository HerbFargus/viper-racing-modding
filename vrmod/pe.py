"""Turn a virtual address into a file offset, correctly.

WHY THIS EXISTS. An instruction that reads a constant names it by VIRTUAL
address -- `fmul dword [0x4c82f4]` -- and to read or write that constant you
need its FILE offset. The two differ, because a PE section's `PointerToRawData`
is not its `VirtualAddress`:

    race.bin   .rdata   rva 0x0c7000   raw 0x0c6200    off by -0xe00
    race.exe   .rdata   rva 0x0db000   raw 0x0d9a00    off by -0x1600

so `va - image_base` is the RVA, not the offset, and using it lands you a few
kilobytes past the thing you meant to touch -- still inside .rdata, so it reads
and writes without complaint and returns plausible-looking floats.

That is exactly how hornball's tuning went unnoticed: apply() and read() shared
the same wrong arithmetic, so the value read back was the value written and the
feature looked like it worked. The game, reading the real constant, saw stock
settings the whole time.

The conversion is per section and cheap. Anything needing it should use this
rather than assume a flat image.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

DEFAULT_IMAGE_BASE = 0x400000


@dataclass
class Section:
    name: str
    rva: int
    size: int            # max(virtual, raw) -- the span the RVA may fall in
    raw: int


def image_base(blob: bytes) -> int:
    """The PE's preferred load address, or the usual default if unreadable."""
    try:
        pe = struct.unpack_from("<I", blob, 0x3C)[0]
        return struct.unpack_from("<I", blob, pe + 24 + 28)[0]
    except Exception:
        return DEFAULT_IMAGE_BASE


def sections(blob: bytes) -> list[Section]:
    """Every section header, in file order."""
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    count = struct.unpack_from("<H", blob, pe + 6)[0]
    opt = struct.unpack_from("<H", blob, pe + 20)[0]
    start = pe + 24 + opt
    out = []
    for i in range(count):
        o = start + i * 40
        name = blob[o:o + 8].rstrip(b"\x00").decode("ascii", "replace")
        vsize = struct.unpack_from("<I", blob, o + 8)[0]
        rva, rawsize, raw = struct.unpack_from("<III", blob, o + 12)
        out.append(Section(name, rva, max(vsize, rawsize), raw))
    return out


def va_to_offset(blob: bytes, va: int) -> int | None:
    """File offset of a virtual address, or None if it falls outside every section."""
    rva = va - image_base(blob)
    for s in sections(blob):
        if s.rva <= rva < s.rva + s.size:
            off = s.raw + (rva - s.rva)
            return off if 0 <= off < len(blob) else None
    return None


def offset_to_va(blob: bytes, off: int) -> int | None:
    """The inverse: virtual address of a file offset, or None if unmapped."""
    base = image_base(blob)
    for s in sections(blob):
        if s.raw <= off < s.raw + s.size:
            return base + s.rva + (off - s.raw)
    return None
