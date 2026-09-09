"""Catalogue a collection of Viper Racing cars into one structured dataset.

Walks a directory of cars -- loose `.car` files and/or the one-zip-per-car
packaging the community actually distributed (`<name>.car` + `<name>.jpg` +
a readme) -- and pulls out, for every car:

  * its filename, internal prefix and in-game display name;
  * which of the engine's FIXED part slots it fills (see PART_SLOTS);
  * its full `.cf` physics stats and its showroom spec card (`<prefix>1.tab`);
  * geometry size (total/peak vertices, so "does this need a patched race.bin");
  * and whatever the readme says about author, base car and source game.

The readme fields are the only soft ones, so every one of them carries its own
confidence (see Provenance): `parsed` when a known pattern matched, `guessed`
when a loose heuristic did, absent when the readme simply doesn't say. Nothing
is inferred silently -- a blank means the readme didn't state it.

Email addresses found in readmes are redacted. These are twenty-year-old
personal addresses in files people distributed for a game; they add nothing to
a catalogue and republishing them isn't ours to do.
"""
from __future__ import annotations

import io
import json
import re
import struct
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import archive, cf, envelope, mod as mod_mod
from . import car as car_mod

# The engine builds member names from hardcoded format strings and looks up
# exactly these -- it never enumerates the archive (see the runtime doc). So a
# car has 12 own-name model slots and nothing else: an extra .mod under any
# other name is never loaded. The suffix is what follows the car's prefix.
PART_SLOTS: dict[str, str] = {
    "0": "body (LOD0)", "1": "LOD1", "2": "LOD2", "3": "LOD3",
    "4": "LOD4", "5": "LOD5", "6": "LOD6", "7": "LOD7",
    "b": "brake lights", "c": "cockpit", "s": "spoiler", "w": "steering wheel",
}

# Fixed-name parts that normally come from race.res. A car may SHIP its own copy
# to override the shared default (every Mario-Kart conversion does this with the
# wheels), so their presence is a real property of the car, not of the install.
SHARED_OVERRIDES = (
    "needle.mod", "ball.mod", "brakelt.mod", "diskglow.mod", "xray.mod",
    "wheel_1.mod", "wheel_2.mod", "wheel_3.mod",
    "fwheel_1.mod", "fwheel_2.mod", "fwheel_3.mod",
    "spin_l.mod", "spin_r.mod",
)

def _sevenzip() -> str | None:
    """Path to a 7-Zip binary, or None.

    The community distributed most of its cars as RAR, which the standard library
    cannot read and which has no pure-Python decoder worth depending on. 7-Zip is
    the pragmatic answer: ubiquitous on Windows, reads RAR fine, and shelling out
    keeps it an optional capability -- without it .rar files are reported as
    skipped rather than silently dropped from the catalogue.
    """
    import shutil as _sh
    found = _sh.which("7z") or _sh.which("7za")
    if found:
        return found
    for c in (str(Path("C:/Program Files/7-Zip/7z.exe")), str(Path("C:/Program Files (x86)/7-Zip/7z.exe"))):
        if Path(c).is_file():
            return c
    return None


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TAB_FIELD = 33          # same fixed-width field car.set_car_name writes


@dataclass
class Provenance:
    """A readme-derived value plus how much to trust it."""
    value: str | None = None
    confidence: str | None = None      # "parsed" | "guessed" | None


@dataclass
class CarRecord:
    filename: str
    collection: str = ""
    container: str = ""                # the .zip/.rar it came from, "" if loose
    container_path: str = ""           # that container's path relative to the scan root
    size: int = 0
    prefix: str | None = None
    display_name: str | None = None
    parts: dict = field(default_factory=dict)        # slot suffix -> bool
    overrides: list = field(default_factory=list)    # shared parts it ships itself
    lod_levels: int = 0
    stats: dict = field(default_factory=dict)        # .cf physics
    spec: dict = field(default_factory=dict)         # <prefix>1.tab showroom card
    textures: list = field(default_factory=list)
    sounds: list = field(default_factory=list)
    vertices: int = 0
    peak_vertices: int = 0
    needs_patch: bool = False
    author: Provenance = field(default_factory=Provenance)
    base_car: Provenance = field(default_factory=Provenance)
    source_game: Provenance = field(default_factory=Provenance)
    date: Provenance = field(default_factory=Provenance)
    thumbnail: str | None = None
    readme_file: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# the archive side
# ---------------------------------------------------------------------------

