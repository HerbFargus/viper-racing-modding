"""Put a Streets of SimCity dashboard into a Viper Racing cockpit.

The two games disagree about what a cockpit IS. SoSC draws a flat 640x190
bitmap across the bottom of the screen. Viper renders 3D geometry in car space
-- `Viperc.mod`, 45 faces -- and drives a separate needle from `cockpit.tab`.

So the SoSC look is rebuilt as a flat billboard sitting in front of the cockpit
camera. Not a compromise: a flat panel filling the lower view is exactly what
the original is, and Viper has no objection to a cockpit mesh being flat.

WHAT THE DISC PROVIDES. Five panels, by car CLASS rather than by car, which
covers all seven conversions:

    COMPF2  640x180  compact   -> strtrat   (confirmed from a screenshot)
    SEDF2   640x192  sedan     -> airhawk, police   (airhawk confirmed)
    SPORTF1 640x200  sport     -> azzaroni
    RACEF2  640x198  race      -> j57, hunter       (j57 confirmed)
    UTILF3  640x185  utility   -> hmxvan

THREE TILES, not one. Viper's textures cap at 256 pixels square, so a 640-wide
panel cannot be one texture. Scaling it down to 256 would throw away 60% of the
horizontal detail, which is precisely where the gauge markings are -- so the
panel is cut into three tiles across three quads instead, each keeping its
pixels at 1:1.

CYAN IS THE TRANSPARENCY KEY. Between 10% and 26% of each panel is cyan: the
mirror inset, and the whole region above the dash that has to show the road.
Viper stores a per-texture colorkey value in the .tex header, so cyan maps
straight onto it -- no repainting needed.

THE MECHANISM IS PROVEN, which is the part that could have sunk this: 4x4cos.car
ships with its own `4x4cosc.mod` and `cockpit.tab`, so a car carrying a cockpit
of its own is something the game already does. (MGI copied the Viper's mesh and
textures wholesale, so there is no precedent for one that LOOKS different --
only for one existing.)

POSITIONING IS A GUESS on the first pass and will need correcting from the
game, the same way the brake lights did. Nothing here can render a cockpit:
carshot draws the body and wheels, so the panel's placement is invisible until
somebody sits in it.
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from vrmod import archive, cockpit_tab, envelope, mod, tex  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_car import unkey  # noqa: E402

# The straight-ahead steering sprite for each class. SoSC pre-rendered seven
# angles (-90 to +90 in 30-degree steps) and swaps them as you steer; Viper does
# not need them. Its wheel is `Viperw.mod`, a single flat quad at the origin with
# full-texture UVs that the game places at cockpit.tab's `wheel` point and
# rotates itself -- structurally the same sprite, rotated smoothly instead of in
# steps. So one frame is all that transfers.
#
# With one caveat that the seven frames exist to avoid: these sprites are
# CROPPED wheels, cut off square at the bottom edge of the image. SoSC never
# rotates one, so the crop never shows. Viper rotates the quad rigidly, so at
# large steering angles that straight edge swings into view. Small inputs look
# right; full lock will not. Nothing in the source art fixes this -- all seven
# frames are cropped the same way, and the missing half of the rim was never
# drawn.
WHEELS = {
    "strtrat": "COMP_0~1.BMP", "airhawk": "SED_0~1.BMP", "police": "SED_0~1.BMP",
    "azzaroni": "SPORT_~1.BMP", "j57": "RACE_0~1.BMP", "hunter": "RACE_0~1.BMP",
    "hmxvan": "UTIL_0~1.BMP",
}

PANELS = {
    "strtrat": "COMPF2.BMP", "airhawk": "SEDF2.BMP", "police": "SEDF2.BMP",
    "azzaroni": "SPORTF1.BMP", "j57": "RACEF2.BMP", "hunter": "RACEF2.BMP",
    "hmxvan": "UTILF3.BMP",
}
# The rest of the cockpit. SoSC does not draw one dashboard picture -- it
# composites a 640x480 frame from tight-cropped pieces, and PANELS only ever
# picked the dash out of it. The pillars and the windscreen header were sitting
# in the same folder unused.
#
# The F-number means something different per class, which is why this is a table
# and not a rule: SPORT has no F2 (its dash IS F1), and UTIL's dash is F3 while
# its F1 and F2 are two DIFFERENT pillars, 32 and 40 wide -- so the van cannot
# use the mirror path the others do.
#
# Evidence for the layout: SED's pillar is 100 wide and its header 540, which is
# exactly 640. Every pillar image touches its own top edge and both sides, so
# they are tight crops anchored to the screen's top corners, and they are 38-46%
# opaque -- the rest cyan, so they are keyed silhouettes that composite over the
# track rather than solid plates.
FRAME = {
    "airhawk":  {"pillar": "SEDF0.BMP",   "header": "SEDF1.BMP"},
    "police":   {"pillar": "SEDF0.BMP",   "header": "SEDF1.BMP"},
    "strtrat":  {"pillar": "COMPF0.BMP",  "header": "COMPF1.BMP"},
    "hunter":   {"pillar": "RACEF0.BMP",  "header": "RACEF1.BMP"},
    "j57":      {"pillar": "RACEF0.BMP",  "header": "RACEF1.BMP"},
    "azzaroni": {"pillar": "SPORTF0.BMP", "header": None},
    "hmxvan":   {"pillar": "UTILF1.BMP",  "header": "UTILF0.BMP",
                 "pillar_right": "UTILF2.BMP"},
}

TILES = 3
TILE_PX = 256
CYAN = (0, 255, 255)                  # the source art's colour key

# How many times each wheel maps onto itself in a full turn. This is the angle
# the cropped bottom gets filled at, and it has to be the wheel's OWN symmetry or
# the fill lands spokes where there are none.
#
# Read off the five sprites rather than detected. Three detectors were tried --
# whole-disc rotation matching, spoke-annulus matching, and a full rotational
# autocorrelation -- and all three failed the same way: the rim dominates the
# picture and a rim matches itself at EVERY angle, so they locked onto the rim
# and returned noise (the autocorrelation's best answers were 5 and 350 degrees,
# which is just a smooth profile matching itself). Five hand-checked numbers beat
# a detector that is wrong.
#
#   SPORT  a true three-spoke Y, and turned off-axis in the art, so 180 degrees
#          throws a phantom spoke into an empty quadrant -- this is the one that
#          looked wrong
#   SED    one horizontal bar through the hub: 180 maps it onto itself
#   UTIL   likewise, a horizontal two-spoke
#   RACE   three spokes at 9, 3 and 6 o'clock -- mirror-symmetric, NOT 3-fold, so
#          2 is the honest answer: the rim closes and the 6 o'clock spoke stays
#          absent rather than being invented somewhere wrong
#   COMP   bare rim, so any angle does
SYMMETRY = {"SPORT_~1.BMP": 3, "SED_0~1.BMP": 2, "UTIL_0~1.BMP": 2,
            "RACE_0~1.BMP": 2, "COMP_0~1.BMP": 2}
DEFAULT_SYMMETRY = 2

# Things drawn in front of a wheel that are not the wheel, as (x, y, r) discs in
# the sprite's own pixels. UTIL has a mirror ball hung on the rim at 2 o'clock;
# left alone its 180-degree copy appears as a second ball at 8 o'clock.
#
# These are marked UNKNOWN rather than simply erased -- erasing would leave a
# bite out of the rim that nothing is allowed to fill, because the fill only
# touches what the sprite never covered. Unknown means "the wheel is behind this
# and we cannot see it", which is exactly true, and the rim gets rebuilt there
# from the far side.
#
# Hand-placed, because they cannot be found automatically: the ball touches the
# rim, so a flood fill from it swallows the whole wheel (24,478 px -- every
# opaque pixel in the sprite).
#
# Empty on purpose. UTIL's ball was tried here as (281, 76, 36) and REVERTED: the
# region it frees can only be rebuilt from 8 o'clock, which is itself inside the
# cropped-away part of the sprite, so there is nothing valid to copy. It traded
# one small phantom ball for a broken rim AND a floating spoke fragment. An
# occluder is only worth declaring when the far side of the wheel is visible.
OCCLUDERS = {}
BORDER = 1                            # texels of ring around each tile

# THE SKIRT. The panel is a flat quad sized to just cover the frame, but the
# cockpit banks with the car, and a rotated rectangle no longer covers the
# rectangle it was cut to fit -- its corners sweep inward and the frame edges
# show through at the sides and bottom.
#
# The stock cockpit never does this because it is a mesh that wraps around the
# cabin. A flat panel cannot, so instead a large dark quad sits behind it,
# spanning well past the frame, with its top edge on the same cowl line. Rolled
# back into the dash's own frame, the lowest corner of a 16:9 frame sits at
# y' -0.304 at rest and rises to -0.101 at 20 degrees of roll, against a cowl
# line at -0.070 -- so a half-plane below that line covers roll to about 22
# degrees. Past that the corner genuinely clears the dash and you see track,
# which is what a real dashboard does too.
#
# It costs no extra texture: a solid patch is painted into the first tile's
# unused padding and all four skirt corners point at the middle of it.
SKIRT_SIZE = (2.4, 1.6)               # world units, w x h: generous on purpose
SKIRT_DEPTH = 0.005                   # further from the eye than the panel
SKIRT_PATCH_AT = 224                  # texel, inside tile 0's padding
SKIRT_PATCH_PX = 16

# The panel is COMPUTED from the camera rather than hardcoded, because the first
# hardcoded guess was 95 degrees wide and filled the screen with a magnified
# corner of the dash.
#
# The anchor is the stock cockpit. Viperc.mod spans x -0.96..0.52 -- 1.48 units
# -- but sits further forward than the guess did, out to z +0.38, so at its own
# depth it subtends about 77 degrees. That is the game's cockpit field of view,
# near enough to work from; the same 1.48 at the guess's distance was 95.
#
# Everything else follows from wanting the panel to sit where SoSC puts it: a
# 640x192 image in a 640x480 frame is exactly the bottom 40% of the screen.
CAMERA = (-0.408, 0.906, -0.791)      # cockpit.tab's own camera record
GAUGE_Z = -0.14                       # the plane the needle pivots sit on

# Every earlier number here was derived from a screenshot, and every one of them
# was wrong, because a screenshot measures the panel I was trying to place. The
# stock cockpit mesh settles all of it without a screenshot at all.
#
# Viperc.mod's cowl -- the top of the dash, the silhouette that decides how much
# track you keep -- is a flat edge at y 0.780, z +0.377. Seen from cockpit.tab's
# own eye at (-0.408, 0.906, -0.791) that is 6.1 degrees BELOW the straight-ahead
# axis, and it holds that angle across the whole forward view (-25 to +40 deg
# horizontally). That is the line the game itself draws the dash up to.
#
# Two stock screenshots, 640x480 and 1920x1080, both put that cowl edge ~65% of
# the way down the frame. Same fraction at both aspects, so the vertical FOV does
# not move with the window: the game is Hor+, widening sideways at 16:9 rather
# than cropping. That part held up.
#
# Pinning the top edge to an ANGLE is what finally made the vertical correct at
# any resolution, which the previous four attempts were not. An in-game shot of
# the fitted panel at 1920x1080 put its top edge 63% down against the stock
# cowl's 64% -- so the anchor works, and it works even though the eye position is
# slightly off, because both the cowl angle and the panel are measured from the
# same (slightly wrong) camera and the error cancels.
#
# The WIDTH cannot cancel like that, and it was short by 1.35x. Solving the
# projection from that same screenshot -- tile seams at x 250/710/1190/1670 for a
# panel built 0.842 wide -- gives 1686 px per world unit at the gauge plane, so
# 1.139 units fill a 1920-wide frame. Back-solving with square pixels puts the
# eye at y 0.922 against cockpit.tab's 0.906 and the vertical FOV at 50 degrees,
# and the near-agreement on eye height is what makes the rest trustworthy.
#
# 50 degrees is where this started. The 40 in between came from eyeballing the
# cowl at "65%" in a downscaled screenshot; it is really ~62%, and that 3% is a
# 10-degree FOV error. Angles read off screenshots are worth about +-2%, so they
# can pin a RELATIVE anchor like the cowl and cannot pin an absolute FOV.
#
# The bottom of the art then hangs below the frame: a 640x192 strip stretched to
# fill the width is 0.342 tall where only 0.234 fits. That overhang is left in
# place. Cropping it away was tried and reverted -- it bought nothing, because
# cropping does not change the art's world scale, so the visible band is covered
# by the same ~131 texture rows either way (measured, all seven cars). It only
# deleted rows, and those rows turn out to be worth keeping: when the car banks
# they swing up into frame, and real lower-dash art there beats the flat skirt
# colour behind it. The full art still fits a 256px tile -- the tallest is 200
# rows plus the border.
FOV_V = 50.0                          # deg, back-solved from an in-game shot
COWL_ANGLE = -6.1                     # deg below the eye axis; Viperc.mod's own
PANEL_HALF_ANGLE = 41.2               # deg; measured to fill a 16:9 frame.
                                      # ~1.5 deg wider than the ideal-model value
                                      # of 39.7, deliberately: the eye-height
                                      # discrepancy above means the model runs
                                      # narrow, and a gap at the frame edge is a
                                      # far worse defect than a little overhang.


def frame_bottom() -> float:
    """World y of the bottom edge of the screen, at the gauge plane."""
    import math
    return CAMERA[1] - math.tan(math.radians(FOV_V / 2)) * (GAUGE_Z - CAMERA[2])


def panel_top() -> float:
    """World y of the panel's top edge: the stock cowl line."""
    import math
    return CAMERA[1] + math.tan(math.radians(COWL_ANGLE)) * (GAUGE_Z - CAMERA[2])


