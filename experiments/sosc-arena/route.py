"""The arena's lap: the perimeter ring as a Viper Racing route line.

Phase 2, step 1. The route line is what the timing gates, the starting grid and
the AI lines hang off; the arena's geometry carries none of them. `trackgen`
can recover a line from a road surface only when the road is a plain strip,
and this ring is a square with a T-junction and a ramp on every side, so the
line is built from the city instead.

    python route.py <sosc_dir> <city.sc2> <out_dir>

writes route.obj (the line as an OBJ polyline, which `trackgen` reads), and
route.png (the line, gates and grid drawn over the map, with its height profile).

THE RING, as Arena.sc2 has it
    corners    crossings (tile id 43) at x 38/84, y 42/88
    sides      46 tiles corner to corner, 736 m; a lap is just under 2.9 km
    the dips   mid-side the berm-top road drops two levels (15.8 m) over two
               slope tiles, runs 32 m flat past a T-junction whose ramp leads
               to the floor, and climbs back. West sits three tiles further
               along its side than north and south, east two further still.

DECISIONS (the user's, 2026-09-15): clockwise as seen from above with north --
the y = 42 side -- at the top; no walls; the floor drivable, with the gates
enforcing the route; start/finish mid-side.

GATES. Start/finish on the north side, plus one just past every corner. A gate
at a dip would sit on the ramp junction, where a car coming up from the floor
may or may not cross it; a gate past a corner cannot be reached without driving
that corner, so every shortcut across the floor misses at least one.

GRID. The flat at the bottom of the north dip is only 32 m. The line goes at its
far end and the grid's rows are 7.5 m apart rather than trackgen's 10, which
keeps all eight slots on the flat instead of on the 49% slope before it.
"""
from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import arena                                                # noqa: E402
import sc2                                                  # noqa: E402

TILE = sc2.TILE_M
CORNERS = ((38, 42), (84, 42), (84, 88), (38, 88))   # clockwise from north-west
START = (62.0, 42.5)          # tile units: the far (east) end of the north flat
FILLET = 0.5                  # corner radius, tiles (8 m): inside the crossing tile
SPACING = 4.0                 # metres between stations
GATE_AFTER_CORNER = 24.0      # metres past each corner's apex
GATE_HALF_WIDTH = 20.0        # 2.5 x the 8 m road half-width, as trackgen widens its gates
GRID_SLOTS, GRID_SPACING, GRID_OFFSET = 8, 7.5, 3.0


def ring_polyline() -> list[tuple[float, float]]:
    """The ring in tile units, clockwise, starting at START, corners filleted."""
    c = [(x + 0.5, y + 0.5) for x, y in CORNERS]
    pts = [START]
    for i in range(4):
        corner = c[(i + 1) % 4]                      # NE first: START is on the north side
        prev, nxt = c[i], c[(i + 2) % 4]
        din = _unit(corner[0] - prev[0], corner[1] - prev[1])
        dout = _unit(nxt[0] - corner[0], nxt[1] - corner[1])
        centre = (corner[0] + (dout[0] - din[0]) * FILLET, corner[1] + (dout[1] - din[1]) * FILLET)
        a0 = math.atan2(-dout[1], -dout[0])          # from the centre to the arc's entry
        a1 = math.atan2(din[1], din[0])              # ... and to its exit
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for k in range(9):
            a = a0 + sweep * k / 8
            pts.append((centre[0] + FILLET * math.cos(a), centre[1] + FILLET * math.sin(a)))
    return pts


def _unit(dx, dy):
    n = math.hypot(dx, dy)
    return dx / n, dy / n


def road_height(city, level, tx: float, ty: float) -> float:
    """Height of the road surface at a point in tile units -- bilinear over the
    tile's corners, which is exactly how arena.py builds a road tile."""
    x, y = min(int(tx), sc2.SIZE - 1), min(int(ty), sc2.SIZE - 1)
    u, v = tx - x, ty - y
    h = arena.corner_heights(city, x, y, level)
    lo = h[(-1, -1)] * (1 - u) + h[(1, -1)] * u
    hi = h[(-1, 1)] * (1 - u) + h[(1, 1)] * u
    return lo * (1 - v) + hi * v