def _clean_text(v: str | None) -> str | None:
    """Strip control bytes out of a name read from a fixed-width field.

    The spec-sheet Name field is padded rather than terminated, and some cars
    carry stray control characters inside it (one Camaro renders as a row of
    boxes). They are not part of the name and they break the display, so drop
    anything non-printable and collapse the whitespace that leaves behind.
    """
    if not v:
        return v
    cleaned = "".join(c for c in v if c.isprintable())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def read_spec_tab(entries) -> dict[str, str]:
    """The showroom spec card (`<prefix>1.tab`) as {label: value}.

    Record 0 is "Name"; the rest are the advertised figures the car-select screen
    shows (0-60, top speed, engine, ...). Advertised, note -- these are display
    text, not the physics in the .cf, and nothing makes a car live up to them.

    Layout: recordCount and fieldsPerRecord are int32 at 0 and 4, the field WIDTH
    is int32 at 12 (33 on every car seen). The header is bigger than those ints
    -- 76 bytes on stock viper -- so rather than hardcode it we derive the data
    start from the end: `len(payload) - records*fields*width`, which lands exactly
    on the first field (76 + 13*2*33 = 934 = the payload length) and self-checks,
    since a wrong reading gives a negative or non-aligned offset.
    """
    e = next((x for x in entries if x.name.lower().endswith("1.tab")
              and b"Name" in x.payload[:400]), None)
    if e is None:
        return {}
    p = e.payload
    try:
        rec_count, fields_per_record = struct.unpack_from("<2i", p, 0)
        width = struct.unpack_from("<i", p, 12)[0]
    except struct.error:
        return {}
    if not (0 < rec_count < 200 and 0 < fields_per_record < 10 and 8 < width < 128):
        return {}
    start = len(p) - rec_count * fields_per_record * width
    if start < 0:
        return {}
    out: dict[str, str] = {}
    off = start
    for _ in range(rec_count):
        fields = []
        for _f in range(fields_per_record):
            raw = p[off: off + width]
            off += width
            fields.append(_clean_text(raw.split(b"\x00")[0].decode("latin-1", "replace")) or "")
        if fields and fields[0]:
            out[fields[0]] = fields[1] if len(fields) > 1 else ""
    return out


def _geometry(entries) -> tuple[int, int]:
    """(total, peak) vertices. Peak is what matters: the engine's ceiling is per
    object, so the largest single part decides whether a patched race.bin is
    needed -- a total would be misleading."""
    total = peak = 0
    for e in entries:
        if not e.name.lower().endswith(".mod"):
            continue
        try:
            m = mod_mod.parse(envelope.build(e.tag, e.version, e.payload))
        except Exception:
            continue
        total += len(m.vertices)
        peak = max(peak, len(m.vertices))
    return total, peak


def describe_car(data: bytes, filename: str) -> CarRecord:
    """Everything derivable from the .car archive itself."""
    rec = CarRecord(filename=filename, size=len(data))
    try:
        entries = archive.read_bytes(data)
    except Exception as ex:
        rec.error = f"{type(ex).__name__}: {ex}"
        return rec

    names = {e.name.lower() for e in entries}
    try:
        rec.prefix = car_mod.body_prefix(entries)
    except Exception:
        rec.prefix = None
    rec.display_name = _clean_text(car_mod.read_car_name(entries))

    if rec.prefix:
        pl = rec.prefix.lower()
        rec.parts = {s: f"{pl}{s}.mod" in names for s in PART_SLOTS}
        rec.lod_levels = sum(1 for s in "01234567" if rec.parts.get(s))
        rec.spec = read_spec_tab(entries)
    rec.overrides = [n for n in SHARED_OVERRIDES if n in names]
    rec.textures = sorted(e.name for e in entries if e.name.lower().endswith(".tex"))
    rec.sounds = sorted(e.name for e in entries if e.name.lower().endswith((".sfx", ".ens")))

    cfe = next((e for e in entries if e.name.lower().endswith(".cf")), None)
    if cfe is not None:
        try:
            rec.stats = cf.parse(envelope.build(cfe.tag, cfe.version, cfe.payload))
        except Exception:
            pass
    rec.vertices, rec.peak_vertices = _geometry(entries)
    rec.needs_patch = rec.peak_vertices > mod_mod.VERTEX_BUDGETS["original"]
    return rec


# ---------------------------------------------------------------------------
# the readme side -- the only soft data, so everything is confidence-tagged
# ---------------------------------------------------------------------------

def redact(text: str) -> str:
    """Drop email addresses. See the module docstring."""
    return _EMAIL.sub("[email removed]", text)


