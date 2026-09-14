"""Lift opaque textures off the transparency marker.

A `.tex` stores RGB565, and a pixel that decodes to black is reserved: it means
"this pixel is transparent". `mktex.exe` nudged any opaque pixel that would land
there to `0x0040` -- the green field's low bit, still black to look at -- so real
black could never be mistaken for the marker. It only did so for textures it was
encoding as colorkey, which leaves every plain opaque texture in the game free to
contain genuine black, and plenty do.

TWO raw values decode to black, which is easy to miss and was missed here. Green
sits in a 6-bit field whose low bit is not significant -- the decoder masks it
off -- so `0x0000` and `0x0020` both come out RGB (0, 0, 0). Sweeping only
`0x0000` left 75,839 texels of the other kind behind across a full install.

The file-format reference had this as `R5 == 0 && B5 == 0`, from three
solid-colour samples in 2026-09-07. That predicate is too wide: `0x0040` also has
red and blue at zero, and 1,092,129 texels were moved there and confirmed solid
in game. The rule that fits every observation is **the decoded colour is exactly
black** -- raw `0x0000` or `0x0020`, and nothing else.

Whether that matters is the driver's decision, and drivers disagree. Running the
game on an AMD card and an Nvidia card renders blacks differently from identical
files; on the machine this was found on, the marker is honoured in opaque
textures too. The symptoms are all the same defect: see-through bands along a
car's flank, speckled patches around the stock Viper cockpit's gauges, a black
direction arrow that reads as a hole in its sign.

The data is not the cause -- but it is the half that can be fixed. The driver
decides whether `0x0000` is keyed; the file decides whether any texel sits on
`0x0000` for it to key. Move the texels and the question stops arising, on every
card, with no change to the format, the flags, or the file's layout.

WHAT IS LEFT ALONE, and why each one matters:

  flags 0x01 (colorkey)   `0x0000` is the POINT there. Sunset Mesa's
                          `cactus.tex` is one of these: sweeping it would turn
                          every cactus into a solid rectangle.
  flags 0x02/0x03 (alpha) The same bytes are ARGB4444, where an all-zero pixel
                          is a legitimately transparent one.
  the first 0x3C bytes    Reserved block plus the 2x2 level's padded slot, both
                          of pixel data      meant to be zero. Stock textures carry 26 zero
                          words apiece there and the game is fine with it.

Everything else -- base level and every mip -- is swept, because averaging two
dark texels during mip generation lands back on the marker even when the base
level is clean.

The file is patched IN PLACE at byte offsets rather than re-serialised. Payload
sizes never change, so every byte that is not a lifted texel is left exactly as
it was found: re-packing an archive is not guaranteed byte-identical (4x4cos.car
round-trips to a different arrangement of the same size), and that is not a risk
worth taking with somebody's install.
"""
from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import archive, backups as backups_mod, envelope, tex

# TWO raw values decode to black, not one. Green occupies a 6-bit field but only
# its top 5 bits are significant -- the decoder masks the low bit off -- so
# 0x0000 and 0x0020 both come out RGB (0, 0, 0) and both read as the marker.
# Sweeping only 0x0000 left 75,839 of the other kind behind in a full install.
#
# The nudge target is 0x0040, the next green step up: RGB (0, 8, 0), which is
# black to look at and is NOT the marker. That it survives is the evidence for
# where the real boundary lies -- see the docstring.
KEY_RAWS = (0x0000, 0x0020)
KEY_LOW_BYTES = frozenset(v & 0xFF for v in KEY_RAWS)   # high byte is 0 for both
NUDGE_RAW = 0x0040
RESERVED_HEAD = 0x3C        # of the pixel data; see module docstring
BACKUP_SUFFIX = ".dekey-backup"

# Where a .tex's pixel data starts inside a standalone file or an archive
# payload: past the 0SER envelope, past the tex header, past the reserved block.
PIXELS_AT = tex.HEADER_SIZE + RESERVED_HEAD
SWEPT_SUFFIXES = (".car", ".trk", ".res")

# The assets the game shipped with -- the default scope. Everything else in a
# Data folder was put there by somebody, and rewriting somebody else's work in
# bulk is not a default worth having: not because a mod is likely to rely on the
# marker (one that did would already look broken on an AMD card, so nobody could
# have shipped it deliberately), but because it is their file. Sweeping it should
# be something a person asks for, with `--all` or by naming the file.
#
# Matched by FILENAME, not by hash, which was the first attempt. Hashes do not
# survive ordinary use: of the 26 retail assets in a real install, 21 had already
# drifted from the disc -- community patches, retextures, earlier tool runs, and
# this sweep itself. A hash gate refuses to touch a file the moment anything else
# has, which is exactly backwards. The cost of the filename rule is that a
# community RETEXTURE occupying a stock slot (a replacement viper.car) is treated
# as stock; it is backed up like anything else.
RETAIL_ASSETS = frozenset("""
    bemidji.trk career1.res career2.res career3.res career4.res common.res
    drivers.res dundas.trk easy.res exotic.car hard.res hastings.trk heaven.trk
    kenyon.trk limbo.trk medium.res nfield.trk paintkit.res plane.car
    postrace.res race.res sedan.car sports.car ui.res uptown.trk viper.car
""".split())


