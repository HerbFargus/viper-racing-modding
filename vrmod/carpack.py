"""Read a community car pack without unpacking it.

WHY. The community's cars survive as ~1,700 loose .rar and .zip archives across
several collections, and almost nothing is known about them in bulk: who made
each one, what it contains, which are duplicates of each other, which are
conversions from another game. Answering that by hand is not feasible, and
every plan for a hosted gallery needs it first -- the catalogue is the durable
asset, more so than any particular place the bytes happen to live.

So this reads a pack in place and reports what is in it. It never writes to the
archive and never repacks: the original file, and its hash, stay the record of
what the author actually uploaded.

FORMATS. .zip goes through the standard library. .rar needs an external tool --
there is no rar reader in the stdlib and the reference unrar is not free -- so
7-Zip is shelled out to, which handles both and is already present on most
Windows machines. `sevenzip()` finds it; without it, .rar packs are reported as
unreadable rather than silently skipped, because a silent skip would quietly
drop 1,480 of the 1,667 packs from the index.

EMAIL ADDRESSES. These readmes are twenty-year-old personal files and most carry
the author's home email. The packs themselves are left exactly as they are, but
an index built from them is a different thing -- it gets published, and it is
searchable in a way a .txt inside a .rar never was. So `describe()` redacts
addresses out of the text it records by default. `keep_domains` exists for the
cases where an address is a company one and redacting it would lose real
provenance rather than protect anyone.

NAMES ARE KEPT. The authorship is the point: these readmes are often the only
surviving record that a particular person made a particular car, and several of
the people named are credited nowhere else. Attribution is extracted and stored.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SEVENZIP_ENV = "VRMOD_SEVENZIP"
_SEVENZIP_CANDIDATES = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
)

TEXT_SUFFIXES = (".txt", ".nfo", ".diz", ".me")
# Add-on tracks ship as .tra (the track archive); .trk is the slot file a
# few packs carry instead. Recording only .trk made every real track pack
# look as though it shipped nothing -- 269 of them.
CAR_SUFFIXES = (".car",)
TRACK_SUFFIXES = (".tra", ".trk")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".bmp")

# Cap what is pulled out of any one pack: a readme is a few KB, and a pack that
# claims a 50 MB .txt is either broken or hostile.
MAX_TEXT_BYTES = 256 * 1024

_EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+(?:\.[\w-]+)+)\b")

# "Stock.car CONVERTED from one of my games to VIPER RACING   Jan 10 2008 BY:"
# followed by the author on the next non-blank line. The template is Val's and
# is by far the most common, but the parser only claims a name when it sees the
# marker -- a guess here would be worse than a blank.
_BY_LINE = re.compile(r"\bBY\s*:\s*$", re.I | re.M)

# Frank Wolf's packs use a different shape entirely:
#   name: Ferrari 250 GTO (4 litre) 1962
#   imported from SCGT to Viper format by Frank P. Wolf
# Both templates are matched explicitly. Anything fitting neither is left blank
# rather than guessed at -- a wrong author is worse than no author, and these
# readmes are often the only surviving credit for the person who did the work.
_BY_INLINE = re.compile(
    r"(?:converted|imported|made|created|modified)\b[^.\n]{0,60}?\bby\s+"
    r"([A-Za-z][\w.'\- ]{2,40})", re.I)
_TITLE = re.compile(r"^\s*name\s*:\s*(\S.*?)\s*$", re.I | re.M)
_CONVERTED = re.compile(
    r"(?:converted|imported)\s+from\s+(.+?)\s+to\s+Viper", re.I)
_DATE = re.compile(
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\s+"
    r"(?:19|20)\d\d)\b", re.I)


class CarPackError(RuntimeError):
    """The pack cannot be read."""


@dataclass
class Member:
    name: str
    size: int

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()


@dataclass
class PackInfo:
    path: str
    collection: str
    filename: str
    kind: str                      # "zip" | "rar"
    size: int
    sha256: str
    # Size + mtime is what lets an index skip a pack it has already read. The
    # sha256 is the identity; this pair is just the cheap "has it changed?"
    # test, so a re-index costs seconds instead of re-hashing 1.8 GB.
    mtime: float = 0.0
    members: list[Member] = field(default_factory=list)
    cars: list[str] = field(default_factory=list)
    tracks: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    readme: str | None = None
    readme_name: str | None = None
    title: str | None = None
    author: str | None = None        # canonical, for grouping
    author_raw: str | None = None    # exactly as the readme wrote it
    converted_from: str | None = None
    dated: str | None = None
    emails_redacted: int = 0
    error: str | None = None

    def to_json(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "members"}
        d["members"] = [{"name": m.name, "size": m.size} for m in self.members]
        return d


def sevenzip() -> Path | None:
    """7-Zip, from $VRMOD_SEVENZIP, PATH, or the usual install locations."""
    env = os.environ.get(SEVENZIP_ENV)
    if env and Path(env).is_file():
        return Path(env)
    found = shutil.which("7z") or shutil.which("7za")
    if found:
        return Path(found)
    for c in _SEVENZIP_CANDIDATES:
        if Path(c).is_file():
            return Path(c)
    return None


def _run7z(args: list[str], *, binary: bool = False):
    exe = sevenzip()
    if exe is None:
        raise CarPackError(
            "no 7-Zip found, so .rar packs cannot be read. Install it, or point "
            f"{SEVENZIP_ENV} at 7z.exe. (.zip packs do not need it.)")
    p = subprocess.run([str(exe)] + args, capture_output=True,
                       timeout=120)
    if p.returncode != 0:
        raise CarPackError(
            f"7-Zip failed ({p.returncode}): "
            f"{p.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def members(path: str | Path) -> list[Member]:
    """Every file in the pack, without extracting it."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(p) as z:
                return [Member(i.filename, i.file_size) for i in z.infolist()
                        if not i.is_dir()]
        except (zipfile.BadZipFile, OSError) as e:
            raise CarPackError(f"not a readable zip: {e}")
    out, name = [], None
    for line in _run7z(["l", "-slt", str(p)]).splitlines():
        if line.startswith("Path = "):
            name = line[7:]
        elif line.startswith("Folder = ") and line[9:].strip() == "+":
            name = None                       # a directory entry, not a file
        elif line.startswith("Size = ") and name:
            try:
                out.append(Member(name, int(line[7:] or 0)))
            except ValueError:
                pass
            name = None
    # 7-Zip's first "Path =" is the archive itself; drop it.
    return [m for m in out if Path(m.name).name != p.name]