def panel_width() -> float:
    """How wide the dash is, in world units. Independent of the art's aspect."""
    import math
    d = GAUGE_Z - CAMERA[2]
    return 2 * math.tan(math.radians(PANEL_HALF_ANGLE)) * d


def panel_box(aspect: float):
    """(x0, x1, top, bottom, z) for a panel of the given height/width ratio.

    Top edge on the stock cowl line, width out to the frame edge; see the
    COWL_ANGLE commentary above for why those are the two anchors.

    Centred on the CAMERA's x -- the eye is at x -0.408, not on the centreline,
    and a panel centred on the car hangs off to one side.
    """
    import math
    d = GAUGE_Z - CAMERA[2]
    top = CAMERA[1] + math.tan(math.radians(COWL_ANGLE)) * d
    half_w = math.tan(math.radians(PANEL_HALF_ANGLE)) * d
    bottom = top - (2 * half_w) * aspect
    return (CAMERA[0] - half_w, CAMERA[0] + half_w, top, bottom, GAUGE_Z)


def load_panel(path: Path):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    return im


def tile_textures(im, prefix: str, tiles: int = TILES,
                  kind: str = "p") -> list[tuple[str, bytes]]:
    """Cut the panel into TILES columns, each its own colorkey .tex."""
    from PIL import Image
    out = []
    edges = [round(im.width * i / tiles) for i in range(tiles + 1)]
    usable = TILE_PX - 2 * BORDER
    for i in range(tiles):
        crop = im.crop((edges[i], 0, edges[i + 1], im.height))
        if crop.width > usable or crop.height > usable:
            # A .tex page is 256 square and the art does not have to be. SEDF0 is
            # 100x289 and UTILF1/F2 are 280 and 287 tall, so pasting them in
            # clipped 34 rows AND pushed the UVs to v 1.13 -- off the page
            # entirely, which with wrap=1 samples the padding and renders as
            # black slabs floating beside the dash. Scale to fit instead: the
            # world placement is computed from the ORIGINAL pixel size in
            # add_frame, so this costs resolution and moves nothing.
            k = min(usable / crop.width, usable / crop.height)
            crop = crop.resize((max(1, round(crop.width * k)),
                                max(1, round(crop.height * k))), Image.LANCZOS)
            # ...and then re-key it, because the resample just blended the
            # transparency marker into the art. Transparency here is a COLOUR,
            # not a channel, so LANCZOS happily averages cyan with the pixels
            # beside it -- and its ringing darkens the result, so the halo comes
            # out at (8,192,192) rather than (0,255,255) and the exact-match
            # colorkey no longer removes it. In game that is a dotted cyan line
            # down the A-pillar edge. Only the frame pieces are big enough to
            # need scaling (SEDF0 is 100x289, UTILF1/F2 are 280-287 tall), which
            # is exactly where the artefact showed and why the dash never did.
            crop, _halo = defringe(crop)
        # Pad into a square power-of-two page: the .tex format is square and
        # power-of-two only, and padding beats scaling because the UVs can
        # simply address the used corner.
        #
        # BORDER. The art is inset by one texel and ringed with a copy of the
        # pixels just outside it, and the UVs address only the inset region.
        # Without that ring the joins show as slivers of track: the padding is
        # cyan, cyan is the transparency key, and wrap=1 means a sample that
        # strays past an edge does not clamp -- it wraps to the far side of the
        # page and lands in that padding. Guttering only the right edge (which
        # is what this did first) fixes nothing visible, because the seams you
        # see are the LEFT edges of tiles 1 and 2, where u just below 0 wraps
        # round to texel 255.
        page = Image.new("RGB", (TILE_PX, TILE_PX), (0, 255, 255))
        page.paste(crop, (BORDER, BORDER))
        w, h = crop.width, crop.height
        left = (im.crop((edges[i] - 1, 0, edges[i], im.height)) if i
                else crop.crop((0, 0, 1, h)))
        right = (im.crop((edges[i + 1], 0, edges[i + 1] + 1, im.height))
                 if edges[i + 1] < im.width else crop.crop((w - 1, 0, w, h)))
        page.paste(left, (0, BORDER))
        page.paste(right, (BORDER + w, BORDER))
        # top and bottom repeat the art's own outermost rows, across the full
        # bordered width so the corners are covered too
        band = page.crop((0, BORDER, BORDER + w + 1, BORDER + 1))
        page.paste(band, (0, 0))
        band = page.crop((0, BORDER + h - 1, BORDER + w + 1, BORDER + h))
        page.paste(band, (0, BORDER + h))
        if i == 0:
            # the skirt's colour: the median of the art's own bottom row, so the
            # quad behind the dash reads as the unlit footwell below it
            row = [im.getpixel((x, im.height - 1)) for x in range(im.width)]
            mid = tuple(sorted(c[k] for c in row)[len(row) // 2] for k in range(3))
            page.paste(Image.new("RGB", (SKIRT_PATCH_PX, SKIRT_PATCH_PX), mid),
                       (SKIRT_PATCH_AT, SKIRT_PATCH_AT))
        rgba = bytearray()
        for (r, g, b) in page.getdata():
            # cyan -> transparent; everything else opaque AND lifted off the
            # marker. A .tex texel that decodes to black IS transparent, flag or
            # no flag, and these dashes are 5-19% near-black by area -- gauge
            # faces, vents, the lower dash. Without the nudge those read as
            # holes.
            if r < 60 and g > 200 and b > 200:
                rgba += bytes((r, g, b, 0))
            else:
                rgba += bytes((*unkey((r, g, b)), 255))
        raw = tex.encode_to_tex(bytes(rgba), TILE_PX, mode="colorkey", wrap=1)
        out.append((f"{prefix}{kind}{i}.tex", raw, crop.width, crop.height))
    return out


def _is_cyan(p) -> bool:
    r, g, b = p[0], p[1], p[2]
    return r < 60 and g > 200 and b > 200


def defringe(im):
    """Clean the cyan halo off anti-aliased art.

    Only exactly-cyan is keyed, so a painted edge that fades into the cyan
    background leaves a rim of half-cyan pixels that stay opaque and render as a
    bright halo -- up to 1.3% of a hand-painted wheel. The original sprites have
    hard edges and no halo, so this is a no-op on them.

    A pixel far into the background is made fully transparent; one only partly
    contaminated takes the colour of the nearest clean opaque pixel, which keeps
    the silhouette exactly where the artist put it instead of eroding it.
    """
    W, H = im.size
    px = im.load()

    def tinted(q):
        r, g, b = q[0], q[1], q[2]
        return not _is_cyan(q) and g > r + 40 and b > r + 40 and (g > 120 or b > 120)

    bad = [(x, y) for y in range(H) for x in range(W) if tinted(px[x, y])]
    for x, y in bad:
        q = px[x, y]
        if q[1] > 170 and q[2] > 170:
            px[x, y] = CYAN                      # mostly background: drop it
            continue
        best = None
        for radius in (1, 2, 3):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < W and 0 <= ny < H):
                        continue
                    n = px[nx, ny]
                    if _is_cyan(n) or tinted(n):
                        continue
                    d = dx*dx + dy*dy
                    if best is None or d < best[0]:
                        best = (d, n)
            if best:
                break
        px[x, y] = best[1] if best else CYAN
    return im, len(bad)


PAINTED_WHEELS = Path(__file__).resolve().parent / "wheels"


def wheel_source(steer_dir: Path, art_name: str):
    """A hand-painted <stem>.png wins over the sprite: beside it, else ours.

    The completion in complete_wheel is a reconstruction from cropped, pre-lit
    art, and it has limits nothing algorithmic gets past -- where a wheel is both
    cropped AND occluded at the same angle there is no valid source anywhere on
    it. A painted wheel has no missing region at all, so complete_wheel finds
    nothing unknown and passes it through: same circle fit, same hub-centring,
    no invented pixels. Paint square, hub in the middle, cyan for transparent.

    Two places are searched so the build is reproducible without any manual
    step: your own painting beside the extracted sprite wins, and otherwise the
    five that ship in wheels/ beside this script are used. Falling back to the
    raw sprite still works -- it just goes back through the reconstruction, with
    the mirrored-spoke artefacts that motivated painting these in the first
    place.
    """
    if not art_name:
        return None
    stem = Path(art_name).stem + ".png"
    for cand in (steer_dir / stem, PAINTED_WHEELS / stem):
        if cand.is_file():
            return cand
    return steer_dir / art_name


def fit_wheel_circle(im):
    """(cx, cy, R) of the wheel's rim, by least squares on its outer edge.

    The sprite is NOT the wheel: SoSC drew only what showed above its own dash,
    so the art is a circle cropped by the bottom of the frame and the centre of
    that circle is nowhere near the centre of the image -- 11% to 25% of a
    diameter below it across the seven cars. That offset is why the wheel used to
    swing round the screen instead of spinning: the quad pivots about its own
    middle, and its middle is not the hub.
    """
    W, H = im.size
    px = im.load()
    pts = []
    for y in range(H):
        row = [x for x in range(W) if not _is_cyan(px[x, y])]
        if len(row) < 4 or row[0] <= 0 or row[-1] >= W - 1:
            continue                       # empty, or clipped by the sprite edge
        pts += [(row[0], y), (row[-1], y)]
    n = len(pts)
    if n < 6:
        raise SystemExit("wheel sprite has too little rim to fit a circle")
    Sx = sum(q[0] for q in pts); Sy = sum(q[1] for q in pts)
    Sxx = sum(q[0]*q[0] for q in pts); Syy = sum(q[1]*q[1] for q in pts)
    Sxy = sum(q[0]*q[1] for q in pts)
    Sz = sum(q[0]**2 + q[1]**2 for q in pts)
    A = [[2*Sxx, 2*Sxy, Sx], [2*Sxy, 2*Syy, Sy], [2*Sx, 2*Sy, n]]
    B = [sum((q[0]**2+q[1]**2)*q[0] for q in pts),
         sum((q[0]**2+q[1]**2)*q[1] for q in pts), Sz]
    for i in range(3):
        j = max(range(i, 3), key=lambda r: abs(A[r][i]))
        A[i], A[j] = A[j], A[i]; B[i], B[j] = B[j], B[i]
        for r in range(3):
            if r == i:
                continue
            f = A[r][i] / A[i][i]
            for c in range(3):
                A[r][c] -= f * A[i][c]
            B[r] -= f * B[i]
    a, b, c = (B[i] / A[i][i] for i in range(3))
    return a, b, (c + a*a + b*b) ** 0.5


def fit_rim_lighting(im, cx, cy, R):
    """(A, C, D) of a directional shading model over the rim: A + C*cos + D*sin.

    These sprites are lit, hard. The SED rim swings 73% either side of its mean
    brightness and the COMP 90%, both brightest toward the top. That is why
    turning the top cap through 180 degrees to close the rim reads wrong even
    though the geometry is right: it lays the wheel's brightest arc across the
    bottom, where the same wheel is darkest. Fitting the falloff lets the fill be
    re-lit for where it has landed instead of carrying the light round with it.
    """
    import math
    W, H = im.size
    px = im.load()
    pts = []
    for b in range(360):
        th = 2 * math.pi * b / 360
        vals = []
        for k in range(12):
            r = R * (0.88 + 0.12 * k / 11)
            xi, yi = int(round(cx + r*math.cos(th))), int(round(cy + r*math.sin(th)))
            if not (0 <= xi < W and 0 <= yi < H - 3):
                continue
            q = px[xi, yi]
            if _is_cyan(q):
                continue
            vals.append(0.299*q[0] + 0.587*q[1] + 0.114*q[2])
        if len(vals) >= 6:
            pts.append((th, sum(vals) / len(vals)))
    n = len(pts)
    if n < 30:
        return None
    A = [[n, sum(math.cos(t) for t, _ in pts), sum(math.sin(t) for t, _ in pts)],
         [0, sum(math.cos(t)**2 for t, _ in pts),
          sum(math.cos(t)*math.sin(t) for t, _ in pts)],
         [0, 0, sum(math.sin(t)**2 for t, _ in pts)]]
    A[1][0] = A[0][1]; A[2][0] = A[0][2]; A[2][1] = A[1][2]
    B = [sum(v for _, v in pts), sum(v*math.cos(t) for t, v in pts),
         sum(v*math.sin(t) for t, v in pts)]
    for i in range(3):
        j = max(range(i, 3), key=lambda r: abs(A[r][i]))
        A[i], A[j] = A[j], A[i]; B[i], B[j] = B[j], B[i]
        if abs(A[i][i]) < 1e-9:
            return None
        for r in range(3):
            if r == i:
                continue
            f = A[r][i] / A[i][i]
            for c in range(3):
                A[r][c] -= f * A[i][c]
            B[r] -= f * B[i]
    return tuple(B[i] / A[i][i] for i in range(3))


def complete_wheel(im, fold: int = DEFAULT_SYMMETRY, occluders=()):
    """Square canvas holding the WHOLE wheel, hub at the centre.

    Returns (image, diameter_px). Two jobs at once: re-centre the art on the hub
    so the quad pivots where the wheel actually turns, and put back the 21-48%
    of the rim that SoSC cropped off the bottom, which shows the moment you wind
    on lock.

    The missing piece is a bottom cap. It is filled by point-reflecting the TOP
    of the wheel through the hub -- and only the top, only as much of it as the
    gap needs: source rows down to 2*cy - H, which is precisely the missing
    fraction, 21% to 48% depending on the car.

    Taking the topmost rows is the whole trick. They are almost pure rim, and a
    rim is a circle, so reflecting it is exact rather than invented. Reflecting
    the WHOLE sprite instead -- which is what this did first -- drags the spokes
    round with it, and steering wheels are mostly three-spoke Ys whose arms do
    not land on their own reflection. It also carries the sprite's own bottom
    edge into the middle of the wheel as a straight cut. Detecting each wheel's
    rotational order and filling at that angle was tried first and abandoned:
    the spoke annulus is only 51-75% visible, which is not enough to identify
    the order, and the detector disagreed with itself across the fleet.

    So the lower spokes are simply absent rather than wrong. That is the honest
    trade: the rim closes, and nothing is invented where the art does not say.
    """
    from PIL import Image
    im, _fringed = defringe(im.copy())
    cx, cy, R = fit_wheel_circle(im)
    W, H = im.size
    pad = 4
    side = int(2 * R) + 2 * pad
    mid = side / 2

    def placed(src, sx, sy):
        """`src` positioned so its (sx, sy) lands on the canvas centre."""
        page = Image.new("RGB", (side, side), CYAN)
        page.paste(src, (round(mid - sx), round(mid - sy)))
        return page

    canvas = placed(im, cx, cy)
    # What the sprite could NEVER have said. Everything else -- including the
    # places where it says "transparent" -- is known, and known is never
    # overwritten. Restricting the fill by what is unknown rather than by where
    # the source came from is what stops a rotation from inventing a spoke in an
    # empty quadrant: at 12 o'clock RACE genuinely has no spoke, the sprite
    # covers 12 o'clock, so nothing is allowed to put one there.
    #
    # That in turn frees the SOURCE to be the whole visible wheel instead of just
    # its top cap. Taking only the cap meant only the outer ends of spokes were
    # ever copied, which left fragments floating near the rim with no arm joining
    # them to the hub -- right by symmetry, but obviously wrong to look at.
    known = Image.new("L", (side, side), 0)
    kp = known.load()
    masked = im.copy()
    mp = masked.load()
    for y in range(H):
        for x in range(W):
            if (x - cx)**2 + (y - cy)**2 > R*R:
                mp[x, y] = CYAN          # anything outside the rim is not wheel
    for ox, oy, orad in occluders:
        for y in range(max(0, oy-orad), min(H, oy+orad+1)):
            for x in range(max(0, ox-orad), min(W, ox+orad+1)):
                if (x-ox)**2 + (y-oy)**2 <= orad*orad:
                    mp[x, y] = CYAN
    inside = placed(masked, cx, cy)
    for y in range(H - BORDER - 2):
        for x in range(W):
            if any((x-ox)**2 + (y-oy)**2 <= orad*orad for ox, oy, orad in occluders):
                continue                 # occluded: we cannot see the wheel here
            cxx, cyy = round(mid + x - cx), round(mid + y - cy)
            if 0 <= cxx < side and 0 <= cyy < side:
                kp[cxx, cyy] = 255
    fills = [inside.rotate(360.0 * k / fold, resample=Image.NEAREST,
                           center=(mid, mid), fillcolor=CYAN)
             for k in range(1, fold)]

    lit = fit_rim_lighting(im, cx, cy, R)
    out = canvas.load()
    for step, fill in enumerate(fills, start=1):
        f = fill.load()
        for y in range(side):
            for x in range(side):
                if kp[x, y] or not _is_cyan(out[x, y]) or _is_cyan(f[x, y]):
                    continue
                q = f[x, y]
                if lit:
                    # the fill came from `fold` symmetry angles away, so
                    # re-light it: scale by however much darker (or brighter)
                    # this side of the wheel is than the side it came from
                    A, C, D = lit
                    th = math.atan2(y - mid, x - mid)
                    src = th - 2 * math.pi * step / fold
                    here = A + C*math.cos(th) + D*math.sin(th)
                    there = A + C*math.cos(src) + D*math.sin(src)
                    k = min(1.8, max(0.20, here / max(there, 0.15*abs(A) + 1e-6)))
                    q = tuple(min(255, max(0, int(round(c * k)))) for c in q)
                out[x, y] = CYAN if _is_cyan(q) else q
    return canvas, 2 * R


def wheel_texture(im, prefix: str):
    """The steering sprite as a colorkey .tex, cyan keyed out.

    Colorkey rather than the flags=0x03 alpha the stock wheel uses: 0x03 is a
    four-byte-per-pixel format, and writing ARGB4444 under it hands the game
    half the data it expects and panics the loader. Hard-edged transparency is
    what the source has anyway -- it is a colour key in SoSC too.
    """
    from PIL import Image
    page = Image.new("RGB", (TILE_PX, TILE_PX), (0, 255, 255))
    fitted = im.resize((TILE_PX, TILE_PX), Image.NEAREST)
    page.paste(fitted, (0, 0))
    rgba = bytearray()
    for (r, g, b) in page.getdata():
        # same nudge as the dash, and it matters more here: a steering wheel is
        # mostly black, so un-nudged it is mostly a hole.
        if r < 60 and g > 200 and b > 200:
            rgba += bytes((r, g, b, 0))
        else:
            rgba += bytes((*unkey((r, g, b)), 255))
    return f"{prefix}w.tex", tex.encode_to_tex(bytes(rgba), TILE_PX,
                                               mode="colorkey", wrap=1)


def build_wheel_mesh(name: str, diameter_px: float, version: int = 1) -> mod.Mesh:
    """A quad at the ORIGIN, like the stock wheel -- the game moves and turns it.

    Sized from the sprite's own proportions against the dash panel, so the wheel
    keeps the size relationship it has in the original: a SED wheel is 392 of the
    panel's 640 pixels wide, and the panel spans 0.84 units here, so the wheel is
    0.52 units across. Guessing a size would be guessing the one thing the source
    art actually tells us.
    """
    hw = hh = panel_width() * (diameter_px / 640.0) / 2
    verts = [mod.Vertex(x=hw, y=hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=1.0, v=0.0),
             mod.Vertex(x=-hw, y=hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=0.0, v=0.0),
             mod.Vertex(x=-hw, y=-hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=0.0, v=1.0),
             mod.Vertex(x=hw, y=-hh, z=0.001, nx=0.0, ny=0.0, nz=-1.0, u=1.0, v=1.0)]
    # the stock Viperw.mod's own face tuples. The mirror of these -- (0,1,2),
    # (0,2,3), which is what this had -- puts the normal at +z, facing away from
    # the eye, and the game culls the quad: no steering wheel at all, silently.
    faces = [(2, 1, 0), (3, 2, 0)]
    return mod.Mesh(vertices=verts,
                    materials=[mod.Material(name, 0, 4, 0, 2)],
                    faces=faces, version=version)


# Depth order at the gauge plane. Forward is +z and the eye is behind at -0.791,
# so SMALLER z is nearer the driver. The pillars sit in front of everything
# because SED's pillar reaches down past the top of the dash and the two would
# otherwise z-fight along that overlap; the header sits behind the pillars
# because COMP's and RACE's overrun their frame by 8-12px and the pillar is the
# piece that should win.
PILLAR_Z = GAUGE_Z - 0.002
HEADER_Z = GAUGE_Z - 0.001

PX_PER_FRAME = 640.0      # SoSC composites its cockpit into a 640x480 frame


def world_per_px() -> float:
    """World units per pixel of SoSC's 640-wide frame, at the gauge plane."""
    return panel_width() / PX_PER_FRAME


def frame_top() -> float:
    import math
    return CAMERA[1] + math.tan(math.radians(FOV_V / 2)) * (GAUGE_Z - CAMERA[2])


def _lay_tiles(verts, faces, mats, tiles, x0, x1, ytop, ybot, z, mirror=False):
    """Lay a row of tiles across x0..x1. Shared by the dash and the frame pieces.

    `mirror` flips U so the right-hand pillar can reuse the left one's texture
    instead of shipping a second copy. It does NOT touch the winding: only the u
    values swap, the vertices are still laid out left to right in the same order,
    so handedness is unchanged. Reversing the faces as well -- which is what this
    did first -- turns the quad inside out and the game culls it. faces_check
    caught that on the first build.
    """
    total = sum(t[2] for t in tiles)
    cut = x0
    for name, _raw, w, h in tiles:
        span = (x1 - x0) * (w / total)
        u0, v0 = BORDER / TILE_PX, BORDER / TILE_PX
        u1, v1 = (BORDER + w) / TILE_PX, (BORDER + h) / TILE_PX
        if mirror:
            u0, u1 = u1, u0
        base = len(verts)
        for (x, y, u, v) in ((cut, ytop, u0, v0), (cut, ybot, u0, v1),
                             (cut + span, ytop, u1, v0),
                             (cut + span, ybot, u1, v1)):
            verts.append(mod.Vertex(x=x, y=y, z=z, nx=0.0, ny=0.0, nz=-1.0,
                                    u=u, v=v))
        fstart = len(faces)
        faces += [(base + 2, base + 1, base), (base + 1, base + 2, base + 3)]
        mats.append(mod.Material(name, base, len(verts), fstart, len(faces)))
        cut += span


def add_frame(mesh: mod.Mesh, prefix: str, code: str, panels_dir: Path):
    """Add the A-pillars and windscreen header. Returns the textures they need.

    Horizontally these use SoSC's own pixel scale: the dash is 640 px wide and
    fills the frame, so one pixel is panel_width()/640 in world units.

    Vertically they cannot. SoSC composites into 480 rows, and the two heights
    that matter are tied: SED's pillar is 289 and its dash 192, summing to 481,
    so the pillar bottom lands exactly on the dash top. UTIL is the same (280 +
    185). COMP and RACE deliberately fall short and leave a gap. Using the
    horizontal pixel scale for height instead -- which is what this did first --
    dropped the SED pillar to 85% of a 16:9 frame when it should reach 62%, and
    it buried its lower half behind the dash.
    
    So the vertical mapping is proportional to the space ABOVE the dash: SoSC's
    480-minus-dash rows map onto our frame-top-to-dash-top. That reproduces both
    behaviours -- the pillars that meet the dash still meet it, the ones that stop
    short still stop short -- at whatever aspect the frame happens to be.
    """
    spec = FRAME.get(prefix)
    if not spec:
        return {}
    scale = world_per_px()
    left, right = CAMERA[0] - panel_width() / 2, CAMERA[0] + panel_width() / 2
    top = frame_top()
    dash_top = panel_top()
    dash_px = load_panel(panels_dir / PANELS[prefix]).height
    vscale = (top - dash_top) / (480.0 - dash_px)
    out = {}

    pil = crop_alpha(load_panel(panels_dir / spec["pillar"]))
    ptiles = tile_textures(pil, code, tiles=1, kind="l")
    pw, ph = pil.width * scale, pil.height * vscale
    _lay_tiles(mesh.vertices, mesh.faces, mesh.materials, ptiles,
               left, left + pw, top, top - ph, PILLAR_Z)
    out.update({n: r for n, r, _w, _h in ptiles})

    # the right pillar: the van has its own, everyone else mirrors the left
    if spec.get("pillar_right"):
        rim = crop_alpha(load_panel(panels_dir / spec["pillar_right"]))
        rtiles = tile_textures(rim, code, tiles=1, kind="r")
        rw, rh = rim.width * scale, rim.height * vscale
        _lay_tiles(mesh.vertices, mesh.faces, mesh.materials, rtiles,
                   right - rw, right, top, top - rh, PILLAR_Z)
        out.update({n: r for n, r, _w, _h in rtiles})
    else:
        _lay_tiles(mesh.vertices, mesh.faces, mesh.materials, ptiles,
                   right - pw, right, top, top - ph, PILLAR_Z, mirror=True)

    if spec.get("header"):
        hdr = crop_alpha(load_panel(panels_dir / spec["header"]))
        htiles = tile_textures(hdr, code, tiles=TILES, kind="h")
        hw, hh = hdr.width * scale, hdr.height * vscale
        # starts where the left pillar ends: SED's 100 + 540 is exactly 640
        hx0 = left + pw
        _lay_tiles(mesh.vertices, mesh.faces, mesh.materials, htiles,
                   hx0, hx0 + hw, top, top - hh, HEADER_Z)
        out.update({n: r for n, r, _w, _h in htiles})
    return out


def crop_alpha(im):
    """Trim fully-cyan rows/columns off the edges of a piece.

    The pieces are already tight crops, but a stray transparent margin would
    otherwise be paid for in world space and push the artwork away from the
    corner it is supposed to sit in.
    """
    W, H = im.size
    px = im.load()
    cols = [x for x in range(W) if any(not _is_cyan(px[x, y]) for y in range(H))]
    rows = [y for y in range(H) if any(not _is_cyan(px[x, y]) for x in range(W))]
    if not cols or not rows:
        return im
    if (cols[0], cols[-1], rows[0], rows[-1]) == (0, W - 1, 0, H - 1):
        return im
    return im.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))


