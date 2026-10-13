"""Checks for physics presets (vrmod/presets.py, vrmod/assets/presets/*.json).

Run anywhere; given a Data folder it also applies every preset to the real stock viper.car's .cf:

    python scripts/check_presets.py [path/to/Data]

WHAT THESE GUARD. A preset must never carry geometry -- the wheels would leave the car's arches (a tune search
that could move the wheelbase once squashed it to half the body) -- and must only name real .cf fields, or cf.build
raises at Save. Applying one sets every field it names, keeps every geometry field and every unnamed byte, and scales
the three inertias by the change in mass. The loader refuses a file that breaks either rule, so a bad preset fails
here rather than in someone's car.
"""
from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, cf, envelope, presets  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def synth_cf(values: dict) -> bytes:
    """A .cf built from scratch: every named field set, 0x228 bytes of payload."""
    size = max(off for off, _ in cf.FIELD_MAP.values()) + 4
    body = bytearray(size)
    for name, (off, kind) in cf.FIELD_MAP.items():
        struct.pack_into("<f" if kind == "f" else "<i", body, off, values.get(name, 1.0 if kind == "f" else 1))
    return envelope.build(cf.TAG, cf.VERSION, bytes(body))


def close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-4 * max(1.0, abs(b))


def check_preset_on(label: str, cf_raw: bytes, preset: presets.Preset) -> None:
    before = cf.parse(cf_raw)
    after = cf.parse(presets.apply_to_cf(cf_raw, preset))
    check(f"{label}: {preset.name}: every preset field set",
          all(close(after[k], v) for k, v in preset.values.items()))
    check(f"{label}: {preset.name}: geometry kept",
          all(close(after[k], before[k]) for k in presets.GEOMETRY))
    if "mass" in preset.values and before["mass"]:
        r = preset.values["mass"] / before["mass"]
        check(f"{label}: {preset.name}: inertias scaled by the mass",
              all(close(after[k], before[k] * r) for k in presets.INERTIA), f"x{r:.3f}")
    untouched = [k for k in cf.FIELD_MAP if k not in preset.values and k not in presets.INERTIA]
    check(f"{label}: {preset.name}: fields it doesn't name kept", all(close(after[k], before[k]) for k in untouched))


def main() -> None:
    shipped = presets.load_all()
    check("presets ship with vrmod", len(shipped) > 0, ", ".join(p.name for p in shipped))
    for p in shipped:
        check(f"{p.name}: only real .cf fields", all(k in cf.FIELD_MAP for k in p.values))
        check(f"{p.name}: no geometry or inertia", not any(k in presets.GEOMETRY or k in presets.INERTIA for k in p.values))
        check(f"{p.name}: has a description and a credit", bool(p.description and p.credit))
        check(f"{p.name}: found by key and by name", presets.find(p.key).key == p.key == presets.find(p.name).key)

    with tempfile.TemporaryDirectory() as td:
        for bad, why in (({"wheelbase": 50.0}, "geometry"), ({"mx": 1.0}, "inertia"), ({"not_a_field": 1.0}, "unknown")):
            path = Path(td) / f"bad_{why}.json"
            path.write_text(json.dumps({"name": why, "values": bad}))
            try:
                presets.load(path)
                ok = False
            except ValueError:
                ok = True
            check(f"the loader refuses a preset with {why}", ok)

    base = synth_cf({"mass": 3000.0, "mx": 60000.0, "my": 60000.0, "mz": 10000.0, "wheelbase": 96.0, "num_gears": 6})
    for p in shipped:
        check_preset_on("synthetic car", base, p)

    if len(sys.argv) > 1:
        car = Path(sys.argv[1]) / "viper.car"
        if car.exists():
            e = next(e for e in archive.read(car) if e.name.lower().endswith(".cf"))
            raw = envelope.build(e.tag, e.version, e.payload)
            for p in shipped:
                check_preset_on(car.name, raw, p)
        else:
            print(f"  (no {car}: skipped the real-car checks)")

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