def read_member(path: str | Path, name: str, limit: int = MAX_TEXT_BYTES) -> bytes:
    """One member's bytes, truncated to `limit`."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            with z.open(name) as f:
                return f.read(limit)
    return _run7z(["e", "-so", str(p), name], binary=True)[:limit]


def redact_emails(text: str, keep_domains: tuple[str, ...] = ()) -> tuple[str, int]:
    """Replace email addresses with a marker. Returns (text, count).

    keep_domains: addresses at these domains are left alone -- for company
    addresses, where the address IS the provenance and removing it loses
    information without protecting anybody.
    """
    n = 0

    def sub(m: re.Match) -> str:
        nonlocal n
        if m.group(1).lower() in keep_domains:
            return m.group(0)
        n += 1
        return "[email redacted]"

    return _EMAIL.sub(sub, text), n


def author_of(text: str) -> str | None:
    """The author line, when the readme uses the community's `BY:` template."""
    m = _BY_LINE.search(text)
    if m:
        for line in text[m.end():].splitlines():
            s = line.strip().strip(".").strip()
            if s:
                return s[:120]
    m = _BY_INLINE.search(text)
    if m:
        name = m.group(1).strip().rstrip(".,").strip()
        # "made by my friend Enigma_Incognito" -- the filler is not the name.
        name = re.sub(r"^(?:my\s+(?:friend|buddy|mate|pal)\s+|the\s+)", "",
                      name, flags=re.I).strip()
        return None if name.lower() in ("me", "myself", "author", "") else name
    return None


def converted_from(text: str) -> str | None:
    m = _CONVERTED.search(text)
    if not m:
        return None
    # "my NFS4 game" -> "NFS4"; "one of my games" names nothing at all.
    src = re.sub(r"^(?:one of\s+)?my\s+", "", m.group(1).strip(), flags=re.I)
    src = re.sub(r"\s*\bgames?$", "", src, flags=re.I).strip(" .,")
    return src[:80] or None


# Author strings as written, and who they actually are. Only entries that can
# be verified from the readmes themselves are here: Val signs 995 packs under
# eight spellings of the same Moose Jaw line, Frank signs as both his full name
# and initials, and "an UNKNOWN AUTHOR" is a stock phrase in Val's template
# meaning the opposite of an attribution. Everything else is left exactly as
# written -- collapsing two names that merely look similar would invent a
# credit, and these readmes are often the only credit a person has.
_NOT_A_NAME = re.compile(
    r"^(?:an?\s+)?unknown\s+author\b|^me\b|^i\s|^the\s+author$", re.I)
