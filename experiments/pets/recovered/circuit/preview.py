"""Map + elevation profile of the designed circuit, drawn with Pillow."""
import math
from PIL import Image, ImageDraw, ImageFont
import design

pts, L = design.design()
n = len(pts)
W, H = 1200, 900
MAP = (60, 70, 1000, 650)          # x0, y0, x1, y1
PROF = (60, 720, 1140, 860)
BG, PANEL, GRID, TXT, DIM, ACC = "#15181c", "#1d232a", "#39424c", "#f1f3f5", "#8a949e", "#ffb454"
try:
    F = ImageFont.truetype("segoeui.ttf", 15); FB = ImageFont.truetype("segoeuib.ttf", 15)
    FT = ImageFont.truetype("segoeuib.ttf", 22); FS = ImageFont.truetype("segoeui.ttf", 12)
except OSError:
    F = FB = FT = FS = ImageFont.load_default()

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.rectangle(MAP, fill=PANEL); d.rectangle(PROF, fill=PANEL)

xs, ys, zs = [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts]
zmin, zmax = min(zs), max(zs)
pad = 60
sx = (MAP[2] - MAP[0] - 2 * pad) / (max(xs) - min(xs))
sy = (MAP[3] - MAP[1] - 2 * pad) / (max(ys) - min(ys))
s = min(sx, sy)
cx = (MAP[0] + MAP[2]) / 2 - s * (max(xs) + min(xs)) / 2
cy = (MAP[1] + MAP[3]) / 2 + s * (max(ys) + min(ys)) / 2
def P(x, y): return (cx + s * x, cy - s * y)          # north up


def ramp(t):
    """Dark teal (low) -> green -> yellow (high)."""
    stops = [(0.0, (38, 84, 124)), (0.5, (50, 168, 120)), (1.0, (240, 214, 80))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0)
            return tuple(int(a + (b - a) * u) for a, b in zip(c0, c1))
    return stops[-1][1]


# the corridor: road + verges, 28 m each side, faint
corr = max(2, int(2 * 28 * s))
d.line([P(x, y) for x, y in zip(xs + xs[:1], ys + ys[:1])], fill="#2a323b", width=corr, joint="curve")
for i in range(n):
    a, b = pts[i], pts[(i + 1) % n]
    t = ((a[2] + b[2]) / 2 - zmin) / (zmax - zmin)
    d.line([P(a[0], a[1]), P(b[0], b[1])], fill=ramp(t), width=7)

# start line and direction
x0, y0, _ = pts[0]
d.line([P(x0, y0 - 14), P(x0, y0 + 14)], fill="#ffffff", width=3)
ax, ay = P(pts[8][0], pts[8][1]); bx, by = P(pts[20][0], pts[20][1])
d.line([(ax, ay + 22), (bx, by + 22)], fill=ACC, width=3)
d.polygon([(bx + 10, by + 22), (bx - 4, by + 15), (bx - 4, by + 29)], fill=ACC)

labels = [(0, "START / FINISH", (-60, 18)), (620, "T1", (18, -4)), (1000, "ESSES", (22, -8)),
          (1480, "BLIND CREST", (-40, -34)), (1920, "HAIRPIN", (-30, 22)), (2340, "THE DIP", (-30, -34)),
          (2780, "BACK STRAIGHT", (-150, -8)), (3150, "FINAL CORNER", (-150, 10))]
def at(m): return pts[int(m / (L / n)) % n]
for m, t, (ox, oy) in labels:
    x, y = P(*at(m)[:2])
    d.line([(x, y), (x + ox * 0.6, y + oy * 0.6)], fill=DIM, width=1)
    d.text((x + ox, y + oy), t, fill=TXT, font=FB)

d.text((60, 22), f"Hilly road course   {L / 1000:.2f} km, anticlockwise", fill=TXT, font=FT)
d.text((620, 30), "tightest corner 44 m radius   ·   climbs 30 m   ·   steepest 8%", fill=DIM, font=F)

# legend
lx, ly = 1030, 90
d.text((lx, ly - 24), "elevation", fill=TXT, font=FB)
for k in range(200):
    t = 1 - k / 199
    d.line([(lx, ly + k), (lx + 22, ly + k)], fill=ramp(t))
d.text((lx + 30, ly - 6), f"{zmax:+.0f} m", fill=DIM, font=FS)
d.text((lx + 30, ly + 190), f"{zmin:+.0f} m", fill=DIM, font=FS)
d.text((lx, ly + 230), "grey band =", fill=DIM, font=FS)
d.text((lx, ly + 246), "road + verges", fill=DIM, font=FS)

# profile
px0, py0, px1, py1 = PROF
def Q(m, z): return (px0 + (m / L) * (px1 - px0), py1 - 12 - (z - zmin) / (zmax - zmin) * (py1 - py0 - 30))
prof = [Q(i * L / n, zs[i]) for i in range(n)] + [Q(L, zs[0])]
d.polygon(prof + [(px1, py1), (px0, py1)], fill="#2c5f52")
d.line(prof, fill="#7fd1b9", width=2)
for m, t, _ in labels:
    x = px0 + m / L * (px1 - px0)
    d.line([(x, py0), (x, py1)], fill=GRID)
    d.text((x + 4, py0 + 3), t.split(" /")[0], fill=DIM, font=FS)
d.text((px0, py1 + 6), "0 m", fill=DIM, font=FS)
d.text((px1 - 60, py1 + 6), f"{L:.0f} m", fill=DIM, font=FS)
d.text((px0, py0 - 22), "elevation round the lap", fill=TXT, font=FB)
img.save("circuit_preview.png")
print("ok")
