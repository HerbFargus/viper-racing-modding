"""Track-level operations -- packaging a track archive for installation.

The game exposes only EIGHT fixed track slots (see SLOTS), so a modded track
reaches the game one of two ways: overwrite a stock <slot>.trk in Data/, or
ship a .tra that the community trackman tool swaps into a slot. This module
handles the second, which is the shareable one.

.tra and .trk are the SAME 0TSR container -- same directory format, same
internal member names (track.grf, track.bpp, ...). They differ only in the
core/bulk header convention (see archive.ArchiveLayout):

  partitioned  every retail .trk/.car/.res -- bulk-tagged members (.tex,
               .ili, .dnt) moved to the end, coreCount marking the split.
  flat         every fan-made .tra checked -- coreCount == entryCount, no
               bulk section declared, bulk members left interleaved.

The game loads both, so exporting is fundamentally a repack under a chosen
convention, not a format conversion. Default is `flat`, matching what the
existing .tra ecosystem produces, on the reasoning that trackman was written
against those files. sunretx.tra is the precedent that matters: a 50-member,
15,635-vertex full replacement of the nfield slot, shipped flat, so a
stock-sized track is known to work under that convention.

REQUIRED_MEMBERS below is the exact set common to all 15 track archives on
hand (8 stock .trk + 7 fan .tra), so it's an observed invariant rather than a
guess. Note trackmap.stp is one of them -- the in-game map is per-track and
lives in the archive, while the track-select screenshot is a separate
<slot>.stp inside ui.res.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import archive, envelope, ili

# The eight slots the game ships. A .tra is installed by swapping it over one
# of these, so a track's slot identity comes from where it lands, not from
# anything inside the file.
SLOTS = (
    "bemidji", "dundas", "hastings", "heaven",
    "kenyon", "limbo", "nfield", "uptown",
)

# Present in all 8 stock .trk AND all 7 fan .tra -- treated as the minimum a
# loadable track must carry.
REQUIRED_MEMBERS = (
    "aidef.ccs", "camera.tab", "default.ili", "rdefault.ili",
    "sky1.tex", "sky2.tex", "sky3.tex", "sky4.tex",
    "track.bpp", "track.bsp", "track.grf", "track.ild",
    "track.obt", "track.sol", "trackmap.stp",
)

LAYOUTS = ("flat", "partitioned", "preserve")


class TrackExportError(ValueError):
    """The source archive isn't a usable track bundle."""


@dataclass
class ExportResult:
    dest: Path
    member_count: int
    layout: str
    byte_identical: bool
    # Members that look tied to a specific slot (a <slot>.ccs). Harmless to
    # carry along -- sunretx.tra ships nfield.ccs -- but worth surfacing,
    # since a bemidji.ccs riding inside a track destined for the dundas slot
    # is the kind of thing that's confusing to debug later.
    slot_specific: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def inspect(path: Path | str) -> tuple[list[archive.ArchiveEntry], archive.ArchiveLayout]:
    data = Path(path).read_bytes()
    return archive.read_bytes(data), archive.read_layout(data)


def export_tra(
    src: Path | str,
    dest: Path | str,
    *,
    layout: str = "flat",
    require_members: bool = True,
) -> ExportResult:
    """Repack a track archive (.trk or .tra) as a .tra under `layout`.

    Every member is carried through byte for byte; only the container header
    convention and member ordering can change. Passing layout="preserve" on a
    file that already uses the target convention is therefore a byte-identical
    copy, which `ExportResult.byte_identical` reports.
    """
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}, got {layout!r}")

    src = Path(src)
    dest = Path(dest)
    src_bytes = src.read_bytes()
    entries = archive.read_bytes(src_bytes)
    src_layout = archive.read_layout(src_bytes)

    names = {e.name.lower() for e in entries}
    missing = [m for m in REQUIRED_MEMBERS if m not in names]
    if missing and require_members:
        raise TrackExportError(
            f"{src.name} is missing {len(missing)} member(s) every known track carries: "
            f"{', '.join(missing)}. Pass require_members=False to export anyway."
        )

    partitioned = {
        "flat": False,
        "partitioned": True,
        "preserve": src_layout.partitioned,
    }[layout]

    out = archive.to_bytes(entries, partitioned=partitioned)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)

    stem = src.stem.lower()
    slot_specific = sorted(
        e.name for e in entries
        if e.name.lower().endswith(".ccs")
        and e.name.lower() != "aidef.ccs"
        and e.name.lower()[:-4] in SLOTS
        and e.name.lower()[:-4] != stem
    )
    return ExportResult(
        dest=dest,
        member_count=len(entries),
        layout=layout,
        byte_identical=(out == src_bytes),
        slot_specific=slot_specific,
        missing=missing,
    )


# The game's Track Info screen reports a length reproduced EXACTLY, for all 8
# stock tracks, by scaling the arc length of track.ild -- the timing/centre
# line, not either racing line -- by this constant and rounding to 0.1 mile.
# Solving each track independently for the factor that rounds to its displayed
# figure leaves one consistent window of [1.0127, 1.0175), so this is a real
# relationship rather than a fit; the ~1.5% is the true centreline running
# marginally longer than the stored waypoints.
LENGTH_LINE = "track.ild"
LENGTH_SCALE = 1.0151
METRES_PER_MILE = 1609.34


def length_miles(source) -> float | None:
    """Track length in miles, as the game itself reports it.

    Accepts a path to a .trk/.tra or an already-read entry list. Returns None
    when the archive carries no centre line.
    """
    entries = source if isinstance(source, list) else archive.read(source)
    entry = next((e for e in entries if e.name.lower() == LENGTH_LINE), None)
    if entry is None:
        return None
    try:
        points = ili.parse(envelope.build(entry.tag, entry.version, entry.payload))
    except Exception:
        return None
    if not points:
        return None
    return points[-1].distance * LENGTH_SCALE / METRES_PER_MILE
