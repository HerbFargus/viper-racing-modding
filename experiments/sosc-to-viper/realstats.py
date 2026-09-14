"""Give the converted cars the specifications of the real cars they are.

Every value here is in the units the `.cf` already uses, which are real-world US
units -- confirmed against viper.car, whose file says 3583 lb, 450 hp, 96.2 in
wheelbase and 47.0 in height, and a real Viper GTS-R is 3,400 lb, 450 hp, 96.2
in and 47.0 in. So this is a mapping job, not a conversion one.

THE HONEST WARNING. The cars Viper Racing ships are not real-world specified:

    viper   450 hp / 3,583 lb        exotic  600 hp / 2,460 lb
    sedan   550 hp / 3,850 lb        4x4cos  700 hp / 2,350 lb

The whole field is 450-700 hp. A 1966 Beetle has FIFTY, and a 1973 GMC van 155.
Given real specifications they are authentic and they are also lapped twice a
race. `--scale` exists for that: it lifts every car's power and torque by a
common factor, so the relative differences the real cars have -- a GT40 pulling
away from a Cutlass -- survive while the slowest car stays raceable. A scale of
about 1.8 puts the Beetle where the slowest shipped car is.

WHAT IS SET AND WHAT IS NOT. Mass, power, torque, their peak RPMs, redline,
idle, the dimensions, wheelbase, track, weight distribution, gearing, fuel and
aerodynamics -- everything a specification sheet actually states. Springs,
dampers, bars, camber, toe, brake balance and the rest are LEFT at the donor's
values, because no spec sheet gives them and inventing suspension numbers for a
car that has to drive is worse than inheriting ones that already work.

The rotational inertias (mx/my/mz) are not on any spec sheet either, but they
scale with mass, so they are scaled from the donor by the mass ratio rather than
left at a value belonging to a car of a different weight.

SOURCES are the standard published figures for each car. Where a model had many
variants the one chosen is noted, because "a 1969 Camaro" is anywhere from 140
to 430 hp depending on which box was ticked.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from vrmod import archive, cf, envelope  # noqa: E402

# Horsepower before 1972 is GROSS and after it is NET, which is why a 375 hp
# Camaro and a 140 hp Cutlass are closer in reality than the numbers suggest.
# The figures are left as published rather than converted: the game has no
# opinion about which standard a number came from.
SPECS = {
    "airhawk": dict(
        real="1969 Chevrolet Camaro SS 396 (L78)",
        mass=3550, power_max=375, power_rpm=5600, torque_max=415, torque_rpm=3600,
        redline=6000, idle_speed=700, wheelbase=108.0, width=74.0, height=51.0,
        ftrack=59.6, rtrack=59.5, weight_distribution=56.0, num_gears=4,
        rear_end_ratio1=3.55, fuel_capacity=18.0,
        frontal_area=21.5, drag_coefficient=0.45),
    "azzaroni": dict(
        real="Ferrari 250 GT Berlinetta SWB (1960)",
        mass=2320, power_max=280, power_rpm=7000, torque_max=203, torque_rpm=5500,
        redline=7500, idle_speed=900, wheelbase=94.5, width=66.9, height=50.4,
        ftrack=53.9, rtrack=53.1, weight_distribution=53.0, num_gears=4,
        rear_end_ratio1=4.25, fuel_capacity=26.0,
        frontal_area=17.8, drag_coefficient=0.40),
    "j57": dict(
        real="1966 Ford GT40 Mk II (427)",
        mass=2660, power_max=485, power_rpm=6200, torque_max=475, torque_rpm=4200,
        redline=6400, idle_speed=900, wheelbase=95.3, width=70.0, height=40.5,
        ftrack=54.9, rtrack=55.9, weight_distribution=42.0, num_gears=4,
        rear_end_ratio1=3.09, fuel_capacity=42.0,
        frontal_area=16.5, drag_coefficient=0.35),
    "strtrat": dict(
        real="Volkswagen Beetle 1300 (1966)",
        mass=1808, power_max=50, power_rpm=4600, torque_max=69, torque_rpm=2600,
        redline=4600, idle_speed=800, wheelbase=94.5, width=60.6, height=59.1,
        ftrack=51.4, rtrack=53.1, weight_distribution=42.0, num_gears=4,
        rear_end_ratio1=4.375, fuel_capacity=10.6,
        frontal_area=18.3, drag_coefficient=0.48),
    "hmxvan": dict(
        real="1973 GMC C-Series (350 V8, net)",
        mass=4600, power_max=155, power_rpm=4000, torque_max=255, torque_rpm=2400,
        redline=4500, idle_speed=650, wheelbase=125.0, width=79.0, height=84.0,
        ftrack=65.0, rtrack=63.7, weight_distribution=56.0, num_gears=4,
        rear_end_ratio1=4.10, fuel_capacity=20.0,
        frontal_area=38.0, drag_coefficient=0.60),
    "police": dict(
        real="1985 Oldsmobile Cutlass Supreme (307 V8)",
        mass=3350, power_max=140, power_rpm=3200, torque_max=240, torque_rpm=2000,
        redline=4400, idle_speed=600, wheelbase=108.1, width=71.6, height=54.9,
        ftrack=58.5, rtrack=57.7, weight_distribution=56.0, num_gears=4,
        rear_end_ratio1=3.42, fuel_capacity=17.5,
        frontal_area=22.0, drag_coefficient=0.44),
    # hunter has no identified real-world twin, so it keeps the donor's numbers
    # rather than being given invented ones.
}

SCALED = ("power_max", "torque_max")

# The shipped field's power-to-weight, in hp per ton: viper 251, sedan 286,
# exotic 488, 4x4cos 596. The real cars span 55 to 365, which is a 6.6x spread
# against the game's 2.4x -- so scaling everything by one factor cannot fix the
# bottom without making the top absurd. Putting the Beetle on the pace of the
# slowest shipped car takes 4.6x, which turns the GT40 into a 1,680 hp car.
#
# --compress maps the real power-to-weight onto the game's range instead. The
# ORDER is real -- GT40 quickest, Beetle slowest, and every gap in between in
# the right direction -- while the absolute figures land where the game can use
# them. It is the option that gives a field of real cars you can actually race.
GAME_HP_PER_TON = (251.0, 596.0)
INERTIA = ("mx", "my", "mz")


def compressed_scale(spec: dict, lo: float, hi: float) -> float:
    """The factor that puts this car's power-to-weight inside the game's range,
    at the same RANK it holds among the real cars."""
    ratios = sorted(s["power_max"] / (s["mass"] / 2000) for s in SPECS.values())
    mine = spec["power_max"] / (spec["mass"] / 2000)
    span = ratios[-1] - ratios[0]
    frac = (mine - ratios[0]) / span if span else 0.5
    target = GAME_HP_PER_TON[0] + frac * (GAME_HP_PER_TON[1] - GAME_HP_PER_TON[0])
    return target / mine


def apply(car: Path, spec: dict, scale: float = 1.0) -> list[str]:
    """Write one car's specification. Returns the changed fields."""
    entries = archive.read(car)
    e = next(x for x in entries if x.name.lower().endswith(".cf"))
    values = cf.parse(envelope.build(e.tag, e.version, e.payload))

    old_mass = values["mass"]
    write: dict[str, float] = {}
    changes = []
    for key, want in spec.items():
        if key == "real":
            continue
        if key in SCALED:
            want = round(want * scale)
        if abs(values[key] - want) > 1e-6:
            changes.append(f"{key} {values[key]:g} -> {want:g}")
        write[key] = float(want)

    # Inertia is not published anywhere, but it is a property of mass: leaving
    # the donor's would give a 4,600 lb van the rotational feel of a 2,350 lb
    # buggy.
    ratio = write["mass"] / old_mass if old_mass else 1.0
    for key in INERTIA:
        write[key] = round(values[key] * ratio)
    changes.append(f"inertia x{ratio:.2f} with mass")

    # Only the named fields are written; every other byte of the .cf -- including
    # the stretches nobody has named yet -- carries over from the original.
    raw = cf.build(envelope.build(e.tag, e.version, e.payload), write)
    out = [archive.ArchiveEntry(name=x.name, tag=x.tag, version=x.version,
                                payload=raw[20:]) if x is e else x
           for x in entries]
    archive.write(out, car)
    return changes


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    scale = 1.0
    compress = "--compress" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("--scale="):
            scale = float(a.split("=", 1)[1])
    if len(args) != 1:
        raise SystemExit("realstats.py [--scale=N | --compress] <fleet_dir>")
    fleet = Path(args[0])

    if compress:
        print(f"  power-to-weight compressed into the game's range "
              f"({GAME_HP_PER_TON[0]:.0f}-{GAME_HP_PER_TON[1]:.0f} hp/ton) -- real "
              f"ORDER kept, absolute figures made raceable\n")
    elif scale != 1.0:
        print(f"  power and torque scaled x{scale} -- relative differences kept, "
              f"absolute figures lifted so the slowest car can race\n")
    for car in sorted(fleet.glob("*.car")):
        spec = SPECS.get(car.stem)
        if not spec:
            print(f"  {car.stem:9s} no real-world twin identified, left as the donor")
            continue
        use = compressed_scale(spec, *GAME_HP_PER_TON) if compress else scale
        changes = apply(car, spec, use)
        p = round(spec["power_max"] * use)
        print(f"  {car.stem:9s} {spec['real']}")
        print(f"      {spec['mass']:>5} lb  {p:>4} hp  {round(spec['torque_max']*use):>4} lb-ft"
              f"  {spec['wheelbase']:>5.1f} in wb  {spec['num_gears']}-speed"
              f"   ({len(changes)} fields)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
