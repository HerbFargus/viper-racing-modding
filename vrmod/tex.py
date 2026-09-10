"""
.tex texture decoding and encoding (base/full-resolution mip level only).

Header (0SER payload, offsets relative to start of payload i.e. after the
20-byte envelope from envelope.py -- these are the technical reference's
full-file offsets 0x14-0x24 minus 0x14):

    0x00  byte   flags: bit0=colorkey transparency, bit1=full alpha channel
    0x01  byte   1 for a texture drawn on 3D geometry, 0 for sky and 2D
                  overlays. Surveying every texture in a full install splits
                  cleanly: of 880, the only ones carrying 0 are sky1-4 across
                  every track plus uptown's 2dtele.tex and oo1-4.tex. Every
                  road, kerb, grass and prop texture carries 1. It is not about
                  mipmapping -- both groups ship full mip chains. Written as 0
                  here originally, which leaves an imported track's surfaces
                  rendering as flat untextured colour.
    0x02  byte   (unconfirmed)
    0x03  byte   wrap flag (tileable vs. decal)
    0x04  int32  for colorkey/alpha textures: the 1x1 mip level's own pixel
                  value (same encoding as the base level -- RGB565 or
                  ARGB4444), duplicated (same value as the 0x0C field below);
                  0 for plain opaque textures.
    0x08  int32  mip level count
    0x0C  int32  duplicate of the 1x1 mip level's pixel value (see 0x04)
    0x10+ padding, then mip chain -- see MIP CHAIN LAYOUT below

There is no separate width/height field. The reference doc's earlier "packed
int16 w,h at this offset" hypothesis was a coincidental fit for a square
256x256 sample -- those same bytes are individually meaningful (flags/wrap),
confirmed against a real asph.tex where flags=0 (opaque, matches its
alpha-less reference .tga) and wrap=1 (tileable, matches asphalt being a
repeating road surface). Width/height aren't needed anyway: every sampled
texture is square and power-of-two, and mip_count alone gives the base size
via `2 ** (mip_count - 1)` (mip_count=9 -> 256, matching floor(log2(w))+1
confirmed in the reference doc).

MIP CHAIN LAYOUT

Not simply "smallest mip first, tightly packed, largest last" -- there's a
consistent 50-byte gap between where that naive model puts the base level and
where it actually is, confirmed identical (exactly 50, regardless of image
size) across four samples from 8x8 to 256x256. Solved by inspecting a small
(8x8) synthetic test file byte-for-byte: the real layout is

    [0x00:0x1C]  28 bytes, always zero in every sample -- reserved/unused.
                 The 1x1 mip level is NOT stored here or anywhere else in the
                 chain; its only storage is the duplicated header fields
                 above (payload offsets 0x04 and 0x0C).
    [0x1C:0x3C]  the 2x2 mip level, but padded into a 4x4-sized slot (32
                 bytes): the 4 real pixels occupy the top-left 2x2 of what
                 would be a 4x4 image, row-stride 4 pixels, with the other
                 12 pixel slots zero-filled.
    [0x3C:...]   every level from 4x4 up to (but not including) the base
                 level, tight-packed (no padding), in ascending size order.
    [...:end]    the base (full-resolution) level, tight-packed, LAST.

Algebraically this reconciles the "50-byte gap" exactly: the padded-2x2 slot
costs 32 bytes instead of the 8 a tight 2x2 would need (+24), the 28-byte
reserved block adds the rest (+24+28=52... the precise reconciliation is
28 + (32-8) = 52 minus the 2 bytes saved by NOT storing 1x1 at all = 50).
Verified against 256x256 (asph.tex), 128x128 (fang.tex), 64x64 (under.tex),
and a synthetic 8x8 file -- byte-for-byte identical predicted vs. actual
base-level offset in every case.

Only levels 8x8 and above have been round-trip verified in the ENCODE
direction (see encode_to_tex() below); the 4x4 and padded-2x2 slots are
built the same way but not independently confirmed against a real encoder
output smaller than 8x8 at the base level (no such sample exists in the
retail data).

BASE LEVEL ENCODE: verified against the strongest available test -- encoding
asph.tga (itself derived from asph.tex) reproduces the exact same base-level
mip layout/offset as the real asph.tex, and decodes to pixel-for-pixel
IDENTICAL colors. It is not literally byte-identical: ~50% of raw 16-bit
samples differ from the real file by exactly bit 5 (the green field's
low/"don't care" bit that decode_base_level() already masks off). The real
encoder sets that bit via some rounding rule that was not reverse-engineered
-- since it provably has zero effect on the decoded color, it wasn't chased
further.

PIXEL FORMATS

Opaque (flags == 0x00): 16-bit little-endian RGB565, row-major, base level
LAST in the chain. Confirmed byte-exact (100% of 65,536 pixels, whole-file-
identical .tga output) against a real reference conversion of asph.tex:

    r8 = r5 << 3
    g8 = (g6 & 0x3E) << 2   -- note: the low bit of the 6-bit green field is
                               NOT used; green is effectively 5 significant
                               bits like red/blue, just packed in a 6-bit slot
    b8 = b5 << 3

Equivalently, g6 is always even -- i.e. green really is just a 5-bit value
(g8 >> 3) like red/blue, left-shifted one extra bit to sit in the 6-bit
field. That's what encode_to_tex() does in reverse:

    r5 = r8 >> 3;  g5 = g8 >> 3;  b5 = b8 >> 3
    v  = (r5 << 11) | (g5 << 6) | b5

Full alpha (flags bit1 set, i.e. 0x02 or 0x03): same 16-bit-per-pixel budget,
but packed as ARGB4444 instead of RGB565:

    a8 = a4 << 4;  r8 = r4 << 4;  g8 = g4 << 4;  b8 = b4 << 4
    -- encode: a4 = a8>>4, r4 = r8>>4, g4 = g8>>4, b4 = b8>>4

Confirmed by round-tripping a synthetic test image (solid color, a linear
8-step alpha ramp) through the real encoder tool (mktex.exe /a) and decoding
the result: every R/G/B nibble matched `channel8 >> 4` exactly, every A
nibble matched the input ramp exactly, and the whole mip chain -- including
the redundant 1x1-level value duplicated into the header -- downsamples by
consistent pairwise averaging at every level.

CAVEAT: that test produced flags=0x02 (bit1 only). Every real in-game alpha
texture sampled has flags=0x03 (both bits set) instead -- passing both /a and
/t to the real encoder didn't reproduce 0x03, it fell back to colorkey-only
(0x01) behavior and silently dropped the alpha switch. So it's UNCONFIRMED
whether real 0x03 textures are really ARGB4444 like the 0x02 test, or
something subtly different -- decoding several real 0x03 textures this way
produces clean, uncorrupted images (visual support, not byte-exact proof).
encode_to_tex() writes flags=0x03 for alpha output (matching real files) even
though only 0x02 was byte-exact confirmed; pass flags explicitly to override.

Colorkey-only (flags == 0x01, bit0 set / bit1 clear) is SOLVED: it's plain
RGB565, byte-for-byte identical to the opaque encoding, with exactly one
special case -- raw value 0x0000 is reserved as the "this pixel is
transparent" signal. Any real (opaque) pixel that would naturally quantize
to 0x0000 (i.e. any color with all three 5-bit channels at 0 -- not just
literal black, any color that rounds down to it, e.g. RGB (1,2,3)) gets
nudged to 0x0040 instead (the smallest possible perturbation: green's LSB)
so it doesn't collide with the transparency marker.

Confirmed cleanly: encoded a 16-color test image (a real mktex.exe /t
conversion) covering red/green/blue/white/black/gray/magenta/cyan/yellow and
several off-black near-zero colors, and diffed it pixel-for-pixel against a
plain (non-colorkey) encode of the identical image. All 16 pixels matched
exactly except the two that quantize to 0x0000 in the plain version, which
were both nudged to 0x0040 in the colorkey version -- 16/16 predicted vs.
actual. (An earlier, messier test that varied a source alpha channel instead
of RGB color produced a confusing, position-correlated pattern unrelated to
this rule -- likely /t behaves differently, or extra, when the source has an
alpha channel at all; not investigated further. Feed a plain 24-bit,
no-alpha source when encoding colorkey textures.)
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import envelope

HEADER_SIZE = 0x10  # size of the tex-specific header within the 0SER payload
RESERVED_BLOCK_SIZE = 0x1C  # 28 zero bytes at the start of the mip chain
PADDED_2X2_SLOT_SIZE = 32  # the 2x2 level, padded into a 4x4-pixel slot


@dataclass
class TexInfo:
    flags: int
    wrap: int
    mip_count: int
    pixel_data: bytes  # everything after the tex-specific header
    colorkey: int = 0  # header 0x04: the transparent pixel value, see decode_base_level()

    @property
    def has_alpha(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def has_colorkey(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def size(self) -> int:
        """Base level width/height (square, power-of-two), derived from mip_count."""
        return 2 ** (self.mip_count - 1)


# ---------------------------------------------------------------------------
# decoding: .tex -> pixels
# ---------------------------------------------------------------------------

def parse(data: bytes) -> TexInfo:
    """Parse a standalone .tex file's bytes (0SER envelope + tex payload)."""
    env = envelope.parse(data)
    if env.mnemonic != "TEX ":
        raise ValueError(f"not a .tex file (tag mnemonic {env.mnemonic!r})")
    payload = env.payload
    flags = payload[0x00]
    wrap = payload[0x03]
    mip_count = struct.unpack_from("<i", payload, 0x08)[0]
    return TexInfo(
        flags=flags,
        wrap=wrap,
        mip_count=mip_count,
        pixel_data=payload[HEADER_SIZE:],
        colorkey=struct.unpack_from("<i", payload, 0x04)[0] & 0xFFFF,
    )


