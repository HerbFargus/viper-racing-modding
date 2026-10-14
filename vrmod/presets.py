"""Physics presets: named, complete .cf values that make any car drive exactly like a tested car.

A preset is a JSON file in vrmod/assets/presets/ (it ships with the app):

    {"name": "Best", "description": "...", "credit": "...", "values": {"mass": 1791.5, "power_max": 585.0, ...}}

`values` holds EVERY .cf field of the car it was tested as -- drivetrain, aero, suspension, brakes, diffs, and the
geometry and inertia too: wheelbase, track, tyre sizes, body size, ride-height range, mx/my/mz. Applying a preset
writes all of them, so the car gets that physics exactly, whatever its model: the Best preset raced on an Alleycat
body scored 660.0 s over the 8 stock tracks against 659.8 s for the Viper it was tuned on, every track within 0.1 s.

The trade-off is the look: the game draws each car's own wheel models at the .cf's tyre sizes and wheel positions,
so on a car with a different shape the wheels change size and can sit outside its arches. Adapting a preset to each
car's own geometry was tried and dropped: tyre width decides the pace (the same tune on the Alleycat's own thin
tyres was 21 s slower; raising its grip scales instead of widening the tyres won back only 3 s), so a preset that
kept the car's tyres couldn't promise the tested result.

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

# the fields that move or resize the wheels (what the car page warns about); a preset sets them like any other
GEOMETRY = frozenset({
    "wheelbase", "ftrack", "rtrack", "width", "height",
    "ftyre_width", "ftyre_aspect", "ftyre_rim", "rtyre_width", "rtyre_aspect", "rtyre_rim",
    "fground_clearance1", "fground_clearance2", "rground_clearance1", "rground_clearance2",
})


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
    """One preset file. Raises ValueError for a field .cf doesn't have, or for one it's missing (a preset is
    complete, or it can't promise the tested car's behaviour)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    values = {str(k): float(v) for k, v in raw.get("values", {}).items()}
    unknown = sorted(k for k in values if k not in cf.FIELD_MAP)
    if unknown:
        raise ValueError(f"{Path(path).name}: not .cf fields: {', '.join(unknown)}")
    missing = sorted(k for k in cf.FIELD_MAP if k not in values)
    if missing:
        raise ValueError(f"{Path(path).name}: a preset sets every .cf field; missing {', '.join(missing)}")
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


def values_for(preset: Preset, current: dict[str, float] | None = None) -> dict[str, float]:
    """The .cf fields to write: all of the preset's, as tested (`current` is accepted and ignored -- the car's own
    values don't change the result)."""
    out = dict(preset.values)
    for k, (_off, kind) in cf.FIELD_MAP.items():
        if kind == "i" and k in out:
            out[k] = int(round(out[k]))
    return out


def apply_to_cf(cf_raw: bytes, preset: Preset) -> bytes:
    """A .cf's bytes with the preset applied (every other byte kept)."""
    return cf.build(cf_raw, values_for(preset, cf.parse(cf_raw)))
