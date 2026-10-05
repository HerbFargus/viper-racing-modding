"""modtool.res -- the resource set v1.0's hidden model editor loads, built by vrmod.

THE EDITOR. v1.0's race.exe carries MGI's in-house model editor ("Texture Tool" in its title bar):
Ctrl+E on the main menu opens it (EditMenu -> ModTool). It loads every car's .car, race.res and
modtool.res, and modtool.res is the only one no disc ever shipped -- without it the editor has no
button art, no background and no marker model. The 1.1 and later builds dropped the editor, so
this is a v1.0-only file. What it reads from the set (viper-racing-port hook/edit_tool.cpp,
edit_view.cpp, gx_2d.cpp and ui_widget.cpp, checked against race_v10.exe's strings):

  * 21 button stamps (STMP). 13 are BRadioButtons (dialog item type 13): frame 0 drawn while
    unselected, frame 1 while selected -- the 3D view's modes tview / ttri / tvert / tedge / tgeom,
    the texture view's tools tnewp / tmovp / ttrans / tscale and its locks tnlock / tulock /
    tvlock / tuvsnap. The other 8 are BButtons (type 3): frame 0 up, frame 1 pressed (a third and
    fourth frame would be drawn while focused, a fifth while disabled; two frames is what the
    stock ok / cancel carry, and what we write). The widget takes its size from the stamp and its
    hit test is the stamp's rectangle, so the size is ours to pick within the layout -- see
    BUTTONS for each one's room. All are the uncompressed variant (stp.build_payload), opaque.
  * carback.stp: ModelViewer::Draw draws it at the 3D view's corner, clipped to the view, so only
    a 300 x 256 corner of it is ever seen -- that is the size we write. Composed at install time
    from the player's own ui.res (a crop of the dark chequered panel in catalog.stp, kept in its
    own palette), or generated (a dark viewport grid) when that isn't there.
  * point.mod: the marker drawn at the picked vertex (vertex mode), turned 10 degrees a frame and
    pulled to 1.1 in front of the camera so it is always the same size on screen. Its one
    material names null.tex -- that is the only thing that loads null.tex.
  * wire_f.tex: the texture of the whole model in the triangle / vertex / geometry modes
    (ModBuilderBuildGeometry). Every triangle gets its own corners: (0,0) (1,0) (0,1) normally,
    (.5,.5) (0,1) (1,1) for the picked triangle, (.5,.5) (1,0) (1,1) for the current surface's
    triangles -- so the texture is three regions, each a fill with its triangle's edges drawn.
  * wedge.tex: the texture in edge mode (build_edge_model). Each triangle is mapped onto one of 8
    half-quadrants of a 2 x 2 grid chosen by its three edges' smoothing flags, so the texture
    draws each edge as smoothed or hard. The community stand-in lacks it.

Not loaded from here: ok / cancel / lscroll / rscroll / cross come from common.res, prev / next /
dialog1 from ui.res -- both always loaded -- so they are not duplicated. "texture.stp" is named in
the texture view's struct but never loaded.

THE STAND-IN. Before this, the only modtool.res was a community stand-in (Frank P. Wolf's
toolpack2), in which 18 of the 21 buttons are one identical 24 x 21 placeholder (and wedge.tex is
missing). install() replaces exactly that file (matched by sha256) or a missing one; any other
modtool.res is somebody's work and is left alone unless --force. The stand-in is kept as modtool.res.vrmod-backup and put back by remove().
A small JSON record (modtool.res.vrmod) says the file is ours and which generator wrote it.

THE ART is drawn here from scratch -- pictograms, a 3 x 5 pixel font, bevels -- nothing copied.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import archive, envelope, mod, stp, tex
from .safewrite import write_atomic

NAME = "modtool.res"
BACKUP = "modtool.res.vrmod-backup"
RECORD = "modtool.res.vrmod"
GENERATOR = 1                      # bump when the generated content changes: installs then show "outdated"
STANDIN_SHA256 = "88091911e4486ce7baedadba4fffefaedf31912378b46f6ba678a2db58fe7f27"   # toolpack2's modtool.res

ABSENT, INSTALLED, OUTDATED, STANDIN, FOREIGN = "absent", "installed", "outdated", "standin", "foreign"

BACKGROUND = "carback.stp"
BG_W, BG_H = 300, 256              # the 3D view's rectangle: ModTool's item 0, 0x12c x 0x100
BG_SOURCE = ("ui.res", "catalog.stp", 36, 92)   # archive, stamp, crop x, y -- inside its dark panel
BG_MAX_MEAN = 64                   # a crop brighter than this (a modded catalog.stp) isn't a backdrop

# Each tool's room in the editor's layout (ModTool's item list, 640 x 480):
#   modes  x = 20, 44, 68, 92, 114 at y 360   -- tedge to tgeom is 22 apart: 22 wide, so none overlap
#   texture tools 340..412, locks 440..512, tplane / t3pput 540, 564 (24 apart) at y 360; the next
#     row (Translate...) is at y 390: 27 tall
#   capture at (500, 341) between lscroll (480, 18 wide) and rscroll (520): 20 wide, 19 tall
#   zoom at (597, 317), the corner where the texture view's scroll bars meet; the coordinates text
#     sits at (540, 335): 24 x 18
#   newsurf, surfprop at (480, 390), (550, 390) in the prev (340) / next (410) row, 70 apart: 64 x 32
#   browse at (220, 19) in the 320 x 200 Surface Properties box, beside the texture name (100..212),
#     above the Material row (y 40): 64 x 20
#   mktmplt at (90, 163) between ok (8, 64 wide) and cancel (248): 140 x 32, centred on the box


# ---------------------------------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------------------------------
RGB = tuple[int, int, int]


class Canvas:
    """A tiny RGB888 raster with just what the pictograms need."""

    def __init__(self, w: int, h: int, fill: RGB = (0, 0, 0)):
        self.w, self.h = w, h
        self.px = bytearray(bytes(fill) * (w * h))

    def set(self, x: int, y: int, c: RGB) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            o = (y * self.w + x) * 3
            self.px[o:o + 3] = bytes(c)

    def get(self, x: int, y: int) -> RGB:
        o = (y * self.w + x) * 3
        return self.px[o], self.px[o + 1], self.px[o + 2]

    def rect(self, x0: int, y0: int, x1: int, y1: int, c: RGB) -> None:
        """Filled, inclusive corners."""
        for y in range(max(y0, 0), min(y1, self.h - 1) + 1):
            for x in range(max(x0, 0), min(x1, self.w - 1) + 1):
                self.set(x, y, c)

    def frame(self, x0: int, y0: int, x1: int, y1: int, c: RGB) -> None:
        for x in range(x0, x1 + 1):
            self.set(x, y0, c)
            self.set(x, y1, c)
        for y in range(y0, y1 + 1):
            self.set(x0, y, c)
            self.set(x1, y, c)

    def line(self, x0: float, y0: float, x1: float, y1: float, c: RGB, width: int = 1) -> None:
        """Bresenham between rounded ends; width 2 thickens down / right."""
        x0, y0, x1, y1 = (int(round(v)) for v in (x0, y0, x1, y1))
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            for k in range(width):
                if dx >= -dy:
                    self.set(x0, y0 + k, c)
                else:
                    self.set(x0 + k, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def poly(self, pts: list[tuple[float, float]], c: RGB) -> None:
        """Filled polygon: every pixel whose centre is inside (even-odd)."""
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        for y in range(max(int(min(ys)), 0), min(int(max(ys)) + 1, self.h)):
            cy = y + 0.5
            for x in range(max(int(min(xs)), 0), min(int(max(xs)) + 1, self.w)):
                cx, inside = x + 0.5, False
                for i in range(len(pts)):
                    (ax, ay), (bx, by) = pts[i], pts[i - 1]
                    if (ay > cy) != (by > cy) and cx < (bx - ax) * (cy - ay) / (by - ay) + ax:
                        inside = not inside
                if inside:
                    self.set(x, y, c)

    def disc(self, cx: float, cy: float, r: float, c: RGB) -> None:
        for y in range(int(cy - r) - 1, int(cy + r) + 2):
            for x in range(int(cx - r) - 1, int(cx + r) + 2):
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    self.set(x, y, c)

    def ring(self, cx: float, cy: float, r: float, c: RGB, t: float = 1.0) -> None:
        for y in range(int(cy - r) - 2, int(cy + r) + 3):
            for x in range(int(cx - r) - 2, int(cx + r) + 3):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                if r - t <= d <= r:
                    self.set(x, y, c)

    def arrow(self, x0: float, y0: float, x1: float, y1: float, c: RGB, head: int = 2,
              both: bool = False) -> None:
        self.line(x0, y0, x1, y1, c)
        ends = [(x1, y1, x0, y0)] + ([(x0, y0, x1, y1)] if both else [])
        for tx, ty, fx, fy in ends:
            ang = math.atan2(ty - fy, tx - fx)
            for side in (-1, 1):
                a = ang + math.pi - side * math.pi / 4
                self.line(tx, ty, tx + head * math.cos(a), ty + head * math.sin(a), c)

    def text(self, x: int, y: int, s: str, c: RGB, scale: int = 1) -> None:
        for ch in s.upper():
            g = FONT.get(ch, FONT["?"])
            for gy, row in enumerate(g):
                for gx, bit in enumerate(row):
                    if bit == "#":
                        for sy in range(scale):
                            for sx in range(scale):
                                self.set(x + (gx * scale) + sx, y + gy * scale + sy, c)
            x += (len(g[0]) + 1) * scale if g[0] else 2 * scale

    def blit(self, other: "Canvas", x: int, y: int, scale: int = 1) -> None:
        for sy in range(other.h * scale):
            for sx in range(other.w * scale):
                self.set(x + sx, y + sy, other.get(sx // scale, sy // scale))


# A 3 x 5 capital font (M, N, W are wider so they stay readable); a space is a 2-pixel gap.
FONT: dict[str, list[str]] = {
    "A": [".#.", "#.#", "###", "#.#", "#.#"], "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": [".##", "#..", "#..", "#..", ".##"], "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"], "F": ["###", "#..", "##.", "#..", "#.."],
    "G": [".##", "#..", "#.#", "#.#", ".##"], "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"], "J": ["..#", "..#", "..#", "#.#", ".#."],
    "K": ["#.#", "#.#", "##.", "#.#", "#.#"], "L": ["#..", "#..", "#..", "#..", "###"],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#"], "N": ["#..#", "##.#", "#.##", "#..#", "#..#"],
    "O": [".#.", "#.#", "#.#", "#.#", ".#."], "P": ["##.", "#.#", "##.", "#..", "#.."],
    "Q": [".#.", "#.#", "#.#", "##.", ".##"], "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": [".##", "#..", ".#.", "..#", "##."], "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"], "V": ["#.#", "#.#", "#.#", ".#.", ".#."],
    "W": ["#...#", "#...#", "#.#.#", "##.##", "#...#"], "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."], "Z": ["###", "..#", ".#.", "#..", "###"],
    "0": [".#.", "#.#", "#.#", "#.#", ".#."], "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["##.", "..#", ".#.", "#..", "###"], "3": ["##.", "..#", ".#.", "..#", "##."],
    "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "##.", "..#", "##."],
    "6": [".##", "#..", "###", "#.#", "###"], "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"], "9": ["###", "#.#", "###", "..#", "##."],
    "-": ["...", "...", "###", "...", "..."], ".": ["...", "...", "...", "...", ".#."],
    "+": ["...", ".#.", "###", ".#.", "..."], "?": ["##.", "..#", ".#.", "...", ".#."],
    "_": ["...", "...", "...", "...", "###"],
    " ": ["", "", "", "", ""],
}


def text_width(s: str, scale: int = 1) -> int:
    w = 0
    for ch in s.upper():
        g = FONT.get(ch, FONT["?"])
        w += (len(g[0]) + 1) if g[0] else 2
    return max(w - 1, 0) * scale


# ---- the buttons' look: dark gunmetal, a yellow ring and yellow ink when selected or pressed ----
BORDER = (10, 11, 13)
FACE_TOP, FACE_BOTTOM = (92, 99, 108), (54, 59, 66)
BEVEL_LIGHT, BEVEL_DARK = (156, 164, 174), (30, 33, 37)
INK, LABEL_INK, ACCENT = (232, 235, 238), (196, 201, 208), (242, 193, 46)
SEL_TOP, SEL_BOTTOM = (38, 42, 48), (52, 57, 64)
SEL_RING, SEL_INK = (242, 184, 28), (255, 214, 74)
SEL_ACCENT = (255, 236, 150)
DARK = (22, 24, 28)               # pictogram details: a pupil, a keyhole


@dataclass
class Ink:
    ink: RGB
    accent: RGB
    dark: RGB = DARK


Pictogram = Callable[[Canvas, int, int, int, int, Ink], None]   # (canvas, x, y, w, h, ink)


def _button(w: int, h: int, label: str, pict: Pictogram, pressed: bool, *, side: bool = False) -> Canvas:
    """One frame: border, face, bevel (up) or yellow ring (pressed / selected), the pictogram over
    the label -- or beside it with side=True, for a short wide button."""
    c = Canvas(w, h, BORDER)
    top, bottom = (SEL_TOP, SEL_BOTTOM) if pressed else (FACE_TOP, FACE_BOTTOM)
    for y in range(1, h - 1):
        t = (y - 1) / max(h - 3, 1)
        col = tuple(int(round(a + (b - a) * t)) for a, b in zip(top, bottom))
        for x in range(1, w - 1):
            c.set(x, y, col)
    if pressed:
        c.frame(1, 1, w - 2, h - 2, SEL_RING)
        ink = Ink(SEL_INK, SEL_ACCENT)
        label_ink, off = SEL_INK, 1
    else:
        for x in range(1, w - 1):
            c.set(x, 1, BEVEL_LIGHT)
            c.set(x, h - 2, BEVEL_DARK)
        for y in range(1, h - 1):
            c.set(1, y, BEVEL_LIGHT)
            c.set(w - 2, y, BEVEL_DARK)
        ink = Ink(INK, ACCENT)
        label_ink, off = LABEL_INK, 0
    # Inside the border and bevel / ring: columns 2..w-3, rows 2..h-3. The pictogram moves a pixel
    # down and right when pressed; the label stays put (it already fills its row).
    if side:
        pw = 16
        tw = text_width(label)
        x0 = (w - (pw + 4 + tw)) // 2
        pict(c, x0 + off, 2 + off, pw, h - 5, ink)
        c.text(x0 + pw + 4, (h - 5) // 2, label, label_ink)
    else:
        ly = h - 8                               # the label: rows ly..ly+4, a row clear above the bevel
        pict(c, 2 + off, 2 + off, w - 5, ly - 3, ink)
        c.text((w - text_width(label)) // 2, ly, label, label_ink)
    return c


# ---- the pictograms. Each draws into the box (x, y, w, h), centred, in pixels. ------------------
def _box(x, y, w, h, bw, bh):
    """The top-left of a bw x bh design centred in the box."""
    return x + (w - bw) // 2, y + (h - bh) // 2


def p_view(c: Canvas, x, y, w, h, k: Ink):          # an eye: turn the model to look at it
    ox, oy = _box(x, y, w, h, 18, 11)
    pts = [(0, 5.5), (4, 1.5), (14, 1.5), (18, 5.5), (14, 9.5), (4, 9.5)]
    for i in range(len(pts)):
        (ax, ay), (bx, by) = pts[i - 1], pts[i]
        c.line(ox + ax, oy + ay, ox + bx, oy + by, k.ink)
    c.disc(ox + 9, oy + 5.5, 3.6, k.accent)
    c.disc(ox + 9, oy + 5.5, 1.5, k.dark)


def p_tris(c: Canvas, x, y, w, h, k: Ink):          # a filled triangle
    ox, oy = _box(x, y, w, h, 17, 12)
    tri = [(0.5, 11.5), (16.5, 11.5), (8.5, 0.5)]
    c.poly([(ox + px, oy + py) for px, py in tri], k.accent)
    for i in range(3):
        (ax, ay), (bx, by) = tri[i - 1], tri[i]
        c.line(ox + ax - 0.5, oy + ay - 0.5, ox + bx - 0.5, oy + by - 0.5, k.ink)


def p_verts(c: Canvas, x, y, w, h, k: Ink):         # a triangle's outline with its corners marked
    ox, oy = _box(x, y, w, h, 17, 12)
    a, b, t = (ox + 1, oy + 10), (ox + 15, oy + 10), (ox + 8, oy + 1)
    c.line(*a, *b, k.ink)
    c.line(*b, *t, k.ink)
    c.line(*t, *a, k.ink)
    for px, py in (a, b, t):
        c.rect(px - 1, py - 1, px + 1, py + 1, k.accent)


def p_edges(c: Canvas, x, y, w, h, k: Ink):         # two triangles, their shared edge picked out
    ox, oy = _box(x, y, w, h, 18, 12)
    tl, tr, br, bl = (ox + 1, oy + 1), (ox + 16, oy + 1), (ox + 16, oy + 11), (ox + 1, oy + 11)
    for a, b in ((tl, tr), (tr, br), (br, bl), (bl, tl)):
        c.line(*a, *b, k.ink)
    c.line(*bl, *tr, k.accent, width=2)


def p_geom(c: Canvas, x, y, w, h, k: Ink):          # a wireframe box
    ox, oy = _box(x, y, w, h, 17, 13)
    f = [(0, 4), (10, 4), (10, 12), (0, 12)]
    b = [(5, 0), (15, 0), (15, 8), (5, 8)]
    for i in range(4):
        c.line(ox + b[i - 1][0], oy + b[i - 1][1], ox + b[i][0], oy + b[i][1], k.ink)
        c.line(ox + f[i][0], oy + f[i][1], ox + b[i][0], oy + b[i][1], k.ink)
    for i in range(4):
        c.line(ox + f[i - 1][0], oy + f[i - 1][1], ox + f[i][0], oy + f[i][1], k.accent)


def p_addpt(c: Canvas, x, y, w, h, k: Ink):         # a point and a plus
    ox, oy = _box(x, y, w, h, 16, 11)
    c.disc(ox + 5, oy + 6.5, 3.2, k.accent)
    c.rect(ox + 12, oy + 0, ox + 13, oy + 7, k.ink)
    c.rect(ox + 9, oy + 3, ox + 16, oy + 4, k.ink)


def p_move(c: Canvas, x, y, w, h, k: Ink):          # a point with four arrows
    ox, oy = _box(x, y, w, h, 15, 13)
    cx, cy = ox + 7, oy + 6
    for dx, dy in ((0, -6), (0, 6), (-7, 0), (7, 0)):
        c.arrow(cx + (dx and (2 if dx > 0 else -2)), cy + (dy and (2 if dy > 0 else -2)),
                cx + dx, cy + dy, k.ink)
    c.rect(cx - 1, cy - 1, cx + 1, cy + 1, k.accent)


def p_trans(c: Canvas, x, y, w, h, k: Ink):         # three points carried right together
    ox, oy = _box(x, y, w, h, 19, 12)
    pts = [(1, 10), (8, 10), (4, 3)]
    for i in range(3):
        c.line(ox + pts[i - 1][0], oy + pts[i - 1][1], ox + pts[i][0], oy + pts[i][1], k.ink)
    for px, py in pts:
        c.rect(ox + px - 1, oy + py - 1, ox + px + 1, oy + py + 1, k.accent)
    c.arrow(ox + 11, oy + 6, ox + 18, oy + 6, k.ink, head=3)


def p_scale(c: Canvas, x, y, w, h, k: Ink):         # a small square growing into a large one
    ox, oy = _box(x, y, w, h, 15, 13)
    for i in range(0, 15, 2):                   # the large one, dotted
        c.set(ox + i, oy, k.ink)
        c.set(ox + 14, oy + i if i < 13 else oy + 12, k.ink)
    for i in range(0, 13, 2):
        c.set(ox, oy + i, k.ink)
        c.set(ox + i, oy + 12, k.ink)
    c.rect(ox, oy + 7, ox + 5, oy + 12, k.accent)
    c.arrow(ox + 6, oy + 6, ox + 12, oy + 1, k.ink, head=3)


def p_ulock(c: Canvas, x, y, w, h, k: Ink):         # along u only
    ox, oy = _box(x, y, w, h, 18, 9)
    c.arrow(ox + 1, oy + 4, ox + 16, oy + 4, k.accent, head=3, both=True)
    c.rect(ox + 7, oy + 1, ox + 10, oy + 7, k.ink)
    c.rect(ox + 8, oy + 3, ox + 9, oy + 5, k.dark)


def p_vlock(c: Canvas, x, y, w, h, k: Ink):         # along v only
    ox, oy = _box(x, y, w, h, 9, 13)
    c.arrow(ox + 4, oy + 0, ox + 4, oy + 12, k.accent, head=3, both=True)
    c.rect(ox + 1, oy + 4, ox + 7, oy + 8, k.ink)
    c.rect(ox + 3, oy + 5, ox + 5, oy + 7, k.dark)


def p_snap(c: Canvas, x, y, w, h, k: Ink):          # a magnet
    ox, oy = _box(x, y, w, h, 12, 13)
    c.rect(ox + 0, oy + 0, ox + 3, oy + 7, k.ink)
    c.rect(ox + 8, oy + 0, ox + 11, oy + 7, k.ink)
    c.rect(ox + 0, oy + 0, ox + 3, oy + 2, k.accent)
    c.rect(ox + 8, oy + 0, ox + 11, oy + 2, k.accent)
    for yy in range(8, 13):
        for xx in range(12):
            d = math.hypot(xx + 0.5 - 6, yy + 0.5 - 7.5)
            if 2.2 <= d <= 6.0:
                c.set(ox + xx, oy + yy, k.ink)


def p_free(c: Canvas, x, y, w, h, k: Ink):          # an open padlock
    ox, oy = _box(x, y, w, h, 11, 13)
    c.rect(ox + 0, oy + 6, ox + 10, oy + 12, k.ink)
    c.rect(ox + 4, oy + 8, ox + 6, oy + 10, k.dark)
    for xx in range(1, 8):                       # the shackle, swung open to the left
        for yy in range(0, 6):
            d = math.hypot(xx + 0.5 - 4.5, yy + 0.5 - 4)
            if 2.3 <= d <= 4.0 and yy < 4.5:
                c.set(ox + xx - 3, oy + yy, k.accent)
    c.rect(ox - 2, oy + 4, ox - 2, oy + 5, k.accent)
    c.rect(ox + 4, oy + 4, ox + 4, oy + 5, k.accent)


def p_plane(c: Canvas, x, y, w, h, k: Ink):         # projected straight down onto a plane
    ox, oy = _box(x, y, w, h, 19, 13)
    quad = [(ox + 0.5, oy + 12.5), (ox + 5.5, oy + 7.5), (ox + 18.5, oy + 7.5), (ox + 13.5, oy + 12.5)]
    c.poly(quad, k.accent)
    for xx in (6, 12):
        c.arrow(ox + xx, oy + 0, ox + xx, oy + 6, k.ink, head=2)


def p_3pt(c: Canvas, x, y, w, h, k: Ink):           # a plane through three points
    ox, oy = _box(x, y, w, h, 18, 13)
    pts = [(1, 11), (16, 9), (8, 1)]
    c.poly([(ox + px + 0.5, oy + py + 0.5) for px, py in pts], (k.ink[0] // 3, k.ink[1] // 3, k.ink[2] // 3))
    for i in range(3):
        c.line(ox + pts[i - 1][0], oy + pts[i - 1][1], ox + pts[i][0], oy + pts[i][1], k.ink)
    for px, py in pts:
        c.rect(ox + px - 1, oy + py - 1, ox + px + 1, oy + py + 1, k.accent)


def p_capture(c: Canvas, x, y, w, h, k: Ink):       # a camera
    ox, oy = _box(x, y, w, h, 12, 8)
    c.rect(ox + 0, oy + 1, ox + 11, oy + 7, k.ink)
    c.rect(ox + 2, oy + 0, ox + 5, oy + 0, k.ink)
    c.disc(ox + 6, oy + 4.5, 2.6, k.dark)
    c.disc(ox + 6, oy + 4.5, 1.3, k.accent)


def p_zoom(c: Canvas, x, y, w, h, k: Ink):          # a magnifier
    ox, oy = _box(x, y, w, h, 10, 7)
    c.ring(ox + 3.5, oy + 3.5, 3.5, k.ink, 1.2)
    c.set(ox + 3, oy + 3, k.accent)
    c.set(ox + 3, oy + 2, k.accent)
    c.set(ox + 2, oy + 3, k.accent)
    c.line(ox + 6, oy + 5, ox + 9, oy + 6, k.ink, width=2)


def _swatch(c: Canvas, ox, oy, n, cell, k: Ink):
    for j in range(n):
        for i in range(n):
            col = k.accent if (i + j) % 2 == 0 else k.ink
            c.rect(ox + i * cell, oy + j * cell, ox + i * cell + cell - 1, oy + j * cell + cell - 1, col)


def p_newsurf(c: Canvas, x, y, w, h, k: Ink):       # a texture swatch and a plus
    ox, oy = _box(x, y, w, h, 22, 12)
    _swatch(c, ox, oy, 4, 3, k)
    c.rect(ox + 17, oy + 2, ox + 18, oy + 9, k.ink)
    c.rect(ox + 14, oy + 5, ox + 21, oy + 6, k.ink)


def p_surfprop(c: Canvas, x, y, w, h, k: Ink):      # a swatch and its settings (three sliders)
    ox, oy = _box(x, y, w, h, 26, 12)
    _swatch(c, ox, oy, 4, 3, k)
    for i, knob in enumerate((3, 8, 5)):
        yy = oy + 1 + i * 4
        c.line(ox + 15, yy, ox + 25, yy, k.ink)
        c.rect(ox + 15 + knob - 1, yy - 1, ox + 15 + knob, yy + 1, k.accent)


def p_browse(c: Canvas, x, y, w, h, k: Ink):        # a folder
    ox, oy = _box(x, y, w, h, 14, 11)
    c.rect(ox + 0, oy + 0, ox + 5, oy + 1, k.accent)
    c.rect(ox + 0, oy + 2, ox + 13, oy + 10, k.accent)
    c.line(ox + 0, oy + 4, ox + 13, oy + 4, k.dark)


def p_template(c: Canvas, x, y, w, h, k: Ink):      # a sheet with the texture's triangles laid out
    ox, oy = _box(x, y, w, h, 15, 17)
    c.rect(ox + 0, oy + 0, ox + 14, oy + 16, k.ink)
    for i in range(4):                               # the folded corner
        for j in range(4 - i):
            c.set(ox + 14 - j, oy + i, _behind(c, ox + 15, oy + i))
    c.line(ox + 11, oy + 0, ox + 14, oy + 3, k.dark)
    tris = ([(2, 3), (8, 3), (2, 9)], [(4, 14), (11, 14), (11, 7)])
    for t in tris:
        c.poly([(ox + px + 0.5, oy + py + 0.5) for px, py in t], k.accent)
        for i in range(3):
            c.line(ox + t[i - 1][0], oy + t[i - 1][1], ox + t[i][0], oy + t[i][1], k.dark)


def _behind(c: Canvas, x: int, y: int) -> RGB:
    """The face colour just outside a pictogram, for cut-outs."""
    return c.get(min(x, c.w - 1), y)


@dataclass(frozen=True)
class Button:
    name: str          # the stamp's name in modtool.res
    kind: str          # "radio" (frame 1 = selected) or "button" (frame 1 = pressed)
    w: int
    h: int
    label: str
    pict: Pictogram
    does: str          # what the tool does, from the editor's code
    side: bool = False


RADIO = "radio"
PUSH = "button"
BUTTONS: list[Button] = [
    Button("tview.stp", RADIO, 24, 27, "VIEW", p_view, "3D view mode: drag to turn the model"),
    Button("ttri.stp", RADIO, 24, 27, "TRIS", p_tris,
           "triangle mode: a click puts the triangle into the surface's texture triangles (Delete takes it out)"),
    Button("tvert.stp", RADIO, 24, 27, "VERT", p_verts, "vertex mode: a click picks the vertex under the mouse (the marker)"),
    Button("tedge.stp", RADIO, 22, 27, "EDGE", p_edges,
           "edge mode: a click flips an edge between smoothed and hard (Ctrl: smooth all, Ctrl+Shift: facet all)"),
    Button("tgeom.stp", RADIO, 24, 27, "GEOM", p_geom,
           "geometry mode: a click puts the triangle with texture points from the plane / 3-point transform"),
    Button("tnewp.stp", RADIO, 24, 27, "ADD", p_addpt, "texture tool: add a texture point on the picked vertex"),
    Button("tmovp.stp", RADIO, 24, 27, "MOVE", p_move, "texture tool: drag one texture point"),
    Button("ttrans.stp", RADIO, 24, 27, "ALL", p_trans, "texture tool: move all the points (Ctrl rotates them)"),
    Button("tscale.stp", RADIO, 24, 27, "SIZE", p_scale, "texture tool: scale the points about the texture's middle"),
    Button("tulock.stp", RADIO, 24, 27, "U LCK", p_ulock, "lock: a dragged point moves along u only"),
    Button("tvlock.stp", RADIO, 24, 27, "V LCK", p_vlock, "lock: a dragged point moves along v only"),
    Button("tuvsnap.stp", RADIO, 24, 27, "SNAP", p_snap, "lock: a dragged point snaps to the captured overlay's points"),
    Button("tnlock.stp", RADIO, 24, 27, "FREE", p_free, "lock off: points move freely"),
    Button("tplane.stp", PUSH, 24, 27, "PROJ", p_plane,
           "texture transform from the last three points as a planar projection (key s)"),
    Button("t3pput.stp", PUSH, 24, 27, "3 PT", p_3pt,
           "texture transform from the last three points' own plane (key S)"),
    Button("capture.stp", PUSH, 20, 19, "CAPT", p_capture,
           "capture every surface's texture points as overlays (lscroll / rscroll step through them; "
           "Tab shows the captured *<file> model)"),
    Button("zoom.stp", PUSH, 24, 18, "ZOOM", p_zoom, "the texture view's zoom, 1x to 5x and round again"),
    Button("newsurf.stp", PUSH, 64, 32, "NEW SURF", p_newsurf, "add a surface (copying the current one's texture and material)"),
    Button("surfprop.stp", PUSH, 64, 32, "SURF PROPS", p_surfprop,
           "the Surface Properties box: texture, material, alpha, smoothing group"),
    Button("browse.stp", PUSH, 64, 20, "BROWSE", p_browse, "(Surface Properties) pick the surface's .tex file", side=True),
    Button("mktmplt.stp", PUSH, 140, 32, "MAKE TEMPLATE", p_template,
           "(Surface Properties) write the surface's texture triangles as a .bmp paint template"),
]
BUTTON_NAMES = [b.name for b in BUTTONS]

# A tool button's 8-byte tail is (row count, 1.0) on every MGI tool button of this kind (the paint
# kit's 24 x 21 ones); its meaning is unidentified (stp.py), so the buttons carry the same.
_BUTTON_TAIL_FLOAT = 1.0


def button_frames(b: Button) -> list[Canvas]:
    return [_button(b.w, b.h, b.label, b.pict, False, side=b.side),
            _button(b.w, b.h, b.label, b.pict, True, side=b.side)]


def _stamp_bytes(frames: list[Canvas], tail_float: float) -> bytes:
    w, h = frames[0].w, frames[0].h
    pixels = b"".join(bytes(f.px) for f in frames)
    pal555, pal565, rows = stp.quantize(pixels, w, h * len(frames))
    payload = stp.build_payload(w, h, len(frames), (0, 0), pal555, pal565, rows,
                                struct.pack("<if", h * len(frames), tail_float))
    return envelope.build(stp.TAG, 3, payload)


def build_button(b: Button) -> bytes:
    return _stamp_bytes(button_frames(b), _BUTTON_TAIL_FLOAT)


# ---------------------------------------------------------------------------------------------------
# the background
# ---------------------------------------------------------------------------------------------------
def generated_background() -> Canvas:
    """A plain dark viewport: a blue-grey gradient with a faint grid, a brighter line every 4th."""
    c = Canvas(BG_W, BG_H)
    for y in range(BG_H):
        t = y / (BG_H - 1)
        base = (int(30 - 14 * t), int(34 - 15 * t), int(42 - 16 * t))
        for x in range(BG_W):
            col = base
            gx, gy = (x - BG_W // 2) % 16 == 0, (y - BG_H // 2) % 16 == 0
            if gx or gy:
                major = (gx and (x - BG_W // 2) % 64 == 0) or (gy and (y - BG_H // 2) % 64 == 0)
                lift = 14 if major else 7
                col = (base[0] + lift, base[1] + lift, base[2] + lift + 3)
            c.set(x, y, col)
    return c


def _find_member(data_dir: Path, res: str, member: str) -> bytes | None:
    p = data_dir / res
    if not p.is_file():
        return None
    try:
        for e in archive.read(p):
            if e.name.lower() == member.lower():
                return e.payload if e.tag == stp.TAG else None
    except (OSError, ValueError, struct.error):
        return None
    return None


def compose_background(data_dir: str | Path | None) -> tuple[bytes, str]:
    """carback.stp's standalone bytes and where its picture came from: a 300 x 256 crop of the dark
    panel in the player's own ui.res catalog.stp, in that stamp's own palette (nothing quantised,
    nothing of it shipped with vrmod), or -- when that isn't there, isn't the uncompressed 640 x 480
    stamp, or isn't dark -- vrmod's generated panel."""
    if data_dir is not None:
        res, member, cx, cy = BG_SOURCE
        payload = _find_member(Path(data_dir), res, member)
        if payload is not None:
            try:
                s = stp.parse_payload(payload)
            except (ValueError, struct.error):
                s = None
            if s is not None and s.frames == 1 and s.width >= cx + BG_W and s.height >= cy + BG_H:
                rows = [s.indices[cy + y][cx:cx + BG_W] for y in range(BG_H)]
                lum = 0
                for y in range(cy, cy + BG_H, 4):
                    for x in range(cx, cx + BG_W, 4):
                        o = (y * s.width + x) * 3
                        lum += s.pixels[o] + s.pixels[o + 1] + s.pixels[o + 2]
                mean = lum / 3 / ((BG_H // 4) * (BG_W // 4))
                if mean <= BG_MAX_MEAN:
                    tail = struct.pack("<i", BG_H) + s.reserved_tail[4:8]
                    out = stp.build_payload(BG_W, BG_H, 1, (0, 0), s.palette555, s.palette565, rows, tail)
                    return envelope.build(stp.TAG, 3, out), f"{res} {member}"
    return _stamp_bytes([generated_background()], 0.0), "generated"


# ---------------------------------------------------------------------------------------------------
# the 3D pieces: the vertex marker, its texture, and the two overlay textures
# ---------------------------------------------------------------------------------------------------
MARKER_TEX = "null.tex"
WIRE_TEX = "wire_f.tex"
WEDGE_TEX = "wedge.tex"
MARKER_RGB = (255, 48, 200)          # hot pink: unlike any of the overlay colours or a car's paint


def build_point_mod() -> bytes:
    """Two square pyramids meeting tip to tip at the origin (the picked vertex): one above, one
    below, so the marker points at the vertex whichever way up the model is. Every face is written
    both ways round, so no culling convention can hide it. 0.08 long at the 1.1 the editor pulls it
    to is about a sixth of the view's height."""
    L, a = 0.08, 0.022
    verts: list[mod.Vertex] = []
    faces: list[tuple[int, int, int]] = []

    def tri(p, q, r):
        ux, uy, uz = (q[i] - p[i] for i in range(3))
        vx, vy, vz = (r[i] - p[i] for i in range(3))
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        ln = math.sqrt(sum(v * v for v in n)) or 1.0
        n = tuple(v / ln for v in n)
        for order, sign in (((p, q, r), 1), ((p, r, q), -1)):
            base = len(verts)
            for pt in order:
                verts.append(mod.Vertex(pt[0], pt[1], pt[2], n[0] * sign, n[1] * sign, n[2] * sign, 0.5, 0.5))
            faces.append((base, base + 1, base + 2))

    for s in (1, -1):
        corners = [(a, s * L, a), (-a, s * L, a), (-a, s * L, -a), (a, s * L, -a)]
        for i in range(4):
            tri((0.0, 0.0, 0.0), corners[i], corners[i - 1])
        tri(corners[0], corners[1], corners[2])
        tri(corners[0], corners[2], corners[3])
    mesh = mod.Mesh(vertices=verts, materials=[mod.Material(MARKER_TEX, 0, len(verts), 0, len(faces))],
                    faces=faces)
    return mod.build(mesh)


