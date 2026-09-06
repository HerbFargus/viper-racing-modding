"""
0TSR archive container.

Groups a track's, car's, or shared-resource bundle's full member set into one
file (.trk / .car / .res):

    0x00  "0TSR"              archive magic (distinct from the per-resource "0SER" envelope)
    0x04  int32 entryCount
    0x08  int32 coreCount       -- see _bulk_tags() below
    0x0C  int32 coreBoundary    -- byte offset where "bulk" payload data begins
    0x10  entryCount x 36-byte directory entries:
             name[16]          null-padded filename, no path
             tag[4]            same reversed-FourCC convention as the resource envelope
             version[4]
             payloadSize[4]    size *excluding* the resource's normal 20-byte 0SER envelope
             reserved[8]       = 0
          -> then entryCount payload blocks, back-to-back, in the SAME order as the directory:
             reserved[4] = 0, marker "!IGM"[4], then raw payload[payloadSize]

A standalone member file is normally "0SER"+tag+version+reserved+"!IGM"+payload --
the archive just splits that 20-byte envelope in half: tag+version live in the
directory entry, reserved+marker sit immediately before the payload.

coreCount/coreBoundary: every archive splits its members into a "core" group and
a "bulk" group. Bulk is a FIXED set of tag types -- BATS_TEX (" XET", textures),
NILI (AI-path variants), and TNDA (.dnt per-tier driver tuning) -- whichever of
those are present in a given archive, regardless of how many instances of each
there actually are. (An earlier pass at this documented the rule as "whichever
tag has the highest occurrence count," which happened to fit the handful of
archives spot-checked at the time but doesn't hold up: several .car/.res
archives have a non-tex/non-NILI tag with far more instances that is NOT
treated as bulk. The fixed-set rule is what actually reproduces every
archive.) Given that:

    coreCount     = number of entries whose tag is NOT in the bulk set
    coreBoundary  = (16 + 36*entryCount) + 8*coreCount + sum(payload sizes of core entries)

Verified byte-exact against all 26 archives on the retail disc (8 .trk, 5 .car,
13 .res), including a 1,220-member archive, with zero mismatches -- confirmed
via full read -> write -> compare-to-original round-trips, not just the header
math in isolation.

If a future archive doesn't round-trip, the likely cause is a new tag type this
engine also treats as bulk that hasn't been seen in the 26 samples checked here
-- extend BULK_TAGS below rather than reintroducing a frequency-based heuristic.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import envelope

MAGIC = b"0TSR"
HEADER_SIZE = 16
ENTRY_SIZE = 36
NAME_FIELD_SIZE = 16
CHUNK_PREFIX_SIZE = 8  # reserved[4] + "!IGM"[4]

# Tag types (on-disk, reversed form -- see envelope.py) the engine always treats
# as "bulk" when present, regardless of how many instances appear in a given
# archive. See the module docstring for how this was determined.
BULK_TAGS = {
    b" XET",  # .tex  (TEX )
    b"NILI",  # .ili/.ild/.ilg (NILI)
    b"TNDA",  # .dnt  (ADNT)
}


@dataclass
class ArchiveEntry:
    name: str
    tag: bytes
    version: int
    payload: bytes

    @property
    def payload_size(self) -> int:
        return len(self.payload)

    @property
    def mnemonic(self) -> str:
        return self.tag[::-1].decode("ascii", errors="replace")

    def to_standalone_bytes(self) -> bytes:
        """This member's bytes as a normal standalone 0SER-enveloped file."""
        return envelope.build(self.tag, self.version, self.payload)


