"""Build the RACING set: every SoSC car on Val's complete physics file.

The original set (wheelfit --chassis) puts each car on Val's chassis but keeps
its OWN engine, scaled to his weight, so a Beetle still accelerates like a
Beetle. This is the other set: Val's whole .cf -- his 350 hp / 550 lb-ft engine
revving to 9000 through six gears, his chassis, his drag -- under each car's own
body, so all seven race on the car that handled best. It is not tuned down to the
stock Viper. Matching the field is the player's call: make the AI the same
primary car.

What a racing car keeps from its original:
    body     size, wheelbase, ride height and tyre sizes (wheelfit.CHASSIS_BODY)
             and the even track that drove (wheelfit.EVEN_TRACK)
    cockpit  the calibrated cockpit.tab, as is. Needles stay true to their
             painted dials and run off the end past the dial's top rpm or speed
    art      meshes, textures, sounds, horn ball -- everything else

Each is forked to <stem>r.car, with carfork's renaming rather than a file copy:
the game derives every member name it loads from the .car's own filename, so a
plain copy under a new name crashes it. It is named "<name> Race", and both sets
sit in the car list together.

    python raceset.py <fleet_dir_or_car> --chassis=<Val's Viper.car>

Run it on the finished original set, after wheelfit.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from vrmod import archive, car, cf, envelope                   # noqa: E402
from wheelfit import CHASSIS_BODY, EVEN_TRACK, load_chassis    # noqa: E402

SUFFIX = "r"             # airhawk.car -> airhawkr.car
NAME_SUFFIX = " Race"
NAME_SHOWN = 24          # the car-select menu truncates past this


def race_cf(car_raw: bytes, chassis_raw: bytes, stem: str) -> bytes:
    """Val's .cf, whole, carrying only this car's body and track."""
    mine = cf.parse(car_raw)
    new = {k: mine[k] for k in CHASSIS_BODY}
    new["ftrack"] = new["rtrack"] = EVEN_TRACK[stem]
    return cf.build(chassis_raw, new)


def build(car_path: Path, chassis_raw: bytes) -> Path:
    stem = car_path.stem.lower()
    entries = archive.read(car_path)
    ce = next(e for e in entries if e.name.lower().endswith(".cf"))
    raw = race_cf(envelope.build(ce.tag, ce.version, ce.payload), chassis_raw, stem)
    entries = [archive.ArchiveEntry(name=x.name, tag=x.tag, version=x.version,
                                    payload=raw[20:]) if x is ce else x
               for x in entries]
    # named before the fork, while the spec sheet still has the name it was built with
    name = car.read_car_name(entries) or stem.title()
    entries = car.set_car_name(entries, (name + NAME_SUFFIX)[:NAME_SHOWN])
    entries = car.fork_car(entries, stem + SUFFIX)
    out = car_path.with_name(stem + SUFFIX + ".car")
    archive.write(entries, out)
    return out


def main(argv: list[str]) -> int:
    flags = [a for a in argv if a.startswith("--chassis=")]
    args = [a for a in argv if not a.startswith("--chassis=")]
    if len(args) != 1 or not flags:
        raise SystemExit("raceset.py <fleet_dir_or_car> --chassis=<Val's Viper.car>")
    chassis = load_chassis(Path(flags[-1].split("=", 1)[1]))
    target = Path(args[0])
    # Only the seven originals, by exact name: a Data folder also holds Val's own
    # Viper.car, the stock cars, and -- after one run -- the racing cars themselves.
    cars = sorted(p for p in (target.glob("*.car") if target.is_dir() else [target])
                  if p.stem.lower() in EVEN_TRACK)
    if not cars:
        raise SystemExit(f"no SoSC originals ({', '.join(EVEN_TRACK)}) under {target}")
    for p in cars:
        out = build(p, chassis)
        print(f"  {p.name:14s} -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
