"""Physics presets: named sets of .cf values that give any car a known tune, keeping the car's own geometry.

A preset is a JSON file in vrmod/assets/presets/ (it ships with the app):

    {"name": "Best", "description": "...", "credit": "...", "values": {"mass": 1791.5, "power_max": 585.0, ...}}

`values` holds every .cf field the tune sets. Applying a preset to a car writes those fields into its .cf, with two
rules so the result still fits the car:

  * geometry is never carried (GEOMETRY): wheelbase, track, tyre sizes, body width and height and the ride-height
    range stay the car's own, so the wheels stay in its arches -- a preset that moved them would leave them under
    the body (a search that was allowed to move the wheelbase once squashed it to half the body's length);
  * the three moments of inertia (mx, my, mz) aren't copied but scaled by the change in mass, so a car made lighter
    is lighter to turn too, in its own proportions.

Every other field is set outright, so a preset carries its whole drivetrain, aero, suspension, brakes and diffs and
the same preset gives the same behaviour on any car body (the tyres' size aside).

The presets shipped here were made by vrmod-experiments' tune tools: an AI search over the .cf, starting from MGI's
stock Viper and scored by AI drivers' lap times on the 8 stock tracks, with handling limits (no spins in scripted
tests, no straight-line wobble, no scraping). Nothing in them comes from another author's car.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import cf

PRESET_DIR = Path(__file__).resolve().parent / "assets" / "presets"

# never carried: these place the wheels and size the body, so they belong to the car's model
GEOMETRY = frozenset({
    "wheelbase", "ftrack", "rtrack", "width", "height",
    "ftyre_width", "ftyre_aspect", "ftyre_rim", "rtyre_width", "rtyre_aspect", "rtyre_rim",
    "fground_clearance1", "fground_clearance2", "rground_clearance1", "rground_clearance2",
})
INERTIA = ("mx", "my", "mz")    # scaled with the mass, not copied


@dataclass
class Preset:
    key: str                     # the file's stem
    name: str
    description: str = ""
    credit: str = ""
    values: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"key": self.key, "name": self.name, "description": self.description, "credit": self.credit,
                "values": self.values}


def load(path: Path) -> Preset:
    """One preset file. Raises ValueError for a field .cf doesn't have, or for geometry (never carried)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    values = {str(k): float(v) for k, v in raw.get("values", {}).items()}
    unknown = sorted(k for k in values if k not in cf.FIELD_MAP)
    if unknown:
        raise ValueError(f"{Path(path).name}: not .cf fields: {', '.join(unknown)}")
    carried = sorted(k for k in values if k in GEOMETRY or k in INERTIA)
    if carried:
        raise ValueError(f"{Path(path).name}: a preset never sets geometry or inertia: {', '.join(carried)}")
    return Preset(Path(path).stem, str(raw.get("name") or Path(path).stem), str(raw.get("description", "")),
                  str(raw.get("credit", "")), values)


def load_all(folder: Path = PRESET_DIR) -> list[Preset]:
    """Every preset in `folder`, by name."""
    if not folder.is_dir():
        return []
    return sorted((load(p) for p in folder.glob("*.json")), key=lambda p: p.name.lower())


def find(name: str, folder: Path = PRESET_DIR) -> Preset:
    """A preset by its key or its name (case ignored)."""
    want = name.strip().lower()
    for p in load_all(folder):
        if want in (p.key.lower(), p.name.lower()):
            return p
    names = ", ".join(p.name for p in load_all(folder)) or "none installed"
    raise KeyError(f"no preset {name!r} (presets: {names})")


def values_for(preset: Preset, current: dict[str, float]) -> dict[str, float]:
    """The .cf fields to write into a car whose current .cf values are `current`."""
    out = dict(preset.values)
    new_mass, old_mass = preset.values.get("mass"), current.get("mass")
    if new_mass is not None and old_mass:
        ratio = new_mass / old_mass
        for k in INERTIA:
            if k in current:
                out[k] = current[k] * ratio
    if "num_gears" in out:
        out["num_gears"] = int(round(out["num_gears"]))
    return out


def apply_to_cf(cf_raw: bytes, preset: Preset) -> bytes:
    """A .cf's bytes with the preset applied (every other byte kept)."""
    return cf.build(cf_raw, values_for(preset, cf.parse(cf_raw)))