# Some community cars -- Frank P. Wolf's SCGT/NFS conversions -- carry a trailing
# run of decoy directory entries after the real members: names "lockd1.tab" ..
# "lockdN.tab" (up to 975 of them), tag STAB, 12 bytes each, and NO payload data
# behind them. They pad the directory but the game ignores them (it reads only
# the real, "core" members), so a straight payload walk hits the first decoy --
# right where the real content ends -- and finds no chunk marker. Nothing in the
# preserved toolchain (rescrack/mkres) or Frank's own docs treats this as a
# protection; the real members are fully intact and already read by the time the
# walk reaches the padding. So we recognise this exact signature and stop cleanly
# rather than failing. See read_bytes. (A car re-packed after such a read comes
# out as a normal archive with the decoys dropped, which is harmless -- the game
# never used them.)
_DECOY_TAG = b"BATS"          # "STAB" reversed (see envelope.py)
_DECOY_SIZE = 12


def _is_decoy_tail(remaining: list[tuple]) -> bool:
    """True iff every remaining directory entry is a lockd*.tab STAB decoy -- the
    tight signature above, so a genuinely corrupt archive still raises."""
    return bool(remaining) and all(
        tag == _DECOY_TAG and payload_size == _DECOY_SIZE
        and name.lower().startswith("lockd") and name.lower().endswith(".tab")
        for (name, tag, _version, payload_size) in remaining
    )


def read(path: Path | str) -> list[ArchiveEntry]:
    return read_bytes(Path(path).read_bytes())


def read_bytes(data: bytes) -> list[ArchiveEntry]:
    if data[0:4] != MAGIC:
        raise ValueError(f"bad archive magic {data[0:4]!r}, expected {MAGIC!r}")
    entry_count = struct.unpack_from("<i", data, 4)[0]
    # coreCount/coreBoundary at offsets 8 and 12 are redundant with the directory
    # itself -- recomputed on write, not needed to read.

    dir_start = HEADER_SIZE
    meta = []
    for i in range(entry_count):
        off = dir_start + i * ENTRY_SIZE
        raw = data[off:off + ENTRY_SIZE]
        name = raw[0:16].rstrip(b"\x00").decode("ascii", errors="replace")
        tag = raw[16:20]
        version = struct.unpack_from("<i", raw, 20)[0]
        payload_size = struct.unpack_from("<i", raw, 24)[0]
        meta.append((name, tag, version, payload_size))

    cursor = dir_start + entry_count * ENTRY_SIZE
    entries = []
    for idx, (name, tag, version, payload_size) in enumerate(meta):
        marker = data[cursor + 4:cursor + 8]
        if marker != envelope.MARKER:
            # A trailing run of lockd*.tab decoys (see _is_decoy_tail) is the one
            # non-marker we tolerate: every real member is already read, and the
            # rest is padding the game ignores. Anything else is a real problem.
            if _is_decoy_tail(meta[idx:]):
                break
            raise ValueError(
                f"{name!r}: expected chunk marker {envelope.MARKER!r} at offset "
                f"{cursor + 4}, got {marker!r} -- archive layout assumption broken"
            )
        payload = data[cursor + 8: cursor + 8 + payload_size]
        entries.append(ArchiveEntry(name=name, tag=tag, version=version, payload=payload))
        cursor += CHUNK_PREFIX_SIZE + payload_size

    return entries


def read_layout(data: bytes) -> "ArchiveLayout":
    """Read an archive's core/bulk header convention without its payloads.

    Needed because the retail engine accepts TWO conventions and the fan-made
    track toolchain uses the other one -- see ArchiveLayout."""
    if data[0:4] != MAGIC:
        raise ValueError(f"bad archive magic {data[0:4]!r}, expected {MAGIC!r}")
    entry_count, core_count, core_boundary = struct.unpack_from("<3i", data, 4)
    return ArchiveLayout(
        entry_count=entry_count,
        core_count=core_count,
        core_boundary=core_boundary,
        partitioned=core_count < entry_count,
    )


@dataclass
class ArchiveLayout:
    """Which core/bulk convention an archive was written with.

    `partitioned=True` (every retail .trk/.car/.res): bulk-tagged entries are
    moved to the end, coreCount is the index of the first of them, and
    coreBoundary is that entry's payload offset.

    `partitioned=False` (every fan-made .tra checked): the writer declares no
    bulk section at all -- coreCount == entryCount and coreBoundary == EOF --
    while leaving bulk-tagged entries (.ili, .tex) interleaved wherever they
    happened to fall. The game loads these fine, so this is a legitimate
    alternative layout, not a corrupt file. Normalizing one into the other
    rewrites ~29% of a 2.3 MB track for no reason, so to_bytes() preserves
    whichever convention it's told to use.
    """
    entry_count: int
    core_count: int
    core_boundary: int
    partitioned: bool