def _base_level_offset(info: TexInfo) -> tuple[int, int]:
    w = h = info.size
    base_size = w * h * 2
    base_off = len(info.pixel_data) - base_size
    if base_off < 0:
        raise ValueError(
            f"pixel data ({len(info.pixel_data)} bytes) too small for a "
            f"{w}x{h} base level ({base_size} bytes)"
        )
    return base_off, w * h


def _decode_pixel_rgb(v: int) -> tuple[int, int, int]:
    r5 = (v >> 11) & 0x1F
    g6 = (v >> 5) & 0x3F
    b5 = v & 0x1F
    return r5 << 3, (g6 & 0x3E) << 2, b5 << 3


def _decode_pixel_rgba(v: int) -> tuple[int, int, int, int]:
    a4 = (v >> 12) & 0xF
    r4 = (v >> 8) & 0xF
    g4 = (v >> 4) & 0xF
    b4 = v & 0xF
    return r4 << 4, g4 << 4, b4 << 4, a4 << 4


def decode_base_level(info: TexInfo) -> bytes:
    """Decode the base (full-resolution) mip level to raw bytes, row-major.

    Returns RGBA8888 (4 bytes/pixel) for textures with the full-alpha flag
    set, or for colorkey-only textures (raw value 0x0000 decodes to alpha=0,
    everything else alpha=255 -- see module docstring). Returns RGB888
    (3 bytes/pixel) for plain opaque textures.
    """
    base_off, pixel_count = _base_level_offset(info)

    if info.has_alpha:
        out = bytearray(pixel_count * 4)
        for i in range(pixel_count):
            v = struct.unpack_from("<H", info.pixel_data, base_off + i * 2)[0]
            r, g, b, a = _decode_pixel_rgba(v)
            o = i * 4
            out[o], out[o + 1], out[o + 2], out[o + 3] = r, g, b, a
        return bytes(out)

    if info.has_colorkey:
        # The transparent value is the one stored in the header at 0x04, NOT
        # a hardcoded 0x0000. Confirmed across a real track's textures: for
        # colorkey files that field matches the image's dominant background
        # value exactly (3ter.tex 0x526A covering half the image, bnch.tex
        # 0x7B2A, fount.tex 0x8410, orange.tex 0x62A8, redwh.tex 0x6B6D).
        # Assuming 0x0000 left those backgrounds fully opaque, so every
        # cutout billboard -- trees, signs, fences -- rendered as a solid
        # rectangle. 0x0000 is still treated as transparent so files whose
        # key field is genuinely zero keep working.
        key = info.colorkey
        out = bytearray(pixel_count * 4)
        for i in range(pixel_count):
            v = struct.unpack_from("<H", info.pixel_data, base_off + i * 2)[0]
            o = i * 4
            if v == 0x0000 or v == key:
                out[o], out[o + 1], out[o + 2], out[o + 3] = 0, 0, 0, 0
            else:
                r, g, b = _decode_pixel_rgb(v)
                out[o], out[o + 1], out[o + 2], out[o + 3] = r, g, b, 255
        return bytes(out)

    out = bytearray(pixel_count * 3)
    for i in range(pixel_count):
        v = struct.unpack_from("<H", info.pixel_data, base_off + i * 2)[0]
        r, g, b = _decode_pixel_rgb(v)
        o = i * 3
        out[o], out[o + 1], out[o + 2] = r, g, b
    return bytes(out)


