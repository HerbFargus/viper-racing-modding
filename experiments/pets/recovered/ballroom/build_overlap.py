"""Overlap: what happens to obstacles that spawn inside each other -- and can a ceiling
bounce them back down?

In the infield beside the start straight (x runs along it, clusters west to east):
  A  x=-60  two balls overlapping 25% of a diameter (centres 1.2 m apart)
  B  x=-30  two balls overlapping 75% (centres 0.4 m apart)
  C  x=  0  a clump of ten, centres within 0.4 m of each other      -- under the ceiling
  D  x= 30  two balls at EXACTLY the same spot (the risky one)       -- under the ceiling
  E  x= 70  another clump of ten, no ceiling, to compare with C

THE CEILING is a flat .sol BOX, 7 m up and 1 m thick, over C and D: box_from_segment
with a long segment at 7 m, a 1 m "height" and a 26 m "thickness" is a horizontal slab.
It's appended to track.sol after assembly (the build only turns walls into boxes), and
drawn as a grey panel on both faces so you can see it.
"""
import math
import random
import sys

import build_ballroom as B
from vrmod import archive, envelope, sol, track, trackgen

Y_ROW = -35.0                                     # infield, 11 m from the start straight's inner edge
CEIL_X, CEIL_Y, CEIL_Z, CEIL_T = (-12.0, 42.0), (Y_ROW - 10.0, Y_ROW + 13.0), 7.0, 1.0   # clear of the road (inner edge y = -46)
NAME = "Overlap"


def clusters(rng):
    """(x, y) centres, cluster by cluster."""
    d = 2 * B.BALL_R
    spots = [(-60.0 - 0.375 * d, Y_ROW), (-60.0 + 0.375 * d, Y_ROW)]          # A: 25% overlap
    spots += [(-30.0 - 0.125 * d, Y_ROW), (-30.0 + 0.125 * d, Y_ROW)]         # B: 75% overlap
    for cx in (0.0, 70.0):                                                    # C and E: clumps of ten
        for _ in range(10):
            a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.2)
            spots.append((cx + r * math.cos(a), Y_ROW + r * math.sin(a)))
    spots += [(30.0, Y_ROW), (30.0, Y_ROW)]                                   # D: exactly coincident
    return spots


_orig_scene = B.build_scene


def scene_with_ceiling():
    scene, line = _orig_scene()
    panel = B.Batch(scene, "ceil", "grey.tex", solid=False)
    x0, x1 = CEIL_X
    y0, y1 = CEIL_Y
    lo, hi = CEIL_Z, CEIL_Z + CEIL_T
    panel.quad([(x0, y0, lo), (x1, y0, lo), (x1, y1, lo), (x0, y1, lo)], 0.8, up=((x0 + x1) / 2, (y0 + y1) / 2, lo - 5))
    panel.quad([(x0, y0, hi), (x1, y0, hi), (x1, y1, hi), (x0, y1, hi)], 0.9)
    panel.flush()
    return scene, line


B.build_scene = scene_with_ceiling


def add_ceiling_solid(trk):
    ents = archive.read(trk)
    e = next(x for x in ents if x.name.lower() == "track.sol")
    s = sol.parse(envelope.build(e.tag, e.version, e.payload))
    prims = list(s.primitives)
    tpl = sol.wall_template(s)
    y_mid = (CEIL_Y[0] + CEIL_Y[1]) / 2
    a = trackgen.to_viper((CEIL_X[0], y_mid, CEIL_Z))
    b = trackgen.to_viper((CEIL_X[1], y_mid, CEIL_Z))
    prims.append(sol.box_from_segment(tpl, a, b, height=CEIL_T, thickness=CEIL_Y[1] - CEIL_Y[0]))
    index, tail = sol.build_spatial_index(prims)
    built = sol.Sol(primitives=prims, index=index, tail=tail, version=s.version)
    env = envelope.parse(sol.build(built))
    e.tag, e.version, e.payload = env.tag, env.version, env.payload
    archive.write(ents, trk)
    return len(prims)


if __name__ == "__main__":
    B.make_base()
    rng = random.Random(B.SEED + 20)
    spots = clusters(rng)
    B.write_count(spots, [rng.uniform(0, 360) for _ in spots], NAME)
    trk = B.HERE / f"{NAME}.trk"
    n = add_ceiling_solid(trk)
    out = B.DATA / f"{NAME}.tra"
    track.export_tra(trk, out, layout="flat")
    ents = {x.name.lower(): x for x in archive.read(out)}
    s = sol.parse(envelope.build(ents["track.sol"].tag, ents["track.sol"].version, ents["track.sol"].payload))
    c = s.primitives[-1]
    import struct
    rows = struct.unpack_from("<9f", c.raw, 0)
    centre = struct.unpack_from("<3f", c.raw, sol.POSITION_OFFSET)
    ext = struct.unpack_from("<3f", c.raw, 0x58)
    print(f"{out.name}: {len(spots)} balls; {n} solids; ceiling box centre {tuple(round(v, 2) for v in centre)} "
          f"half-extents {tuple(round(v, 2) for v in ext)} up-row {tuple(round(v, 2) for v in rows[3:6])}")
