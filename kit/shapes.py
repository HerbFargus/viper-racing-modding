"""Low-poly modelling: tapered boxes, pyramids and prisms in flat palette colours.

The API matches the three.js mockups' JS Builder part for part, so a model drawn in a mockup
page ports by changing syntax only. Geometry is in the game's frame for cars and obstacles
(metres, y up, +z the nose) -- or the mockup's frame for track props, which tracks.py turns
into the source frame -- and every triangle is wound so its right-hand normal points out,
the side the game draws.

COLOURS live in a Palette: one 8x8 cell per colour in a 128 px texture, each face's UVs at
its cell's centre. A palette has a NAME, and every build must give its own: the game caches
textures by name, so two different palettes under one name recolour each other's models
(Cats vs Dogs, 2026-10-10: the cars and the track shipped `cvdpal.tex` in different colour
orders and everything came out wrong). Encode the palette AFTER building every mesh that
uses it -- a mesh's UVs point at cells, and cells are handed out as colours are first seen.
"""
from __future__ import annotations

import math
import random

import kit  # noqa: F401  (vrmod on sys.path)
from vrmod import archive, envelope, mod, tex

CELL, GRID = 8, 16                   # 16 x 16 cells of 8 px: a 128 px texture, 256 colours


class Palette:
    def __init__(self, name: str):
        if not name.endswith(".tex") or len(name) > 12 or "_" in name:
            raise ValueError(f"{name!r}: texture names are 8.3 (<= 12 chars with .tex) and no underscores")
        self.name = name
        self.colours: list[str] = []

    def cell(self, hexc: str) -> int:
        hexc = hexc.lower()
        if len(hexc) == 4:
            hexc = "#" + "".join(ch * 2 for ch in hexc[1:])
        if hexc not in self.colours:
            if len(self.colours) >= GRID * GRID:
                raise ValueError("palette full")
            self.colours.append(hexc)
        return self.colours.index(hexc)

    def uv(self, hexc: str) -> tuple[float, float]:
        c = self.cell(hexc)
        return ((c % GRID) + 0.5) / GRID, ((c // GRID) + 0.5) / GRID

    def pixels(self) -> bytes:
        """RGB888. Unused cells grey; no texel on raw 0x0000, the colour key."""
        size = CELL * GRID
        px = bytearray(bytes((128, 128, 128)) * (size * size))
        for i, h in enumerate(self.colours):
            r, g, b = (max(10, int(h[k:k + 2], 16)) for k in (1, 3, 5))
            cx, cy = (i % GRID) * CELL, (i // GRID) * CELL
            for y in range(cy, cy + CELL):
                for x in range(cx, cx + CELL):
                    o = (y * size + x) * 3
                    px[o:o + 3] = bytes((r, g, b))
        return bytes(px)

    def tex_bytes(self, wrap: int = 0) -> bytes:
        return tex.encode_to_tex(self.pixels(), CELL * GRID, mode="opaque", wrap=wrap)

    def entry(self, wrap: int = 0) -> archive.ArchiveEntry:
        t = envelope.parse(self.tex_bytes(wrap))
        return archive.ArchiveEntry(name=self.name, tag=t.tag, version=t.version, payload=t.payload)


# ---------- vector helpers ----------
def _rot(r):
    """three.js Euler 'XYZ': M = Rx * Ry * Rz."""
    a, b, c = r
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    rx = ((1, 0, 0), (0, ca, -sa), (0, sa, ca))
    ry = ((cb, 0, sb), (0, 1, 0), (-sb, 0, cb))
    rz = ((cc, -sc, 0), (sc, cc, 0), (0, 0, 1))

    def mul(m, n):
        return tuple(tuple(sum(m[i][k] * n[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    return mul(mul(rx, ry), rz)


def _xf(at, rot):
    m = _rot(rot)

    def V(x, y, z):
        return (m[0][0] * x + m[0][1] * y + m[0][2] * z + at[0],
                m[1][0] * x + m[1][1] * y + m[1][2] * z + at[1],
                m[2][0] * x + m[2][1] * y + m[2][2] * z + at[2])
    return V


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def both(f):
    f(1); f(-1)


class Builder:
    """Triangles, one hex colour each. Same calls as the mockups' JS Builder."""

    def __init__(self):
        self.tris: list[tuple[tuple, tuple, tuple, str]] = []

    def tri(self, a, b, c, col):
        self.tris.append((a, b, c, col))

    def quad(self, a, b, c, d, col):
        self.tri(a, b, c, col)
        self.tri(a, c, d, col)

    def box(self, at, s, c, top=(1, 1), sh=(0, 0), r=(0, 0, 0)):
        """A box w x h x d centred at `at`; `top` scales the top face (0.04 makes a gable roof),
        `sh` shifts it, `r` turns the whole box (radians, three.js XYZ order)."""
        w, h, d = s
        tx, tz = top
        sx, sz = sh
        V = _xf(at, r)
        b = [V(-w / 2, -h / 2, -d / 2), V(w / 2, -h / 2, -d / 2), V(w / 2, -h / 2, d / 2), V(-w / 2, -h / 2, d / 2)]
        t = [V(-w * tx / 2 + sx, h / 2, -d * tz / 2 + sz), V(w * tx / 2 + sx, h / 2, -d * tz / 2 + sz),
             V(w * tx / 2 + sx, h / 2, d * tz / 2 + sz), V(-w * tx / 2 + sx, h / 2, d * tz / 2 + sz)]
        self.quad(t[0], t[3], t[2], t[1], c); self.quad(b[0], b[1], b[2], b[3], c)
        self.quad(b[3], b[2], t[2], t[3], c); self.quad(b[1], b[0], t[0], t[1], c)
        self.quad(b[2], b[1], t[1], t[2], c); self.quad(b[0], b[3], t[3], t[0], c)

    def pyr(self, at, s, c, apex=(0, 0), r=(0, 0, 0)):
        """A pyramid standing on its base centre `at`; `apex` offsets the tip (x, z)."""
        w, h, d = s
        V = _xf(at, r)
        b = [V(-w / 2, 0, -d / 2), V(w / 2, 0, -d / 2), V(w / 2, 0, d / 2), V(-w / 2, 0, d / 2)]
        a = V(apex[0], h, apex[1])
        self.quad(b[0], b[1], b[2], b[3], c)
        self.tri(b[3], b[2], a, c); self.tri(b[1], b[0], a, c); self.tri(b[2], b[1], a, c); self.tri(b[0], b[3], a, c)

    def cyl(self, at, rad, h, c, n=8, rad2=None, c2=None, rot=(0, 0, 0)):
        """An n-sided prism standing on its base centre; rad2 tapers the top, c2 colours the caps."""
        rad2 = rad if rad2 is None else rad2
        c2 = c2 or c
        V = _xf(at, rot)
        B = [V(math.cos(i / n * 2 * math.pi) * rad, 0, math.sin(i / n * 2 * math.pi) * rad) for i in range(n)]
        T = [V(math.cos(i / n * 2 * math.pi) * rad2, h, math.sin(i / n * 2 * math.pi) * rad2) for i in range(n)]
        cb, ct = V(0, 0, 0), V(0, h, 0)
        for i in range(n):
            j = (i + 1) % n
            self.quad(B[j], B[i], T[i], T[j], c)
            self.tri(ct, T[j], T[i], c2)
            self.tri(cb, B[i], B[j], c)

    def extend(self, other: "Builder", offset=(0, 0, 0), scale=1.0):
        f = lambda p: tuple(p[k] * scale + offset[k] for k in range(3))  # noqa: E731
        self.tris += [(f(a), f(b), f(c), col) for a, b, c, col in other.tris]
        return self

    def bounds(self):
        ps = [p for t in self.tris for p in t[:3]]
        return [min(p[k] for p in ps) for k in range(3)], [max(p[k] for p in ps) for k in range(3)]

    def transformed(self, scale=1.0, offset=(0, 0, 0)) -> "Builder":
        return Builder().extend(self, offset, scale)

    def centred(self, scale=1.0) -> "Builder":
        """Scaled and moved so the bounding box's middle is the origin -- what an obstacle
        needs (the engine draws it at the ball's centre; built on its feet, it floats)."""
        lo, hi = self.bounds()
        c = [(lo[k] + hi[k]) / 2 for k in range(3)]
        return self.transformed(scale, tuple(-c[k] * scale for k in range(3)))

    def mesh(self, palette: Palette) -> mod.Mesh:
        """Flat-shaded mesh on `palette`; vertices shared only where position, normal and
        colour all match. Degenerate triangles are dropped."""
        verts: list[mod.Vertex] = []
        index: dict = {}
        faces = []
        for a, b, c, col in self.tris:
            n = cross(sub(b, a), sub(c, a))
            ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
            if ln < 1e-12:
                continue
            n = (n[0] / ln, n[1] / ln, n[2] / ln)
            cell = palette.cell(col)
            u, v = ((cell % GRID) + 0.5) / GRID, ((cell // GRID) + 0.5) / GRID
            f = []
            for p in (a, b, c):
                key = (round(p[0], 5), round(p[1], 5), round(p[2], 5),
                       round(n[0], 4), round(n[1], 4), round(n[2], 4), cell)
                if key not in index:
                    index[key] = len(verts)
                    verts.append(mod.Vertex(p[0], p[1], p[2], n[0], n[1], n[2], u, v))
                f.append(index[key])
            faces.append(tuple(f))
        return mod.Mesh(vertices=verts, faces=faces,
                        materials=[mod.Material(palette.name, 0, len(verts), 0, len(faces))])


# ---------- ready-made parts ----------
def wheel(R, W, tyre, rim, pad, n=12) -> Builder:
    """A wheel centred on its hub, axle along x, with a paw-print hubcap on BOTH faces (one
    model serves all four corners). The game scales it to the .cf tyre by its bounding box."""
    B = Builder()
    rot = (0, 0, -math.pi / 2)
    B.cyl([-W / 2, 0, 0], R, W, tyre, n=n, rot=rot)
    B.cyl([W / 2 - .005, 0, 0], R * .62, .02, rim, n=n, rot=rot)
    B.cyl([-W / 2 - .015, 0, 0], R * .62, .02, rim, n=n, rot=rot)
    for x in (W / 2 + .02, -W / 2 - .02):
        B.box([x, -R * .12, 0], [.02, R * .28, R * .34], pad, top=(1, .7))
        for z, y in ((-.32, .18), (-.12, .34), (.12, .34), (.32, .18)):
            B.box([x, y * R, z * R], [.02, R * .13, R * .13], pad)
    return B


def icosphere(subdiv):
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    nrm = lambda p: tuple(c / math.sqrt(sum(q * q for q in p)) for c in p)  # noqa: E731
    v = [nrm(p) for p in v]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
         (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
         (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    for _ in range(subdiv):
        cache, nf = {}, []

        def mid(a, b):
            k = (min(a, b), max(a, b))
            if k not in cache:
                v.append(nrm(tuple(v[a][i] + v[b][i] for i in range(3))))
                cache[k] = len(v) - 1
            return cache[k]
        for a, b, c in f:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    return v, f


def sphere(radius: float, colour_of, subdiv: int = 2) -> Builder:
    """An icosphere centred on the origin; colour_of(unit centre (x, y, z)) -> hex per face."""
    B = Builder()
    v, f = icosphere(subdiv)
    for a, b, c in f:
        pa, pb, pc = (tuple(x * radius for x in v[i]) for i in (a, b, c))
        n = cross(sub(pb, pa), sub(pc, pa))
        cen = tuple((pa[i] + pb[i] + pc[i]) / 3 / radius for i in range(3))
        if sum(n[i] * cen[i] for i in range(3)) < 0:
            pb, pc = pc, pb
        B.tri(pa, pb, pc, colour_of(cen))
    return B


def yarn_ball(radius: float) -> Builder:
    rng = random.Random(3)

    def colour(c):
        band = math.sin(9 * (c[0] * .8 + c[1] * .6)) + .6 * math.sin(7 * (c[2] - c[1] * .5))
        return "#e86a82" if rng.random() < .06 else ("#d64561" if band > -.2 else "#8e1f3a")
    return sphere(radius, colour)


def tennis_ball(radius: float) -> Builder:
    def colour(c):
        seam = abs(c[1] - .55 * math.cos(2 * math.atan2(c[2], c[0])))
        return "#f2efe8" if seam < .12 else "#d7e84a"
    return sphere(radius, colour)
