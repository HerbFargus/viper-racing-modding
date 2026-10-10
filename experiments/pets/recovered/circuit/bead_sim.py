"""Reproduce IdealLine::reset_bead_position -> get_nearest_bead, to find car
positions that leave the AI's segment pointer null.

get_nearest_pair picks the claiming segment (see vrmod.ili.segment_claiming);
then up to 10 Newton steps: d = dot(p - lerp(P), normalize(lerp(T))), t += d/len.
While t > 1 it walks to the next segment, adding each segment's length to a
running total, and if that total passes the limit (10,000 for a reset) it
stores NULL. If t goes negative it clamps to 0 and stops.
"""
import math
import struct
import sys

import numpy as np

sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
from vrmod import archive  # noqa: E402

LIMIT = 10000.0


def load(path, member="default.ili"):
    by = {e.name.lower(): e for e in archive.read(path)}
    p = by[member].payload
    return np.array([struct.unpack_from("<17f", p, 12 + 68 * i)
                     for i in range((len(p) - 12) // 68)], dtype=np.float64)


class Line:
    def __init__(self, R):
        self.P = R[:, 1:3]; self.T = R[:, 3:5]; self.L = R[:, 8]; self.n = len(R)
        self.N = np.roll(self.P, -1, 0); self.TN = np.roll(self.T, -1, 0)

    def pair(self, q):
        a = q - self.P; b = q - self.N
        ok = ((a * self.T).sum(1) > 0) & ((b * self.TN).sum(1) < 0)
        if not ok.any():
            return None
        d2 = np.minimum((a * a).sum(1), (b * b).sum(1))
        d2[~ok] = np.inf
        return int(np.argmin(d2))

    def reset(self, q):
        """(segment or None, why, metres walked)."""
        seg = self.pair(q)
        if seg is None:
            return None, "no claiming segment", 0.0
        t, acc = 0.0, 0.0
        for _ in range(10):
            nx = (seg + 1) % self.n
            pos = self.P[seg] + t * (self.P[nx] - self.P[seg])
            tan = self.T[seg] + t * (self.T[nx] - self.T[seg])
            tan = tan / math.hypot(*tan)
            d = float(np.dot(q - pos, tan))
            if abs(d) < 0.0005:
                break
            t += d / self.L[seg]
            while t > 1.0:
                acc += self.L[seg]
                if acc > LIMIT:
                    return None, "walk passed 10 km", acc
                seg = (seg + 1) % self.n
                t -= 1.0
            if t < 0.0:
                t = 0.0
                break
        return seg, "ok", acc


def scan(path, spans=(200, 500, 1000, 2000, 5000), n=6000, seed=0):
    ln = Line(load(path))
    lo, hi = ln.P.min(0), ln.P.max(0)
    rng = np.random.default_rng(seed)
    print(path.split("/")[-1].split("\\")[-1], f"{ln.n} segments, mean {ln.L.mean():.1f} m")
    for span in spans:
        Q = rng.uniform(lo - span, hi + span, size=(n, 2))
        bad = [(q, *ln.reset(q)[1:]) for q in Q]
        bad = [b for b in bad if b[1] != "ok"]
        eg = [(round(float(q[0])), round(float(q[1])), why) for q, why, _ in bad[:3]]
        print(f"   within {span:>5} m of the line's box: {len(bad):>4} of {n} null  {eg}")
    return ln


if __name__ == "__main__":
    for p in sys.argv[1:]:
        scan(p)
