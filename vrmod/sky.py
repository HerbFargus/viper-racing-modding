"""Read and replace a track's sky.

A track's sky is four square opaque textures, sky1-4.tex, which are four
consecutive slices of ONE panoramic strip. Seam continuity between adjacent
slices -- including sky4 -> sky1, which closes the loop -- measures a mean edge
difference of only 1-7 out of 255 across every stock track, so they are
genuinely one image cut into quarters rather than four independent backdrops.

The strip is NOT one full turn of the horizon, though it closes as if it were.
It spans roughly 90 degrees and the game repeats it FOUR TIMES around. That was
confirmed by turning a full circle in game on the Telly track and counting four
copies of its distinctive baby-face sun. It also follows from the art alone:
that sun is 200x110 in the strip (nearly twice as wide as tall) but renders
round in game, and since a perspective camera preserves angular aspect, a
single 360-degree wrap would need the strip to stand ~148 degrees tall --
past the zenith, impossible.

The practical consequence for anyone authoring a sky: **what you draw is a
90-degree quarter-view that will be seen four times**, so it has to tile
seamlessly left-to-right, and anything unique in it (a sun, a landmark) appears
four times around the horizon. That is how the stock skies are built.

Tile size is NOT uniform in the wild. All eight stock retail tracks use
**128x128** tiles (a 512x128 strip); most community add-ons use **256x256** --
6 of the 9 in one real collection -- which is itself evidence the game is not
limited to what the stock tracks happen to ship. Tiles are opaque, no colorkey,
wrap 0 throughout. Colour mode and wrap are always read from the real tiles
rather than assumed, so an unusual track round-trips unchanged; tile SIZE is
kept as-is unless overridden (see MIN_TILE below).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import archive, envelope, tex

TILES = ("sky1.tex", "sky2.tex", "sky3.tex", "sky4.tex")

# How many times the game repeats the strip around the horizon. Not used to
# write anything -- recorded here because it is the fact that makes a sky
# authorable, and viewer.py's buildSky() has to agree with it.
REPEATS = 4

# The stock game's textures are all 256x256 or smaller, which is not an
# arbitrary choice: 256x256 was the maximum texture dimension on much of the
# 3D hardware of 1998 (3dfx Voodoo among it). That is almost certainly why the
# sky is four tiles rather than one wide image in the first place -- a
# 1024x256 sky could not have been uploaded as a single texture.
#
# Community patches are reported to lift that to 512x512. This module CAN write
# larger tiles, but does not do so on its own: the default is to keep whatever
# size the track already had, so importing a strip you happened to edit at 2x
# resolution cannot silently produce a track an unpatched game may refuse to
# load. Pass tile_size explicitly to change it -- an informed choice, not an
# accident of what your image editor saved.
MIN_TILE, MAX_TILE = 64, 1024


class SkyError(RuntimeError):
    """The track's sky can't be read or replaced."""


def _tile_entries(entries: list) -> list:
    by_name = {e.name.lower(): e for e in entries}
    missing = [n for n in TILES if n not in by_name]
    if missing:
        raise SkyError(f"missing sky tiles: {', '.join(missing)}")
    return [by_name[n] for n in TILES]


def read_strip(trk_path: str | Path) -> tuple[bytes, int, int]:
    """The track's sky as one RGB888 strip. Returns (pixels, width, height)."""
    entries = archive.read(Path(trk_path))
    tiles = []
    for entry in _tile_entries(entries):
        info = tex.parse(envelope.build(entry.tag, entry.version, entry.payload))
        pixels = tex.decode_base_level(info)
        step = 4 if (info.has_alpha or info.has_colorkey) else 3
        tiles.append((info.size, step, pixels))
    size = tiles[0][0]
    if any(t[0] != size for t in tiles):
        raise SkyError("sky tiles are not all the same size")

    width, height = size * len(TILES), size
    out = bytearray(width * height * 3)
    for i, (tile_size, step, pixels) in enumerate(tiles):
        for y in range(tile_size):
            src = y * tile_size * step
            dst = (y * width + i * tile_size) * 3
            for x in range(tile_size):
                out[dst + x * 3: dst + x * 3 + 3] = pixels[src + x * step: src + x * step + 3]
    return bytes(out), width, height