def parse_readme(text: str) -> dict[str, Provenance]:
    """Pull author / base car / source game / date out of a car's readme.

    Two house styles cover most of the corpus and are matched exactly ("parsed");
    anything else falls back to loose patterns ("guessed"). A field the readme
    doesn't state is left absent rather than filled in.
    """
    out = {k: Provenance() for k in ("author", "base_car", "source_game", "date")}
    t = text.replace("\r\n", "\n")

    # Style A (Frank P. Wolf): a small key: value block, then a conversion line.
    #   name: Ferrari 250 GTO (4 litre) 1962
    #   imported from SCGT to Viper format by Frank P. Wolf
    m = re.search(r"^\s*name\s*:\s*(.+?)\s*$", t, re.I | re.M)
    if m:
        out["base_car"] = Provenance(m.group(1).strip(), "parsed")
    m = re.search(r"imported\s+from\s+(.+?)\s+to\s+viper(?:\s+format)?\s+by\s+(.+?)\s*$",
                  t, re.I | re.M)
    if m:
        out["source_game"] = Provenance(m.group(1).strip(), "parsed")
        out["author"] = Provenance(m.group(2).strip(" .\t"), "parsed")

    # Style B (Val): "<car> CAR CONVERTED FROM <source> TO VIPER RACING <date> BY:"
    # with the author on the following non-empty line.
    m = re.search(r"converted\s+from\s+(.+?)\s+to\s+viper\s+racing\s*(.*?)\s*by\s*:?\s*\n+\s*(.+?)\s*$",
                  t, re.I | re.S | re.M)
    if m:
        src, when, who = (g.strip() for g in m.groups())
        if not out["source_game"].value and src:
            out["source_game"] = Provenance(src, "parsed")
        if when:
            out["date"] = Provenance(when, "parsed")
        if not out["author"].value and who:
            # Val's line is "VAL IN MOOSE JAW , SASKATCHEWAN , CANADA" -- keep the
            # name, drop the address, which is location not authorship.
            out["author"] = Provenance(re.split(r"\s+IN\s+|,", who)[0].strip(), "parsed")

    # Loose fallbacks, clearly marked as such.
    if not out["author"].value:
        m = re.search(r"(?:converted|created|made|built|modell?ed)\s+(?:for\s+viper\s+)?by[:\s]+(.+?)\s*$",
                      t, re.I | re.M)
        if m:
            cand = m.group(1).strip(" .\t")
            # "made by" also appears mid-sentence ("...are converted from X by
            # superimposing method"), which yields prose, not a person. Require
            # something name-shaped: short, and free of obvious sentence glue.
            if len(cand) <= 40 and not re.search(r"\b(are|is|was|were|the|method|using)\b", cand, re.I):
                out["author"] = Provenance(cand, "guessed")
    # A source game stated in prose ("...one of the first cars i converted from
    # SCGT to Viper..."), where no "by <author>" follows to anchor the strict
    # pattern above. Guessed, since the sentence structure is doing the work.
    if not out["source_game"].value:
        m = re.search(r"convert(?:ed)?\s+from\s+([A-Za-z0-9 .\-]{2,20}?)\s+to\s+viper", t, re.I)
        if m:
            out["source_game"] = Provenance(m.group(1).strip(), "guessed")

    # Tidy the free-text captures: readmes trail URLs, emails and asides after a
    # name ("Chris (foo@bar and hometown.aol.com/...)"), which are contact details
    # rather than authorship. Cut at the first bracket/URL and collapse the rest.
    for k in ("author", "base_car", "source_game"):
        v = out[k].value
        if not v:
            continue
        v = re.split(r"\s*[\(\[]|https?://|www\.|\S+\.(?:com|net|org|de|se)\b", v)[0]
        v = re.sub(r"\s+", " ", v).strip(" ,.-\t")
        out[k] = Provenance(v or None, out[k].confidence if v else None)
    if not out["date"].value:
        m = re.search(r"\b(\d{1,2}\s+[A-Z][a-z]{2,8}\s+(?:19|20)\d{2}|(?:19|20)\d{2})\b", t)
        if m:
            out["date"] = Provenance(m.group(1), "guessed")
    return out


# ---------------------------------------------------------------------------
# walking a collection
# ---------------------------------------------------------------------------