def build_null_tex() -> bytes:
    """point.mod's texture: one flat colour (no black, which some cards key out)."""
    return tex.encode_to_tex(bytes(MARKER_RGB) * 64, 8, mode="opaque")


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _inside(px, py, tri) -> bool:
    (ax, ay), (bx, by), (cx, cy) = tri
    d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by)
    d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy)
    d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


WIRE_SIZE = 128
WIRE_EDGE = (34, 40, 66)             # dark navy, not black (black can key out)
WIRE_FILLS = (                       # (the region's triangle in u, v; its fill)
    (((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), (168, 176, 188)),     # every triangle: light grey
    (((0.5, 0.5), (0.0, 1.0), (1.0, 1.0)), (246, 200, 40)),      # the picked one: yellow
    (((0.5, 0.5), (1.0, 0.0), (1.0, 1.0)), (96, 156, 222)),      # the surface's triangles: blue
)


def wire_pixels(size: int = WIRE_SIZE) -> bytes:
    """wire_f.tex's picture: three regions, each its fill with its triangle's three edges drawn,
    so every triangle in the triangle / vertex / geometry modes shows its own wireframe."""
    t = 2.6 / size
    out = bytearray()
    for y in range(size):
        v = (y + 0.5) / size
        for x in range(size):
            u = (x + 0.5) / size
            col = WIRE_FILLS[0][1]
            for tri, fill in WIRE_FILLS:
                if _inside(u, v, tri):
                    d = min(_seg_dist(u, v, *tri[i - 1], *tri[i]) for i in range(3))
                    col = WIRE_EDGE if d < t else fill
                    break
            out += bytes(col)
    return bytes(out)


def build_wire_tex() -> bytes:
    return tex.encode_to_tex(wire_pixels(), WIRE_SIZE, mode="opaque")


# build_edge_model's table: per flag pattern k (edge[2] = bit 0, edge[1] = bit 1, edge[0] = bit 2;
# edge i runs from corner i to corner i+1, as mrModelPickEdge numbers them), the three corners' u, v.
WEDGE_UV = (
    ((0, 0), (.5, 0), (0, .5)), ((.5, .5), (.5, 0), (0, .5)),
    ((.5, 0), (1, 0), (.5, .5)), ((1, .5), (1, 0), (.5, .5)),
    ((0, .5), (.5, .5), (0, 1)), ((.5, 1), (.5, .5), (0, 1)),
    ((.5, .5), (1, .5), (.5, 1)), ((1, 1), (1, .5), (.5, 1)),
)
WEDGE_SIZE = 128
WEDGE_FILL = (168, 176, 188)
WEDGE_HARD = (236, 96, 24)           # a hard (faceted) edge: a bold orange line
WEDGE_SMOOTH = (84, 168, 96)         # a smoothed edge: a thin green one


def wedge_pixels(size: int = WEDGE_SIZE) -> bytes:
    """wedge.tex's picture: each of the 8 half-quadrants draws its triangle's edges by that
    pattern's flags -- set (smoothed) thin green, clear (hard) bold orange."""
    hard_t, smooth_t = 2.8 / size, 1.4 / size
    out = bytearray()
    for y in range(size):
        v = (y + 0.5) / size
        for x in range(size):
            u = (x + 0.5) / size
            col = WEDGE_FILL
            for k, tri in enumerate(WEDGE_UV):
                if not _inside(u, v, tri):
                    continue
                flags = ((k >> 2) & 1, (k >> 1) & 1, k & 1)     # edge[0], edge[1], edge[2]
                best = None
                for i in range(3):
                    d = _seg_dist(u, v, *tri[i], *tri[(i + 1) % 3])
                    lim = smooth_t if flags[i] else hard_t
                    if d < lim and (best is None or d < best[0]):
                        best = (d, WEDGE_SMOOTH if flags[i] else WEDGE_HARD)
                if best:
                    col = best[1]
                break
            out += bytes(col)
    return bytes(out)


def build_wedge_tex() -> bytes:
    return tex.encode_to_tex(wedge_pixels(), WEDGE_SIZE, mode="opaque")


# ---------------------------------------------------------------------------------------------------
# the archive
# ---------------------------------------------------------------------------------------------------
LOADED = [BACKGROUND] + BUTTON_NAMES + ["point.mod", MARKER_TEX, WIRE_TEX, WEDGE_TEX]


def build(data_dir: str | Path | None = None) -> tuple[bytes, str]:
    """The whole modtool.res, and where its background came from ("ui.res catalog.stp" or
    "generated"). data_dir is the install whose own art the background is composed from."""
    members: list[tuple[str, bytes]] = []
    bg, source = compose_background(data_dir)
    members.append((BACKGROUND, bg))
    for b in BUTTONS:
        members.append((b.name, build_button(b)))
    members.append(("point.mod", build_point_mod()))
    members.append((MARKER_TEX, build_null_tex()))
    members.append((WIRE_TEX, build_wire_tex()))
    members.append((WEDGE_TEX, build_wedge_tex()))
    entries = []
    for name, data in members:
        env = envelope.parse(data)
        entries.append(archive.ArchiveEntry(name=name, tag=env.tag, version=env.version, payload=env.payload))
    return archive.to_bytes(entries), source


# ---------------------------------------------------------------------------------------------------
# install / status / remove
# ---------------------------------------------------------------------------------------------------
class ModtoolError(Exception):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(d: Path) -> dict | None:
    try:
        rec = json.loads((d / RECORD).read_text(encoding="utf-8"))
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def is_v10(data_dir: str | Path) -> bool:
    from . import modern_engine          # the one v1.0 test (race.exe's PE timestamp)
    return modern_engine.race_exe_is_v10(data_dir)


def status(data_dir: str | Path) -> dict:
    """{"state": absent | installed | outdated | standin | foreign, "background": where ours took
    its background from (or None), "backup": a set-aside modtool.res is here}. installed / outdated
    = written by vrmod (its record matches the file), by this generator or an older one."""
    d = Path(data_dir)
    p = d / NAME
    out = {"state": ABSENT, "background": None, "backup": (d / BACKUP).is_file()}
    if not p.is_file():
        return out
    data = p.read_bytes()
    sha = _sha(data)
    rec = _record(d)
    if rec and rec.get("sha256") == sha:
        out["state"] = INSTALLED if rec.get("generator") == GENERATOR else OUTDATED
        out["background"] = rec.get("background")
    elif sha == STANDIN_SHA256:
        out["state"] = STANDIN
    else:
        out["state"] = FOREIGN
    return out


def install(data_dir: str | Path, force: bool = False) -> str:
    """Write vrmod's modtool.res beside a v1.0 race.exe. Replaces a missing one, the community
    stand-in (kept as modtool.res.vrmod-backup) or an earlier one of ours; leaves any other
    modtool.res alone unless force (then it is the one kept as the backup)."""
    d = Path(data_dir)
    if not d.is_dir():
        raise ModtoolError(f"no folder {d}")
    if not is_v10(d):
        raise ModtoolError("the model editor is in v1.0's race.exe only -- there's no v1.0 race.exe here")
    st = status(d)["state"]
    p = d / NAME
    note = ""
    if st == FOREIGN and not force:
        return (f"Left the {NAME} here alone: it isn't the community stand-in or vrmod's, so it's someone's "
                "own work. `vrmod modtool <Data> --force` replaces it (keeping it as "
                f"{BACKUP}).")
    if st in (STANDIN, FOREIGN):
        if (d / BACKUP).exists():
            if _sha((d / BACKUP).read_bytes()) != _sha(p.read_bytes()):
                raise ModtoolError(f"{BACKUP} already exists and holds a different file -- move one of them aside first")
            p.unlink()
        else:
            p.rename(d / BACKUP)
        note = (" The community stand-in it replaces is kept as " if st == STANDIN
                else " The one it replaces is kept as ") + f"{BACKUP}, and Remove puts it back."
    data, source = build(d)
    write_atomic(p, data)
    (d / RECORD).write_text(json.dumps({"generator": GENERATOR, "sha256": _sha(data), "background": source},
                                       indent=1) + "\n", encoding="utf-8")
    bg = ("its background cropped from your own ui.res (catalog.stp)" if source != "generated"
          else "a generated background (no usable catalog.stp in ui.res)")
    verb = "updated" if st in (INSTALLED, OUTDATED) else "written"
    return (f"{NAME} {verb}: the model editor's 21 tool buttons, {bg}, the vertex marker and its "
            f"overlay textures. Ctrl+E on the main menu opens the editor.{note}")


def remove(data_dir: str | Path) -> str:
    """Take vrmod's modtool.res out and put back the one it replaced, if any. Leaves anyone else's alone."""
    d = Path(data_dir)
    st = status(d)
    p = d / NAME
    msg = []
    if st["state"] in (INSTALLED, OUTDATED):
        p.unlink()
        msg.append(f"Took out vrmod's {NAME}")
    if (d / RECORD).is_file():
        (d / RECORD).unlink()            # ours, or stale (the file it described has gone or changed)
    if (d / BACKUP).is_file() and not p.exists():
        (d / BACKUP).rename(p)
        msg.append(f"the {NAME} it replaced is back in place")
    if not msg:
        if st["state"] in (STANDIN, FOREIGN):
            return f"The {NAME} here isn't vrmod's -- left alone."
        return f"No {NAME} of vrmod's here -- nothing to remove."
    out = "; ".join(msg)
    return out[0].upper() + out[1:] + "."


# ---------------------------------------------------------------------------------------------------
# a contact sheet of the buttons (for the docs and a quick look)
# ---------------------------------------------------------------------------------------------------
def contact_sheet(scale: int = 4) -> tuple[bytes, int, int]:
    """Every button, both frames side by side at `scale`, captioned; returns (RGB888, w, h)."""
    pad, cap = 8 * scale // 2, 7 * 2
    cells = []
    for b in BUTTONS:
        f0, f1 = button_frames(b)
        cw = 2 * b.w * scale + pad
        cells.append((b, f0, f1, max(cw, text_width(b.name, 2) + 4), b.h * scale + cap + 4))
    width_limit = 1400
    sheet_rows: list[list] = [[]]
    x = 0
    for cell in cells:
        if x + cell[3] + pad > width_limit and sheet_rows[-1]:
            sheet_rows.append([])
            x = 0
        sheet_rows[-1].append(cell)
        x += cell[3] + pad
    W = max(sum(c[3] + pad for c in r) for r in sheet_rows) + pad
    H = sum(max(c[4] for c in r) + pad for r in sheet_rows) + pad
    sheet = Canvas(W, H, (40, 42, 46))
    y = pad
    for r in sheet_rows:
        x = pad
        for b, f0, f1, cw, ch in r:
            sheet.text(x, y, b.name, (220, 220, 220), 2)
            sheet.blit(f0, x, y + cap, scale)
            sheet.blit(f1, x + b.w * scale + pad // 2, y + cap, scale)
            x += cw + pad
        y += max(c[4] for c in r) + pad
    return bytes(sheet.px), W, H


def png(pixels: bytes, w: int, h: int) -> bytes:
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += pixels[y * w * 3:(y + 1) * w * 3]

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
