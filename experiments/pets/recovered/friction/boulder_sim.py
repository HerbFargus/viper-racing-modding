"""1-D model of a Viper Racing obstacle ball, from the retail exe (SphereVolume::CollideGround,
PhobDyno::Update, parse_obstacle):
  m = 0.4545 * M (obt mass is pounds); I = m * (2r)^2 (inertia from the mesh extent, i.e. diameter);
  ground spring k = 36 m per metre of sink, so sink d = g cos / 36;
  contact friction = -1000 N.s/m x slip, capped at 0.5 x normal force; spin capped at 10 rad/s;
  no air drag, no rolling resistance, no surface dependence; dt 0.016.
"""
import math
G, DT = 9.81, 0.016

def run(M, r, slope, x_end, v0=0.0):
    """slope(x) -> angle in degrees at horizontal distance x. Returns samples (t, x, v, slip)."""
    m = 0.4545 * M; I = m * (2 * r) ** 2
    x = t = w = 0.0; v = v0; out = []
    while x < x_end and t < 300:
        th = math.radians(slope(x)); d = G * math.cos(th) / 36.0; rc = r - d
        s = v - w * rc
        F = -math.copysign(min(1000.0 * abs(s), 0.5 * m * G * math.cos(th)), s)
        v += (G * math.sin(th) + F / m) * DT
        w = min(10.0, w - F * rc / I * DT)
        x += v * math.cos(th) * DT; t += DT
        out.append((t, x, v, s))
        if v < 0.5 and t > 2: break
    return out

def lane(deg, h=120.0):
    x1 = h / math.tan(math.radians(deg))
    return lambda x: deg if x < x1 else 0.0

MPH = 2.23694
if __name__ == "__main__":
    print("LAB 2: M 30000 lb, r 4 m, 120 m drop then flat; along to x = 1388 (the lane end)")
    for deg in (5, 10, 15, 20):
        s = run(30000, 4, lane(deg), 1388)
        x1 = 120 / math.tan(math.radians(deg))
        vb = max(p[2] for p in s if p[1] <= x1)
        t, x, v, _ = s[-1]
        print(f"  {deg:2d} deg: {vb*MPH:5.0f} mph at the foot (x {x1:4.0f}); at x {x:4.0f}: t {t:5.1f} s, {v*MPH:4.0f} mph")
    print("LAB 1: 10 deg, 173.6 m drop, r 4, by mass (speed at the foot, and 250 m on along the flat)")
    for M in (1000, 3000, 10000, 30000):
        s = run(M, 4, lane(10, 173.6), 1234.5)
        x1 = 173.6 / math.tan(math.radians(10))
        vb = max(p[2] for p in s if p[1] <= x1)
        t, x, v, _ = s[-1]
        print(f"  {M:6d} lb: {vb*MPH:5.0f} mph at the foot, {v*MPH:4.0f} mph at x {x:.0f}, t {t:5.1f} s")
    print("Flat, from 100 mph, r 4: how speed decays")
    for M in (1000, 10000, 30000, 100000):
        s = run(M, 4, lambda x: 0.0, 5000, v0=100 / MPH)
        pts = {int(p[0]): p[2] for p in s}
        print(f"  {M:6d} lb: " + "  ".join(f"t{k}s {pts.get(k, 0)*MPH:3.0f}" for k in (2, 5, 10, 20, 40)))
