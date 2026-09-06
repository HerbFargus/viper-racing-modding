"""
0SER resource envelope.

Every native Viper Racing binary resource opens with a 20-byte envelope:

    0x00  4   b"0SER"      magic
    0x04  4   tag           4-byte FourCC, byte-reversed on disk
    0x08  4   int32 version
    0x0C  4   reserved (always 0)
    0x10  4   b"!IGM"       marker
    0x14+ --  payload

The tag is byte-reversed on disk: a 4-character constant like 'MINF' declared in
C source is packed MSB-first into a 32-bit int, and lands on disk in reverse
order on little-endian x86 -- so ".mod" files carry the on-disk tag b"FNIM",
which reverses back to "MINF" (Mesh INFo).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"0SER"
MARKER = b"!IGM"
SIZE = 20


@dataclass
class Envelope:
    tag: bytes  # 4 bytes, as stored on disk (reversed FourCC)
    version: int
    payload: bytes

    @property
    def mnemonic(self) -> str:
        """Reverse the on-disk tag to recover the mnemonic (e.g. b"FNIM" -> "MINF")."""
        return self.tag[::-1].decode("ascii", errors="replace")


def parse(data: bytes) -> Envelope:
    if len(data) < SIZE:
        raise ValueError(f"too short for a 0SER envelope: {len(data)} bytes")
    if data[0:4] != MAGIC:
        raise ValueError(f"bad magic {data[0:4]!r}, expected {MAGIC!r}")
    tag = data[4:8]
    version = struct.unpack_from("<i", data, 8)[0]
    marker = data[16:20]
    if marker != MARKER:
        raise ValueError(f"bad marker {marker!r}, expected {MARKER!r}")
    return Envelope(tag=tag, version=version, payload=data[20:])


def build(tag: bytes, version: int, payload: bytes) -> bytes:
    if len(tag) != 4:
        raise ValueError(f"tag must be exactly 4 bytes, got {tag!r}")
    return MAGIC + tag + struct.pack("<i", version) + b"\x00\x00\x00\x00" + MARKER + payload
