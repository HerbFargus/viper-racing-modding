"""Fit a converted car's brake lights to its own bodywork.

`<prefix>b.mod` is the brake mesh: two quads, eight vertices, a flat plane at the
car's tail sampling the glow patch of the shared `effects.tex`. `carfork` copies
it from the donor unchanged, so every converted car wears the donor's lights at
the donor's dimensions. Measured across the fleet before this ran:

    azzaroni / airhawk / j57   body tail z -2.14, brake plane z -1.95
                               -> 19cm INSIDE the body, invisible
    strtrat / police           body tail z -2.16, brake plane z -2.25
                               ->  9cm BEHIND the body, floating
    hmxvan / hunter            flush by luck, donor's width and height

WHERE THE LIGHTS ARE. The lights are painted into the skin, not modelled, and on
a 90s mesh the whole rear panel is one or two quads with the lights as texels
inside them -- so "which face is the light" has no answer. Not one face on the
Airhawk is more than 25% red. What does have an answer is "where do the red
texels land in car space": sample each rear face across its UV triangle,
interpolate the position of every sample that reads as a lamp, and cluster.

WHAT COUNTS AS A LAMP. Red is not enough. The Airhawk's gold livery is
RGB(128, 80, 0), which passes any "red beats green and blue" test and smears the
cluster across the whole rear of the car. Real lamps are red with almost no
green: the police car's are RGB(112, 8, 8) and RGB(120, 40, 8). Requiring green
and blue to be genuinely low separates them cleanly.

A car whose art has no recognisable lamps still needs a brake mesh, so the
geometric fallback places the quads on the tail using the proportions the
shipped cars use. It is always reported, never silent -- a fitted pair and a
guessed pair should not look the same in the output.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from vrmod import archive, envelope, mod, tex  # noqa: E402

# Barycentric sample grid over a face's UV triangle. 91 points is enough to find
# a lamp that covers a few percent of a panel without making the pass slow.
GRID = [(a / 12, b / 12) for a in range(13) for b in range(13 - a)]

# The rear fraction of the car to look in. Tail lights are not halfway up a bonnet.
REAR_FRACTION = 0.30

# The glow patch on effects.tex, taken from the shipped brake meshes -- every
# stock car uses the same corner of the same shared texture.
GLOW_UV = ((0.004, 0.383), (0.004, 0.480), (0.110, 0.379), (0.117, 0.484))
BRAKE_TEXTURE = "effects.tex"

# Sit the quads this far proud of the panel they belong to, so they cannot
# z-fight with it.
PROUD = 0.01


@dataclass
class Lamp:
    x0: float
    x1: float
    y0: float
    y1: float
    z: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def is_lamp(r: int, g: int, b: int) -> bool:
    """A red lamp, not red-ish bodywork.

    The thresholds come from comparing a car whose lamps the loose test found
    cleanly (police: RGB 112,8,8 / 120,40,8 / 96,32,8) against one where it
    found the paint instead (airhawk gold: RGB 128,80,0 / 112,72,56 / 104,64,8).
    Green is what separates them, so green is what the test leans on.
    """
    return r >= 90 and g <= 48 and b <= 48 and r >= 2.2 * max(g, b, 1)


def load(car: Path, prefix: str):
    ents = {e.name.lower(): e for e in archive.read(car)}
    e = ents[f"{prefix}0.mod"]
    body = mod.parse(envelope.build(e.tag, e.version, e.payload))
    textures = {}
    for name, en in ents.items():
        if name.endswith(".tex"):
            info = tex.parse(envelope.build(en.tag, en.version, en.payload))
            px = tex.decode_base_level(info)
            textures[name] = (px, info.size, len(px) // (info.size ** 2))
    return ents, body, textures


def lamp_points(body, textures) -> list[tuple[float, float, float]]:
    """Every lamp texel on the rear of the car, in car space.

    Each face's UV triangle is RASTERISED -- every texel it actually covers is
    visited -- rather than sampled on a fixed grid. That is not fussiness: the
    Airhawk's lamps are 90 texels out of 65,536, nine hundredths of one percent
    of its skin, and a 91-point grid over a whole rear panel lands on them
    essentially never. The first version of this used the grid, found nothing on
    six of seven cars, and reported a lamp 1cm wide on the seventh.
    """
    zs = [v.z for v in body.vertices]
    cut = min(zs) + REAR_FRACTION * (max(zs) - min(zs))
    pts = []
    for mat in body.materials:
        key = mat.name.lower()
        if key not in textures:
            continue
        px, n, ch = textures[key]
        for fi in range(mat.face_start, mat.face_end):
            vs = [body.vertices[i] for i in body.faces[fi]]
            if sum(v.z for v in vs) / 3 > cut:
                continue
            # the triangle in texel space
            tri = [(v.u * (n - 1), (1 - v.v) * (n - 1)) for v in vs]
            (x0, y0), (x1, y1), (x2, y2) = tri
            det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(det) < 1e-9:
                continue                       # degenerate in UV space
            lo_x = max(int(min(x0, x1, x2)), 0)
            hi_x = min(int(max(x0, x1, x2)) + 1, n - 1)
            lo_y = max(int(min(y0, y1, y2)), 0)
            hi_y = min(int(max(y0, y1, y2)) + 1, n - 1)
            for ty in range(lo_y, hi_y + 1):
                for tx in range(lo_x, hi_x + 1):
                    a = ((y1 - y2) * (tx - x2) + (x2 - x1) * (ty - y2)) / det
                    b = ((y2 - y0) * (tx - x2) + (x0 - x2) * (ty - y2)) / det
                    c = 1 - a - b
                    if a < -0.02 or b < -0.02 or c < -0.02:
                        continue               # outside the triangle
                    i = (ty * n + tx) * ch
                    if is_lamp(px[i], px[i + 1], px[i + 2]):
                        pts.append((a * vs[0].x + b * vs[1].x + c * vs[2].x,
                                    a * vs[0].y + b * vs[1].y + c * vs[2].y,
                                    a * vs[0].z + b * vs[1].z + c * vs[2].z))
    return pts


def _cluster(points, axis_span=0.30):
    """Trim a side's points to the tight group around the median.

    A handful of stray red texels elsewhere on the tail would otherwise stretch
    the lamp box across the whole panel, which is how the first version of this
    produced "lights" the width of the car.
    """
    if len(points) < 4:
        return None
    ys = sorted(p[1] for p in points)
    zs = sorted(p[2] for p in points)
    my, mz = ys[len(ys) // 2], zs[len(zs) // 2]
    keep = [p for p in points if abs(p[1] - my) <= axis_span
            and abs(p[2] - mz) <= axis_span]
    if len(keep) < 4:
        return None
    return Lamp(min(p[0] for p in keep), max(p[0] for p in keep),
                min(p[1] for p in keep), max(p[1] for p in keep),
                min(p[2] for p in keep))


def _mirror(lamp: Lamp) -> Lamp:
    return Lamp(-lamp.x1, -lamp.x0, lamp.y0, lamp.y1, lamp.z)


# Where the five shipped cars put their lamps, as a fraction of their own body.
# They agree closely, which is what makes this usable as a rule rather than as
# one car's habit:
#
#     viper   height 40..74%   outboard 35..95%
#     exotic  height 44..80%   outboard 32..86%
#     sedan   height 39..70%   outboard 36..98%
#     4x4cos  height 46..65%   outboard 42..79%
#     sports  height 45..83%   outboard 36..98%
# ...but the SoSC bodies do not wear them there. Rendering the brake mesh merged
# into the body -- the only way to see it, since carshot never draws b.mod --
# shows the painted lamps sitting LOW on these cars, just above the bumper:
# roughly 45% of body height on the Airhawk, 20% on the Ferrari, 25% on the
# Beetle. So the vertical band is taken from the converted cars themselves and
# the horizontal one from the shipped cars, which agree closely enough to trust.
LAMP_BAND = dict(y_lo=0.24, y_hi=0.58, x_in=0.34, x_out=0.95, min_w=0.28,
                 min_h=0.12)


def _place(lamp: Lamp, body) -> Lamp:
    """Fit a detected lamp into the envelope the shipped cars use.

    The texels locate a lamp's HEIGHT well -- that is where the red is -- and
    bound its width badly, because only the columns of panel that happen to map
    to it show up: the police car's came out 1cm wide. Worse, a detection can be
    confidently wrong about x. On the Airhawk the cluster ran from 19% to 69% of
    the half-width, which put the inner edge of each lamp in the number-plate
    recess, and that is exactly where they appeared in game.

    So the detection is CONSTRAINED rather than trusted: it keeps whatever falls
    inside the band above and is slid out to the band's edge where it does not.
    A car whose art genuinely disagrees with every car the game shipped is more
    likely a bad detection than a bad car.
    """
    xs = [v.x for v in body.vertices]
    ys = [v.y for v in body.vertices]
    half = max(abs(min(xs)), abs(max(xs)))
    h = max(ys) - min(ys)
    base = min(ys)
    b = LAMP_BAND

    # X comes from the band, NOT from the detection. The texels bound a lamp
    # horizontally only as well as the panel's UV columns happen to line up with
    # it, and on the Airhawk that produced an inner edge at 19% of the
    # half-width -- lamps sitting on the number plate, which is exactly where
    # they turned up in game. Constraining that to 32% still left them inboard
    # of the real ones. Five shipped cars agree on 32-98%, so the proportion is
    # better evidence than this detector's x has ever been.
    #
    # Height is the opposite case: the detector put the Airhawk's lamps at
    # 64-76%, and rendering the brake mesh merged into the body (the only way to
    # see it at all, since carshot never draws b.mod) confirms the painted lamps
    # really are about two thirds up the panel. So height is kept.
    inner = b["x_in"] * half
    outer = b["x_out"] * half
    sign = -1.0 if (lamp.x0 + lamp.x1) < 0 else 1.0

    # Height DOES come from the detection. This flip-flopped once: the detector
    # put the Airhawk's lamps at 64-76% of body height, a render was misread as
    # saying 45%, the band was lowered to match, and in game the lights came out
    # sitting on the bumper. The detector was right. Reading a small grey quad's
    # height off a 240px render is simply less reliable than the texels, which
    # are the art itself -- so the texels win, and the band only has to serve
    # cars where no lamps were found at all.
    #
    # Heights genuinely differ per car: the Airhawk carries its lamps high on a
    # fastback tail, the Beetle and Ferrari low. One band cannot serve both,
    # which is why the band is the fallback and not the rule.
    cy = (lamp.y0 + lamp.y1) / 2
    t = max(lamp.height, b["min_h"] * h) / 2
    cy = min(max(cy, base + 0.18 * h), base + 0.88 * h)
    lo = cy - t

    # Depth: sit proud of however far back the BODY reaches at the lamps' own
    # height, not at the z the texels were found at. The Airhawk's lamp texels
    # are at z -2.02 while its bumper reaches -2.14, so using the detected z put
    # the quads 12cm inside the bodywork -- in game, brake lights under the
    # bumper. Measuring at the lamp's height rather than globally matters too: a
    # rear wing or a spare wheel is the rearmost point of some cars and would
    # leave the lamps floating in mid-air behind the tail.
    band = [v.z for v in body.vertices if lo - 0.05 <= v.y <= lo + 2 * t + 0.05]
    z = (min(band) if band else min(v.z for v in body.vertices)) - PROUD
    return Lamp(min(sign * inner, sign * outer), max(sign * inner, sign * outer),
                lo, lo + 2 * t, z)


def find_lamps(body, textures):
    """(left, right) lamp boxes, or None if the art does not locate them."""
    pts = lamp_points(body, textures)
    left = _cluster([p for p in pts if p[0] < 0])
    right = _cluster([p for p in pts if p[0] >= 0])

    # These cars mirror their UVs down the centreline, so both physical lamps
    # sample the SAME texels and only one side's faces map them back: the
    # Airhawk yields 19 points all on the left, the Ferrari 20 all on the right,
    # the police car 11 and 11. One good side is therefore a normal result, not
    # a partial failure -- mirror it rather than discarding the car.
    if left and not right:
        right = _mirror(left)
    elif right and not left:
        left = _mirror(right)
    if not (left and right):
        return None
    # Cars are symmetric, and a genuine pair of lamps is the strongest evidence
    # available that what was found is lamps rather than two unrelated red
    # patches. Reject anything that does not mirror.
    cx_l = abs((left.x0 + left.x1) / 2)
    cx_r = abs((right.x0 + right.x1) / 2)
    cy_l, cy_r = (left.y0 + left.y1) / 2, (right.y0 + right.y1) / 2
    if abs(cx_l - cx_r) > 0.25 * max(cx_l, cx_r, 0.01):
        return None
    if abs(cy_l - cy_r) > 0.15 or abs(left.z - right.z) > 0.20:
        return None
    # A tail light is outboard. A cluster sitting on the centreline is a badge,
    # a number-plate lamp or a centre reflector -- the Ferrari's found cluster is
    # at x 0.10 and the van's at -0.09, and mirroring those produces two lamps
    # that overlap each other across the middle of the car. Require the centre
    # of each to be at least a quarter of the way out.
    xs = [v.x for v in body.vertices]
    half = max(abs(min(xs)), abs(max(xs)))
    if min(cx_l, cx_r) < 0.25 * half:
        return None
    return _place(left, body), _place(right, body)


def fallback_lamps(body):
    """Where the shipped cars put them, as a fraction of the body.

    Taken from viper.car: lamps from 40% to 100% of the half-width, and from
    21% to 39% of the body height, on the rearmost plane.
    """
    xs = [v.x for v in body.vertices]
    ys = [v.y for v in body.vertices]
    zs = [v.z for v in body.vertices]
    half = max(abs(min(xs)), abs(max(xs)))
    h = max(ys) - min(ys)
    b = LAMP_BAND
    # The same envelope a detected lamp is held to, so a fallback and a fit
    # differ in WHERE they came from, not in what shape they can be.
    y0 = min(ys) + b["y_lo"] * h
    y1 = min(ys) + b["y_hi"] * h
    mid = (y0 + y1) / 2
    t = b["min_h"] * h
    # Same depth rule as a fitted lamp: proud of the body AT THIS HEIGHT, not at
    # the car's rearmost point anywhere. The Hunter's tail reaches 12cm further
    # back somewhere other than its lamp band, so the global minimum left its
    # lights hanging in mid-air behind the truck.
    band = [v.z for v in body.vertices if mid - t - 0.05 <= v.y <= mid + t + 0.05]
    z = (min(band) if band else min(zs)) - PROUD
    return (Lamp(-half * b["x_out"], -half * b["x_in"], mid - t, mid + t, z),
            Lamp(half * b["x_in"], half * b["x_out"], mid - t, mid + t, z))


def build_mesh(left: Lamp, right: Lamp, version: int = 1) -> mod.Mesh:
    """Two quads facing rearward, on the shared glow texture."""
    verts = []
    for lamp in (left, right):
        z = lamp.z - PROUD
        for (x, y), (u, v) in zip(
                ((lamp.x0, lamp.y1), (lamp.x0, lamp.y0),
                 (lamp.x1, lamp.y1), (lamp.x1, lamp.y0)), GLOW_UV):
            verts.append(mod.Vertex(x=x, y=y, z=z, nx=0.0, ny=0.0, nz=-1.0,
                                    u=u, v=v))
    faces = [(2, 1, 0), (1, 2, 3), (6, 5, 4), (5, 6, 7)]
    mats = [mod.Material(BRAKE_TEXTURE, 0, len(verts), 0, len(faces))]
    return mod.Mesh(vertices=verts, materials=mats, faces=faces, version=version)


def fit(car: Path, prefix: str, write: bool = True):
    """Refit one car's brake mesh. Returns (how, left, right)."""
    ents, body, textures = load(car, prefix)
    found = find_lamps(body, textures)
    how = "fitted"
    if found is None:
        found = fallback_lamps(body)
        how = "FALLBACK (no convincing pair in the art)"
    left, right = found

    name = next((n for n in ents if n == f"{prefix}b.mod"), None)
    if name is None:
        return "no brake mesh in this car", left, right
    old = ents[name]
    mesh = build_mesh(left, right, version=mod.parse(
        envelope.build(old.tag, old.version, old.payload)).version)
    if write:
        raw = mod.build(mesh)
        entries = [e if e.name.lower() != name
                   else archive.ArchiveEntry(name=e.name, tag=e.tag,
                                             version=e.version,
                                             payload=raw[20:])
                   for e in archive.read(car)]
        archive.write(entries, car)
    return how, left, right


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("brakelights.py <car> [<car> ...]   (or a fleet dir)")
    targets = []
    for a in sys.argv[1:]:
        p = Path(a)
        targets.extend(sorted(p.rglob("*.car")) if p.is_dir() else [p])
    for car in targets:
        prefix = car.stem
        how, left, right = fit(car, prefix)
        print(f"  {prefix:10s} {how}")
        for side, lamp in (("L", left), ("R", right)):
            print(f"      {side}  x {lamp.x0:6.2f}..{lamp.x1:5.2f}  "
                  f"y {lamp.y0:5.2f}..{lamp.y1:4.2f}  z {lamp.z:6.2f}  "
                  f"({lamp.width:.2f} x {lamp.height:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