# ---------------------------------------------------------------------------
# TGA read/write
# ---------------------------------------------------------------------------

TGA_FOOTER = b"\x00\x00\x00\x00" + b"TRUEVISION-XFILE." + b"\x00\x00\x00"


def read_tga(path: Path | str) -> tuple[bytes, int, int]:
    """Read an uncompressed 24- or 32-bit TGA. Returns (RGB(A) bytes, width, height)."""
    return read_tga_bytes(Path(path).read_bytes())


def read_tga_bytes(data: bytes) -> tuple[bytes, int, int]:
    """Same as read_tga(), for TGA bytes already in memory (e.g. received over the
    shell's local commit endpoint) rather than a file on disk."""
    id_len, cmap_type, img_type = data[0], data[1], data[2]
    if cmap_type != 0 or img_type != 2:
        raise ValueError("only uncompressed truecolor TGA (no color map) is supported")
    width, height = struct.unpack_from("<2H", data, 12)
    depth = data[16]
    desc = data[17]
    if depth not in (24, 32):
        raise ValueError(f"unsupported bit depth {depth}")
    channels = depth // 8
    # NOTE: descriptor bit 4 ("right-to-left") is deliberately ignored here.
    # It's set (0x30, not just 0x20) on real reference .tga output, but
    # empirically the pixels are NOT actually right-to-left -- a plain,
    # unflipped row-major read was independently verified byte-exact against
    # the corresponding .tex's pixel data. Treat bit 4 as unreliable/unused
    # in practice, matching that earlier validated ground truth.
    top_to_bottom = bool(desc & 0x20)

    off = 18 + id_len
    raw = data[off:off + width * height * channels]

    rows = [raw[y * width * channels:(y + 1) * width * channels] for y in range(height)]
    if not top_to_bottom:
        rows.reverse()

    bgr = b"".join(rows)
    out = bytearray(len(bgr))
    out[0::channels] = bgr[2::channels]
    out[1::channels] = bgr[1::channels]
    out[2::channels] = bgr[0::channels]
    if channels == 4:
        out[3::channels] = bgr[3::channels]
    return bytes(out), width, height


