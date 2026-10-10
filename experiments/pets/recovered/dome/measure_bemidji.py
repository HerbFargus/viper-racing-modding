"""Measure stock Bemidji: the centreline's shape (straights, turn radii), and cross-sections of
the collision surface -- road width and banking -- along it. Measurement only."""
import math
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
from vrmod import archive, bpp, envelope, ili  # noqa: E402

TRK = r"C:\Users\seamus\Desktop\claude-code\game-files\viper-racing-usa\Data\bemidji.trk"
by = {e.name.lower(): e for e in archive.read(TRK)}
line = ili.parse_line(envelope.build(by["track.ild"].tag, by["track.ild"].version, by["track.ild"].payload))
P = np.array([(r[ili.FIELD_X], r[ili.FIELD_Z]) for r in line.records])
n = len(P)
seg = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1)
L = seg.sum()
print(f"track.ild: {n} points, lap {L:.0f} m; bounds x {P[:,0].min():.0f}..{P[:,0].max():.0f}, "
      f"z {P[:,1].min():.0f}..{P[:,1].max():.0f}; corridor {sorted({round(r[ili.FIELD_CORRIDOR],1) for r in line.records})}")

# curvature per point -> radius; group into straights and bends
def radius(i):
    a, b, c = P[i - 1], P[i], P[(i + 1) % n]
    ab, bc_, ca = np.linalg.norm(b - a), np.linalg.norm(c - b), np.linalg.norm(a - c)
    cr = (b - a)[0] * (c - a)[1] - (b - a)[1] * (c - a)[0]
    area = abs(cr) / 2
    return math.inf if area < 1e-6 else ab * bc_ * ca / (4 * area), np.sign(cr)
R = [radius(i) for i in range(n)]
s = np.concatenate([[0], np.cumsum(seg)[:-1]])
run, runs = None, []
for i in range(n):
    r, sg = R[i]
    kind = "straight" if r > 600 else ("L" if sg > 0 else "R")
    if run and run[0] == kind:
        run[2] = i; run[3].append(r)
    else:
        if run: runs.append(run)
        run = [kind, i, i, [r]]
runs.append(run)
print("sections (kind, from s, length, median radius):")
for kind, i0, i1, rs in runs:
    length = s[i1] - s[i0] + seg[i1]
    if length < 25:
        continue
    med = np.median([x for x in rs if x < 1e9]) if kind != "straight" else float("inf")
    print(f"  {kind:8s} s={s[i0]:6.0f}  {length:5.0f} m  r~{med:6.0f}")

# cross-sections of the collision surface
b = bpp.parse(by["track.bpp"].payload)
tris = b.triangles
T = np.array([t.v for t in tris])                 # game frame (x, y, z)
flags = np.array([t.flag for t in tris])
print("surface codes:", Counter(flags.tolist()).most_common(6))
bx0, bx1 = T[:, :, 0].min(1), T[:, :, 0].max(1)
bz0, bz1 = T[:, :, 2].min(1), T[:, :, 2].max(1)


def surf(x, z):
    idx = np.nonzero((bx0 <= x) & (bx1 >= x) & (bz0 <= z) & (bz1 >= z))[0]
    for i in idx:
        a, b_, c = T[i][:, [0, 2]]
        d = (b_[1] - c[1]) * (a[0] - c[0]) + (c[0] - b_[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b_[1] - c[1]) * (x - c[0]) + (c[0] - b_[0]) * (z - c[1])) / d
        l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (z - c[1])) / d
        if min(l1, l2, 1 - l1 - l2) >= -1e-6:
            y = l1 * T[i][0][1] + l2 * T[i][1][1] + (1 - l1 - l2) * T[i][2][1]
            return y, int(flags[i])
    return None, None


print("cross-sections (lat from -40 to +40 m, every 2 m): road extent and bank")
for frac in np.linspace(0, 1, 16, endpoint=False):
    i = int(frac * n)
    t = P[(i + 1) % n] - P[i - 1]
    t /= np.linalg.norm(t)
    nrm = np.array([-t[1], t[0]])
    prof = []
    for lat in np.arange(-40, 41, 2.0):
        q = P[i] + nrm * lat
        y, f = surf(*q)
        prof.append((lat, y, f))
    road = [(lat, y) for lat, y, f in prof if f == 0 and y is not None]
    if road:
        lats = [a for a, _ in road]
        w = max(lats) - min(lats)
        ys = np.array([y for _, y in road]); ls = np.array(lats)
        k = np.polyfit(ls, ys, 1)[0] if len(ls) > 2 else 0
        print(f"  s={s[i]:6.0f} r~{R[i][0]:7.0f}  road {min(lats):+.0f}..{max(lats):+.0f} ({w:.0f} m)  "
              f"bank {math.degrees(math.atan(k)):+5.1f} deg  codes {sorted({f for _, _, f in prof if f is not None})}")
    else:
        print(f"  s={s[i]:6.0f}: no road-coded surface across -40..40")