def to_bytes(entries: list[ArchiveEntry], *, partitioned: bool = True) -> bytes:
    # coreBoundary (below) only correctly describes where bulk payload data
    # begins if every core-tagged entry's payload physically precedes every
    # bulk-tagged entry's payload -- true of every real archive on disk, but not
    # an invariant any caller here is required to maintain: upsert_entry()
    # appends new entries at the end of the list regardless of tag, which lands
    # a new core-tagged entry (e.g. a Parts-drawer override like ball.mod) AFTER
    # the real archive's bulk (.tex) section. coreBoundary would still get
    # computed as if all core payloads came first, understating the real offset
    # by exactly the appended entries' size -- confirmed to make the game crash,
    # reading texture data 27KB past where it actually starts. A stable
    # partition here (core entries first, each group's own relative order
    # preserved) makes to_bytes() correct regardless of input order instead of
    # silently trusting it -- a no-op for every real archive, which already
    # arrives in this order (verified against all 26 retail archives).
    if partitioned:
        entries = [e for e in entries if e.tag not in BULK_TAGS] + [e for e in entries if e.tag in BULK_TAGS]
        core_entries = [e for e in entries if e.tag not in BULK_TAGS]
    else:
        # The .tra convention: keep the caller's order exactly as given and
        # declare no bulk section, so coreCount == entryCount and the
        # boundary falls at EOF.
        core_entries = list(entries)
    entry_count = len(entries)
    core_count = len(core_entries)
    dir_size = entry_count * ENTRY_SIZE
    core_boundary = (
        HEADER_SIZE
        + dir_size
        + CHUNK_PREFIX_SIZE * core_count
        + sum(e.payload_size for e in core_entries)
    )

    header = MAGIC + struct.pack("<3i", entry_count, core_count, core_boundary)

    directory = bytearray()
    for e in entries:
        name_bytes = e.name.encode("ascii")
        if len(name_bytes) > NAME_FIELD_SIZE:
            raise ValueError(f"name {e.name!r} too long for the 16-byte name field")
        if len(e.tag) != 4:
            raise ValueError(f"{e.name!r}: tag must be 4 bytes, got {e.tag!r}")
        directory += name_bytes.ljust(NAME_FIELD_SIZE, b"\x00")
        directory += e.tag
        directory += struct.pack("<i", e.version)
        directory += struct.pack("<i", e.payload_size)
        directory += b"\x00" * 8

    payloads = bytearray()
    for e in entries:
        payloads += b"\x00\x00\x00\x00" + envelope.MARKER + e.payload

    return header + bytes(directory) + bytes(payloads)


def write(entries: list[ArchiveEntry], path: Path | str) -> None:
    Path(path).write_bytes(to_bytes(entries))


MANIFEST_NAME = "_manifest.txt"


def unpack(archive_path: Path | str, out_dir: Path | str) -> list[str]:
    """Unpack an archive into standalone 0SER files.

    Writes a manifest recording the original member order, since `pack()` needs
    it to reproduce the archive's layout on the way back in.
    """
    data = Path(archive_path).read_bytes()
    entries = read_bytes(data)
    layout = read_layout(data)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for e in entries:
        (out_dir / e.name).write_bytes(e.to_standalone_bytes())
        names.append(e.name)
    # The layout line records which core/bulk convention the source used, so
    # pack() can reproduce it. Without it a .tra unpack->pack round-trip
    # silently renormalizes into the retail partitioned layout, rewriting most
    # of the file. Written as a comment so manifests stay readable and older
    # manifests (which have no such line) still parse.
    header = f"# layout: {'partitioned' if layout.partitioned else 'flat'}\n"
    (out_dir / MANIFEST_NAME).write_text(header + "\n".join(names) + "\n")
    return names


