"""Cats vs Dogs models: the six pets and the two cars, ported part for part from the three.js
mockups (pets-mockup.html, cats-vs-dogs-cars.html) onto kit.shapes.Builder.

Every function returns Builders; turn them into meshes with .mesh(palette), using the
build's own kit.shapes.Palette.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.shapes import Builder, both, tennis_ball, wheel, yarn_ball  # noqa: E402,F401

PINK, BLK = "#e59a9a", "#1d1a18"


def cat_head(B, y, z, c, c2, muz, eye):
    B.box([0, y, z], [.13, .11, .11], c, top=(.85, .85))
    B.box([0, y - .025, z + .06], [.065, .045, .03], muz)
    B.box([0, y - .008, z + .077], [.018, .012, .006], PINK)
    for k in (1, -1):
        B.box([k * .032, y + .015, z + .057], [.022, .018, .008], eye)
        B.pyr([k * .042, y + .05, z - .005], [.045, .06, .03], c2, apex=(k * .008, 0))


def tabby(B):
    T1, T2, CR = "#c08a4e", "#8a5a2e", "#ead7b5"
    for k in (1, -1):
        for z in (.14, -.14):
            B.box([k * .055, .08, z], [.045, .16, .045], T1); B.box([k * .055, .012, z + .005], [.05, .025, .055], CR)
    B.box([0, .215, .13], [.14, .13, .12], T1); B.box([0, .215, .01], [.145, .135, .12], T2)
    B.box([0, .215, -.11], [.14, .13, .12], T1); B.box([0, .215, -.19], [.12, .12, .06], T2)
    B.box([0, .15, 0], [.11, .02, .3], CR)
    cat_head(B, .31, .25, T1, T2, CR, "#7cc35a")
    B.box([0, .37, .245], [.04, .008, .08], T2)
    B.box([0, .27, -.26], [.03, .03, .1], T2, r=(.6, 0, 0))
    B.box([0, .33, -.3], [.028, .028, .09], T1, r=(1.2, 0, 0))
    B.box([0, .40, -.31], [.026, .026, .07], T2, r=(1.5, 0, 0))


def blkcat(B):
    K, K2 = "#2a2930", "#3d3b46"
    for k in (1, -1):
        B.box([k * .065, .06, -.04], [.07, .12, .17], K, top=(.8, .8))
        B.box([k * .035, .09, .075], [.035, .18, .035], K2); B.box([k * .035, .01, .085], [.04, .02, .05], K2)
    B.box([0, .14, 0], [.15, .24, .15], K, top=(.7, .75), r=(.2, 0, 0))
    cat_head(B, .31, .06, K, K, K2, "#e8c547")
    B.box([.09, .015, .03], [.03, .03, .14], K); B.box([.065, .015, .12], [.03, .03, .08], K2, r=(0, -1.0, 0))


def loaf(B):
    G, G2, CR = "#d9822b", "#b5641c", "#f0dcc0"
    B.box([0, .075, 0], [.2, .15, .3], G, top=(.8, .85))
    for z in (-.08, 0, .08):
        B.box([0, .153, z], [.13, .006, .03], G2)
    cat_head(B, .17, .15, G, G2, CR, "#7cc35a")
    for k in (1, -1):
        B.box([k * .04, .012, .155], [.04, .024, .04], CR)
    B.box([.09, .03, -.02], [.03, .03, .26], G2)


def corgi(B):
    O, W = "#d9893a", "#f3ece0"
    for k in (1, -1):
        for z in (.14, -.14):
            B.box([k * .06, .045, z], [.05, .09, .05], W)
    B.box([0, .15, 0], [.2, .15, .4], O, top=(.9, .92))
    B.box([0, .085, .02], [.16, .03, .32], W); B.box([0, .15, .195], [.14, .12, .02], W)
    B.box([0, .27, .23], [.15, .13, .14], O, top=(.85, .85))
    B.box([0, .235, .33], [.08, .065, .08], W, top=(.85, .85))
    B.box([0, .255, .372], [.025, .02, .01], BLK)
    for k in (1, -1):
        B.box([k * .04, .29, .301], [.018, .018, .006], BLK)
        B.pyr([k * .05, .33, .22], [.06, .12, .035], O, apex=(k * .012, 0))
    B.box([0, .2, -.215], [.04, .04, .04], O)


def lab(B):
    Y, Y2 = "#e2c07c", "#c9a35f"
    for k in (1, -1):
        for z in (.24, -.24):
            B.box([k * .085, .16, z], [.065, .32, .065], Y2); B.box([k * .085, .015, z + .01], [.07, .03, .08], Y)
    B.box([0, .43, 0], [.25, .24, .62], Y, top=(.85, .9))
    B.box([0, .40, .29], [.22, .24, .08], Y)
    B.box([0, .54, .33], [.15, .18, .13], Y, r=(.5, 0, 0))
    B.box([0, .64, .4], [.18, .16, .19], Y, top=(.9, .9))
    B.box([0, .6, .53], [.11, .09, .13], Y2, top=(.85, .9))
    B.box([0, .625, .598], [.04, .03, .012], BLK)
    for k in (1, -1):
        B.box([k * .05, .67, .496], [.022, .02, .008], BLK)
        B.box([k * .095, .61, .38], [.03, .13, .08], Y2, r=(0, 0, k * .15))
    B.box([0, .53, -.46], [.045, .045, .32], Y, r=(.3, 0, 0))


def dachs(B):
    Br, Br2, TAN = "#7a3e1f", "#5c2c14", "#c48a52"
    for k in (1, -1):
        for z in (.17, -.17):
            B.box([k * .045, .04, z], [.04, .08, .04], Br2)
    B.box([0, .135, 0], [.13, .12, .46], Br, top=(.9, .95))
    B.box([0, .08, .15], [.1, .03, .14], TAN)
    B.box([0, .18, .22], [.08, .1, .08], Br, r=(.5, 0, 0))
    B.box([0, .22, .27], [.1, .1, .12], Br, top=(.85, .85))
    B.box([0, .2, .37], [.055, .05, .11], TAN, top=(.8, .85))
    B.box([0, .21, .428], [.02, .018, .008], BLK)
    for k in (1, -1):
        B.box([k * .033, .24, .331], [.018, .018, .008], BLK)
        B.box([k * .058, .2, .27], [.025, .1, .06], Br2, r=(0, 0, k * .12))
    B.box([0, .18, -.31], [.025, .025, .18], Br, r=(.35, 0, 0))


PETS = {"tabby": ("cat", tabby), "blkcat": ("cat", blkcat), "loaf": ("cat", loaf),
        "corgi": ("dog", corgi), "lab": ("dog", lab), "dachs": ("dog", dachs)}


def pet(name: str, scale: float = 4.0) -> Builder:
    """A pet at `scale`, centred on its bounding-box middle (the obstacle-ball rule)."""
    B = Builder()
    PETS[name][1](B)
    return B.centred(scale)


def alley_cat():
    B = Builder()
    BK, BK2, CH, GL, EYE, PUR, RED = "#1c1a22", "#2c2834", "#c9cfd6", "#3c5866", "#8dff5a", "#7a4fc0", "#d23c2a"
    for k in (1, -1):
        B.box([k * .45, .38, 0], [.12, .14, 4.0], BK2)
    B.box([0, .5, -.45], [1.3, .14, 2.1], BK)
    B.box([0, .76, 1.05], [.78, .46, 1.5], BK, top=(.92, .98))
    for k in (1, -1):
        for i in range(5):
            B.box([k * .395, .8, .6 + i * .2], [.02, .2, .06], BK2)
        B.box([k * .39, .66, 1.2], [.02, .1, 1.1], PUR, top=(1, .6), sh=(0, .15))
    B.box([0, 1.08, .85], [.36, .2, .5], CH)
    B.box([0, 1.26, .85], [.3, .18, .36], "#3a3a3a", top=(.9, .6), sh=(0, .06))
    B.box([0, .78, 1.83], [.64, .58, .1], BK2, top=(.8, 1))
    for k in (1, -1):
        B.pyr([k * .2, 1.07, 1.83], [.2, .26, .1], BK, apex=(k * .05, 0))
        B.box([k * .15, .88, 1.885], [.14, .07, .02], EYE, r=(0, 0, k * .25))
        for i in range(3):
            B.box([k * .46, .7 + i * .06, 1.86], [.36, .015, .015], "#e8e8e8", r=(0, 0, k * (i - 1) * .15))
        B.box([k * .5, .86, 1.55], [.05, .2, .05], CH)
        B.cyl([k * .5, .98, 1.48], .11, .16, BK, n=8, c2=EYE, rot=(math.pi / 2, 0, 0))
    B.pyr([0, .66, 1.88], [.09, .07, .04], "#e59a9a", r=(math.pi, 0, 0))
    B.box([0, .86, -.45], [1.3, .6, 1.5], BK, top=(.96, .92))
    B.box([0, 1.28, -.55], [1.18, .26, 1.1], BK, top=(.9, .82), sh=(0, -.04))
    for k in (1, -1):
        B.box([k * .62, 1.25, -.5], [.02, .12, .8], GL)
    B.box([0, 1.25, .06], [1.06, .12, .02], GL, r=(-.35, 0, 0))
    B.box([0, 1.25, -1.08], [1.0, .12, .02], GL)
    for k in (1, -1):
        B.pyr([k * .34, 1.41, -.4], [.24, .28, .14], BK, apex=(k * .05, 0))
    B.box([0, .78, -1.6], [1.2, .42, .8], BK, top=(.95, .8), sh=(0, .06))
    for k in (1, -1):
        B.box([k * .4, .86, -2.005], [.18, .06, .02], RED, r=(0, 0, -k * .25))
        B.box([k * .78, .66, 1.3], [.26, .06, .7], BK2, top=(1, .6))
        B.box([k * .8, .62, -1.4], [.42, .5, 1.0], BK, top=(.7, .8))
        B.cyl([k * .7, .42, -.9], .06, 1.9, CH, n=6, rot=(math.pi / 2, 0, 0))
        for i in range(4):
            B.cyl([k * .55, .62, .62 + i * .12], .035, .25, CH, n=5, rot=(0, 0, k * 1.1))
    p = [.3, 1.0, -1.85]
    L, A = .26, (25, 50, 75, 100, 125, 150)
    for i, deg in enumerate(A):                      # the curling tail antenna
        t = math.radians(deg)
        d = (0, math.sin(t), -math.cos(t))
        B.box([p[0], p[1] + d[1] * L / 2, p[2] + d[2] * L / 2], [.06, .06, L + .03],
              "#e8e8e8" if i == len(A) - 1 else BK2, r=(t, 0, 0))
        p = [p[0], p[1] + d[1] * L, p[2] + d[2] * L]
    return {"body": B.transformed(1.0, (0, 0, .05)),          # axles at +1.3 / -1.4 -> midpoint at z 0
            "front": wheel(.3, .18, "#151515", CH, PUR), "rear": wheel(.36, .34, "#151515", CH, PUR),
            "wheelbase": 2.7, "ftrack": 1.54, "rtrack": 1.64}


def doghouse():
    B = Builder()
    RD, RD2, RF, RF2, WH, CH, YL, TB = "#c0392b", "#a33024", "#5d4037", "#4a332c", "#f2efe8", "#c9cfd6", "#e2c07c", "#d7e84a"
    B.box([0, .45, 0], [1.5, .16, 3.3], "#3b4652")
    for k in (1, -1):
        B.box([k * .55, .38, 0], [.1, .1, 3.6], "#2b333c")
    B.box([0, 1.05, -.15], [1.5, 1.05, 2.2], RD)
    for k in (1, -1):
        for i in range(4):
            B.box([k * .755, .7 + i * .24, -.15], [.01, .03, 2.2], RD2)
    B.box([0, 1.95, -.15], [1.95, .75, 2.5], RF, top=(.04, 1))
    B.box([0, 2.34, -.15], [.14, .06, 2.56], RF2)
    for k in (1, -1):
        for i in range(3):
            B.box([k * (.28 + i * .24), 1.82 + (2 - i) * .2, -.15], [.02, .04, 2.5], RF2, r=(0, 0, -k * .72))
    B.box([0, 1.95, .95], [1.5, .7, .06], RD, top=(.04, 1))
    B.box([0, 1.0, .965], [.62, .8, .04], "#141414")
    B.cyl([0, 1.4, .945], .31, .06, "#141414", n=10, rot=(math.pi / 2, 0, 0))
    O = "#d9893a"
    B.box([0, 1.18, 1.0], [.42, .36, .36], O, top=(.85, .85))
    B.box([0, 1.08, 1.22], [.22, .18, .2], WH)
    B.box([0, 1.13, 1.33], [.07, .06, .03], BLK)
    for k in (1, -1):
        B.box([k * .1, 1.24, 1.185], [.05, .05, .02], BLK)
        B.pyr([k * .14, 1.34, 1.0], [.15, .3, .08], O, apex=(k * .03, 0))
    B.box([0, 1.72, .99], [.55, .16, .03], YL)
    B.box([0, .55, 1.82], [1.3, .16, .16], WH)
    for k in (1, -1):
        for j in (1, -1):
            B.cyl([k * .68, .55 + j * .09, 1.73], .11, .18, WH, n=8, rot=(math.pi / 2, 0, 0))
        B.cyl([k * .42, .64, 1.68], .05, .14, TB, n=8, rad2=.15)
        B.cyl([k * .42, .78, 1.68], .15, .14, TB, n=8, rad2=.05)
    B.cyl([-.35, .53, -1.55], .26, .16, CH, n=10, rad2=.32, c2="#8b5a2b")
    B.cyl([.4, .53, -1.55], .11, .42, "#d7261e", n=8)
    B.cyl([.4, .95, -1.55], .13, .1, "#b81f18", n=8, rad2=.06)
    for z, y, r in ((-1.42, 2.0, .4), (-1.5, 2.25, .9), (-1.52, 2.52, 1.4)):
        B.box([-.3, y, z], [.08, .08, .32], YL, r=(r, 0, -.25))
    for k in (1, -1):
        for z in (1.15, -1.15):
            B.box([k * .88, .92, z], [.38, .05, .8], "#3b4652")
    for k in (1, -1):                                       # tail lamps on the back of the deck
        B.box([k * .58, .45, -1.66], [.18, .1, .04], "#8a1a14")
    w = wheel(.38, .3, "#1b1b1b", "#f2efe8", "#c0392b", n=10)
    return {"body": B, "front": w, "rear": w, "wheelbase": 2.3, "ftrack": 1.76, "rtrack": 1.76}


# ---------------------------------------------------------------- cockpits and brake lights
# Each car's cockpit is a purpose-built interior frame plus the part of its own body the driver
# can see, for kit.cockpit.build. Eyes sit behind the car's centre (z <= 0.07), as the game needs.

def _keep(body, keep):
    out = Builder()
    for a, b, c, col in body.tris:
        cen = tuple((a[k] + b[k] + c[k]) / 3 for k in range(3))
        if keep(cen, col):
            out.tri(a, b, c, col)
    return out


def alley_cat_cockpit(body):
    """A chopped-roof slot: dash and door cappings in oxblood, a low header, and through the
    slot the blower and the grille's cat ears. Left-hand drive, so the blower sits to the right."""
    F = Builder()
    BK2, OX, HL = "#2c2834", "#6e2424", "#3a3438"
    F.box([0, .95, .38], [1.24, .3, .04], BK2)                         # dash panel
    for k in (1, -1):
        F.box([k * .62, .84, -.33], [.03, .5, 1.36], OX)               # door panels
        F.box([k * .63, 1.1, -.33], [.07, .04, 1.36], BK2)             # door cappings
        F.box([k * .6, 1.26, .36], [.06, .32, .06], BK2)               # A-pillars
    F.box([0, 1.43, .36], [1.26, .1, .07], BK2)                        # the chopped header
    F.box([0, 1.48, -.33], [1.26, .02, 1.42], HL)                      # headliner
    ahead = _keep(body, lambda c, col: c[2] > .42)                      # hood, blower, grille, ears
    shell = Builder().extend(F).extend(ahead)
    return dict(shell=shell, eye=(-0.3, 1.24, -0.5), wheel=(-0.3, 0.86, 0.05), wheel_R=0.16,
                gauges={"rpm": (-0.42, 1.03, .355), "mph": (-0.19, 1.03, .355)}, gauge_r=0.05,
                plate_at=(0.25, 1.0, .355), plate_w=0.22, atlas_name="acdash.tex",
                rpm_max=9000, rpm_red=8000, mph_max=200,
                art=dict(face=(24, 22, 30), ink=(141, 255, 90), red=(214, 52, 38),
                         plate_bg=(122, 79, 192), plate_ink=(240, 236, 250), plate_text="ALLEY CAT",
                         swatches={"needle": (141, 255, 90), "rim": (30, 28, 34), "spoke": (201, 207, 214),
                                   "bezel": (201, 207, 214), "hub": (122, 79, 192), "pod": (44, 40, 52)}))


