"""BigBalls at three masses: find the lightest that still falls (stays above the 0.5 m/s
the engine needs to keep an obstacle awake) and so drifts down like a balloon."""
import random
import sys

import build_bigballs as BB

B = BB.B
if __name__ == "__main__":
    masses = [float(m) for m in sys.argv[1:]] or [40.0, 400.0, 4000.0]
    line = B.make_base(drop=BB.DROP)
    rng = random.Random(B.SEED + 10)
    spots = B.ball_spots(line, BB.COUNT, rng, gap=BB.GAP, on_road=0.3)
    yaws = [rng.uniform(0, 360) for _ in spots]
    for m in masses:
        B.BALL_MASS = m
        B.write_count(spots, yaws, f"BigBall{int(m)}")
