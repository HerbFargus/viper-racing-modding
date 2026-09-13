"""`english.lng` -- the game's string table, read and write.

THE FORMAT. A header, an index, and a blob of NUL-terminated strings:

```
0x00  'RES0' 'LANG', eight zero bytes, 'MGI!' then the language name
0x54  u32 entry count                          (822 in the stock English file)
0x58  entry count * (u32 key offset, u32 value offset)
      -- each offset is +OFFSET_BIAS short of the real file position
0x?   the strings, NUL-terminated, packed with no slack
```

The index ends exactly where the strings begin, which is the check that the
count and the layout agree. Several header words hold `0x0012fb68` and friends:
those are runtime pointers left in a dumped struct, not offsets into the file,
and nothing here touches them.

**There is no length field anywhere.** Not the file size, not the size of the
string blob. That is what makes this module able to do the useful thing.

WHY NOT EDIT IN PLACE. switcher.py writes a track's display name over the old
one, truncated and space-padded to the original width, on the grounds that
growing the file is not safe. For a track name that is fine -- "Bemidji" has
room. For the AI driver names it would gut the feature: the Easy tier is Dunne,
Berg, Hall, Hecker, Hook, White and Hayes, so you could replace "Berg" only with
something four characters or shorter.

WHAT THIS DOES INSTEAD. A new value is APPENDED to the end of the file and the
entry's value offset repointed at it. Four bytes change in the index, the
strings already in the file do not move, and every other offset stays valid --
so the length of the new name does not matter. The string it replaced is still
sitting there untouched, which is also what makes reverting exact: point the
offset back and the file is byte-for-byte what it was, minus the appended tail.

The cost is that the file grows by the length of each name written. A few
hundred bytes on a 37 KB file, and `compact()` rebuilds it without the orphans
if that ever matters.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import safewrite

MAGIC = b"0SER"                 # 'RES0' little-endian
KIND = b"GNAL"                  # 'LANG'
COUNT_AT = 0x54
TABLE_AT = 0x58
ENTRY = 8                       # two u32 per entry
# Stored offsets are short of the real file position by this much. Derived from
# the stock file rather than guessed: the table ends exactly where the strings
# begin, and with this bias every one of the 822 entries lands on a string
# start (a byte preceded by a NUL). read() asserts that rather than trusting it.
OFFSET_BIAS = 20


class LngError(ValueError):
    """The file is not a string table this module understands."""


@dataclass
class Lng:
    """A parsed string table. `entries` is ordered as the index is."""
    path: Path
    raw: bytes
    entries: list[tuple[str, str]]
    table_at: int
    count: int

    def value(self, key: str) -> str | None:
        for k, v in self.entries:
            if k == key:
                return v
        return None

    def keys_like(self, prefix: str) -> list[str]:
        return [k for k, _ in self.entries if k.startswith(prefix)]


def _cstr(blob: bytes, off: int) -> bytes:
    end = blob.find(b"\0", off)
    if end < 0:
        raise LngError(f"unterminated string at 0x{off:x}")
    return blob[off:end]


def read(path: str | Path) -> Lng:
    """Parse the table. Raises LngError rather than returning something partly
    understood -- a half-read string table would be written back wrong."""
    path = Path(path)
    blob = path.read_bytes()
    if len(blob) < TABLE_AT + ENTRY or blob[:4] != MAGIC or blob[4:8] != KIND:
        raise LngError(f"{path.name}: not a RES0/LANG string table")
    count = struct.unpack_from("<I", blob, COUNT_AT)[0]
    end_of_table = TABLE_AT + count * ENTRY
    if not (0 < count < 100_000) or end_of_table > len(blob):
        raise LngError(f"{path.name}: entry count {count} does not fit the file")

    entries: list[tuple[str, str]] = []
    for i in range(count):
        ko, vo = struct.unpack_from("<II", blob, TABLE_AT + i * ENTRY)
        ka, va = ko + OFFSET_BIAS, vo + OFFSET_BIAS
        for off in (ka, va):
            if not (end_of_table <= off < len(blob)):
                raise LngError(f"{path.name}: entry {i} points outside the "
                               f"string blob (0x{off:x})")
            # Every string starts just after a NUL, except the very first.
            if off != end_of_table and blob[off - 1] != 0:
                raise LngError(f"{path.name}: entry {i} points into the middle "
                               f"of a string (0x{off:x})")
        entries.append((_cstr(blob, ka).decode("latin-1"),
                        _cstr(blob, va).decode("latin-1")))
    return Lng(path=path, raw=blob, entries=entries,
               table_at=TABLE_AT, count=count)


def set_values(path: str | Path, changes: dict[str, str]) -> int:
    """Point the named keys at new values, appended to the end of the file.

    Returns the number of entries changed. A key that is not in the table is an
    error, not a silent no-op: the caller asked for a name to appear in the
    game and it would not have.

    A value identical to the one already stored is skipped rather than
    appended, so re-applying the same names twice does not grow the file twice.
    """
    path = Path(path)
    lng = read(path)
    index = {k: i for i, (k, _) in enumerate(lng.entries)}
    missing = [k for k in changes if k not in index]
    if missing:
        raise LngError(f"{path.name}: no such key(s): {missing[:5]}")

    blob = bytearray(lng.raw)
    written = 0
    for key, value in changes.items():
        i = index[key]
        if lng.entries[i][1] == value:
            continue
        encoded = value.encode("latin-1", errors="replace") + b"\0"
        new_off = len(blob)
        blob += encoded
        struct.pack_into("<I", blob, TABLE_AT + i * ENTRY + 4,
                         new_off - OFFSET_BIAS)
        written += 1
    if not written:
        return 0

    safewrite.write_atomic(path, bytes(blob))

    # Read it back and confirm the table still parses and says what we asked
    # for. A string table that writes cleanly and reads back wrong would show
    # up as garbled menus in game, long after the moment it went wrong.
    after = read(path)
    if len(after.entries) != len(lng.entries):
        raise LngError(f"{path.name}: entry count changed on write")
    for key, value in changes.items():
        got = after.value(key)
        if got != value:
            raise LngError(f"{path.name}: wrote {key}={value!r} but it reads "
                           f"back as {got!r}")
    for i, ((k0, v0), (k1, v1)) in enumerate(zip(lng.entries, after.entries)):
        if k0 != k1 or (k0 not in changes and v0 != v1):
            raise LngError(f"{path.name}: entry {i} ({k1!r}) changed and "
                           f"should not have: {v0!r} -> {v1!r}")
    return written


def compact(path: str | Path) -> int:
    """Rewrite the file with every string packed once and no orphans.

    Appending leaves the replaced strings in place -- harmless, and what makes a
    revert exact, but it accumulates. This rebuilds the blob from the entries as
    they currently read, which is the only operation here that moves existing
    strings, so it recomputes every offset. Returns the bytes saved.

    Nothing calls it in the normal flow; it exists so that the append strategy
    has a floor rather than being a one-way ratchet.
    """
    path = Path(path)
    lng = read(path)
    header = bytearray(lng.raw[:TABLE_AT])
    table = bytearray(lng.count * ENTRY)
    blob = bytearray()
    seen: dict[bytes, int] = {}
    base = TABLE_AT + lng.count * ENTRY

    def intern(s: str) -> int:
        b = s.encode("latin-1", errors="replace")
        if b not in seen:
            seen[b] = base + len(blob)
            blob.extend(b + b"\0")
        return seen[b]

    for i, (k, v) in enumerate(lng.entries):
        ko, vo = intern(k), intern(v)
        struct.pack_into("<II", table, i * ENTRY,
                         ko - OFFSET_BIAS, vo - OFFSET_BIAS)
    out = bytes(header) + bytes(table) + bytes(blob)
    saved = len(lng.raw) - len(out)
    safewrite.write_atomic(path, out)

    after = read(path)
    if [e for e in after.entries] != [e for e in lng.entries]:
        raise LngError(f"{path.name}: compaction changed the table's contents")
    return saved