def build_panel_mesh(tiles, version: int = 1) -> mod.Mesh:
    """One quad per tile, side by side, facing the driver."""
    verts, faces, mats = [], [], []
    total = sum(t[2] for t in tiles)
    aspect = tiles[0][3] / total          # height / full width, in pixels
    x0, x1, y1, y0, panel_z = panel_box(aspect)
    cut = x0
    for name, _raw, w, h in tiles:
        span = (x1 - x0) * (w / total)
        # the tile sits at (BORDER, BORDER) in a TILE_PX page, ringed by a
        # one-texel copy of its neighbours; the UVs address only the inset art
        u0, v0 = BORDER / TILE_PX, BORDER / TILE_PX
        u1, v1 = (BORDER + w) / TILE_PX, (BORDER + h) / TILE_PX
        base = len(verts)
        for (x, y, u, v) in ((cut, y1, u0, v0), (cut, y0, u0, v1),
                             (cut + span, y1, u1, v0), (cut + span, y0, u1, v1)):
            # V grows DOWNWARD -- v=0 is the TOP of the texture. Checked
            # against the stock brake lamp quad, whose top vertex (y 0.815)
            # carries v 0.383 and whose bottom (y 0.442) carries v 0.480.
            # Storing 1.0 - v instead, which is what this did first, turns every
            # panel upside down: the black lower dash renders across the top of
            # the quad and PRNDL21 reads mirrored along the bottom edge.
            verts.append(mod.Vertex(x=x, y=y, z=panel_z, nx=0.0, ny=0.0, nz=-1.0,
                                    u=u, v=v))
        fstart = len(faces)
        faces += [(base + 2, base + 1, base), (base + 1, base + 2, base + 3)]
        if not mats:
            sw, sh = SKIRT_SIZE
            su = sv = (SKIRT_PATCH_AT + SKIRT_PATCH_PX / 2) / TILE_PX
            sz = panel_z + SKIRT_DEPTH
            sbase = len(verts)
            for (x, y) in ((CAMERA[0] + sw / 2, y1), (CAMERA[0] - sw / 2, y1),
                           (CAMERA[0] - sw / 2, y1 - sh),
                           (CAMERA[0] + sw / 2, y1 - sh)):
                verts.append(mod.Vertex(x=x, y=y, z=sz, nx=0.0, ny=0.0, nz=-1.0,
                                        u=su, v=sv))
            # wound to match the panel's own convention -- TR, BL, TL. The
            # obvious order (TR, TL, BL) is the mirror of it, which puts the
            # normal at +z, facing AWAY from the eye, and the game culls it. It
            # renders fine in carshot, which does not backface-cull, so this is
            # invisible until it reaches the game.
            faces += [(sbase, sbase + 2, sbase + 1),
                      (sbase, sbase + 3, sbase + 2)]
        mats.append(mod.Material(name, base, len(verts), fstart, len(faces)))
        cut += span
    return mod.Mesh(vertices=verts, materials=mats, faces=faces, version=version)


