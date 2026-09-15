"""Convert all seven Streets of SimCity vehicles and finish the job.

`build_car.py` writes one car's LOD 0. This runs the whole fleet, then does the
two things a single conversion leaves undone:

  * `vrmod modlod` -- without it LODs 1..7 are still the DONOR's meshes, which
    means the car morphs into a Viper GTS-R as it gets further away, and its
    distance meshes reference textures the fork does not own.
  * a count assertion -- seven cars in, seven cars out, every one of them
    grading `portable`. Every silent failure in this project so far (a partial
    pack, a wrong render recipe, an empty manifest) was caught by counting the
    result, never by looking at one item and calling it good.

    python build_fleet.py <sosc_extracted_dir> <viper_install_dir> <out_dir>

`sosc_extracted_dir` is the directory holding GEO/SIM3D2.MAX and BMP/SIM3D.BMP,
extracted from a Streets of SimCity install; `viper_install_dir` is a Viper
Racing install to take donor cars from. Neither game's files are in this repo.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from build_car import build                        # noqa: E402
from vrmod import archive, car                     # noqa: E402

# model in SIM3D2.MAX, output prefix, short texture code, donor car, and the
# real car it resembles
# (the last column is the user's identification from the game's own artwork, and
# is here so the fleet is recognisable to someone who knows the cars rather than
# the filenames).
# The codes are distinct across the fleet, not just within each car: all seven
# cars sit in the same Data/ directory, so two of them naming a texture the same
# thing would be one overwriting the other.
# The DISPLAY name is the car's name in Streets of SimCity, not the real car it
# is modelled on: these are the badges that game gave them, and they are what
# somebody who played it will recognise. Without setting it a converted car
# wears its donor's name -- five of the seven showed up in the menu as "Exotic
# Car" or "Sports Sedan". The field stores 32 characters and the car-select
# menu shows about 24, so all of these fit comfortably.
FLEET = [
    ("STREETS_FERRARI", "azzaroni", "azz", "exotic.car", "Azzaroni",
     "Ferrari 250 GT"),
    ("STREETS_GT40",    "j57",      "j57", "exotic.car", "J57",
     "1966 Ford GT40"),
    ("STREETS_BUG",     "strtrat",  "str", "sedan.car",  "Street Rat",
     "Volkswagen Beetle"),
    ("STREETS_UTILITY", "hmxvan",   "hmx", "4x4cos.car", "HMX Utility Van",
     "1973 GMC C-Series"),
    ("STREETS_JAVELIN", "airhawk",  "ahk", "exotic.car", "Airhawk",
     "1969 Chevrolet Camaro"),
    ("STREETS_HUNTER",  "hunter",   "hun", "4x4cos.car", "Hunter",
     "-"),
    ("STREETSCAR6",     "police",   "pol", "sedan.car",  "Police Car",
     "1985 Oldsmobile Cutlass"),
]


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("build_fleet.py <sosc_extracted_dir> "
                         "<viper_install_dir> <out_dir>")
    sosc, install, out = (Path(a) for a in sys.argv[1:4])
    max_path = sosc / "GEO" / "SIM3D2.MAX"
    skin = sosc / "BMP" / "SIM3D.BMP"
    for p in (max_path, skin, install):
        if not p.exists():
            raise SystemExit(f"missing {p}")
    out.mkdir(parents=True, exist_ok=True)

    codes = [c for _, _, c, _, _, _ in FLEET]
    if len(set(codes)) != len(codes):
        raise SystemExit(f"texture codes are not unique: {codes}")

    built = []
    for model, prefix, code, donor, display, real in FLEET:
        print(f"\n{prefix}  ({model}, from {donor} -- {real})")
        path = build(max_path, model, skin, install / donor,
                     out / prefix, prefix, code)
        # The display name has to be written AFTER the fork: carfork copies the
        # donor's name along with everything else, so without this a converted
        # car wears the donor's badge -- five of the seven showed up in the
        # car-select menu as "Exotic Car" or "Sports Sedan". check_mesh.py's
        # "the car has its own name in the menu" is the assertion that catches
        # it, and it was catching it because nothing ever set the name.
        archive.write(car.set_car_name(archive.read(path), display), path)
        built.append(path)

    # --- LODs, which a single conversion does not touch --------------------
    print()
    for path in built:
        r = subprocess.run([sys.executable, "-m", "vrmod.cli", "modlod", str(path)],
                           cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"modlod {path.name}: {r.stderr[-300:]}")
        print(f"  modlod {path.name:16s} {r.stdout.strip().splitlines()[-1]}")

    # --- the count assertion ----------------------------------------------
    print()
    portable = []
    for path in built:
        verdict = car.texture_provenance(path).get("verdict")
        size = path.stat().st_size / 1024
        print(f"  {path.name:16s} {size:>6.0f} KB  {verdict}")
        if verdict == "portable":
            portable.append(path)
    ok = len(built) == len(FLEET) and len(portable) == len(FLEET)
    print(f"\n  {len(portable)}/{len(FLEET)} portable"
          f"{'' if ok else '  -- FAIL, see the verdicts above'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
