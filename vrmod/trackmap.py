"""Generate a track map image -- the outline shown on the game's Track Info
screen -- from a track's own centre line.

The stock maps were hand-drawn: their aspect ratios don't follow any single
projection rule (Dayton's is 201x200 for a path that is 1:1.54), and different
tracks use different orientations. So this doesn't try to reproduce them
byte-for-byte; it draws the same *kind* of map, matching the stock palette and
proportions, from data we can read.

Source is `track.ild`, the timing/centre line -- not either racing line, which
cut corners and would draw a visibly tighter shape.

Stock maps measured for reference: black background, a single yellow
(240, 192, 0) path about 7 px wide, numbered circular markers around the lap,
and a chequered flag at the start/finish. The distance text on the Track Info
screen is drawn by the game's UI, not baked into this image.
"""
from __future__ import annotations

import math

from . import archive, envelope, ili

# Sampled straight out of the stock maps.
BACKGROUND = (0, 0, 0)
TRACK = (240, 192, 0)
MARKER_TEXT = (0, 0, 0)

MAX_WIDTH = 300
MAX_HEIGHT = 200
# Wide enough that an offset turn number can never fall off the canvas: a
# marker sits up to (disc radius + line_width/2 + 2) off the centre line, and
# on an S-bend the inside of the turn faces AWAY from the loop, pushing it
# outward. Roughly 20 px covers the worst case; 22 leaves a little air.
MARGIN = 22
LINE_WIDTH = 7

# 5x7 digit glyphs for the numbered markers. Sized to match the stock maps,
# where the numbers are comfortably legible against the yellow disc; a 3x5
# font at this image scale disappears into the track line.
_DIGIT_W, _DIGIT_H = 5, 7
_DIGITS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}