@dataclass
class TextureReport:
    name: str
    lifted: int = 0
    skipped: str = ""       # why, if it was


@dataclass
class FileReport:
    path: Path
    textures: list[TextureReport] = field(default_factory=list)
    backup: Path | None = None

    @property
    def lifted(self) -> int:
        return sum(t.lifted for t in self.textures)

    @property
    def changed(self) -> list[TextureReport]:
        return [t for t in self.textures if t.lifted]

    @property
    def skipped(self) -> list[TextureReport]:
        return [t for t in self.textures if t.skipped]


def payload_spans(data: bytes) -> list[tuple[str, int, int]]:
    """[(member name, absolute payload offset, payload size)] for an archive.

    Repeats archive.read_bytes()'s walk instead of calling it, because what is
    needed here is the OFFSET, which an ArchiveEntry does not carry -- it holds
    the payload bytes, and writing those back means re-serialising the archive.
    """
    if data[0:4] != archive.MAGIC:
        raise ValueError(f"bad archive magic {data[0:4]!r}")
    count = struct.unpack_from("<i", data, 4)[0]
    meta = []
    for i in range(count):
        off = archive.HEADER_SIZE + i * archive.ENTRY_SIZE
        raw = data[off:off + archive.ENTRY_SIZE]
        meta.append((raw[0:16].rstrip(b"\x00").decode("ascii", "replace"),
                     struct.unpack_from("<i", raw, 24)[0]))
    spans = []
    cursor = archive.HEADER_SIZE + count * archive.ENTRY_SIZE
    for name, size in meta:
        if data[cursor + 4:cursor + 8] != envelope.MARKER:
            break                      # decoy tail; archive.read tolerates it too
        spans.append((name, cursor + archive.CHUNK_PREFIX_SIZE, size))
        cursor += archive.CHUNK_PREFIX_SIZE + size
    return spans


def sweep_payload(buf: bytearray, start: int, size: int) -> tuple[int, str]:
    """Lift one .tex payload in place. Returns (texels lifted, skip reason).

    `start` is where the TEX HEADER begins. Inside an archive that is the member
    payload itself -- the 0SER envelope is not stored with the payload, it is
    rebuilt from the directory's tag and version, which is why a standalone file
    has 20 bytes in front that an archive member does not.
    """
    flags = buf[start]
    if flags not in (0x00, 0x01, 0x02, 0x03):
        return 0, f"unexpected flags {flags:#04x}"
    if flags != 0x00:
        # 0x03 is both bits: label it for what it is rather than letting a
        # bit0 test call it colorkey.
        return 0, {0x01: "colorkey", 0x02: "alpha", 0x03: "alpha+colorkey"}[flags]
    lifted = 0
    for i in range(start + PIXELS_AT, start + size - 1, 2):
        if buf[i + 1] == 0x00 and buf[i] in KEY_LOW_BYTES:
            buf[i] = NUDGE_RAW & 0xFF      # little-endian: 0x0040
            lifted += 1
    return lifted, ""


def sweep_bytes(data: bytes) -> tuple[bytes, list[TextureReport]]:
    """Sweep every .tex in an archive's bytes, or a standalone .tex."""
    buf = bytearray(data)
    reports: list[TextureReport] = []
    if data[0:4] == envelope.MAGIC:                      # a loose .tex
        lifted, why = sweep_payload(buf, envelope.SIZE, len(buf) - envelope.SIZE)
        reports.append(TextureReport("(standalone)", lifted, why))
        return bytes(buf), reports
    for name, off, size in payload_spans(data):
        if not name.lower().endswith(".tex"):
            continue
        lifted, why = sweep_payload(buf, off, size)
        reports.append(TextureReport(name, lifted, why))
    return bytes(buf), reports


def sweep_file(path: Path, *, dry_run: bool = False,
               backup: bool = True) -> FileReport:
    """Sweep one file. Writes only if something was lifted."""
    path = Path(path)
    data = path.read_bytes()
    out, reports = sweep_bytes(data)
    report = FileReport(path=path, textures=reports)
    if not report.lifted or dry_run:
        return report
    if len(out) != len(data):
        raise RuntimeError(f"{path.name}: size changed {len(data)} -> {len(out)}; "
                           "refusing to write")
    if backup:
        # A suffix of its own, alongside .vram-backup / .sky-backup, for two
        # reasons. It is not a loadable game file -- the engine scans Data/ and
        # loads every *.car and *.trk, deriving member names from the filename,
        # so a "viper_original.car" makes it hunt for "viper_original0.mod" and
        # panic. And it is DISTINGUISHABLE: revert() has to know which backup
        # belongs to which file without guessing.
        #
        # It goes in Data/Backups/ rather than beside the file: a whole-install
        # sweep leaves one per changed file, which on a real install was 21 of
        # the 56 backups cluttering a Data root that held 24 actual game assets.
        report.backup = backups_mod.store(path, BACKUP_SUFFIX)
    path.write_bytes(out)
    return report


