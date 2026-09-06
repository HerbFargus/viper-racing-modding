"""STMP -- .stp "stamp" images: all UI art, track-select screenshots, track
maps, cursors and multi-frame button strips.

READ + WRITE. The uncompressed variant is fully mapped: parse() decodes it
and build() re-encodes it BYTE-EXACTLY -- verified on all 96 uncompressed
stamps on the disc. A second, compressed variant (115 further stamps,
including every Trackmap.stp) shares the header and palettes but packs its
rows differently; parse() rejects those rather than guessing.

    payload +0    int32 width
    payload +4    int32 height         (per FRAME, not the whole strip)
    payload +8    int32 hotspot X      (cursors; 0 otherwise)
    payload +12   int32 hotspot Y
    payload +16   int32 frame count    (frames stack VERTICALLY)
    payload +20   256 x int16  RGB555 palette
    payload +532  256 x int16  RGB565 palette -- the same colours again for
                  the other 16-bit display mode of the era; either decodes.
    payload +1044 1024 zero bytes, then an 8-byte tail: int32 row count and
                  a float whose meaning is unidentified (1.0 on some UI art,
                  0.078 on others, 0.0 on every track screenshot).
    payload +2076 rows x int32 row offsets, each simply i * row_stride(width)
    then          rows x row_stride(width) bytes of row data

Because every field is fixed-size, the whole payload length is determined by
(width, height, frames) -- which gives an exact predicate for "is this the
uncompressed variant", and parse() uses it. A lower-bound check is not enough:
compressed stamps of roughly the right size sail through one and then decode
to convincing-looking garbage.

Row data is an RLE stream, not raw indices. Every offset that is a multiple
of 128 holds a CONTROL byte, and the uncompressed variant only ever emits
literal runs, `0x80 | n` meaning "n literal indices follow". So each 128-byte
block carries one control byte and up to 127 indices:

    row_stride(w)   = w + ceil(w / 127)
    index_offset(k) = (k // 127) * 128 + 1 + (k % 127)

Three traps here, all of which produce plausible-looking output:

  * The pixel block is anchored to the END of the payload, so its start is
    computed backwards from the file size.
  * Missing the control byte at offset 0 shifts every row by one, which looks
    almost right -- only column 0 and the last few columns are wrong.
  * Missing the later control bytes leaves a bright vertical stripe at column
    127 while everything else looks perfect, and barely moves a mean-error
    metric (10.5 vs 4.5 on a 0-765 scale). It was caught by eye, not by
    measurement.

And one that only shows on wide art: computing the index offset as
`k + 1 + (k + 1) // 128` agrees for the first two blocks and then drifts,
placing index 254 on a control position. Nothing narrower than 255 pixels can
expose it, so 180-wide track screenshots decoded correctly while 320- and
640-wide UI art was subtly wrong.

Historical note: an earlier attempt at this format failed and was written
off as unsolvable. The real culprit was that the reference .tga files were
being read upside down -- Stp2Tga writes rows top-down but sets the TGA
descriptor byte to 0x00, which nominally means bottom-up origin. Honouring
that descriptor flips the image and destroys any index->colour correlation.
Trust the pixels, not the descriptor.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from . import envelope

# On-disk tags are stored reversed, same convention as .grf's FARG/GRAF.
TAG = b"PMTS"

HEADER_SIZE = 20
PALETTE_ENTRIES = 256
PALETTE555_OFFSET = 20
PALETTE565_OFFSET = 532
# Scanlines carry a pad byte at every row-stream offset that is a multiple of
# BLOCK (0, 128, 256, ...), so index k sits at k + 1 + (k+1)//BLOCK and a row
# occupies width + 1 + width//BLOCK bytes.
BLOCK = 128
# RLE control byte: 0x80 | n means "n literal indices follow".
LITERAL_RUN = 0x80


# Each 128-byte block of the row stream is one control byte plus up to
# INDICES_PER_BLOCK literal indices.
INDICES_PER_BLOCK = BLOCK - 1


def row_stride(width: int) -> int:
    blocks = -(-width // INDICES_PER_BLOCK)      # ceil
    return width + blocks


def index_offset(k: int) -> int:
    """Byte offset of column k within its row.

    Control bytes sit at every offset that is a multiple of 128, so indices
    are laid out 127 per block. An earlier version computed this as
    `k + 1 + (k + 1) // 128`, which agrees for the first two blocks and then
    drifts: it puts index 254 at offset 256, which is a control position.
    Nothing narrower than 255 pixels could expose that, so the track
    screenshots (180 wide) were unaffected while wider art decoded subtly
    wrong.
    """
    return (k // INDICES_PER_BLOCK) * BLOCK + 1 + (k % INDICES_PER_BLOCK)


@dataclass
class Stamp:
    width: int
    height: int          # per frame
    frames: int
    hotspot: tuple[int, int]
    pixels: bytes        # RGB888, width x (height*frames), top-down
    # Kept so a decoded stamp can be re-encoded byte-exactly: quantising the
    # RGB back down would not reproduce the original palette or index choices.
    palette555: list = None
    palette565: list = None
    indices: list = None   # one bytes object per row, width long
    # Last 8 bytes of the reserved block: int32 row count, then a float whose
    # meaning is unidentified (1.0 on some UI art, 0.078 on others, and 0 on
    # every track screenshot). Carried through so a re-encode is byte-exact.
    reserved_tail: bytes = None

    @property
    def total_height(self) -> int:
        return self.height * self.frames


def _expand555(v: int) -> tuple[int, int, int]:
    # 5-bit -> 8-bit by left shift, matching the reference converter (it
    # yields 248 for full white, not 255).
    return ((v >> 10) & 31) << 3, ((v >> 5) & 31) << 3, (v & 31) << 3


RESERVED_SIZE = 1032
# The reserved block is 1024 zero bytes followed by an 8-byte tail.
RESERVED_TAIL_OFFSET = PALETTE565_OFFSET + PALETTE_ENTRIES * 2 + 1024
ROW_TABLE_OFFSET = PALETTE565_OFFSET + PALETTE_ENTRIES * 2 + RESERVED_SIZE


def parse(data: bytes) -> Stamp:
    """Decode a standalone .stp resource (0SER-enveloped, or the loose
    "!IGM"-prefixed form the game's Data folder uses for track screenshots)."""
    if data[:4] == b"!IGM":
        payload = data[4:]
    else:
        env = envelope.parse(data)
        if env.tag != TAG:
            raise ValueError(f"not a .stp: tag {env.tag!r}, expected {TAG!r}")
        payload = env.payload
    return parse_payload(payload)


def parse_payload(payload: bytes) -> Stamp:
    w, h, hx, hy, frames = struct.unpack_from("<5i", payload, 0)
    frames = max(frames, 1)
    if w <= 0 or h <= 0:
        raise ValueError(f"implausible stamp dimensions {w}x{h}")
    total_h = h * frames
    stride = row_stride(w)
    start = len(payload) - total_h * stride

    # Exact size predicate for the uncompressed variant. This must be an
    # equality, not a lower bound: a loose check lets compressed stamps of the
    # right rough size through, and they then decode to convincing-looking
    # garbage rather than raising. Every field is fixed-size, so the whole
    # payload length is determined by (width, height, frames).
    expected = (HEADER_SIZE + PALETTE_ENTRIES * 4 + RESERVED_SIZE
                + total_h * 4 + total_h * stride)
    if len(payload) != expected:
        raise ValueError(
            f"not the uncompressed .stp variant: {w}x{h}x{frames} implies a "
            f"{expected}-byte payload, got {len(payload)}"
        )

    pal = [
        _expand555(struct.unpack_from("<H", payload, PALETTE555_OFFSET + i * 2)[0])
        for i in range(PALETTE_ENTRIES)
    ]
    offsets = [index_offset(k) for k in range(w)]
    out = bytearray(w * total_h * 3)
    o = 0
    for y in range(total_h):
        base = start + y * stride
        for off in offsets:
            r, g, b = pal[payload[base + off]]
            out[o] = r; out[o + 1] = g; out[o + 2] = b
            o += 3
    return Stamp(
        width=w, height=h, frames=frames, hotspot=(hx, hy), pixels=bytes(out),
        palette555=[struct.unpack_from("<H", payload, PALETTE555_OFFSET + i * 2)[0]
                    for i in range(PALETTE_ENTRIES)],
        palette565=[struct.unpack_from("<H", payload, PALETTE565_OFFSET + i * 2)[0]
                    for i in range(PALETTE_ENTRIES)],
        indices=[bytes(payload[start + y * stride + o] for o in offsets)
                 for y in range(total_h)],
        reserved_tail=bytes(payload[RESERVED_TAIL_OFFSET:RESERVED_TAIL_OFFSET + 8]),
    )


def to_png(stamp: Stamp) -> bytes:
    """Encode a decoded stamp as a PNG (no image library needed)."""
    w, h = stamp.width, stamp.total_height
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += stamp.pixels[y * w * 3:(y + 1) * w * 3]

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def parse_file(path) -> Stamp:
    from pathlib import Path
    return parse(Path(path).read_bytes())


# Between the palettes and the row-offset table sits a fixed block of zeros:
# 1032 bytes on every uncompressed stamp regardless of size or frame count.
# Almost certainly a 256-entry int32 table (a 32-bit palette the game never
# populates) plus 8 bytes.
def build_payload(width: int, height: int, frames: int, hotspot: tuple[int, int],
                  palette555, palette565, index_rows, reserved_tail=None) -> bytes:
    """Assemble a .stp payload from an indexed image.

    `index_rows` is one bytes-like of `width` palette indices per row, top-down
    and `height * frames` long. Palettes are lists of 256 packed 16-bit values;
    pass the same colours in both formats so either display mode renders
    correctly (see the module docstring).
    """
    frames = max(frames, 1)
    rows = height * frames
    if len(index_rows) != rows:
        raise ValueError(f"expected {rows} index rows, got {len(index_rows)}")
    for i, row in enumerate(index_rows):
        if len(row) != width:
            raise ValueError(f"row {i} has {len(row)} indices, expected {width}")
    for name, pal in (("palette555", palette555), ("palette565", palette565)):
        if len(pal) != PALETTE_ENTRIES:
            raise ValueError(f"{name} must have {PALETTE_ENTRIES} entries, got {len(pal)}")

    stride = row_stride(width)
    out = bytearray()
    out += struct.pack("<5i", width, height, hotspot[0], hotspot[1], frames)
    for pal in (palette555, palette565):
        for v in pal:
            out += struct.pack("<H", v & 0xFFFF)
    # 1024 zeros, then the 8-byte tail: row count and that unidentified
    # float. Track screenshots carry 0.0 there, so that is the default for a
    # freshly built stamp.
    out += bytes(1024)
    out += reserved_tail if reserved_tail else struct.pack("<if", rows, 0.0)
    for y in range(rows):
        out += struct.pack("<i", y * stride)

    offsets = [index_offset(k) for k in range(width)]
    for row in index_rows:
        buf = bytearray(stride)
        for k, off in enumerate(offsets):
            buf[off] = row[k]
        # The bytes at stream offsets 0, 128, 256... are not padding: they are
        # RLE control bytes, and 0x80|n means "n literal indices follow". The
        # uncompressed variant is simply every run written as a maximal
        # literal, so each control byte carries however many indices fit
        # before the next control position (127, then the remainder).
        for pos in range(0, stride, BLOCK):
            buf[pos] = LITERAL_RUN | min(BLOCK - 1, stride - 1 - pos)
        out += buf
    return bytes(out)


def build(stamp: Stamp, version: int = 3) -> bytes:
    """Re-encode a Stamp as a standalone .stp resource.

    Requires the stamp to still carry its palettes and indices (as parse()
    leaves them). Round-trips stock files byte-for-byte.
    """
    if stamp.indices is None or stamp.palette555 is None or stamp.palette565 is None:
        raise ValueError("stamp has no indexed data; use build_from_rgb() instead")
    payload = build_payload(
        stamp.width, stamp.height, stamp.frames, stamp.hotspot,
        stamp.palette555, stamp.palette565, stamp.indices, stamp.reserved_tail,
    )
    return envelope.build(TAG, version, payload)


def _pack555(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)


def _pack565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def quantize(pixels: bytes, width: int, height: int):
    """Reduce RGB888 pixels to a 256-colour palette plus indices.

    Popularity-based on the 5-bit-per-channel grid the format stores anyway,
    so the quantisation step loses nothing the palette could have kept: colours
    are counted at 555 precision, the 256 most common become the palette, and
    anything else maps to the nearest of those. Good enough for the UI art and
    map/screenshot thumbnails this is used for, and it avoids pulling in an
    image library for a median-cut implementation.
    """
    counts: dict[tuple[int, int, int], int] = {}
    quant = []
    for i in range(width * height):
        r, g, b = pixels[i * 3] >> 3, pixels[i * 3 + 1] >> 3, pixels[i * 3 + 2] >> 3
        key = (r, g, b)
        quant.append(key)
        counts[key] = counts.get(key, 0) + 1

    palette = [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:PALETTE_ENTRIES]]
    while len(palette) < PALETTE_ENTRIES:
        palette.append((0, 0, 0))

    exact = {c: i for i, c in enumerate(palette)}
    cache: dict[tuple[int, int, int], int] = {}

    def nearest(c):
        hit = cache.get(c)
        if hit is not None:
            return hit
        best, best_d = 0, None
        for i, p in enumerate(palette):
            d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2
            if best_d is None or d < best_d:
                best, best_d = i, d
                if d == 0:
                    break
        cache[c] = best
        return best

    rows = []
    for y in range(height):
        row = bytearray(width)
        for x in range(width):
            c = quant[y * width + x]
            row[x] = exact.get(c) if c in exact else nearest(c)
        rows.append(bytes(row))

    pal555 = [_pack555(r << 3, g << 3, b << 3) for r, g, b in palette]
    pal565 = [_pack565(r << 3, g << 3, b << 3) for r, g, b in palette]
    return pal555, pal565, rows


def build_from_rgb(pixels: bytes, width: int, height: int, *, frames: int = 1,
                   hotspot: tuple[int, int] = (0, 0), version: int = 3) -> bytes:
    """Encode raw top-down RGB888 pixels as a standalone .stp resource."""
    pal555, pal565, rows = quantize(pixels, width, height)
    payload = build_payload(width, height // max(frames, 1), frames, hotspot,
                            pal555, pal565, rows)
    return envelope.build(TAG, version, payload)


def to_loose(data: bytes) -> bytes:
    """Convert a standalone .stp to the loose form the Data folder uses for
    add-on track screenshots: the 20-byte envelope truncated to its last 4
    bytes, so the file begins at "!IGM"."""
    if data[:4] == b"!IGM":
        return data
    return b"!IGM" + envelope.parse(data).payload