def write_tga(pixels: bytes, width: int, height: int, path: Path | str) -> None:
    """Write raw row-major RGB888 or RGBA8888 bytes as an uncompressed TGA.

    Depth (24 vs 32-bit) is inferred from len(pixels). Opaque (24-bit) output
    matches a real reference conversion of asph.tex byte-for-byte, including
    the descriptor byte (0x30) and the optional TGA 2.0 footer.
    """
    channels = len(pixels) // (width * height)
    if channels not in (3, 4):
        raise ValueError(f"expected 3 or 4 bytes/pixel, got {channels}")
    depth = channels * 8

    header = struct.pack(
        "<BBBHHBHHHHBB",
        0, 0, 2, 0, 0, 0, 0, 0,
        width, height, depth,
        0x30 if channels == 3 else 0x28,  # image descriptor (0x28: top-to-bottom, 8-bit alpha)
    )
    out = bytearray(len(pixels))  # TGA stores B,G,R[,A] per pixel
    out[0::channels] = pixels[2::channels]
    out[1::channels] = pixels[1::channels]
    out[2::channels] = pixels[0::channels]
    if channels == 4:
        out[3::channels] = pixels[3::channels]
    footer = TGA_FOOTER if channels == 3 else b""
    Path(path).write_bytes(header + bytes(out) + footer)