def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _from_zip(zpath: Path, collection: str, root: Path) -> list[CarRecord]:
    out = []
    try:
        z = zipfile.ZipFile(zpath)
    except Exception as ex:
        return [CarRecord(filename=zpath.name, collection=collection,
                          container=zpath.name, error=f"{type(ex).__name__}: {ex}")]
    names = z.namelist()
    cars = [n for n in names if n.lower().endswith(".car")]
    txts = [n for n in names if n.lower().endswith(".txt")]
    jpgs = [n for n in names if n.lower().endswith((".jpg", ".jpeg"))]
    for c in cars:
        try:
            rec = describe_car(z.read(c), Path(c).name)
        except Exception as ex:
            rec = CarRecord(filename=Path(c).name, error=f"{type(ex).__name__}: {ex}")
        rec.collection, rec.container = collection, zpath.name
        rec.container_path = _rel(zpath, root)
        stem = Path(c).stem.lower()
        # Prefer a readme/jpg whose name matches this car, else the only one there.
        pick = lambda cands: next((x for x in cands if Path(x).stem.lower().startswith(stem)),
                                  cands[0] if len(cands) == 1 else None)
        rt, rj = pick(txts), pick(jpgs)
        if rt:
            rec.readme_file = rt
            try:
                for k, v in parse_readme(redact(z.read(rt).decode("latin-1", "replace"))).items():
                    setattr(rec, k, v)
            except Exception:
                pass
        rec.thumbnail = rj
        out.append(rec)
    return out


