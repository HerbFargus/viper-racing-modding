"""Lift opaque textures off the transparency marker.

A `.tex` stores RGB565, and raw value `0x0000` is reserved: it means "this pixel
is transparent". `mktex.exe` nudged any opaque pixel that would land there to
`0x0040` -- the green field's low bit, still black to look at -- so real black
could never be mistaken for the marker. It only did so for textures it was
encoding as colorkey, which leaves every plain opaque texture in the game free
to contain genuine `0x0000`, and plenty do.

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

from . import archive, envelope, tex

KEY_RAW = 0x0000
NUDGE_RAW = 0x0040          # decodes to (0, 8, 0): still black on screen
RESERVED_HEAD = 0x3C        # of the pixel data; see module docstring

# Where a .tex's pixel data starts inside a standalone file or an archive
# payload: past the 0SER envelope, past the tex header, past the reserved block.
PIXELS_AT = tex.HEADER_SIZE + RESERVED_HEAD
SWEPT_SUFFIXES = (".car", ".trk", ".res")


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
        if buf[i] == 0x00 and buf[i + 1] == 0x00:
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
        # ".bak" so the backup is not itself a loadable game file: the engine
        # scans Data/ and loads every *.car and *.trk, deriving member names
        # from the filename, so a "viper_original.car" makes it hunt for
        # "viper_original0.mod" and panic.
        report.backup = _unique(path.with_name(
            f"{path.stem}_original{path.suffix}.bak"))
        shutil.copy2(path, report.backup)
    path.write_bytes(out)
    return report


def sweep_tree(root: Path, *, dry_run: bool = False,
               backup: bool = True) -> list[FileReport]:
    """Sweep every archive and loose texture under a directory."""
    root = Path(root)
    if root.is_file():
        return [sweep_file(root, dry_run=dry_run, backup=backup)]
    targets = sorted(p for p in root.rglob("*")
                     if p.is_file()
                     and p.suffix.lower() in SWEPT_SUFFIXES + (".tex",)
                     and not p.name.lower().endswith(".bak"))
    out = []
    for p in targets:
        try:
            out.append(sweep_file(p, dry_run=dry_run, backup=backup))
        except ValueError:
            continue                   # not an archive this reader handles
    return out


def remaining_keys(data: bytes) -> int:
    """Key texels still present in opaque textures -- the verification a sweep
    has to satisfy, counted from the file rather than from the sweep's own
    tally."""
    total = 0
    spans = ([("(standalone)", envelope.SIZE, len(data) - envelope.SIZE)]
             if data[0:4] == envelope.MAGIC
             else [s for s in payload_spans(data) if s[0].lower().endswith(".tex")])
    for _, off, size in spans:
        if data[off] != 0x00:
            continue
        for i in range(off + PIXELS_AT, off + size - 1, 2):
            if data[i] == 0 and data[i + 1] == 0:
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