def sweep_tree(root: Path, *, dry_run: bool = False, backup: bool = True,
               scope: str = "stock") -> tuple[list[FileReport], list[Path]]:
    """Sweep archives and loose textures under a directory.

    Returns (reports, skipped) -- the files left out of scope are RETURNED
    rather than silently dropped, so a caller can say how many and offer
    `--all`. A scoped tool that does not report its own scope is how "it did
    nothing" gets mistaken for "there was nothing to do".

    Naming a single file always sweeps it: the scope is a default for bulk
    operations, not a restriction on what the user can point at.
    """
    root = Path(root)
    if root.is_file():
        return [sweep_file(root, dry_run=dry_run, backup=backup)], []
    if scope not in ("stock", "all"):
        raise ValueError(f"scope must be 'stock' or 'all', not {scope!r}")
    found = sorted(p for p in root.rglob("*")
                   if p.is_file()
                   and p.suffix.lower() in SWEPT_SUFFIXES + (".tex",)
                   and not p.name.lower().endswith(".bak"))
    targets, skipped = [], []
    for p in found:
        if scope == "all" or p.name.lower() in RETAIL_ASSETS:
            targets.append(p)
        else:
            skipped.append(p)
    out = []
    for p in targets:
        try:
            out.append(sweep_file(p, dry_run=dry_run, backup=backup))
        except ValueError:
            continue                   # not an archive this reader handles
    return out, skipped


def has_keys(data: bytes) -> bool:
    """Whether anything in this file would be swept -- stopping at the first hit.

    Separate from remaining_keys() because the two answer different questions at
    very different prices. A verification pass has to count every one. Doctor
    only has to know IF, and it runs on every open of the app against a Data
    folder that may hold hundreds of community cars and several gigabytes: an
    affected file answers on its first texel, so the cost falls back to the
    files that are already clean.
    """
    try:
        spans = _tex_spans(data)
    except ValueError:
        return False
    for _, off, size in spans:
        if data[off] != 0x00:
            continue
        for i in range(off + PIXELS_AT, off + size - 1, 2):
            if data[i + 1] == 0 and data[i] in KEY_LOW_BYTES:
                return True
    return False


def affected(root: Path, scope: str = "stock") -> list[Path]:
    """Files in scope that still carry key texels."""
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        if (not p.is_file() or p.suffix.lower() not in SWEPT_SUFFIXES + (".tex",)
                or p.name.endswith(BACKUP_SUFFIX)):
            continue
        if scope == "stock" and p.name.lower() not in RETAIL_ASSETS:
            continue
        try:
            if has_keys(p.read_bytes()):
                out.append(p)
        except (ValueError, OSError):
            continue
    return out


def backups(root: Path) -> list[Path]:
    """Sweep backups, wherever they are -- the folder or loose (older installs)."""
    root = Path(root)
    if root.is_file():
        root = root.parent
    return backups_mod.find(root, BACKUP_SUFFIX)


def revert(root: Path) -> list[tuple[Path, Path]]:
    """Restore every swept file from its backup. Returns [(restored, backup)].

    The backup is removed once its contents are back in place: leaving it would
    mean a second revert silently restoring a file that is already original, and
    the whole point of the dedicated suffix is that what remains on disk says
    truthfully whether there is anything to undo.
    """
    root = Path(root)
    data_dir = root.parent if root.is_file() else root
    done = []
    for b in backups(root):
        target = backups_mod.target_of(b, data_dir)
        shutil.copy2(b, target)
        b.unlink()
        done.append((target, b))
    return done


def _tex_spans(data: bytes) -> list[tuple[str, int, int]]:
    """Texture payload spans, whether `data` is an archive or a lone .tex."""
    if data[0:4] == envelope.MAGIC:
        return [("(standalone)", envelope.SIZE, len(data) - envelope.SIZE)]
    return [s for s in payload_spans(data) if s[0].lower().endswith(".tex")]


def remaining_keys(data: bytes) -> int:
    """Key texels still present in opaque textures -- the verification a sweep
    has to satisfy, counted from the file rather than from the sweep's own
    tally."""
    total = 0
    for _, off, size in _tex_spans(data):
        if data[off] != 0x00:
            continue
        for i in range(off + PIXELS_AT, off + size - 1, 2):
            if data[i + 1] == 0 and data[i] in KEY_LOW_BYTES:
                total += 1
    return total


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, i = path.stem, path.suffix, 2
    while True:
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1
