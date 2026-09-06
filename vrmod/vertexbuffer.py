"""Raise the per-object vertex limit by resizing the engine's fixed vertex buffer.

THE MECHANISM (reverse-engineered 2026-09-05, confirmed in game). At startup the
engine allocates ONE vertex scratch buffer and keeps the pointer in a global:

    push  <size>            ; e.g. 0xEA600 = 960,000 on v1.2.5
    call  <malloc>
    mov   [<global>], eax

The per-object transform loop copies each of a mesh's vertices into that buffer at
`index * 32` bytes (32 = the .mod vertex-record stride), then draws the object with
IDirect3DDevice2::DrawIndexedPrimitive before the next object reuses the buffer. So
the buffer's capacity in vertices is `size / 32`, and a single mesh with more than
that many vertices writes past the end -> EXCEPTION_ACCESS_VIOLATION. Measured stock
capacities: **retail 1.1 = 1,000 verts** (32,000 B), **v1.2.5 = 30,000 verts**
(960,000 B) -- both LOWER than the community-quoted 1,200 / 20,000. Because the
buffer is reused per object, this is a per-single-mesh cap; enlarging it costs a
flat one-time (new_size - old_size) bytes of RAM regardless of how many cars race,
and rendering is per-object immediate mode so there is no scene-wide buffer that
many cars could overflow (§5.2.4).

The int16 face-index format cap (§4.1) means no more than 32,768 vertices can ever
be addressed, so that is the useful ceiling.

LOCATED BY PATTERN, not offset: the sole `push imm32` whose immediate is a multiple
of 32 in a plausible vertex-count range and which is immediately followed by
`call rel32 ; mov [glob], eax` (the malloc-and-store). Verified to match exactly one
site on both retail 1.1 (0x44f57a) and v1.2.5 (0x45031a).
"""
from __future__ import annotations

import struct
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

RACE_BIN = "race.bin"
STRIDE = 32                       # bytes per .mod vertex record
FORMAT_CAP_VERTS = 32768          # int16 face indices address at most 32,767; 32,768 covers it
_MIN_VERTS, _MAX_VERTS = 1000, 60000   # plausible stock buffer range, in vertices

_MD = Cs(CS_ARCH_X86, CS_MODE_32)


class PatchError(RuntimeError):
    """The buffer allocation can't be found, or the request is out of range."""


def _sections(blob: bytes):
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    optsz = struct.unpack_from("<H", blob, pe + 20)[0]
    nsec = struct.unpack_from("<H", blob, pe + 6)[0]
    off = pe + 24 + optsz
    out = []
    for i in range(nsec):
        s = blob[off + i * 40:off + (i + 1) * 40]
        _, va, rs, rp = struct.unpack_from("<IIII", s, 8)
        out.append((0x400000 + va, rp, rs))
    return out


def _f2va(secs, o):
    for va, rp, rs in secs:
        if rp <= o < rp + rs:
            return va + (o - rp)
    return None


def find_site(blob: bytes) -> dict:
    """Locate the vertex-buffer allocation. Returns {off, va, size, verts, glob}.

    Raises PatchError unless exactly one site matches the malloc-and-store shape.
    """
    secs = _sections(blob)
    hits = []
    i = 0
    while True:
        j = blob.find(b"\x68", i)
        if j < 0 or j + 5 > len(blob):
            break
        i = j + 1
        imm = struct.unpack_from("<I", blob, j + 1)[0]
        if imm % STRIDE or not (_MIN_VERTS <= imm // STRIDE <= _MAX_VERTS):
            continue
        va = _f2va(secs, j)
        if va is None:
            continue
        insns = list(_MD.disasm(blob[j:j + 40], va))
        if not insns or insns[0].mnemonic != "push":
            continue
        # the first thing after the push must be the malloc call (nothing may touch esp)
        call_idx = None
        for k in range(1, len(insns)):
            m = insns[k]
            if m.mnemonic == "call" and m.op_str.startswith("0x"):
                call_idx = k
                break
            if m.mnemonic in ("push", "pop", "ret") or (
                    m.mnemonic in ("add", "sub") and m.op_str.startswith("esp")):
                break
        if call_idx is None:
            continue
        # and within the next few insns, the returned pointer is stored to a global
        glob = None
        for m in insns[call_idx + 1:call_idx + 4]:
            if (m.mnemonic == "mov" and m.op_str.startswith("dword ptr [0x")
                    and m.op_str.endswith(", eax")):
                glob = int(m.op_str.split("[")[1].split("]")[0], 16)
                break
        if glob is None:
            continue
        hits.append({"off": j, "va": va, "size": imm, "verts": imm // STRIDE, "glob": glob})
    if len(hits) != 1:
        raise PatchError(
            f"expected exactly one vertex-buffer allocation, found {len(hits)}. "
            "This race.bin is not a build this patch understands.")
    return hits[0]


def buffer_verts(data_dir: str | Path) -> int:
    """Current per-object vertex capacity of the Data folder's race.bin."""
    return find_site((Path(data_dir) / RACE_BIN).read_bytes())["verts"]


def status(data_dir: str | Path) -> str:
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        return "missing"
    try:
        info = find_site(f.read_bytes())
    except PatchError:
        return "unknown"
    return f"{info['verts']:,} verts/object (buffer {info['size']:,} B)"


def apply(data_dir: str | Path, verts: int = FORMAT_CAP_VERTS) -> dict:
    """Resize the vertex buffer to hold `verts` vertices, in place.

    Returns {at, old_verts, new_verts, glob}. Rewrites one push-imm32; the file
    length is unchanged. Values above the int16 format cap (32,768) are pointless
    because faces cannot address them, so they are rejected.
    """
    if verts < _MIN_VERTS:
        raise PatchError(f"{verts} is below the smallest stock buffer; refusing")
    if verts > FORMAT_CAP_VERTS:
        raise PatchError(
            f"{verts} exceeds the int16 face-index cap ({FORMAT_CAP_VERTS}); faces "
            f"cannot address that many vertices")
    f = Path(data_dir) / RACE_BIN
    blob = bytearray(f.read_bytes())
    info = find_site(bytes(blob))
    old = info["verts"]
    struct.pack_into("<I", blob, info["off"] + 1, verts * STRIDE)
    f.write_bytes(bytes(blob))
    return {"at": info["off"], "old_verts": old, "new_verts": verts, "glob": info["glob"]}