def resample_closed(pts, spacing):
    """Even stations round the closed loop, in metres, the first at pts[0]."""
    out, carry = [pts[0]], 0.0
    loop = pts + [pts[0]]
    for a, b in zip(loop, loop[1:]):
        seg = math.dist(a, b)
        t = spacing - carry
        while t <= seg:
            out.append((a[0] + (b[0] - a[0]) * t / seg, a[1] + (b[1] - a[1]) * t / seg))
            t += spacing
        carry = (carry + seg) % spacing
    if math.dist(out[-1], out[0]) < spacing * 0.5:
        out.pop()
    return out


def build(sosc: Path, city_path: Path) -> dict:
    city = sc2.read(city_path)
    city.base_level = Counter(a for col in city.altitude for a in col).most_common(1)[0][0]
    level = arena.level_height(sosc / "GEO")

    ring = [(x * TILE, y * TILE) for x, y in ring_polyline()]       # metres, map frame
    st = resample_closed(ring, SPACING)
    stations = [(x, y, road_height(city, level, x / TILE, y / TILE)) for x, y in st]
    n = len(stations)
    lap = sum(math.dist(stations[i][:2], stations[(i + 1) % n][:2]) for i in range(n))

    def left_normal(i):
        ax, ay, _ = stations[i - 1]
        bx, by, _ = stations[(i + 1) % n]
        dx, dy = _unit(bx - ax, by - ay)
        return dy, -dx      # map frame has y DOWN the page, so this points left of travel

    def gate(i, name):
        x, y, h = stations[i]
        nx, ny = left_normal(i)
        return name, i, [(x + nx * GATE_HALF_WIDTH, y + ny * GATE_HALF_WIDTH, h),
                         (x - nx * GATE_HALF_WIDTH, y - ny * GATE_HALF_WIDTH, h)]

    gates = [gate(0, "check1")]
    for k, (cx, cy) in enumerate(CORNERS[1:] + CORNERS[:1]):       # NE, SE, SW, NW
        apex = min(range(n), key=lambda i: math.dist(stations[i][:2], ((cx + .5) * TILE, (cy + .5) * TILE)))
        gates.append(gate((apex + round(GATE_AFTER_CORNER / SPACING)) % n, f"check{k + 2}"))

    grid = []
    for k in range(GRID_SLOTS):
        back = (k // 2 + 1) * GRID_SPACING
        i = (-round(back / SPACING)) % n
        x, y, _ = stations[i]
        nx, ny = left_normal(i)
        side = GRID_OFFSET if k % 2 == 0 else -GRID_OFFSET
        gx, gy = x + nx * side, y + ny * side
        grid.append((gx, gy, road_height(city, level, gx / TILE, gy / TILE)))

    return {"city": city, "level": level, "stations": stations, "lap_m": lap,
            "gates": gates, "grid": grid}


def to_source(p):
    """Map frame (x right, y down the map, height) -> trackgen's source frame.

    trackgen's meshes are (-source.x, height, -source.y), and the arena's meshes
    will be (map.x, height, map.y), so source = (-map.x, -map.y, height). Both
    ground axes flip together: a rotation, not a mirror, so clockwise stays
    clockwise.
    """
    return (-p[0], -p[1], p[2])


def write_obj(route: dict, path: Path) -> None:
    lines = ["# arena lap, clockwise, trackgen source frame (x, y, elevation)"]
    lines += [f"v {x:.3f} {y:.3f} {h:.3f}" for x, y, h in map(to_source, route["stations"])]
    n = len(route["stations"])
    lines.append("l " + " ".join(str(i + 1) for i in range(n)) + " 1")
    path.write_text("\n".join(lines) + "\n")


def draw(route: dict, path: Path) -> None:
    from PIL import Image, ImageDraw
    city = route["city"]
    B, A = city.grids["XBLD"], city.altitude
    x0, y0, x1, y1 = 34, 38, 93, 97
    S = 12
    W, H = (x1 - x0) * S, (y1 - y0) * S
    prof_h = 190
    img = Image.new("RGB", (W, H + prof_h), (24, 24, 28))
    d = ImageDraw.Draw(img)
    for x in range(x0, x1):
        for y in range(y0, y1):
            b, a = B[x][y], A[x][y]
            if b in arena.ROADS:
                col = (150, 150, 150) if a > city.base_level else (70, 70, 74)
            elif b:
                col = (120, 60, 60)
            elif a > city.base_level:
                col = (196, 160, 118)
            else:
                col = (96, 120, 66)
            d.rectangle(((x - x0) * S, (y - y0) * S, (x - x0 + 1) * S - 1, (y - y0 + 1) * S - 1), fill=col)
    px = lambda p: ((p[0] / TILE - x0) * S, (p[1] / TILE - y0) * S)
    st = route["stations"]
    d.line([px(p) for p in st] + [px(st[0])], fill=(255, 215, 0), width=2)
    n = len(st)
    for i in range(0, n, 60):                                     # direction arrows
        a, b = px(st[i]), px(st[(i + 3) % n])
        dx, dy = _unit(b[0] - a[0], b[1] - a[1])
        tip = (a[0] + dx * 14, a[1] + dy * 14)
        d.polygon([tip, (a[0] - dy * 6, a[1] + dx * 6), (a[0] + dy * 6, a[1] - dx * 6)], fill=(255, 215, 0))
    for name, i, (p, q) in route["gates"]:
        d.line([px(p), px(q)], fill=(230, 40, 40) if name != "check1" else (255, 255, 255), width=4)
        tx, ty = px(p)
        d.text((tx + 4, ty - 12), name, fill=(255, 255, 255))
    for k, g in enumerate(route["grid"]):
        cx, cy = px(g)
        d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(60, 160, 255))
    # height profile along the lap, gates marked
    top = H + 20
    hs = [p[2] for p in st]
    lo, hi = min(hs), max(hs)
    ph = prof_h - 50
    cum = [0.0]
    for i in range(1, n):
        cum.append(cum[-1] + math.dist(st[i - 1][:2], st[i][:2]))
    sx = lambda s: 10 + s / route["lap_m"] * (W - 20)
    sy = lambda h: top + ph - (h - lo) / ((hi - lo) or 1) * ph
    d.line([(sx(c), sy(h)) for c, h in zip(cum, hs)], fill=(255, 215, 0), width=2)
    for name, i, _ in route["gates"]:
        d.line([(sx(cum[i]), top), (sx(cum[i]), top + ph)], fill=(230, 40, 40) if name != "check1" else (255, 255, 255))
        d.text((sx(cum[i]) + 3, top), name, fill=(255, 255, 255))
    d.text((10, top + ph + 8), f"height along the lap: {lo:.1f} m to {hi:.1f} m, lap {route['lap_m']:.0f} m, "
                               f"{n} stations every {SPACING:g} m -- white: start/finish, red: gates, blue: grid",
           fill=(220, 220, 220))
    img.save(path)


def main(argv):
    if len(argv) != 3:
        raise SystemExit("route.py <sosc_dir> <city.sc2> <out_dir>")
    out = Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    r = build(Path(argv[0]), Path(argv[1]))
    write_obj(r, out / "route.obj")
    draw(r, out / "route.png")
    st = r["stations"]
    print(f"  stations   {len(st)} every {SPACING:g} m, lap {r['lap_m']:.1f} m")
    print(f"  height     {min(p[2] for p in st):.2f} .. {max(p[2] for p in st):.2f} m")
    for name, i, (p, q) in r["gates"]:
        x, y, h = st[i]
        print(f"  {name:7}    station {i:4d}  tile ({x / TILE:5.1f}, {y / TILE:5.1f})  h {h:5.2f}")
    flat = st[0][2]
    for k, (x, y, h) in enumerate(r["grid"]):
        print(f"  grid {k + 1}     tile ({x / TILE:5.2f}, {y / TILE:5.2f})  h {h:5.2f}"
              f"  {'flat' if abs(h - flat) < 0.05 else f'{h - flat:+.2f} m off the flat'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
