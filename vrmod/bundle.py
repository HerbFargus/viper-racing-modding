"""Part bundles -- a shareable horn ball, wheel or other swappable part.

A bundle is a flat zip of GAME-FORMAT members that get merged into a .car:

    herb_sosc-missile.zip
      ball.mod        the mesh
      misc061.tex     the textures it names
      misc096.tex
      ...
      horn.sfx        a sound, if the part has one

No manifest. The file extensions already say what everything is, order does not
matter for a merge, and a listed-but-missing entry is a failure mode that cannot
occur if the zip's contents ARE the contents. (`_manifest.txt` exists for packing
a whole car, where layout and ordering matter -- a different job.)

WHY GAME FORMATS AND NOT OBJ/PNG/WAV. A .tex records a wrap mode, a colorkey
flag and a mip chain; a PNG records none of them, so converting one at install
time means something other than the author picks those. This project has been
bitten there already -- a new texture needs wrap=1, and wrap=0 makes the game
reject it outright. Likewise the mesh: obj2mod recomputes vertex normals and
re-derives material ranges, and OBJ cannot express "these faces are double-sided
on purpose" as against "this mesh is inside out".

The deeper reason is reproducibility. With game formats, what the author tested
is byte-identical to what the player installs. With sources, the artefact is
whatever the converter produced that day, so changing the converter silently
rewrites every bundle in a gallery. Editing is still one command away either
way: mod2obj/obj2mod and sfx2wav/wav2sfx both round-trip losslessly.

NAMING: <author>_<part-name>.zip -- underscore splits author from part, hyphens
inside either half. A car needs none of this: it carries its own display name in
<prefix>1.tab and namespaces its members by a unique prefix. A horn ball can do
neither, because the engine hardcodes the bare name `ball.mod` -- so every bundle
in existence has identical member names and the zip filename is its only
identity.

KNOWN, NOT GUARDED: bundles share one texture namespace. Meshes and textures
are cached once globally by bare name (measured -- see file-formats.md), so two
bundles that pick the same texture name would fight, and a mesh whose texture
lives in another car's archive resolves or does not depending on who else is in
the race. `missile.py` hardcodes its texture name, so every missile bundle it
exports is `misall.tex`.

Deliberately left alone. It takes two DIFFERENT bundles in one race to collide;
in singleplayer the whole AI field drives the primary car, so only one horn ball
is ever in play, and multiplayer is documented as collapsing to a single ball
anyway. Naming textures from the bundle's own identity (`herbmis0.tex` fits the
12-character limit) is the fix if it ever does bite -- revisit then, with a real
clash to look at, rather than building for a case that may not be reachable.

THE RULES, and which are worth refusing over. Everything in the BAD list fails
SILENTLY in game -- no error, just wrong pixels or nothing at all -- which is
precisely why it is worth catching here:

    BAD   a texture the mesh names is not in the bundle (and is not one of the
          stock shared names every install already has)
    BAD   a .tex name over 12 characters          -> renders as flat colour
    BAD   a texture not square, not a power of two, or over 256px
    BAD   a UV addressing outside its page
    INFO  how many textures the bundle carries

Texture count is INFO on purpose. Multi-texture is normal -- only 36% of stock
meshes use a single one -- and for a prop it is usually BETTER: one flat colour
per texture makes the texture name a part name ("this one is the fins"), which a
colour picker can expose directly. Consolidating into one atlas throws that
mapping away and saves, measured on the missile, 4KB of 77.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import archive, car, mod, tex

NAME_LIMIT = 12
MAX_TEX = 256
NAME_RE = re.compile(r"^(?P<author>[A-Za-z0-9]+)_(?P<part>[A-Za-z0-9][A-Za-z0-9-]*)$")

BAD, WARN, INFO, OK = "bad", "warn", "info", "ok"


@dataclass
class Finding:
    level: str
    message: str


@dataclass
class Report:
    name: str
    author: str | None = None
    part: str | None = None
    members: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """BAD (refuse) > WARN (works, but affects other cars) > OK.

        INFO is deliberately NOT a verdict level. Every report carries at least
        one -- the member count -- so folding it in here would mean no bundle
        could ever come back OK.
        """
        if any(f.level == BAD for f in self.findings):
            return BAD
        if any(f.level == WARN for f in self.findings):
            return WARN
        return OK

    def add(self, level: str, message: str) -> None:
        self.findings.append(Finding(level, message))


def _is_pow2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


def inspect(zip_path: str | Path) -> Report:
    """Check a bundle zip against the rules above. Reads, never writes."""
    zip_path = Path(zip_path)
    rep = Report(name=zip_path.name)

    m = NAME_RE.match(zip_path.stem)
    if m:
        rep.author, rep.part = m.group("author"), m.group("part")
    else:
        rep.add(INFO, f"filename is not <author>_<part-name>: {zip_path.stem!r}")

    with zipfile.ZipFile(zip_path) as z:
        entries = {Path(n).name: z.read(n) for n in z.namelist()
                   if not n.endswith("/")}
        nested = [n for n in z.namelist() if "/" in n.rstrip("/")]
    rep.members = sorted(entries)
    if nested:
        rep.add(INFO, f"{len(nested)} member(s) sit in a subfolder; a bundle is flat")

    meshes = {n: b for n, b in entries.items() if n.lower().endswith(".mod")}
    textures = {n: b for n, b in entries.items() if n.lower().endswith(".tex")}
    sounds = [n for n in entries if n.lower().endswith(".sfx")]
    if not meshes:
        rep.add(BAD, "no .mod in the bundle")

    for name, blob in sorted(textures.items()):
        if len(name) > NAME_LIMIT:
            rep.add(BAD, f"{name} is {len(name)} characters, over the {NAME_LIMIT} "
                         f"a .tex name may use -- the game renders it flat")
        try:
            info = tex.parse(blob)
        except Exception as exc:
            rep.add(BAD, f"{name} will not parse as a .tex: {exc}")
            continue
        if not _is_pow2(info.size) or info.size > MAX_TEX:
            rep.add(BAD, f"{name} is {info.size}x{info.size}; must be square, a "
                         f"power of two, and no larger than {MAX_TEX}")

    have = {n.lower() for n in textures}
    shared = {s.lower() for s in car.STOCK_SHARED_TEX}
    for name, blob in sorted(meshes.items()):
        try:
            mesh = mod.parse(blob)
        except Exception as exc:
            rep.add(BAD, f"{name} will not parse as a .mod: {exc}")
            continue
        for mat in sorted({mt.name for mt in mesh.materials}):
            low = mat.lower()
            if low in have:
                continue
            if low in shared:
                rep.add(INFO, f"{name} uses the stock shared texture {mat} -- on "
                              f"every install, but it is not yours, and a swap "
                              f"must not delete it")
            else:
                rep.add(BAD, f"{name} names {mat}, which is not in the bundle")
        off = [v for v in mesh.vertices if v.u > 1.0 or v.v > 1.0]
        if off:
            rep.add(BAD, f"{name} has {len(off)} vertex/vertices addressing "
                         f"outside their page (max u {max(v.u for v in off):.3f}, "
                         f"v {max(v.v for v in off):.3f})")

    # Carrying a file under a STOCK SHARED NAME changes other people's cars.
    # Measured: a car holding a magenta ucar.tex displayed none of it -- none of
    # its own meshes reference that name -- and repainted the undercarriage of
    # every stock Viper in the race. Meshes and textures are cached once globally
    # by bare name, so the supplying car does not even have to use the asset.
    #
    # WARN rather than BAD: it works, and someone may want it. But it is
    # invisible from every angle except the one nobody checks -- the mod looks
    # right, the game says nothing, and the damage appears on the rest of the
    # field. That is worth saying out loud.
    #
    # Checked against the fixed stock list rather than against whatever the
    # current install happens to reference. A bundle is shared; the tool cannot
    # know which install it will land on, and computing a narrower surface from
    # one install would give false confidence on every other.
    for name in sorted(set(textures) | set(meshes) | set(sounds)):
        if name.lower() in {s.lower() for s in car.STOCK_SHARED_TEX}:
            rep.add(WARN, f"{name} is a stock SHARED name -- installing this bundle "
                          f"changes it for every car in the race, not just this one, "
                          f"even if nothing in the bundle uses it")

    rep.add(INFO, f"{len(textures)} texture(s), {len(meshes)} mesh(es), "
                  f"{len(sounds)} sound(s)")
    return rep


def sweep_on_swap_entries(entries, outgoing_mesh: str = "ball.mod") -> list[str]:
    """sweep_on_swap against an already-read entry list (the commit path has one)."""
    by_name = {e.name.lower(): e for e in entries}
    raw = by_name.get(outgoing_mesh.lower())
    if raw is None:
        return []
    try:
        mine = {mt.name.lower()
                for mt in mod.parse(raw.to_standalone_bytes()).materials}
    except Exception:
        return []
    others: set[str] = set()
    for name, e in by_name.items():
        if not name.endswith(".mod") or name == outgoing_mesh.lower():
            continue
        try:
            others |= {mt.name.lower()
                       for mt in mod.parse(e.to_standalone_bytes()).materials}
        except Exception:
            continue
    shared = {s.lower() for s in car.STOCK_SHARED_TEX}
    return sorted(by_name[n].name for n in (mine - others - shared) if n in by_name)


def sweep_on_swap(car_path: str | Path, outgoing_mesh: str = "ball.mod") -> list[str]:
    """Texture members belonging to the part being replaced, and only to it.

    The outgoing mesh's own material records name its textures, so the mesh IS
    the list of what to remove -- no bookkeeping needed. Two things are held
    back: the stock shared textures, which every install owns and no part may
    delete (the stock horn ball uses wheels.tex, and taking that with it would
    strip the texture off every wheel on the car), and anything another mesh in
    the archive still refers to.
    """
    return [n.lower() for n in
            sweep_on_swap_entries(archive.read(Path(car_path)), outgoing_mesh)]