def replace_entry(entries: list[ArchiveEntry], name: str, standalone_bytes: bytes) -> list[ArchiveEntry]:
    """Return a copy of `entries` with the entry named `name` replaced by
    `standalone_bytes` (a normal standalone 0SER file's bytes, e.g. from
    cf.build()/cockpit_tab.build()/mod.build() -- same form to_standalone_bytes()
    returns and unpack() writes to disk). Every other entry, and the replaced
    entry's position in the list, is unchanged, so packing the result with
    write()/to_bytes() reproduces the source archive's layout with just this one
    member's bytes swapped in -- the in-archive equivalent of unpack, edit one
    file, pack. Matching is case-insensitive, same as the rest of this codebase's
    name lookups. Raises if no entry with that name exists; this only replaces an
    existing member, it doesn't add a new one.
    """
    env = envelope.parse(standalone_bytes)
    new_entries = []
    found = False
    for e in entries:
        if e.name.lower() == name.lower():
            new_entries.append(ArchiveEntry(name=e.name, tag=env.tag, version=env.version, payload=env.payload))
            found = True
        else:
            new_entries.append(e)
    if not found:
        raise KeyError(f"no entry named {name!r} in this archive")
    return new_entries


def upsert_entry(entries: list[ArchiveEntry], name: str, standalone_bytes: bytes) -> list[ArchiveEntry]:
    """Like replace_entry(), but appends a brand-new entry instead of raising when
    `name` doesn't already exist. Deliberately separate from replace_entry() --
    the CLI patch commands (cfpatch/cockpitpatch/modpatch) want a typo in the
    target name to fail loudly, not silently create an unrelated new member.
    This is for the one case where "add if missing" is actually the intent: the
    shell's commit endpoint turning a reskin of a currently-shared/inherited
    texture (one the car doesn't own yet, e.g. a material still coming from
    race.res) into a real per-car override -- the same override mechanism cars
    already use for ball.mod/wheels in practice, just created here instead of
    requiring it to pre-exist. name is appended at the end of the archive, same
    name-matching rules as replace_entry().
    """
    try:
        return replace_entry(entries, name, standalone_bytes)
    except KeyError:
        env = envelope.parse(standalone_bytes)
        return entries + [ArchiveEntry(name=name, tag=env.tag, version=env.version, payload=env.payload)]


def pack(in_dir: Path | str, archive_path: Path | str, partitioned: bool | None = None) -> None:
    """Pack a directory of standalone 0SER files back into an archive.

    Member order comes from _manifest.txt if present (reproduces the source
    archive's exact layout for a round-trip). Without a manifest, falls back to
    alphabetical order -- note that whether the game loader actually cares about
    member order at all hasn't been independently confirmed, so alphabetical
    packing should be treated as unverified until that's checked.

    `partitioned` selects the core/bulk header convention (see ArchiveLayout).
    None means "take it from the manifest's layout line", falling back to the
    retail partitioned layout for manifests written before that line existed
    or when there's no manifest at all.
    """
    in_dir = Path(in_dir)
    manifest = in_dir / MANIFEST_NAME
    names: list[str] = []
    manifest_partitioned: bool | None = None
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                key, _, value = line[1:].partition(":")
                if key.strip().lower() == "layout":
                    manifest_partitioned = value.strip().lower() != "flat"
                continue
            names.append(line)
    else:
        names = sorted(p.name for p in in_dir.iterdir() if p.is_file())

    if partitioned is None:
        partitioned = True if manifest_partitioned is None else manifest_partitioned

    entries = []
    for name in names:
        data = (in_dir / name).read_bytes()
        env = envelope.parse(data)
        entries.append(
            ArchiveEntry(name=name, tag=env.tag, version=env.version, payload=env.payload)
        )

    Path(archive_path).write_bytes(to_bytes(entries, partitioned=partitioned))