class _Canvas:
    def __init__(self, width: int, height: int, fill=BACKGROUND):
        self.w, self.h = width, height
        self.px = bytearray(bytes(fill) * (width * height))

    def set(self, x: int, y: int, colour):
        if 0 <= x < self.w and 0 <= y < self.h:
            o = (y * self.w + x) * 3
            self.px[o], self.px[o + 1], self.px[o + 2] = colour

    def disc(self, cx: float, cy: float, radius: float, colour):
        r = int(math.ceil(radius))
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= radius * radius:
                    self.set(int(cx) + dx, int(cy) + dy, colour)

    def thick_line(self, x0, y0, x1, y1, width, colour):
        """Stamp discs along the segment -- gives round joins and caps for
        free, which is what the stock maps' corners look like."""
        steps = max(1, int(math.hypot(x1 - x0, y1 - y0)))
        for i in range(steps + 1):
            t = i / steps
            self.disc(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, width / 2, colour)

    def digit(self, x, y, ch, colour):
        rows = _DIGITS.get(ch)
        if not rows:
            return
        for dy, row in enumerate(rows):
            for dx, on in enumerate(row):
                if on == "1":
                    self.set(x + dx, y + dy, colour)

    def number(self, cx, cy, text, colour):
        w = len(text) * (_DIGIT_W + 1) - 1
        x = int(cx) - w // 2
        for ch in text:
            self.digit(x, int(cy) - _DIGIT_H // 2, ch, colour)
            x += _DIGIT_W + 1

    def flag(self, cx, cy, colour=(255, 255, 255), dark=(0, 0, 0), cell=2, cols=5, rows=4):
        """Small chequered start/finish flag."""
        x0 = int(cx) - cols * cell // 2
        y0 = int(cy) - rows * cell // 2
        for r in range(rows):
            for c in range(cols):
                col = colour if (r + c) % 2 == 0 else dark
                for dy in range(cell):
                    for dx in range(cell):
                        self.set(x0 + c * cell + dx, y0 + r * cell + dy, col)


def _project(points, max_w, max_h, margin):
    """Fit the loop into a canvas, choosing whichever of the two top-down
    orientations makes better use of the space.

    Stock maps don't agree on orientation -- most read width as world Z, but
    Dundas and Rock Island read it as world X -- which is consistent with them
    being drawn by hand. Picking the orientation that scales larger keeps a
    generated map filling its canvas either way.
    """
    best = None
    for swap in (False, True):
        us = [(p.z if swap else p.x) for p in points]
        vs = [(p.x if swap else p.z) for p in points]
        du, dv = max(us) - min(us), max(vs) - min(vs)
        if du <= 0 or dv <= 0:
            continue
        scale = min((max_w - 2 * margin) / du, (max_h - 2 * margin) / dv)
        if best is None or scale > best[0]:
            best = (scale, us, vs, du, dv)
    if best is None:
        raise ValueError("degenerate track path")
    scale, us, vs, du, dv = best
    width = int(round(du * scale)) + 2 * margin
    height = int(round(dv * scale)) + 2 * margin
    u0, v0 = min(us), min(vs)
    # V maps straight to screen Y with no flip. Checked against the stock maps:
    # flipping it puts Bemidji's tri-oval bulge at the bottom and its
    # start/finish flag top-left, where the real map has them the other way up.
    xy = [(margin + (u - u0) * scale, margin + (v - v0) * scale)
          for u, v in zip(us, vs)]
    return xy, width, height


# A run of sustained turning worth this many degrees counts as one more
# numbered turn, which is how the stock maps read: an oval end sweeps about
# 180 degrees and carries TWO numbers (Bemidji's 1 and 2, then 4 and 5), with
# the tri-oval bulge as turn 3.
DEGREES_PER_TURN = 100.0
_TURN_THRESHOLD = 3.0   # degrees of heading change per waypoint
# Ignore runs that sweep less than this in total -- kinks rather than corners.
# Tuned so Bemidji lands on its real 5. It does NOT reproduce every track:
# Rock Island's stock map numbers 10 corners where this finds 15, and no
# threshold reproduces both, which is the evidence that the numbering is an
# authoring choice rather than anything computed. Pass markers=N to override.
_MIN_SWEPT = 15.0


def _corner_positions(points) -> list[int]:
    """Waypoint indices to number, one per corner, in driving order.

    The stock maps number corners the way a driver would, and nothing in the
    track archive stores that numbering -- camera.tab holds 7 cameras for
    Bemidji against its 5 map markers, so it isn't that either. This finds
    runs of sustained turning and splits long ones, which reproduces the
    convention closely enough to look right.
    """
    n = len(points)
    heading = []
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        heading.append(math.atan2(b.z - a.z, b.x - a.x))

    turn = []
    for i in range(n):
        d = heading[(i + 1) % n] - heading[i]
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        turn.append(math.degrees(d))

    runs, current = [], []
    for i in range(n):
        if abs(turn[i]) > _TURN_THRESHOLD:
            current.append(i)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    # A corner straddling the start/finish point is one corner, not two.
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == n - 1:
        runs[0] = runs[-1] + runs[0]
        runs.pop()

    spots = []
    for run in runs:
        swept = abs(sum(turn[i] for i in run))
        if swept < _MIN_SWEPT:
            continue
        count = max(1, int(round(swept / DEGREES_PER_TURN)))
        for k in range(count):
            spots.append(run[int((k + 0.5) / count * len(run))])
    return sorted(set(spots))


def _marker_spot(xy, idx, offset):
    """Where to put a turn number: off the centre line, into the open space
    on the inside of the turn.

    The stock maps do this, and it is what makes the numbers readable -- a
    yellow disc sitting on the yellow track blends into it, and the black
    digits end up fighting the line rather than a clean background.

    Direction comes from the angle bisector at the corner, which points into
    the turn regardless of which way the track is running or how the map is
    oriented. On a near-straight run the bisector collapses, so fall back to
    the perpendicular.
    """
    n = len(xy)
    x0, y0 = xy[(idx - 1) % n]
    x1, y1 = xy[idx]
    x2, y2 = xy[(idx + 1) % n]

    def unit(dx, dy):
        m = math.hypot(dx, dy)
        return (dx / m, dy / m) if m > 1e-9 else (0.0, 0.0)

    ax, ay = unit(x0 - x1, y0 - y1)
    bx, by = unit(x2 - x1, y2 - y1)
    bxs, bys = ax + bx, ay + by
    if math.hypot(bxs, bys) < 0.2:          # effectively straight here
        tx, ty = unit(x2 - x0, y2 - y0)
        bxs, bys = -ty, tx
    ux, uy = unit(bxs, bys)
    return x1 + ux * offset, y1 + uy * offset


def render(trk_path, *, max_width=MAX_WIDTH, max_height=MAX_HEIGHT,
           line_width=LINE_WIDTH, markers=None):
    """Draw a track map. Returns (rgb_pixels, width, height), top-down RGB888."""
    entries = archive.read(trk_path)
    entry = next((e for e in entries if e.name.lower() == "track.ild"), None)
    if entry is None:
        raise ValueError("track has no track.ild centre line")
    points = ili.parse(envelope.build(entry.tag, entry.version, entry.payload))
    if len(points) < 4:
        raise ValueError("centre line too short to draw")

    xy, width, height = _project(points, max_width, max_height, MARGIN)
    canvas = _Canvas(width, height)

    for i in range(len(xy)):
        (x0, y0), (x1, y1) = xy[i], xy[(i + 1) % len(xy)]
        canvas.thick_line(x0, y0, x1, y1, line_width, TRACK)

    spots = _corner_positions(points) if markers is None else [
        int((m + 0.5) / markers * len(xy)) % len(xy) for m in range(markers)
    ]
    for number, idx in enumerate(spots, start=1):
        label = str(number)
        # Size the disc to the label so double-digit turns still fit inside it.
        text_w = len(label) * (_DIGIT_W + 1) - 1
        radius = max(_DIGIT_H, text_w) / 2 + 2
        mx, my = _marker_spot(xy, idx, radius + line_width / 2 + 2)
        canvas.disc(mx, my, radius, TRACK)
        canvas.number(mx, my, label, MARKER_TEXT)

    _draw_start(canvas, xy, line_width)
    return bytes(canvas.px), width, height


START_TICK = (0, 0, 0)


def _draw_start(canvas, xy, line_width):
    """Start/finish: a tick drawn across the track, with the chequered flag
    set just off to the outside of the loop -- the arrangement the stock maps
    use, rather than the flag sitting on the racing surface."""
    x0, y0 = xy[0]
    x1, y1 = xy[1 % len(xy)]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    # Unit normal to the track direction.
    nx, ny = -dy / length, dx / length

    half = line_width / 2 + 2
    canvas.thick_line(x0 - nx * half, y0 - ny * half,
                      x0 + nx * half, y0 + ny * half, 2, START_TICK)

    # Push the flag to whichever side faces away from the loop's centre.
    cx = sum(p[0] for p in xy) / len(xy)
    cy = sum(p[1] for p in xy) / len(xy)
    if (x0 - cx) * nx + (y0 - cy) * ny < 0:
        nx, ny = -nx, -ny
    canvas.flag(x0 + nx * (half + 6), y0 + ny * (half + 6))


def build(trk_path, **kwargs) -> bytes:
    """Render a track map and encode it as a standalone .stp resource."""
    from . import stp
    pixels, width, height = render(trk_path, **kwargs)
    return stp.build_from_rgb(pixels, width, height)


MAP_MEMBER = "Trackmap.stp"


def install(trk_path, out_path=None, **kwargs) -> tuple:
    """Write a freshly rendered map into a track archive as Trackmap.stp.

    Returns (out_path, width, height). With no `out_path` this rewrites the
    track in place, after backing it up alongside.

    Note the map is written in the UNCOMPRESSED .stp variant while stock
    Trackmaps use the compressed one. The game reads both -- the community
    tga2stp workflow replaces Trackmap.stp with uncompressed output the same
    way -- but that is the one part of this worth confirming in game.
    """
    from pathlib import Path
    import shutil

    trk_path = Path(trk_path)
    entries = archive.read(trk_path)
    existing = next((e for e in entries if e.name.lower() == MAP_MEMBER.lower()), None)
    if existing is None:
        raise ValueError(f"{trk_path.name} has no {MAP_MEMBER} to replace")

    pixels, width, height = render(trk_path, **kwargs)
    from . import stp
    raw = stp.build_from_rgb(pixels, width, height)

    layout = archive.read_layout(trk_path.read_bytes())
    updated = archive.replace_entry(entries, existing.name, raw)
    out_path = Path(out_path) if out_path else trk_path
    if out_path == trk_path:
        backup = trk_path.with_suffix(trk_path.suffix + ".map-backup")
        if not backup.exists():
            shutil.copy2(trk_path, backup)
    out_path.write_bytes(archive.to_bytes(updated, partitioned=layout.partitioned))
    return out_path, width, height