def _from_rar(rpath: Path, collection: str, root: Path) -> list[CarRecord]:
    """Same as _from_zip, for the RAR half of the corpus.

    The community shipped far more cars as RAR than ZIP (about eight to one), so
    skipping them would leave most of the collection uncatalogued. There is no
    stdlib reader, so this shells out to 7-Zip: extract the whole (small) archive
    to a temp dir, read it, throw it away. Without 7-Zip installed the archive is
    reported as skipped -- never silently dropped.
    """
    import subprocess, tempfile, shutil as _sh
    sz = _sevenzip()
    if sz is None:
        return [CarRecord(filename=rpath.name, collection=collection,
                          container=rpath.name,
                          container_path=str(rpath.relative_to(root)),
                          error="7-Zip not found -- cannot read .rar")]
    out: list[CarRecord] = []
    with tempfile.TemporaryDirectory() as td:
        try:
            subprocess.run([sz, "e", "-y", f"-o{td}", str(rpath)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=180, check=True)
        except Exception as ex:
            return [CarRecord(filename=rpath.name, collection=collection,
                              container=rpath.name,
                              container_path=str(rpath.relative_to(root)),
                              error=f"{type(ex).__name__}: {ex}")]
        d = Path(td)
        # One case-insensitive sweep, NOT glob("*.car") + glob("*.CAR"): on
        # Windows globbing is already case-insensitive, so the two calls return
        # the same files and every car gets catalogued (and rendered) twice.
        def _by_ext(*exts: str) -> list[Path]:
            want = {e.lower() for e in exts}
            return sorted({f.resolve(): f for f in d.iterdir()
                           if f.is_file() and f.suffix.lower() in want}.values())
        cars = _by_ext(".car")
        txts = _by_ext(".txt")
        jpgs = _by_ext(".jpg", ".jpeg")
        for c in cars:
            try:
                rec = describe_car(c.read_bytes(), c.name)
            except Exception as ex:
                rec = CarRecord(filename=c.name, error=f"{type(ex).__name__}: {ex}")
            rec.collection, rec.container = collection, rpath.name
            rec.container_path = str(rpath.relative_to(root))
            stem = c.stem.lower()
            pick = lambda cands: next((x for x in cands if x.stem.lower().startswith(stem)),
                                      cands[0] if len(cands) == 1 else None)
            rt, rj = pick(txts), pick(jpgs)
            if rt is not None:
                rec.readme_file = rt.name
                try:
                    for k, v in parse_readme(redact(rt.read_text("latin-1", errors="replace"))).items():
                        setattr(rec, k, v)
                except Exception:
                    pass
            rec.thumbnail = rj.name if rj is not None else None
            out.append(rec)
    return out


def _from_loose(cpath: Path, collection: str, root: Path) -> CarRecord:
    try:
        rec = describe_car(cpath.read_bytes(), cpath.name)
    except Exception as ex:
        rec = CarRecord(filename=cpath.name, error=f"{type(ex).__name__}: {ex}")
    rec.collection = collection
    rec.container_path = _rel(cpath, root)
    stem = cpath.stem.lower()
    cands = sorted({f.resolve(): f for f in cpath.parent.iterdir()
                    if f.is_file() and f.suffix.lower() == ".txt"}.values())
    for cand in cands:
        if cand.stem.lower().startswith(stem) or cand.stem.lower().startswith(stem + "-readme"):
            rec.readme_file = cand.name
            try:
                for k, v in parse_readme(redact(cand.read_text("latin-1", errors="replace"))).items():
                    setattr(rec, k, v)
            except Exception:
                pass
            break
    for cand in (cpath.with_suffix(".jpg"), cpath.with_suffix(".JPG")):
        if cand.exists():
            rec.thumbnail = cand.name
            break
    return rec


def catalog(root: Path | str) -> list[CarRecord]:
    """Every car under `root`, loose or zipped, with its collection recorded as
    the first directory below root (so one run covers several collections)."""
    root = Path(root)
    out: list[CarRecord] = []
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        try:
            collection = p.relative_to(root).parts[0] if len(p.relative_to(root).parts) > 1 else ""
        except ValueError:
            collection = ""
        ext = p.suffix.lower()
        if ext == ".zip":
            out.extend(_from_zip(p, collection, root))
        elif ext == ".rar":
            out.extend(_from_rar(p, collection, root))
        elif ext == ".car":
            out.append(_from_loose(p, collection, root))
    return out


def to_json(records: list[CarRecord]) -> str:
    return json.dumps([asdict(r) for r in records], indent=1, ensure_ascii=False)


def to_csv(records: list[CarRecord]) -> str:
    """Flat one-row-per-car view. Nested stats/spec are flattened with a prefix;
    the parts matrix becomes one yes/no column per slot."""
    import csv
    stat_keys = sorted({k for r in records for k in r.stats})
    spec_keys = sorted({k for r in records for k in r.spec})
    cols = (["collection", "container", "filename", "prefix", "display_name",
             "author", "author_confidence", "base_car", "base_car_confidence",
             "source_game", "source_game_confidence", "date", "date_confidence",
             "lod_levels", "vertices", "peak_vertices", "needs_patch",
             "overrides", "size", "error"]
            + [f"slot_{s}" for s in PART_SLOTS]
            + [f"cf_{k}" for k in stat_keys] + [f"spec_{k}" for k in spec_keys])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in records:
        row = [r.collection, r.container, r.filename, r.prefix or "", r.display_name or "",
               r.author.value or "", r.author.confidence or "",
               r.base_car.value or "", r.base_car.confidence or "",
               r.source_game.value or "", r.source_game.confidence or "",
               r.date.value or "", r.date.confidence or "",
               r.lod_levels, r.vertices, r.peak_vertices, r.needs_patch,
               " ".join(r.overrides), r.size, r.error or ""]
        row += ["yes" if r.parts.get(s) else "no" for s in PART_SLOTS]
        row += [r.stats.get(k, "") for k in stat_keys]
        row += [r.spec.get(k, "") for k in spec_keys]
        w.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# the browsable page
# ---------------------------------------------------------------------------

_PAGE_CSS = """
:root{--bg:#f5f3ee;--card:#fff;--ink:#1b1d22;--muted:#5d6270;--line:#e3dfd5;--acc:#1a5c2e;
  --warn:#8a5a00;--chip:#eee9df}
@media(prefers-color-scheme:dark){:root{--bg:#14161b;--card:#1c1f26;--ink:#e7e9ef;
  --muted:#9096a4;--line:#2b303a;--acc:#5fbe80;--warn:#e0a24a;--chip:#252a34}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:20px 18px 60px}
h1{font-size:20px;font-weight:600;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px;margin:0 0 16px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
input,select{font:13px inherit;padding:6px 9px;background:var(--card);color:var(--ink);
  border:1px solid var(--line);border-radius:6px}
input[type=search]{min-width:260px}
label.chk{display:inline-flex;gap:6px;align-items:center;color:var(--muted);font-size:13px}
.count{color:var(--muted);font-size:13px;margin-left:auto}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
  border-radius:10px;overflow:hidden}
th,td{padding:7px 9px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
th{background:var(--chip);font-weight:600;font-size:12px;cursor:pointer;white-space:nowrap;
  position:sticky;top:0;z-index:1}
th:hover{color:var(--acc)}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--chip)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
img.thumb{width:74px;height:44px;object-fit:cover;border-radius:4px;display:block;background:var(--chip)}
.nm{font-weight:600}
.fn{color:var(--muted);font-size:12px;font-family:ui-monospace,Menlo,Consolas,monospace}
.slots{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;letter-spacing:1px;white-space:nowrap}
.on{color:var(--acc);font-weight:700}
.off{color:var(--line)}
.g{border-bottom:1px dotted var(--warn);cursor:help}
.warnpill{color:var(--warn);font-size:11px;border:1px solid var(--warn);border-radius:20px;padding:1px 6px;white-space:nowrap}
.detail td{background:var(--bg)}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.dgrid h4{margin:0 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.kv{display:grid;grid-template-columns:1fr auto;gap:1px 10px;font-size:12px}
.kv span:nth-child(even){font-variant-numeric:tabular-nums;color:var(--muted)}
"""

_PAGE_JS = r"""
const F={q:'',col:'',src:'',patch:false};
let SORT={k:'car',dir:1};
const el=id=>document.getElementById(id);
const slotOrder=Object.keys(SLOTS);
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function conf(p){
  if(!p||!p.value) return '<span class="off">--</span>';
  const g = p.confidence==='guessed';
  return '<span'+(g?' class="g" title="guessed from readme wording, not stated outright"':'')+'>'+esc(p.value)+'</span>';
}
function slots(r){
  return slotOrder.map(function(s){
    const on = r.parts && r.parts[s];
    return '<span class="'+(on?'on':'off')+'" title="'+esc(SLOTS[s])+'">'+s+'</span>';
  }).join('');
}
function val(r,k){
  if(k==='car') return (r.display_name||r.filename||'').toLowerCase();
  if(k==='author') return (r.author.value||'').toLowerCase();
  if(k==='base_car') return (r.base_car.value||'').toLowerCase();
  if(k==='source_game') return (r.source_game.value||'').toLowerCase();
  if(k==='hp') return Number(r.spec['power max']||0);
  if(k==='top') return Number(r.spec['top speed']||0);
  if(k==='lod') return r.lod_levels;
  if(k==='peak') return r.peak_vertices;
  return String(r[k]==null?'':r[k]).toLowerCase();
}
function rows(){
  const d=DATA.filter(function(r){
    if(F.col && r.collection!==F.col) return false;
    if(F.src && (r.source_game.value||'')!==F.src) return false;
    if(F.patch && !r.needs_patch) return false;
    if(F.q){
      const h=[r.filename,r.display_name,r.author.value,r.base_car.value,r.source_game.value,r.collection].join(' ').toLowerCase();
      if(h.indexOf(F.q)<0) return false;
    }
    return true;
  });
  d.sort(function(a,b){const x=val(a,SORT.k),y=val(b,SORT.k);return (x<y?-1:x>y?1:0)*SORT.dir;});
  return d;
}
function render(){
  const d=rows();
  el('count').textContent=d.length+' of '+DATA.length+' cars';
  el('tbody').innerHTML=d.map(function(r){
    const thumb=r.thumb_file?'<img class="thumb" loading="lazy" src="thumbs/'+encodeURIComponent(r.thumb_file)+'" alt="">':'';
    return '<tr data-i="'+DATA.indexOf(r)+'">'
      +'<td>'+thumb+'</td>'
      +'<td><div class="nm">'+esc(r.display_name||'--')+'</div><div class="fn">'+esc(r.filename)+'</div></td>'
      +'<td>'+esc(r.collection)+'</td>'
      +'<td>'+conf(r.author)+'</td>'
      +'<td>'+conf(r.base_car)+'</td>'
      +'<td>'+conf(r.source_game)+'</td>'
      +'<td class="slots">'+slots(r)+'</td>'
      +'<td class="num">'+r.lod_levels+'</td>'
      +'<td class="num">'+esc(r.spec['power max']||'')+'</td>'
      +'<td class="num">'+esc(r.spec['top speed']||'')+'</td>'
      +'<td class="num">'+r.peak_vertices.toLocaleString()+(r.needs_patch?' <span class="warnpill">patch</span>':'')+'</td>'
      +'</tr>';
  }).join('');
}
function kv(o){
  return Object.keys(o).map(function(k){return '<span>'+esc(k)+'</span><span>'+esc(o[k])+'</span>';}).join('');
}
function detailHTML(r){
  const parts=slotOrder.map(function(s){return '<span>'+esc(SLOTS[s])+'</span><span>'+(r.parts[s]?'yes':'--')+'</span>';}).join('');
  const geo={'total vertices':r.vertices.toLocaleString(),'largest part':r.peak_vertices.toLocaleString(),
    'needs patched race.bin':r.needs_patch?'yes':'no','textures':r.textures.length,'sounds':r.sounds.length,
    'archive':(r.size/1024).toFixed(0)+' KB','readme':r.readme_file||'--','container':r.container||'(loose)'};
  return '<td colspan="11"><div class="dgrid">'
    +'<div><h4>Spec card (advertised)</h4><div class="kv">'+kv(r.spec)+'</div></div>'
    +'<div><h4>Parts present</h4><div class="kv">'+parts+'</div>'
      +'<h4 style="margin-top:10px">Ships its own shared parts</h4>'
      +'<div style="font-size:12px;color:var(--muted)">'+(r.overrides.length?r.overrides.map(esc).join(', '):'none')+'</div></div>'
    +'<div><h4>Geometry &amp; files</h4><div class="kv">'+kv(geo)+'</div></div>'
    +'<div style="grid-column:1/-1"><h4>Physics (.cf) -- '+Object.keys(r.stats).length+' values</h4>'
      +'<div class="kv" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">'+kv(r.stats)+'</div></div>'
    +'</div></td>';
}
document.addEventListener('DOMContentLoaded',function(){
  const cols=Array.from(new Set(DATA.map(function(r){return r.collection;}).filter(Boolean))).sort();
  const srcs=Array.from(new Set(DATA.map(function(r){return r.source_game.value;}).filter(Boolean))).sort();
  el('col').innerHTML='<option value="">All collections</option>'+cols.map(function(c){return '<option>'+esc(c)+'</option>';}).join('');
  el('src').innerHTML='<option value="">Any source game</option>'+srcs.map(function(c){return '<option>'+esc(c)+'</option>';}).join('');
  el('q').addEventListener('input',function(e){F.q=e.target.value.toLowerCase().trim();render();});
  el('col').addEventListener('change',function(e){F.col=e.target.value;render();});
  el('src').addEventListener('change',function(e){F.src=e.target.value;render();});
  el('patch').addEventListener('change',function(e){F.patch=e.target.checked;render();});
  Array.prototype.forEach.call(document.querySelectorAll('th[data-k]'),function(th){
    th.addEventListener('click',function(){
      const k=th.dataset.k; SORT.dir = (SORT.k===k) ? -SORT.dir : 1; SORT.k=k; render();
    });
  });
  el('tbody').addEventListener('click',function(e){
    const tr=e.target.closest('tr'); if(!tr||tr.classList.contains('detail'))return;
    const nxt=tr.nextElementSibling;
    if(nxt&&nxt.classList.contains('detail')){nxt.remove();return;}
    Array.prototype.forEach.call(document.querySelectorAll('tr.detail'),function(x){x.remove();});
    const d=document.createElement('tr'); d.className='detail';
    d.innerHTML=detailHTML(DATA[+tr.dataset.i]); tr.after(d);
  });
  render();
});
"""


def build_page(records: list[CarRecord], out_dir: Path | str) -> Path:
    """Write a browsable table of the catalogue to out_dir/index.html.

    The dataset is embedded, so the page needs no server; only the thumbnails are
    external (they are the zips' own JPEGs, far too large to inline). Guessed
    readme values are marked in the page itself, so the distinction between
    "the readme said so" and "we inferred it" survives into what people read.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = []
    for r in records:
        d = asdict(r)
        d["thumb_file"] = r.thumbnail      # JS reads thumb_file; keep the mapping explicit
        data.append(d)
    ok = sum(1 for r in records if not r.error)
    cols = len({r.collection for r in records if r.collection})
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Viper Racing car catalogue</title><style>" + _PAGE_CSS + "</style></head><body>"
        '<div class="wrap"><h1>Viper Racing &mdash; car catalogue</h1>'
        f'<p class="sub">{ok} cars read from {cols} collection(s). Click any row for its full '
        "physics, spec card and parts. Values <span class=\"g\">underlined</span> were guessed "
        "from readme wording rather than stated outright.</p>"
        '<div class="bar"><input id="q" type="search" placeholder="Search name, file, author, base car...">'
        '<select id="col"></select><select id="src"></select>'
        '<label class="chk"><input id="patch" type="checkbox"> needs patched race.bin</label>'
        '<span class="count" id="count"></span></div>'
        "<table><thead><tr><th></th>"
        '<th data-k="car">Car</th><th data-k="collection">Collection</th><th data-k="author">Author</th>'
        '<th data-k="base_car">Based on</th><th data-k="source_game">From</th>'
        '<th>Parts</th><th data-k="lod" class="num">LODs</th>'
        '<th data-k="hp" class="num">hp</th><th data-k="top" class="num">top</th>'
        '<th data-k="peak" class="num">largest part</th>'
        '</tr></thead><tbody id="tbody"></tbody></table></div><script>\nconst DATA='
        + json.dumps(data, ensure_ascii=False) + ";\nconst SLOTS="
        + json.dumps(PART_SLOTS) + ";\n" + _PAGE_JS + "\n</script></body></html>"
    )
    p = out_dir / "index.html"
    p.write_text(html, encoding="utf-8")
    return p


def extract_thumbnails(records: list[CarRecord], root: Path | str, out_dir: Path | str) -> int:
    """Copy each car's preview JPEG out of its zip (or from beside it) into
    out_dir/thumbs/, renamed to the car's filename so the page can find it."""
    root, out_dir = Path(root), Path(out_dir)
    tdir = out_dir / "thumbs"
    tdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for r in records:
        if not r.thumbnail:
            continue
        target = tdir / (_shot_name(r) + Path(r.thumbnail).suffix.lower())
        try:
            data = _member_bytes(r, root, r.thumbnail)
            if data is None:
                r.thumbnail = None
                continue
            target.write_bytes(data)
            r.thumbnail = target.name
            n += 1
        except Exception:
            r.thumbnail = None
    return n


def _shot_name(rec: "CarRecord") -> str:
    """A filename unique across collections.

    Car names repeat both BETWEEN collections and between archives inside one
    collection (the packs re-ship the same cars), so keying a picture on the
    stem alone silently overwrote them -- 3,208 renders collapsed into 1,592
    files. Collection + archive + stem keeps every car distinct.
    """
    stem = Path(rec.filename).stem
    box = Path(rec.container).stem if rec.container else ""
    parts = [x for x in (rec.collection, box, stem) if x]
    return "_".join(parts) if len(parts) > 1 else stem


def _member_bytes(rec: "CarRecord", root: Path, member: str) -> bytes | None:
    """Read one file back out of the container a record came from.

    Uses the container path recorded during the walk. The first version searched
    for the container by name on every call, which is a full tree walk per car --
    fine for 200 cars, unusable for 1,700.
    """
    if not rec.container:
        src = root / rec.container_path if rec.container_path else None
        if src is None or not src.is_file():
            return None
        return src.read_bytes()
    cp = root / rec.container_path
    if not cp.is_file():
        return None
    if cp.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(cp) as z:
                inner = next((x for x in z.namelist()
                              if Path(x).name.lower() == member.lower()), None)
                return z.read(inner) if inner else None
        except Exception:
            return None
    # .rar -- stream the single member out through 7-Zip
    sz = _sevenzip()
    if sz is None:
        return None
    import subprocess
    try:
        r = subprocess.run([sz, "e", "-so", str(cp), member],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=180, check=True)
        return r.stdout or None
    except Exception:
        return None


def render_shots(records: list[CarRecord], root: Path | str, out_dir: Path | str,
                 paint_texture: str | Path | None = None,
                 shared_from: Path | str | None = None) -> int:
    """Render every car ourselves, into out_dir/thumbs/<stem>.png.

    Preferred over the community JPEGs the zips carry: those are inconsistent in
    angle, size and era, and a quarter of the corpus has none. A rendered shot is
    the same camera on every car, which is what makes a catalogue scannable.

    `shared_from` should be a game Data folder -- the car is staged beside its
    shared archives so wheels, glass and effect materials resolve the way they do
    in game (they live in race.res, not the car). `paint_texture` fills the
    runtime paint slot for the cars that use one.
    """
    from . import carshot
    import shutil, tempfile
    root, out_dir = Path(root), Path(out_dir)
    tdir = out_dir / "thumbs"
    tdir.mkdir(parents=True, exist_ok=True)
    shared = []
    if shared_from:
        shared = [p for p in Path(shared_from).glob("*.res") if p.is_file()]
    n = 0
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td)
        for sp in shared:                     # staged once, reused for every car
            try:
                shutil.copy2(sp, stage / sp.name)
            except OSError:
                pass
        for r in records:
            if r.error:
                continue
            try:
                data = None
                data = _member_bytes(r, root, r.filename)
                if data is None:
                    continue
                cp = stage / r.filename
                cp.write_bytes(data)
                png = carshot.to_png(cp, style="textured", wheels=True,
                                     width=320, height=190, paint_texture=paint_texture)
                out = tdir / (_shot_name(r) + ".png")
                out.write_bytes(png)
                r.thumbnail = out.name
                n += 1
            except Exception:
                # A car that will not render still belongs in the table with its
                # data; it just has no picture.
                pass
            finally:
                try:
                    (stage / r.filename).unlink(missing_ok=True)
                except OSError:
                    pass
    return n
