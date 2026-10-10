"""Hilly road course: layout, elevation, and the geometric checks the sweep needs.

Writes circuit.obj (a closed centreline with elevation, SOURCE frame: x, y ground,
z = elevation) and a preview PNG. Nothing here touches the game.
"""
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPACING = 5.0                      # dense sampling for checks; trackgen resamples again

# Control points, clockwise-ish, metres. Features noted where they fall.
CTRL = [
    (0, 0),        # start/finish, heading +x
    (260, 0),
    (480, 10),     # end of the main straight
    (590, 70),     # T1: fast right-hander
    (620, 180),
    (585, 270),    # esses begin
    (615, 360),
    (585, 450),
    (615, 540),    # esses end, climbing
    (560, 660),
    (440, 720),    # blind crest
    (300, 700),
    (190, 640),    # descending toward the hairpin
    (150, 560),
    (150, 470),    # hairpin: a 60 m arc about (90, 470), points every 45 degrees
    (132, 428),
    (90, 410),
    (48, 428),
    (30, 470),     # hairpin exit
    (30, 540),
    (-40, 610),
    (-170, 630),   # the dip
    (-300, 580),
    (-360, 470),   # back straight begins (heading -y)
    (-370, 300),
    (-360, 130),   # back straight ends
    (-300, 30),    # final corner
    (-160, -10),
]

# Elevation (metres) by fraction of the lap, smoothed with cosine blends.
ELEV = [(0.00, 0.0), (0.16, 0.0), (0.26, 4.0), (0.36, 14.0), (0.44, 24.0),
        (0.50, 22.0), (0.58, 10.0), (0.66, 6.0), (0.73, -6.0), (0.80, -2.0),
        (0.92, 0.0), (1.00, 0.0)]


def catmull_rom_closed(pts, n_per=40):
    out = []
    N = len(pts)
    for i in range(N):
        p0, p1, p2, p3 = pts[(i - 1) % N], pts[i], pts[(i + 1) % N], pts[(i + 2) % N]
        for k in range(n_per):
            t = k / n_per
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t
                                    + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3)
                             for j in range(2)))
    return out


def resample_closed(pts, step):
    ring = pts + [pts[0]]
    cum = [0.0]
    for a, b in zip(ring, ring[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    L = cum[-1]
    n = int(L // step)
    out, j = [], 0
    for i in range(n):
        s = i * L / n
        while cum[j + 1] < s:
            j += 1
        f = (s - cum[j]) / (cum[j + 1] - cum[j])
        a, b = ring[j], ring[j + 1]
        out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
    return out, L


def elevation(frac):
    for (f0, e0), (f1, e1) in zip(ELEV, ELEV[1:]):
        if f0 <= frac <= f1:
            u = (frac - f0) / (f1 - f0)
            return e0 + (e1 - e0) * (1 - math.cos(math.pi * u)) / 2
    return 0.0


def design():
    xy, L = resample_closed(catmull_rom_closed(CTRL), SPACING)
    pts = [(x, y, elevation(i / len(xy))) for i, (x, y) in enumerate(xy)]
    return pts, L


def checks(pts, L):
    n = len(pts)
    # turning radius from three points
    radii = []
    for i in range(n):
        a, b, c = pts[i - 2], pts[i], pts[(i + 2) % n]
        ab, bc, ca = math.dist(a[:2], b[:2]), math.dist(b[:2], c[:2]), math.dist(c[:2], a[:2])
        area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        radii.append(float("inf") if area2 < 1e-9 else ab * bc * ca / (2 * area2))
    # clearance between stretches more than 150 m apart along the lap
    sep = 150.0 / SPACING
    worst = (1e9, 0, 0)
    for i in range(0, n, 2):
        for j in range(i + 1, n, 2):
            d_idx = min(j - i, n - (j - i))
            if d_idx < sep:
                continue
            d = math.dist(pts[i][:2], pts[j][:2])
            if d < worst[0]:
                worst = (d, i, j)
    grades = [abs(pts[(i + 1) % n][2] - pts[i][2]) / SPACING for i in range(n)]
    return radii, worst, grades


if __name__ == "__main__":
    pts, L = design()
    radii, worst, grades = checks(pts, L)
    rmin = min(radii); imin = radii.index(rmin)
    print(f"lap {L:.0f} m, {len(pts)} stations at {SPACING} m")
    print(f"tightest radius {rmin:.1f} m at {imin * SPACING:.0f} m (need >= 40)")
    print(f"closest approach of separate stretches {worst[0]:.1f} m "
          f"(at {worst[1] * SPACING:.0f} m and {worst[2] * SPACING:.0f} m; need >= 70)")
    print(f"steepest grade {max(grades) * 100:.1f}%  elevation {min(p[2] for p in pts):.1f}"
          f"..{max(p[2] for p in pts):.1f} m")
    with open(HERE / "circuit.obj", "w") as f:
        for p in pts:
            f.write(f"v {p[0]:.3f} {p[1]:.3f} {p[2]:.3f}\n")
        f.write("l " + " ".join(str(i + 1) for i in range(len(pts))) + " 1\n")
