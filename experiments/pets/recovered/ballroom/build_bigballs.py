"""BigBalls: 100 beach balls ten times the size (16 m across), mass 40, dropped the engine's 4 m.

The same white room as the ladder (build_ballroom), with walls tall enough to keep
16 m balls in: 24 m drawn, 45 m solid.

A higher drop is NOT possible from the track: an invisible vertex below the ball does
lift the spawn, but the engine rests the obstacle on its lowest point, so the ball
comes to rest on that vertex like a stilt and hangs in the air (confirmed in game at
masses 4-4000). Kept in build_ballroom.ball_mesh(drop=) for hovering props.
"""
import random

import build_ballroom as B

B.BALL_MASS = 40.0                 # mass 4 floats; 40 still falls

B.BALL_R = 8.0                     # 10x the 0.8 m ball
B.WALL_H, B.WALL_SOLID = 24.0, 45.0
DROP = 0.0                         # no stilt: the engine's own 4 m drop
COUNT, GAP = 100, 18.5             # centres at least a ball-and-a-bit apart

if __name__ == "__main__":
    line = B.make_base(drop=DROP)
    rng = random.Random(B.SEED + 10)
    spots = B.ball_spots(line, COUNT, rng, gap=GAP, on_road=0.3)
    B.write_count(spots, [rng.uniform(0, 360) for _ in spots], "BigBalls")