_ALIASES = (
    (re.compile(r"^val\b(?:\s+in\s+moose\s+jaw\b.*)?$", re.I), "Val"),
    (re.compile(r"^(?:frank\s+p\.?\s*wolf|f\.?\s*p\.?\s*wolf)\.?$", re.I),
     "Frank P. Wolf"),
    (re.compile(r"^sucahyo$", re.I), "Sucahyo"),
)


def canonical_author(raw: str | None) -> str | None:
    """One spelling per person, or None when the string is not an attribution."""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.replace(",", " ")).strip(" .,-")
    if not s or _NOT_A_NAME.match(s):
        return None
    for pat, name in _ALIASES:
        if pat.match(s):
            return name
    return re.sub(r"\s+", " ", raw.strip(" .,-"))[:120]


def title_of(text: str) -> str | None:
    """The human-readable car name, when the readme states one."""
    m = _TITLE.search(text)
    return m.group(1).strip()[:120] if m else None


def dated(text: str) -> str | None:
    m = _DATE.search(text)
    return m.group(1) if m else None


def describe(path: str | Path, *, collection: str = "",
             keep_domains: tuple[str, ...] = ()) -> PackInfo:
    """Everything this can say about one pack. Never raises: errors are recorded."""
    p = Path(path)
    info = PackInfo(
        path=str(p), collection=collection, filename=p.name,
        kind=p.suffix.lower().lstrip("."), size=p.stat().st_size,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        mtime=p.stat().st_mtime,
    )
    try:
        info.members = members(p)
    except CarPackError as e:
        info.error = str(e)
        return info

    info.cars = sorted(m.name for m in info.members if m.suffix in CAR_SUFFIXES)
    info.tracks = sorted(m.name for m in info.members if m.suffix in TRACK_SUFFIXES)
    info.images = sorted(m.name for m in info.members if m.suffix in IMAGE_SUFFIXES)

    texts = [m for m in info.members if m.suffix in TEXT_SUFFIXES]
    # Prefer the biggest readme: packs often carry a stub alongside the real one.
    for m in sorted(texts, key=lambda m: -m.size):
        try:
            raw = read_member(p, m.name)
        except CarPackError:
            continue
        text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
        if not text.strip():
            continue
        info.readme_name = m.name
        info.title = title_of(text)
        info.author_raw = author_of(text)
        info.author = canonical_author(info.author_raw)
        info.converted_from = converted_from(text)
        info.dated = dated(text)
        info.readme, info.emails_redacted = redact_emails(text, keep_domains)
        break
    return info


# ---------------------------------------------------------------------------
# Joining the corpus index to a rendered asset.
#
# Two catalogues describe these mods and neither is redundant:
#
#   the corpus index (this module)  -- every ARCHIVE: hash, author, date, which
#                                      game it was converted from, the readme.
#                                      Provenance. Covers all 2,035 packs.
#   the gallery manifest            -- every extracted ASSET: its garage name and
#                                      spec, parts, vertex count, texture
#                                      portability, a baked thumbnail. What the
#                                      thing IS. Covers what has been curated.
#
# The join is the asset's filename, which the corpus records for every pack. On
# the real collection 93% of asset names are claimed by exactly one pack, so the
# gallery can inherit a person and a date for most of what it shows.
#
# The other 7% are not corruption -- they are retexture and add-on packs
# shipping the STOCK file alongside their own: viper.car appears in 31 packs,
# nfield.trk in 7. `provenance_for` returns nothing for an ambiguous name rather
# than picking one, because picking would credit MGI's own car to whoever last
# repacked it.

def load_manifest(path: str | Path) -> dict:
    """Read a manifest written by scripts/index_carpacks.py."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "items" not in data:
        raise CarPackError(f"{path} is not a carpack manifest (no 'items')")
    return data


_PROVENANCE_FIELDS = ("path", "sha256", "collection", "filename", "author",
                      "author_raw", "title", "dated", "converted_from",
                      "readme_name")


def provenance_index(manifest: dict) -> dict[str, list[dict]]:
    """asset filename (lowercased) -> the pack(s) shipping it."""
    out: dict[str, list[dict]] = {}
    for item in manifest.get("items", ()):
        summary = {k: item.get(k) for k in _PROVENANCE_FIELDS}
        for name in list(item.get("cars") or ()) + list(item.get("tracks") or ()):
            key = name.replace("\\", "/").split("/")[-1].lower()
            out.setdefault(key, []).append(summary)
    return out


def provenance_for(index: dict[str, list[dict]], filename: str) -> dict | None:
    """The pack an asset came from, only when exactly one pack claims it.

    Ambiguity returns None on purpose -- see the note above.
    """
    packs = index.get(Path(filename).name.lower(), ())
    return dict(packs[0]) if len(packs) == 1 else None
