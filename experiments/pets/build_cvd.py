"""Cats vs Dogs cars, and the PetTest track: 36 pets dropped on stock Bemidji.

  cars    kit.car's Willys recipe (forked from the HMX van): our body, paw-print wheels and
          its OWN palette (acpal.tex / dhpal.tex -- the game caches textures by name)
            alleycat  all of Val's .cf, front 155/70 R15, rear 265/55 R17; yarn ball + meow
            doghouse  the Indy Jeep tune (210 hp, 3.50 final); tennis ball + bark
  PetTest six 4x pets, 50 lb each, 18 dogs on the first half of Bemidji's AI line and 18
          cats on the second, plus a six-dog bowling rack; palette ptpal.tex; installed in
          the bemidji slot as "PetTest" (stock kept as bemidji_AS_PetTest.btr)

    python build_cvd.py            build into ./out
    python build_cvd.py --install  ...and install into the test install
"""
from __future__ import annotations

import math
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import kit  # noqa: E402
from kit import car as kcar, tracks  # noqa: E402
from kit.shapes import Palette, tennis_ball, yarn_ball  # noqa: E402
from kit.sound import to_pcm, wav_bytes  # noqa: E402
import cvd_models as M  # noqa: E402
import cvd_sounds as S  # noqa: E402
from vrmod import archive, envelope, ili, obt  # noqa: E402

OUT = HERE / "out"
INCH = 0.0254
PET_MASS = 50
SLOT, TRACK_NAME = "bemidji", "PetTest"
HORN_R = 18 * INCH                     # the horn ball's collision radius is an engine constant

CARS = {
    "alleycat": dict(display="Alley Cat", make=M.alley_cat, palette="acpal.tex", ball=yarn_ball, horn=S.meow,
                     ftyre=(155, 70, 15), rtyre=(265, 55, 17), height=1.45, tune="val"),
    "doghouse": dict(display="Doghouse", make=M.doghouse, palette="dhpal.tex", ball=tennis_ball, horn=S.bark,
                     ftyre=(245, 75, 16), rtyre=(245, 75, 16), height=2.37, tune="indy"),
}


def build_car(prefix, c):
    m = c["make"]()
    pal = Palette(c["palette"])
    meshes = {k: m[k].mesh(pal) for k in ("body", "front", "rear")}
    ball = c["ball"](HORN_R).mesh(pal)                       # every mesh before the palette is encoded
    spec = kcar.CarSpec(prefix=prefix, display=c["display"], body=meshes["body"], front_wheel=meshes["front"],
                        rear_wheel=meshes["rear"], palette=pal.entry(wrap=1), wheelbase=m["wheelbase"],
                        ftrack=m["ftrack"], rtrack=m["rtrack"], height=c["height"], ftyre=c["ftyre"],
                        rtyre=c["rtyre"], tune=c["tune"], horn_ball=ball, horn_wav=wav_bytes(to_pcm(c["horn"]())))
    out = kcar.build(spec, OUT / f"{prefix}.car")
    print(kcar.report(out))
    return out


def place_pets(line):
    """(pet, game x, game z, yaw) in clusters off the racing line (game frame, as .ili is)."""
    pts = line + [line[0]]
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(line))]
    lap = sum(seg)

    def at(d):
        d %= lap
        for i, s in enumerate(seg):
            if d <= s:
                a, b = pts[i], pts[i + 1]
                dx, dz = (b[0] - a[0]) / s, (b[1] - a[1]) / s
                return (a[0] + dx * d, a[1] + dz * d), (dx, dz)
            d -= s
        return pts[0], (1, 0)

    rng = random.Random(42)
    placed = []
    clusters = [(.10, ["corgi", "lab", "dachs"]), (.18, ["lab", "corgi", "dachs"]),
                (.26, ["dachs", "corgi", "lab"]), (.34, ["corgi", "dachs", "lab"]),
                (.58, ["tabby", "blkcat", "loaf"]), (.66, ["loaf", "tabby", "blkcat"]),
                (.74, ["blkcat", "loaf", "tabby"]), (.82, ["tabby", "loaf", "blkcat"]),
                (.90, ["blkcat", "tabby", "loaf"]), (.50, ["loaf", "blkcat", "tabby"])]
    for frac, pets in clusters:
        for j, name in enumerate(pets):
            (x, z), (dx, dz) = at(frac * lap + j * 9)
            off = (-1) ** j * rng.uniform(2.0, 4.5)
            placed.append((name, x - dz * off, z + dx * off, rng.uniform(0, 360)))
    (x0, z0), (dx, dz) = at(.42 * lap)                       # Fetch Lane: six dogs racked as pins
    heading = math.degrees(math.atan2(-dx, -dz)) % 360
    for row, offs in enumerate(([0], [-2.6, 2.6], [-5.2, 0, 5.2])):
        for o in offs:
            d = row * 4.2
            placed.append(("corgi" if (row + len(placed)) % 2 else "dachs",
                           x0 + dx * d - dz * o, z0 + dz * d + dx * o, heading))
    return placed, lap


def build_pettest():
    pal = Palette("ptpal.tex")
    backup = kit.INSTALL / f"{SLOT}_AS_{TRACK_NAME}.btr"
    data = (backup if backup.exists() else kit.INSTALL / f"{SLOT}.trk").read_bytes()   # always the stock file
    entries = archive.read_bytes(data)
    by = tracks.by_name(entries)
    e = by["default.ili"]
    line = [(w.x, w.z) for w in ili.parse(envelope.build(e.tag, e.version, e.payload))]
    placed, lap = place_pets(line)
    meshes = {f"{n}.mod": M.pet(n).mesh(pal) for n in M.PETS}
    entries.append(pal.entry())
    # game (x, z) -> source (x, y) = (-x, -z): add_obstacles works in the source frame
    n_obj = tracks.add_obstacles(entries, meshes, [(f"{n}.mod", -x, -z, yaw, PET_MASS, "ball")
                                                   for n, x, z, yaw in placed])
    out = OUT / f"{TRACK_NAME}.tra"
    out.write_bytes(archive.to_bytes(entries, partitioned=archive.read_layout(data).partitioned))
    print(f"{out.name}: {len(placed)} pets ({PET_MASS} lb), Bemidji lap {lap:.0f} m, {n_obj} placed objects")
    return out


def main():
    OUT.mkdir(exist_ok=True)
    built = [build_car(p, c) for p, c in CARS.items()]
    tra = build_pettest()
    if "--install" in sys.argv:
        for c in built:
            dst = kit.INSTALL / c.name
            if dst.exists():
                shutil.copy2(dst, kit.INSTALL / "Backups" / (c.name + ".prev"))
            shutil.copy2(c, dst)
            print(f"installed {dst.name}")
        print(tracks.install(tra, SLOT))


if __name__ == "__main__":
    main()
