"""Career saves: read each career slot and set its funds.

The game keeps one file per career slot, `career<slot>.dat`, in the user directory's `career\\` folder (on v1.0
with the modern engine or the write-paths fix: `<Data>\\Config\\career\\`). Read off the game's career_load /
career_save (viper-racing-port hook/career_main.cpp, career_types.h):

    header   16 bytes: 'FNIC', version 2, the body's size 0x674, a checksum (the byte sum of the DECODED body)
    body     the CareerInfo, every byte xor'd with 0xa4:
               +0x000  the player's name (16 bytes)      +0x010  realism        +0x014  damage on (byte)
               +0x018  funds (int32, dollars)              +0x01c  upgrades bought (256 bytes, one per upgrade)
               +0x11c  seasons    +0x120  the week (events entered)    +0x124  the class (0..3)

A new career starts with 0 funds (the new-career screen zeroes the whole record), so "lots of money" is a save edit:
set_funds rewrites the funds and the checksum and leaves every other byte as the game wrote it. It works the same on
the original game and the port. The game must be closed -- it holds the career in memory and saves it over the file.
The first edit of a slot keeps a copy of the file in Backups\\ (backups.store).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import backups, casefold, writepaths

MAGIC = b"FNIC"
VERSION = 2
SIZE = 0x674
KEY = 0xA4
HEADER = 16
SLOTS = 4                                  # the career chooser's four slots, career0..3.dat
FUNDS_MAX = 2**31 - 1                      # an int32
BACKUP_SUFFIX = ".career-backup"

OFF_NAME, OFF_FUNDS, OFF_UPGRADES = 0x000, 0x018, 0x01C
OFF_SEASONS, OFF_WEEK, OFF_CLASS = 0x11C, 0x120, 0x124


class CareerError(RuntimeError):
    pass


@dataclass
class Career:
    slot: int
    path: Path
    name: str
    funds: int
    season: int
    week: int
    career_class: int                      # 0..3
    upgrades: int                          # how many are bought (entry 0, set in every career, not counted)

    def to_json(self) -> dict:
        return {"slot": self.slot, "file": self.path.name, "name": self.name, "funds": self.funds,
                "season": self.season, "week": self.week, "class": self.career_class, "upgrades": self.upgrades}


def career_dirs(data_dir: str | Path) -> list[Path]:
    """Where career\\ folders may be, most likely first: the Config folders the game uses (writepaths), then the
    v1.0 RC's hard-coded user directory when its write path hasn't been fixed."""
    out = [c / "career" for c in writepaths.config_dirs(data_dir)]
    out.append(Path(writepaths.USER_DIR.decode()) / "career")
    return out


def career_dir(data_dir: str | Path) -> Path | None:
    """The career folder that holds saves, or None when no career has been made yet."""
    for c in career_dirs(data_dir):
        p = casefold.find(c.parent, c.name) if c.parent.is_dir() else None
        if p is not None and p.is_dir() and any(casefold.find_file(p, f"career{i}.dat") for i in range(SLOTS)):
            return p
    return None


def decode(raw: bytes) -> bytes:
    """A career file's body, decoded and checked. Raises CareerError for anything that isn't one."""
    if len(raw) < HEADER:
        raise CareerError("too short to be a career file")
    magic, version, size, checksum = struct.unpack_from("<4sIII", raw, 0)
    if magic != MAGIC or version != VERSION or size != SIZE or len(raw) < HEADER + SIZE:
        raise CareerError(f"not a v{VERSION} career file (magic {magic!r}, version {version}, size {size:#x})")
    body = bytes(b ^ KEY for b in raw[HEADER:HEADER + SIZE])
    if sum(body) & 0xFFFFFFFF != checksum:
        raise CareerError("its checksum doesn't match (damaged?)")
    return body


def encode(body: bytes) -> bytes:
    """A career file for a decoded body: the header (with the checksum) and the body xor'd."""
    if len(body) != SIZE:
        raise CareerError(f"a career body is {SIZE:#x} bytes, got {len(body):#x}")
    return struct.pack("<4sIII", MAGIC, VERSION, SIZE, sum(body) & 0xFFFFFFFF) + bytes(b ^ KEY for b in body)


def _parse(slot: int, path: Path, body: bytes) -> Career:
    i32 = lambda off: struct.unpack_from("<i", body, off)[0]
    return Career(slot, path, body[OFF_NAME:OFF_NAME + 16].split(b"\0")[0].decode("latin-1"), i32(OFF_FUNDS),
                  i32(OFF_SEASONS), i32(OFF_WEEK), i32(OFF_CLASS),
                  sum(1 for b in body[OFF_UPGRADES + 1:OFF_UPGRADES + 256] if b))   # entry 0: a placeholder every career has


def _slot_path(data_dir: str | Path, slot: int) -> Path:
    if not 0 <= slot < SLOTS:
        raise CareerError(f"there are {SLOTS} career slots (0..{SLOTS - 1}), not {slot}")
    d = career_dir(data_dir)
    p = casefold.find_file(d, f"career{slot}.dat") if d is not None else None
    if p is None:
        raise CareerError(f"career slot {slot} is empty -- start a career in it first")
    return p


def list_careers(data_dir: str | Path) -> list[Career]:
    """Every slot that holds a career, by slot. A damaged file is left out."""
    d = career_dir(data_dir)
    out = []
    for i in range(SLOTS):
        p = casefold.find_file(d, f"career{i}.dat") if d is not None else None
        if p is None:
            continue
        try:
            out.append(_parse(i, p, decode(p.read_bytes())))
        except CareerError:
            continue
    return out


def read(data_dir: str | Path, slot: int) -> Career:
    p = _slot_path(data_dir, slot)
    return _parse(slot, p, decode(p.read_bytes()))


def set_funds(data_dir: str | Path, slot: int, funds: int) -> Career:
    """Set a slot's funds (whole dollars, 0..FUNDS_MAX). Every other byte stays as the game wrote it; the first edit
    keeps a copy in Backups\\. Returns the career as now saved."""
    funds = int(funds)
    if not 0 <= funds <= FUNDS_MAX:
        raise CareerError(f"funds must be 0..{FUNDS_MAX:,}, got {funds:,}")
    p = _slot_path(data_dir, slot)
    body = bytearray(decode(p.read_bytes()))
    if backups.locate(p, BACKUP_SUFFIX, Path(data_dir)) is None:
        backups.store(p, BACKUP_SUFFIX, Path(data_dir))
    struct.pack_into("<i", body, OFF_FUNDS, funds)
    p.write_bytes(encode(bytes(body)))
    return _parse(slot, p, decode(p.read_bytes()))