def _nearest_power_of_two(n: int) -> int:
    """Round to the nearest power of two within the supported range.

    Textures must be power-of-two square, but people will hand over a 1600x400
    strip without thinking about it, and rounding is friendlier than refusing.
    """
    n = max(MIN_TILE, min(MAX_TILE, n))
    lo = 1 << (n.bit_length() - 1)
    hi = lo << 1
    best = lo if (n - lo) <= (hi - n) else hi
    return max(MIN_TILE, min(MAX_TILE, best))


def tile_size_for(width: int) -> int:
    """The tile size a strip of this width implies -- a quarter of it, rounded."""
    return _nearest_power_of_two(max(1, width // len(TILES)))


def build_tiles(pixels: bytes, width: int, height: int, size: int,
                mode: str = "opaque", wrap: int = 0) -> list[bytes]:
    """Cut a strip into four square tiles and encode each as .tex bytes."""
    target_w, target_h = size * len(TILES), size
    pixels = tex.resize_nearest(pixels, width, height, target_w, target_h)
    out = []
    for i in range(len(TILES)):
        tile = bytearray(size * size * 3)
        for y in range(size):
            src = (y * target_w + i * size) * 3
            tile[y * size * 3:(y + 1) * size * 3] = pixels[src:src + size * 3]
        # sky ships with byte 0x01 clear, unlike every texture drawn on geometry
        out.append(tex.encode_to_tex(bytes(tile), size, mode=mode, wrap=wrap,
                                     on_geometry=False))
    return out


def install(trk_path: str | Path, pixels: bytes, width: int, height: int,
            out_path: str | Path | None = None,
            tile_size: int | None = None) -> tuple[Path, int, int]:
    """Replace a track's sky with a panoramic strip.

    Returns (path, new tile size, original tile size) -- compare the last two
    to tell whether the track's sky resolution changed.

    Tile size, colour mode and wrap are all inherited from the existing tiles
    unless tile_size overrides the size -- so by default this changes only the
    picture, never the format. See MIN_TILE's note on the 256px hardware limit
    and the patches said to lift it.

    Rewrites in place after backing the track up alongside, unless out_path is
    given.
    """
    trk_path = Path(trk_path)
    entries = archive.read(trk_path)
    originals = _tile_entries(entries)

    first = tex.parse(envelope.build(originals[0].tag, originals[0].version, originals[0].payload))
    original_size = first.size
    size = _nearest_power_of_two(tile_size) if tile_size else original_size
    mode = "alpha" if first.has_alpha else "colorkey" if first.has_colorkey else "opaque"

    for entry, raw in zip(originals, build_tiles(pixels, width, height, size, mode, first.wrap)):
        entries = archive.replace_entry(entries, entry.name, raw)

    layout = archive.read_layout(trk_path.read_bytes())
    out_path = Path(out_path) if out_path else trk_path
    if out_path == trk_path:
        backup = trk_path.with_suffix(trk_path.suffix + ".sky-backup")
        if not backup.exists():
            shutil.copy2(trk_path, backup)
    out_path.write_bytes(archive.to_bytes(entries, partitioned=layout.partitioned))
    return out_path, size, original_size


def install_tga(trk_path: str | Path, tga_path: str | Path,
                out_path: str | Path | None = None,
                tile_size: int | None = None) -> tuple[Path, int, int]:
    """install() from a TGA on disk -- the interchange format the rest of the
    toolchain uses (see tex2tga/tga2tex)."""
    pixels, width, height = tex.read_tga_bytes(Path(tga_path).read_bytes())
    if len(pixels) == width * height * 4:                 # drop alpha; skies are opaque
        rgb = bytearray(width * height * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = pixels[0::4], pixels[1::4], pixels[2::4]
        pixels = bytes(rgb)
    return install(trk_path, pixels, width, height, out_path, tile_size)


def export_tga(trk_path: str | Path, tga_path: str | Path) -> tuple[int, int]:
    """Write the track's sky out as one editable TGA. Returns (width, height)."""
    pixels, width, height = read_strip(trk_path)
    tex.write_tga(pixels, width, height, tga_path)
    return width, height