def tex_to_tga(tex_path: Path | str, tga_path: Path | str) -> None:
    data = Path(tex_path).read_bytes()
    info = parse(data)
    pixels = decode_base_level(info)
    write_tga(pixels, info.size, info.size, tga_path)


def encode_png(pixels: bytes, width: int, height: int) -> bytes:
    """Encode raw row-major RGB888 or RGBA8888 bytes (top-to-bottom, left-to-right --
    decode_base_level()'s own output order, verified byte-exact against a real
    reference conversion) as a PNG. No external imaging library available in this
    environment, so this builds the file directly: IHDR + one zlib-compressed IDAT
    (filter type 0/None per scanline) + IEND, per the PNG spec."""
    channels = len(pixels) // (width * height)
    if channels not in (3, 4):
        raise ValueError(f"expected 3 or 4 bytes/pixel, got {channels}")
    color_type = 2 if channels == 3 else 6

    raw = bytearray()
    stride = width * channels
    for y in range(height):
        raw.append(0)  # filter type 0 (None) for this scanline
        raw += pixels[y * stride: (y + 1) * stride]
    compressed = zlib.compress(bytes(raw), level=9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def tex_to_png_bytes(tex_bytes: bytes) -> bytes:
    info = parse(tex_bytes)
    pixels = decode_base_level(info)
    return encode_png(pixels, info.size, info.size)


# ---------------------------------------------------------------------------
# encoding: pixels -> .tex
# ---------------------------------------------------------------------------

def _build_mip_chain(pixels: bytes, size: int, channels: int) -> list[list[tuple[int, ...]]]:
    """Box-filter downsample from `size`x`size` down to 1x1.

    Returns a list of levels, index 0 = the base (full-res) level, each a
    flat row-major list of (r,g,b[,a]) tuples. Averaging (not confirmed
    against a real encoder for anything below the 8x8 level -- see module
    docstring) uses simple integer mean, rounding down.
    """
    level = [
        tuple(pixels[i * channels:(i + 1) * channels]) for i in range(size * size)
    ]
    levels = [level]
    s = size
    while s > 1:
        prev = levels[-1]
        s //= 2
        nxt = []
        for y in range(s):
            for x in range(s):
                px00 = prev[(2 * y) * (s * 2) + (2 * x)]
                px01 = prev[(2 * y) * (s * 2) + (2 * x + 1)]
                px10 = prev[(2 * y + 1) * (s * 2) + (2 * x)]
                px11 = prev[(2 * y + 1) * (s * 2) + (2 * x + 1)]
                nxt.append(tuple(
                    (px00[c] + px01[c] + px10[c] + px11[c]) // 4 for c in range(channels)
                ))
        levels.append(nxt)
    return levels  # levels[0]=base ... levels[-1]=1x1


def _encode_pixel_rgb(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    r5, g5, b5 = r >> 3, g >> 3, b >> 3
    return (r5 << 11) | (g5 << 6) | b5


def _encode_pixel_rgba(rgba: tuple[int, int, int, int]) -> int:
    r, g, b, a = rgba
    a4, r4, g4, b4 = a >> 4, r >> 4, g >> 4, b >> 4
    return (a4 << 12) | (r4 << 8) | (g4 << 4) | b4


def _encode_pixel_colorkey(rgba: tuple[int, int, int, int]) -> int:
    r, g, b, a = rgba
    if a < 128:
        return 0x0000
    v = _encode_pixel_rgb((r, g, b))
    return 0x0040 if v == 0x0000 else v  # avoid colliding with the transparency marker


_MODES = {
    # mode: (channels, flags, pixel encoder)
    "opaque": (3, 0x00, _encode_pixel_rgb),
    "alpha": (4, 0x03, _encode_pixel_rgba),
    "colorkey": (4, 0x01, _encode_pixel_colorkey),
}


def resize_nearest(pixels: bytes, width: int, height: int,
                   target_w: int, target_h: int, channels: int = 3) -> bytes:
    """Nearest-neighbour resize of raw row-major pixel bytes.

    Exists so an imported image can be fitted to the size the game already
    expects. Nearest keeps this dependency-free; for the sizes involved --
    usually halving a 512 to 256 -- the difference from a filtered resize is
    not worth an imaging library, and a texture that loads beats a slightly
    sharper one that crashes.
    """
    if (width, height) == (target_w, target_h):
        return pixels
    out = bytearray(target_w * target_h * channels)
    for y in range(target_h):
        sy = min(height - 1, y * height // target_h)
        row = sy * width * channels
        for x in range(target_w):
            sx = min(width - 1, x * width // target_w)
            o, i = (y * target_w + x) * channels, row + sx * channels
            out[o:o + channels] = pixels[i:i + channels]
    return bytes(out)


def encode_to_tex(
    pixels: bytes,
    size: int,
    *,
    mode: str,
    wrap: int = 0,
    flags: int | None = None,
    on_geometry: bool = True,
) -> bytes:
    """Encode raw row-major pixel bytes into a standalone .tex file's bytes
    (0SER envelope included).

    `mode` selects the pixel format and expected input:
      "opaque"   -- RGB888 in (3 bytes/px), RGB565 out
      "alpha"    -- RGBA8888 in (4 bytes/px), ARGB4444 out (flags=0x03 default,
                     matching real files -- only 0x02 is byte-exact confirmed,
                     see module docstring)
      "colorkey" -- RGBA8888 in (4 bytes/px); alpha<128 pixels become the
                     reserved transparent marker (raw 0x0000), everything
                     else is plain RGB565 (nudged off 0x0000 if it would
                     otherwise collide with the marker)

    `size` must be a power of two and >=8 (only 8x8-and-larger base levels
    have been round-trip verified -- see module docstring). `flags` overrides
    the mode's default if given.
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {sorted(_MODES)}, got {mode!r}")
    if size & (size - 1) != 0 or size < 8:
        raise ValueError(f"size must be a power of two >= 8, got {size}")
    channels, default_flags, encode_pixel = _MODES[mode]
    if len(pixels) != size * size * channels:
        raise ValueError(
            f"expected {size * size * channels} bytes ({channels} ch/px) for a "
            f"{size}x{size} image, got {len(pixels)}"
        )
    if flags is None:
        flags = default_flags

    levels = _build_mip_chain(pixels, size, channels)  # levels[0]=base ... levels[-1]=1x1
    mip_count = len(levels)

    onepix_value = encode_pixel(levels[-1][0])

    chain = bytearray(RESERVED_BLOCK_SIZE)

    # 2x2 level (levels[-2]) padded into a 4x4-pixel slot, zero-filled elsewhere
    slot = bytearray(PADDED_2X2_SLOT_SIZE)
    two_by_two = levels[-2]
    for y in range(2):
        for x in range(2):
            v = encode_pixel(two_by_two[y * 2 + x])
            off = (y * 4 + x) * 2
            struct.pack_into("<H", slot, off, v)
    chain += slot

    # every level from 4x4 up to (but not including) the base, tight-packed
    for level in reversed(levels[1:-2]):
        for px in level:
            chain += struct.pack("<H", encode_pixel(px))

    # base level, tight-packed, last
    for px in levels[0]:
        chain += struct.pack("<H", encode_pixel(px))

    header = struct.pack(
        "<BBBBiii",
        flags, 1 if on_geometry else 0, 0, wrap,
        onepix_value if (flags & 0x03) else 0,
        mip_count,
        onepix_value,
    )
    payload = header + bytes(chain)
    return envelope.build(b" XET", 3, payload)


def tga_to_tex(tga_path: Path | str, tex_path: Path | str, **kwargs) -> None:
    """`mode` ("opaque"/"alpha"/"colorkey", see encode_to_tex) defaults to
    "alpha" for a 32-bit source or "opaque" for 24-bit -- pass mode="colorkey"
    explicitly for a colorkey texture, since that also takes a 32-bit
    (RGBA) source and can't be told apart from "alpha" by channel count alone.
    """
    pixels, width, height = read_tga(tga_path)
    if width != height:
        raise ValueError(f"only square textures are supported, got {width}x{height}")
    mode = kwargs.pop("mode", "alpha" if len(pixels) == width * height * 4 else "opaque")
    data = encode_to_tex(pixels, width, mode=mode, **kwargs)
    Path(tex_path).write_bytes(data)