def doghouse_cockpit(body):
    """Inside the doghouse, looking out of a doorway opened up wide: plank walls round you, the
    roof overhead, and out front the kart deck, the tennis-ball lamps and the bone bumper."""
    RD, RD2, WOOD = "#c0392b", "#a33024", "#8a5a2e"

    def keep(c, col):
        if col in ("#5d4037", "#4a332c"):
            return False                                                # the roof: its underside shares the
                                                                        # ceiling's plane and z-fights with it
        if col in ("#d7261e", "#b81f18", "#c9cfd6", "#8b5a2b", "#e2c07c"):
            return False                                                # bowl, hydrant, tail: behind you
        if col == "#a33024" and abs(c[0]) > 0.74:
            return False                                                # plank lines flush on the walls: same
        if 0.9 < c[2] < 1.02 and c[1] > 0.52 and abs(c[0]) < 0.8:
            return False                                                # the front wall, door, sign
        if c[2] > 0.75 and c[1] > 0.9 and col in ("#d9893a", "#f2efe8", "#1d1a18"):
            return False                                                # the corgi: you're driving
        return True
    F = Builder()
    for k in (1, -1):
        F.box([k * .677, 1.05, .93], [.13, 1.04, .075], RD2)            # door posts, clear of the walls
    F.box([0, 1.535, .93], [1.48, .065, .06], RD2)                      # header, clear of the ceiling
    F.box([0, .665, .93], [1.48, .26, .06], RD)                         # sill, clear of the floor
    F.box([0, .96, .91], [.8, .34, .04], WOOD)                          # the gauge board
    walls = lambda c, col: keep(c, col) and col == RD                   # noqa: E731  the house you sit in
    shell = Builder().extend(F).extend(_keep(body, lambda c, col: keep(c, col) and col != RD))
    return dict(shell=shell, inside=_keep(body, walls), eye=(0.0, 1.38, 0.05), wheel=(0.0, 0.98, 0.5), wheel_R=0.17,
                gauges={"rpm": (-0.22, 1.03, .885), "mph": (0.22, 1.03, .885)}, gauge_r=0.055,
                plate_at=(0.0, 1.03, .885), plate_w=0.2, atlas_name="dhdash.tex",
                rpm_max=5000, rpm_red=4500, mph_max=140,
                art=dict(face=(242, 239, 232), ink=(74, 51, 44), red=(192, 57, 43),
                         plate_bg=(226, 192, 124), plate_ink=(74, 51, 44), plate_text="DOGHOUSE",
                         swatches={"needle": (192, 57, 43), "rim": (93, 64, 55), "spoke": (226, 192, 124),
                                   "bezel": (138, 90, 46), "hub": (217, 137, 58), "pod": (93, 64, 55)}))


def alley_cat_brake():
    B = Builder()
    for k in (1, -1):
        B.box([k * .4, .86, -1.965], [.22, .09, .02], "#ff3a24", r=(0, 0, -k * .25))
    return B


def doghouse_brake():
    B = Builder()
    for k in (1, -1):
        B.box([k * .58, .45, -1.69], [.2, .12, .02], "#ff3a24")
    return B