def faces_check(car: Path) -> None:
    """Every face this script writes must present its front to the driver.

    Backfacing geometry is invisible in the game and fully visible in carshot,
    which does not cull -- so it survives every check that does not look at the
    winding directly. It cost a silently absent steering wheel and a skirt that
    was never drawn, both shipped and both only caught from a screenshot.
    """
    def nz(f, vs):
        a, b, c = (vs[i] for i in f)
        u = (b.x - a.x, b.y - a.y, b.z - a.z)
        v = (c.x - a.x, c.y - a.y, c.z - a.z)
        return u[0] * v[1] - u[1] * v[0]
    ents = {e.name.lower(): e for e in archive.read(car)}
    for suffix in ("c.mod", "w.mod"):
        name = next((n for n in ents if n.endswith(suffix)), None)
        if name is None:
            continue
        m = mod.parse(ents[name].to_standalone_bytes())
        bad = [i for i, f in enumerate(m.faces) if nz(f, m.vertices) >= 0]
        if bad:
            raise SystemExit(
                f"{car.name}: {name} has {len(bad)} backfacing face(s) {bad} -- "
                f"the game will cull them and render nothing")


def fit(car: Path, prefix: str, panels_dir: Path, base_car: Path) -> str:
    im = load_panel(panels_dir / PANELS[prefix])
    tiles = tile_textures(im, prefix[:3])
    mesh = build_panel_mesh(tiles)

    entries = archive.read(car)
    # the cockpit table: copied from a car that has one, since its camera and
    # needle calibration are the only reference points that exist
    base = {e.name.lower(): e for e in archive.read(base_car)}
    tab = base["cockpit.tab"]
    entries = archive.upsert_entry(
        entries, "cockpit.tab",
        envelope.build(tab.tag, tab.version, tab.payload))
    frame_tex = add_frame(mesh, prefix, prefix[:3], panels_dir)
    off = [v for v in mesh.vertices if v.u > 1.0 or v.v > 1.0]
    if off:
        raise SystemExit(
            f"{prefix}: {len(off)} vertex/vertices address outside their texture "
            f"page (max u {max(v.u for v in off):.3f}, v {max(v.v for v in off):.3f})"
            f" -- a piece is larger than the page and was clipped")
    entries = archive.upsert_entry(entries, f"{prefix}c.mod", mod.build(mesh))
    for name, raw, _w, _h in tiles:
        entries = archive.upsert_entry(entries, name, raw)
    for name, raw in frame_tex.items():
        entries = archive.upsert_entry(entries, name, raw)

    # the steering wheel, if this class has one
    wheel_note = ""
    src = wheel_source(panels_dir.parent / "steer", WHEELS.get(prefix, ""))
    if src is not None and src.is_file():
        art_name = WHEELS[prefix]
        wim, wdia = complete_wheel(load_panel(src),
                                   SYMMETRY.get(art_name, DEFAULT_SYMMETRY),
                                   OCCLUDERS.get(art_name, ()))
        wname, wraw = wheel_texture(wim, prefix[:3])
        wmesh = build_wheel_mesh(wname, wdia)
        entries = archive.upsert_entry(entries, f"{prefix}w.mod", mod.build(wmesh))
        entries = archive.upsert_entry(entries, wname, wraw)
        wheel_note = (f", wheel {WHEELS[prefix]} "
                      f"(hub-centred, {wdia:.0f}px across -> "
                      f"{panel_width() * wdia / 640:.2f} wide)")

    archive.write(entries, car)
    bx0, bx1, btop, bbot, bz = panel_box(im.height / im.width)
    spec = FRAME.get(prefix, {})
    bits = [k for k in ("pillar", "pillar_right", "header") if spec.get(k)]
    frame_note = (f", frame: {'+'.join(bits)} ({len(frame_tex)} tex)"
                  if bits else ", no frame pieces")
    return (f"{PANELS[prefix]} -> {TILES} tiles ({im.width}x{im.height}), "
            f"panel x {bx0:.2f}..{bx1:.2f} y {bbot:.2f}..{btop:.2f} z {bz:.2f}"
            f"{frame_note}{wheel_note}")


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("cockpits.py <panels_dir> <viper_install> <car_or_fleet>")
    panels, install, target = (Path(a) for a in sys.argv[1:4])
    base_car = install / "viper.car"
    cars = sorted(target.rglob("*.car")) if target.is_dir() else [target]
    for car in cars:
        if car.stem not in PANELS:
            print(f"  {car.stem:10s} no panel assigned")
            continue
        print(f"  {car.stem:10s} {fit(car, car.stem, panels, base_car)}")
        faces_check(car)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
