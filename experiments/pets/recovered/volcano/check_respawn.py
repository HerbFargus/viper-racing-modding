"""Where does a reset put you? The engine's own lookup, reproduced, on the built scene."""
import contextlib
import io
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_volcano as V  # noqa: E402
from vrmod import ili  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    scene, g, _line, _w = V.main(verbose=False)
line, flags = V.respawn_line(g)
recs = line.records
n = len(recs)
P = np.array([(r[ili.FIELD_X], r[ili.FIELD_Z]) for r in recs])          # game frame
SRC = np.array([(-x, -z) for x, z in P])                                 # back to source (x, y)

# the collision surface, for slope and height under a respawn point
T = np.array([[V.bc.source_of((m.vertices[i].x, m.vertices[i].y, m.vertices[i].z)) for i in f]
              for o in scene.driveables for m in [scene.meshes[o.name]] for f in m.faces])
N = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
N /= np.linalg.norm(N, axis=1)[:, None]
SLOPE = np.degrees(np.arccos(np.abs(N[:, 2])))
box = np.stack([T[:, :, 0].min(1), T[:, :, 0].max(1), T[:, :, 1].min(1), T[:, :, 1].max(1)], 1)


def ground(x, y):
    cand = np.nonzero((box[:, 0] <= x) & (box[:, 1] >= x) & (box[:, 2] <= y) & (box[:, 3] >= y))[0]
    for i in cand:
        a, b, c = T[i]
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
        l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
        if min(l1, l2, 1 - l1 - l2) >= -1e-9:
            return l1 * a[2] + l2 * b[2] + (1 - l1 - l2) * c[2], SLOPE[i]
    return None, None


def respawn(x, y, back=0.0):
    """Source (x, y) of the car -> source point a reset lands on (chord foot, shift 0 on the detour)."""
    i = ili.segment_claiming(line, -x, -y)
    if i is None:
        return None, None
    a, b = SRC[i], SRC[(i + 1) % n]
    d = b - a
    t = float(np.clip(np.dot(np.array([x, y]) - a, d) / np.dot(d, d), 0, 1))
    # walk back `back` metres along the line
    seg, s_ = i, t * np.linalg.norm(d) - back
    while s_ < 0:
        seg = (seg - 1) % n
        s_ += np.linalg.norm(SRC[(seg + 1) % n] - SRC[seg])
    a, b = SRC[seg], SRC[(seg + 1) % n]
    u = (b - a) / np.linalg.norm(b - a)
    shift = recs[seg][ili.FIELD_CORRIDOR] * 0.5 - 2.5      # TeleportToLine: to the LEFT of travel (field 11 = 0)
    q = a + u * s_ + np.array([-u[1], u[0]]) * shift
    return (float(q[0]), float(q[1])), (seg, flags[seg], shift, tuple(np.round(u, 2)))


bad = []
worst = 0.0
count = 0
for r in np.arange(0.5, V.RR, 1.5):                       # the whole crater, lava and walls
    for a in np.linspace(0, 2 * math.pi, 48, endpoint=False):
        x, y = V.CX + r * math.cos(a), V.CY + r * math.sin(a)
        for back in (0.0, 7.0, 14.0):
            q, info = respawn(x, y, back)
            count += 1
            if q is None:
                bad.append((x, y, back, "unclaimed"))
                continue
            seg, det, shift, facing = info
            z, sl = ground(*q)
            on = float(V.terrace_dist(*q))
            if on > V.TERRACE_W - 2.0 or sl is None or sl > 3.0 or (back == 0 and (not det or facing[1] < 0.9)):
                bad.append((round(x, 1), round(y, 1), back, f"-> {tuple(round(v, 1) for v in q)} seg {seg} "
                            f"detour {det} shift {shift:.2f} facing {facing} terrace {on:.1f} slope {sl}"))
            else:
                worst = max(worst, sl)
print(f"crater points x (0, 7, 14 m step-back): {count}; respawns off the flat terrace: {len(bad)}; "
      f"worst terrace slope {worst:.2f} deg")
for b in bad[:12]:
    print("  ", b)

# the driven path: approach, the jump, the landing and on; nothing may be unclaimed
path_bad = [(0.0, y) for y in np.arange(-120, 140, 0.5) if ili.segment_claiming(line, -0.0, -y) is None]
print("points on the driven line with no claiming segment:", path_bad[:5] or "none")
# forward: every detour segment heads north-ish (the road runs north here)
fw = [(i, tuple(np.round(SRC[(i + 1) % n] - SRC[i], 1))) for i in range(n) if flags[i]
      and (SRC[(i + 1) % n] - SRC[i])[1] <= 0]
print("detour segments heading backwards:", fw or "none")
print("origin claimed:", ili.origin_is_claimed(line),
      "| lap", round(recs[-1][ili.FIELD_DISTANCE] + recs[-1][ili.FIELD_STEP], 1), "m")

# a reset from ANY position must find a segment, or the game reads through a null next frame
holes = [(x, y) for x in np.arange(-150, 151, 3.0) for y in np.arange(-150, 151, 3.0)
         if ili.segment_claiming(line, -(V.CX + x), -(V.CY + y)) is None]
print("unclaimed points in a 300 m square round the crater:", len(holes), holes[:6])
