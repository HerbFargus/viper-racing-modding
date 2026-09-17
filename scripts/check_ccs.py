"""Checks for `.ccs` / `.csu` — a saved car setup.

The structural claims are checked against the SHIPPED files, because that is
where they came from. The reader and writer are checked for self-consistency and
run anywhere, with or without a Data folder.

    python scripts/check_ccs.py path/to/Data

WHAT THESE GUARD. The field map was read out of `CarFileLoadSetupRes` and
`CarFileCombine` and confirmed against the game's own HTML export, so what is
worth defending is the shape the loader insists on: version 2 and a payload of
exactly 0x8c bytes, or it refuses the file. And that build() touches only what it
was asked to — a setup carries a `.csu` tail and, in the archive form, an
envelope, neither of which belongs to any named field.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, ccs, envelope  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def shipped(data: Path):
    """Every .ccs in every archive under `data`, as (label, entry)."""
    out = []
    for p in sorted(data.glob("*.trk")) + sorted(data.glob("*.car")):
        try:
            for e in archive.read(p):
                if e.name.lower().endswith(".ccs"):
                    out.append((f"{p.stem}:{e.name}", e))
        except Exception:                                        # noqa: BLE001
            continue
    return out


def synth_csu(values=None) -> bytes:
    """A .csu built from scratch: 35 floats, version, size, blank description."""
    body = bytearray(ccs.PAYLOAD_SIZE)
    for i in range(ccs.COUNT):
        struct.pack_into("<f", body, i * 4, 0.5)
    for name, v in (values or {}).items():
        off, kind = ccs.FIELD_MAP[name]
        struct.pack_into("<f" if kind == "f" else "<i", body, off, v)
    return bytes(body) + struct.pack("<2i", ccs.CSU_VERSION, ccs.CSU_SIZE) \
        + bytes(ccs.CSU_DESC)


def main() -> int:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    samples = shipped(data) if data and data.is_dir() else []

    print("ccs -- the shipped setups")
    if not samples:
        print("  no Data folder given -- pass one to check the shipped files")
    else:
        bad = [n for n, e in samples if e.tag != ccs.TAG or e.version != ccs.VERSION]
        check("every shipped .ccs is tag 0SCC version 2", not bad,
              f"{len(samples)} files" if not bad else str(bad[:3]))

        sizes = {}
        for n, e in samples:
            env = envelope.parse(envelope.build(e.tag, e.version, e.payload))
            sizes[n] = len(env.payload)
        odd = [n for n, s in sizes.items() if s != ccs.PAYLOAD_SIZE]
        check("payload is exactly 0x8c bytes -- the loader refuses anything else",
              not odd, f"{ccs.PAYLOAD_SIZE} bytes x {len(sizes)}" if not odd else str(odd))

        parsed = {n: ccs.parse(envelope.build(e.tag, e.version, e.payload))
                  for n, e in samples}
        check("every shipped .ccs parses to 35 named fields",
              all(len(v) == ccs.COUNT for v in parsed.values()),
              f"{len(parsed)} files")

        cars = {n: v for n, v in parsed.items() if ":" in n
                and n.split(":")[0] in ("viper", "sedan", "sports", "exotic", "plane")}
        if cars:
            first = next(iter(cars.values()))
            check("all five car archives ship an identical setup",
                  all(v == first for v in cars.values()),
                  f"{len(cars)} cars -- retail never differentiates it")

        aidef = {n: v for n, v in parsed.items() if n.endswith(":aidef.ccs")}
        if len(aidef) > 1:
            uniq = {tuple(sorted(v.items())) for v in aidef.values()}
            check("every track's aidef.ccs is distinct -- the AI is tuned per track",
                  len(uniq) == len(aidef), f"{len(uniq)}/{len(aidef)} distinct")

        gears = ["gear1", "gear2", "gear3", "gear4", "gear5", "gear6"]
        drops = [n for n, v in parsed.items()
                 if not all(v[a] > v[b] for a, b in zip(gears, gears[1:]))]
        check("gear ratios descend strictly, 1st through 6th", not drops,
              f"{len(parsed)} files" if not drops else str(drops[:3]))

        # These are the fields nothing varies. A change here means either a new
        # sample worth understanding, or the map has drifted.
        #
        # aero_kit is NOT among them, though an earlier pass thought it was: it
        # is an int32, and reading the whole struct as floats makes the values 1
        # and 2 look like denormal zeros. Three shipped tracks really do use a
        # non-default kit.
        for name, want in (("drivetrain_scale", 1.0), ("gear7_unused", 0.0),
                           ("unknown_ratio", 2.66),
                           ("fuel_load", 1.0)):
            vals = {round(v[name], 3) for v in parsed.values()}
            check(f"{name} is constant across every shipped setup",
                  vals == {round(want, 3)}, f"{sorted(vals)}")

        kits = {n: int(v["aero_kit"]) for n, v in parsed.items()}
        check("the aero kit is one of the three the menu offers",
              set(kits.values()) <= set(ccs.AERO_KIT),
              ", ".join(f"{ccs.AERO_KIT[k]} x{list(kits.values()).count(k)}"
                        for k in sorted(set(kits.values()))))

        # Slider positions, so everything except the gearbox and the enum is a
        # 0..1 fraction.
        ratios = set(gears) | {"unknown_ratio", "aero_kit"}
        out_of_range = [(n, k) for n, v in parsed.items() for k, x in v.items()
                        if k not in ratios and not 0.0 <= x <= 1.0]
        check("every non-gear field is a 0..1 slider position", not out_of_range,
              f"{len(parsed)} files" if not out_of_range else str(out_of_range[:3]))

    print("\nccs -- reading and writing")
    base = synth_csu()
    check("a .csu round-trips byte-identically when nothing is changed",
          ccs.build(base, {}) == base, f"{len(base)} bytes")

    edited = ccs.build(base, {"fsprings": 0.75, "aero_kit": 2})
    before, after = ccs.parse(base), ccs.parse(edited)
    changed = {k for k in before if before[k] != after[k]}
    check("build() changes only the fields it was given", changed == {"fsprings", "aero_kit"},
          str(sorted(changed)))
    check("and leaves the .csu version, size and description untouched",
          edited[ccs.PAYLOAD_SIZE:] == base[ccs.PAYLOAD_SIZE:],
          f"{ccs.CSU_DESC}-byte description preserved")
    check("the aero kit survives as an int, not a float",
          after["aero_kit"] == 2, "int32 field")

    try:
        ccs.build(base, {"no_such_field": 1.0})
        check("an unknown field name is refused", False, "silently accepted")
    except KeyError:
        check("an unknown field name is refused", True, "raises KeyError")

    try:
        ccs.parse(b"\x00" * 8)
        check("a truncated payload is refused", False, "accepted a short file")
    except ccs.CcsError:
        check("a truncated payload is refused", True, "raises CcsError")

    print("\nccs -- resolving against a car")
    # The stored value is a position between two .cf limits, so the same 0.5 is a
    # different spring rate on a different car. That is the whole point of
    # resolve(), and it is what makes a setup car-specific.
    fake_cf = {"fsprings1": 200.0, "fsprings2": 600.0,
               "rear_end_ratio1": 3.1, "rear_end_ratio2": 5.1,
               "wheel_lock": 35.0, "fuel_capacity": 19.0}
    r = ccs.resolve(ccs.parse(synth_csu({"fsprings": 0.5, "final_drive": 0.3,
                                         "wheel_lock": 0.5714285714})), fake_cf)
    check("a midpoint slider resolves to the midpoint of the .cf range",
          abs(r["fsprings"] - 400.0) < 0.01, f"0.5 of 200..600 -> {r['fsprings']:.1f}")
    check("final drive resolves the way the garage shows it",
          abs(r["final_drive"] - 3.70) < 0.01, f"0.3 of 3.1..5.1 -> {r['final_drive']:.2f}")
    check("scaled fields multiply rather than interpolate",
          abs(r["wheel_lock"] - 20.0) < 0.01, f"-> {r['wheel_lock']:.1f} degrees")
    untouched = ccs.resolve(ccs.parse(base), {})
    check("a field with no .cf pairing is returned unchanged",
          untouched["gear1"] == ccs.parse(base)["gear1"], "gears are stored as ratios")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
