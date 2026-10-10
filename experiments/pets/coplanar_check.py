"""List coplanar, OVERLAPPING, both-facing-the-eye triangle pairs of different colour in each cockpit shell -- the
z-fighting that flickers in game (every cockpit face is rewound toward the eye, so two solids
touching shows both surfaces)."""
import sys; sys.path.insert(0, '../..'); sys.path.insert(0, '.')
import numpy as np
import kit  # noqa
from kit import cockpit
from kit.shapes import Builder
import cvd_models as M


def overlap2d(P, Q, n):
    ax = int(np.argmax(np.abs(n)))
    keep = [i for i in range(3) if i != ax]
    p, q = P[:, keep], Q[:, keep]
    def sep(a, b):
        for poly in (a, b):
            for i in range(3):
                e = poly[(i + 1) % 3] - poly[i]
                nrm = np.array([-e[1], e[0]])
                pa, pb = a @ nrm, b @ nrm
                if pa.max() <= pb.min() + 1e-6 or pb.max() <= pa.min() + 1e-6:
                    return True
        return False
    return not sep(p, q)


for name, make, ck in (("alleycat", M.alley_cat, M.alley_cat_cockpit), ("doghouse", M.doghouse, M.doghouse_cockpit)):
    m = make(); c = ck(m["body"]); sh = Builder().extend(c["shell"]).extend(cockpit.toward(c["inside"], c["eye"]) if c.get("inside") else Builder())
    T = []
    for a, b, cc, col in sh.tris:
        P = np.array([a, b, cc], float); n = np.cross(P[1] - P[0], P[2] - P[0]); l = np.linalg.norm(n)
        if l > 1e-9:
            n = n / l; T.append((P, n, float(n @ P[0]), col))
    hits = set()
    for i in range(len(T)):
        for j in range(i + 1, len(T)):
            Pi, ni, di, ci = T[i]; Pj, nj, dj, cj = T[j]
            e = np.asarray(c["eye"], float)
            facing = (ni @ (e - Pi.mean(0)) > 0) and (nj @ (e - Pj.mean(0)) > 0)
            if facing and ni @ nj > 1 - 1e-4 and abs(di - dj) < 2e-3:
                if ci != cj and overlap2d(Pi, Pj, ni):
                    hits.add((ci, cj, tuple(np.round(Pi.mean(0), 2))))
    print(name, len(hits), "overlapping coplanar pairs", sorted(hits)[:12])
