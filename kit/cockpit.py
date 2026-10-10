"""3D cockpits: the car's own body seen from the driver's seat, with generated gauges, a name
plate, a turning 3D steering wheel and a needle. The jeeps' recipe (CONFIRMED in game,
2026-09-23), with the generators moved from their cockpit/parts.py.

A cockpit is five members: <prefix>c.mod (the shell + dash), <prefix>w.mod (the wheel, in its
own frame: rim in x-y, driver on -z), Needle.mod, cockpit.tab (positions, from Val's), and one
256 px colorkey atlas (dials, plate, swatches) with its own 8.3 name.

RULES the game imposes, both learned the hard way:
  * c.mod is drawn in the CAR's frame and skipped unless the car's centre is ahead of the eye:
    the cockpit.tab camera z must be <= ~0.07 (race.exe 0x44f290). build() refuses otherwise.
  * The game culls back faces: every shell triangle is wound toward the eye, with normals that
    agree with the winding.
  * Needle angles: 0 is straight up, + runs clockwise as the driver sees it; the dials sweep
    -135..+135. The in-game view is 16:9, about 54 degrees vertical.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import kit
from kit.shapes import Builder, Palette
from vrmod import archive, cockpit_tab, envelope, mod, tex

FONT = r"C:\Windows\Fonts\bahnschrift.ttf"
SWEEP = (-135.0, 135.0)
SWATCH = {"needle": 0, "rim": 1, "spoke": 2, "bezel": 3, "hub": 4, "pod": 5}
MPH = 0.44704


# ---------------------------------------------------------------- the atlas
def _font(size, style="Bold"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(style)
    except Exception:
        pass
    return f


def swatch_uv(name):
    k = SWATCH[name]
    return ((k * 32 + 16) / 256, (192 + 16) / 256)


def _pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def dial(size, *, top, major, minor, labels, red_from, face, ink, red, caption, sub=None):
    S = size * 4
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = S / 2
    d.ellipse([2, 2, S - 3, S - 3], fill=face + (255,))
    a0, a1 = SWEEP
    if red_from is not None:
        for k in range(200):
            f = red_from + (1 - red_from) * k / 199
            x, y = _pt(c, c, S * 0.43, a0 + (a1 - a0) * f)
            d.ellipse([x - S * 0.022, y - S * 0.022, x + S * 0.022, y + S * 0.022], fill=red + (255,))
    for k in range(minor + 1):
        f = k / minor
        ang = a0 + (a1 - a0) * f
        is_major = (k * major) % minor == 0
        r0 = S * (0.34 if is_major else 0.39)
        w = S * (0.022 if is_major else 0.011)
        col = red if (red_from is not None and f > red_from + 1e-6) else ink
        x0, y0 = _pt(c, c, r0, ang)
        x1, y1 = _pt(c, c, S * 0.455, ang)
        d.line([x0, y0, x1, y1], fill=col + (255,), width=max(2, int(w)))
    fnt = _font(int(S * 0.13))
    for k, lab in enumerate(labels):
        if lab is None:
            continue
        f = k / major
        x, y = _pt(c, c, S * 0.25, a0 + (a1 - a0) * f)
        col = red if (red_from is not None and f > red_from + 1e-6) else ink
        d.text((x, y), lab, font=fnt, fill=col + (255,), anchor="mm")
    d.text((c, c + S * 0.2), caption, font=_font(int(S * 0.085)), fill=ink + (255,), anchor="mm")
    if sub:
        d.text((c, c + S * 0.3), sub, font=_font(int(S * 0.06), "Regular"), fill=ink + (255,), anchor="mm")
    d.text((c, c - S * 0.2), top, font=_font(int(S * 0.07)), fill=ink + (255,), anchor="mm")
    return im.resize((size, size), Image.LANCZOS)


def atlas(*, tach, speedo, plate_text, plate_bg, plate_ink, swatches, plate_font="Bold Condensed"):
    """(0,0) tach, (128,0) speedo, (0,128) plate, row 192 swatches; colorkey outside the dials."""
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    im.paste(dial(128, **tach), (0, 0))
    im.paste(dial(128, **speedo), (128, 0))
    p = Image.new("RGBA", (1024, 192), plate_bg + (255,))
    d = ImageDraw.Draw(p)
    d.rectangle([6, 6, 1017, 185], outline=plate_ink + (255,), width=8)
    for x in (40, 984):
        d.ellipse([x - 14, 82, x + 14, 110], fill=plate_ink + (255,))
    d.text((512, 98), plate_text, font=_font(128, plate_font), fill=plate_ink + (255,), anchor="mm")
    im.paste(p.resize((256, 48), Image.LANCZOS), (0, 128))
    d = ImageDraw.Draw(im)
    for name, rgb in swatches.items():
        k = SWATCH[name]
        d.rectangle([k * 32, 192, k * 32 + 31, 223], fill=rgb + (255,))
    a = np.array(im)
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    rgb = a[..., :3]
    rgb[(a[..., 3] > 0) & (rgb.max(axis=2) < 16)] = 16           # never the colour key
    return Image.fromarray(a, "RGBA")


# ---------------------------------------------------------------- textured parts
class Parts:
    """Triangles on the atlas, game frame. face=: a point the triangle must be seen from;
    out=: the direction it must face. Normals follow the winding."""

    def __init__(self):
        self.v, self.f = [], []

    def _vert(self, p, uv, n):
        self.v.append(mod.Vertex(float(p[0]), float(p[1]), float(p[2]), *map(float, n), float(uv[0]), float(uv[1])))
        return len(self.v) - 1

    def tri(self, a, b, c, uva, uvb, uvc, face=None, out=None):
        a, b, c = map(np.asarray, (a, b, c))
        g = np.cross(b - a, c - a)
        want = (np.asarray(face) - (a + b + c) / 3) if face is not None else np.asarray(out)
        if np.dot(g, want) < 0:
            b, c, uvb, uvc = c, b, uvc, uvb
            g = -g
        n = g / (np.linalg.norm(g) + 1e-12)
        self.f.append((self._vert(a, uva, n), self._vert(b, uvb, n), self._vert(c, uvc, n)))

    def quad(self, a, b, c, d, uvs, **kw):
        self.tri(a, b, c, uvs[0], uvs[1], uvs[2], **kw)
        self.tri(a, c, d, uvs[0], uvs[2], uvs[3], **kw)

    def mesh(self, material):
        return mod.Mesh(vertices=self.v, faces=self.f,
                        materials=[mod.Material(material, 0, len(self.v), 0, len(self.f))])


def gauge(b, centre, radius, eye, cell, depth=0.03, segs=20):
    """A dial facing -z (toward the driver) with a bezel and a short pod behind it."""
    cx, cy, cz = centre
    u0, v0 = cell
    uv = lambda x, y: (u0 + (0.5 + 0.5 * x) * 0.5, v0 + (0.5 - 0.5 * y) * 0.5)  # noqa: E731
    rim = radius * 1.12
    for k in range(segs):
        t0, t1 = 2 * math.pi * k / segs, 2 * math.pi * (k + 1) / segs
        p0 = (cx + radius * math.cos(t0), cy + radius * math.sin(t0), cz)
        p1 = (cx + radius * math.cos(t1), cy + radius * math.sin(t1), cz)
        b.tri(centre, p0, p1, uv(0, 0), uv(math.cos(t0), math.sin(t0)), uv(math.cos(t1), math.sin(t1)), face=eye)
    bz, pod = swatch_uv("bezel"), swatch_uv("pod")
    for k in range(segs):
        t0, t1 = 2 * math.pi * k / segs, 2 * math.pi * (k + 1) / segs
        c0, s0, c1, s1 = math.cos(t0), math.sin(t0), math.cos(t1), math.sin(t1)
        zf = cz - 0.006
        b.quad((cx + radius * c0, cy + radius * s0, zf), (cx + rim * c0, cy + rim * s0, zf),
               (cx + rim * c1, cy + rim * s1, zf), (cx + radius * c1, cy + radius * s1, zf), [bz] * 4, face=eye)
        b.quad((cx + radius * c0, cy + radius * s0, zf), (cx + radius * c1, cy + radius * s1, zf),
               (cx + radius * c1, cy + radius * s1, cz), (cx + radius * c0, cy + radius * s0, cz), [bz] * 4, face=eye)
        b.quad((cx + rim * c0, cy + rim * s0, zf), (cx + rim * c1, cy + rim * s1, zf),
               (cx + rim * c1, cy + rim * s1, cz + depth), (cx + rim * c0, cy + rim * s0, cz + depth), [pod] * 4,
               out=(c0 + c1, s0 + s1, 0))


def plate(b, centre, width, eye):
    cx, cy, cz = centre
    h = width * 48 / 256
    u0, u1, v0, v1 = 2 / 256, 254 / 256, 130 / 256, 174 / 256
    b.quad((cx - width / 2, cy + h / 2, cz), (cx + width / 2, cy + h / 2, cz),
           (cx + width / 2, cy - h / 2, cz), (cx - width / 2, cy - h / 2, cz),
           [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], face=eye)


def steering_wheel(material, *, R=0.19, r=0.016, segs=24, sides=6):
    b = Parts()
    rim, spoke, hub = swatch_uv("rim"), swatch_uv("spoke"), swatch_uv("hub")
    ring = lambda t, s: np.array([(R + r * math.cos(s)) * math.cos(t), (R + r * math.cos(s)) * math.sin(t), r * math.sin(s)])  # noqa: E731
    for i in range(segs):
        t0, t1 = 2 * math.pi * i / segs, 2 * math.pi * (i + 1) / segs
        for j in range(sides):
            s0, s1 = 2 * math.pi * j / sides, 2 * math.pi * (j + 1) / sides
            a, bb, c, d = ring(t0, s0), ring(t1, s0), ring(t1, s1), ring(t0, s1)
            tm, sm = (t0 + t1) / 2, (s0 + s1) / 2
            out = ring(tm, sm) - np.array([R * math.cos(tm), R * math.sin(tm), 0])
            b.quad(a, bb, c, d, [rim] * 4, out=out)

    def box(p0, p1, w, t, uvc, z0=0.0):
        p0, p1 = np.array(p0, float), np.array(p1, float)
        ax = p1 - p0; ax /= np.linalg.norm(ax)
        side = np.cross(ax, [0, 0, 1.0]); side /= np.linalg.norm(side)
        up = np.array([0, 0, 1.0])
        corners = lambda p: [p + side * w / 2 + up * (z0 + t / 2), p - side * w / 2 + up * (z0 + t / 2),  # noqa: E731
                             p - side * w / 2 + up * (z0 - t / 2), p + side * w / 2 + up * (z0 - t / 2)]
        A, B = corners(p0), corners(p1)
        mid = (p0 + p1) / 2 + up * z0
        for k in range(4):
            q = [A[k], A[(k + 1) % 4], B[(k + 1) % 4], B[k]]
            b.quad(*q, [uvc] * 4, out=(sum(q) / 4) - mid)
    for deg in (180, 0, 270):
        t = math.radians(deg)
        box((0.03 * math.cos(t), 0.03 * math.sin(t), 0), ((R - r * 0.5) * math.cos(t), (R - r * 0.5) * math.sin(t), 0),
            0.028, 0.008, spoke, z0=-0.004)
    hr, hz, n = 0.042, 0.03, 12
    for k in range(n):
        t0, t1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        p = lambda t, z: np.array([hr * math.cos(t), hr * math.sin(t), z])  # noqa: E731
        b.quad(p(t0, 0.01), p(t1, 0.01), p(t1, -hz), p(t0, -hz), [hub] * 4,
               out=(math.cos((t0 + t1) / 2), math.sin((t0 + t1) / 2), 0))
        b.tri((0, 0, -hz), p(t0, -hz), p(t1, -hz), hub, hub, hub, out=(0, 0, -1))
    return b.mesh(material)


def needle(material, length=0.05, tail=0.012, half=0.0035):
    b = Parts()
    uv = swatch_uv("needle")
    pts = [(-half, -tail, 0), (half, -tail, 0), (0, length, 0)]
    b.tri(*pts, uv, uv, uv, out=(0, 0, -1))
    b.tri(*pts, uv, uv, uv, out=(0, 0, 1))
    return b.mesh(material)


# ---------------------------------------------------------------- the shell
def toward(builder: Builder, eye) -> Builder:
    """Every triangle rewound to face the eye (the game draws one side only)."""
    e = np.asarray(eye, float)
    out = Builder()
    for a, b, c, col in builder.tris:
        A, B, C = (np.asarray(p, float) for p in (a, b, c))
        n = np.cross(B - A, C - A)
        out.tri(a, *((b, c) if np.dot(n, e - (A + B + C) / 3) >= 0 else (c, b)), col)
    return out


def select(builder: Builder, keep) -> Builder:
    """The triangles for which keep(centroid (3,), colour) is true."""
    out = Builder()
    for a, b, c, col in builder.tris:
        cen = tuple((a[k] + b[k] + c[k]) / 3 for k in range(3))
        if keep(cen, col):
            out.tri(a, b, c, col)
    return out


def _merge(meshes):
    verts, faces, mats = [], [], []
    for m in meshes:
        base, f0 = len(verts), len(faces)
        verts += m.vertices
        faces += [(a + base, b + base, c + base) for a, b, c in m.faces]
        for mt in m.materials:
            mats.append(mod.Material(mt.name, mt.vertex_start + base, mt.vertex_end + base,
                                     mt.face_start + f0, mt.face_end + f0))
    return mod.Mesh(vertices=verts, materials=mats, faces=faces)


def build(*, shell: Builder, palette: Palette, eye, wheel, wheel_R, gauges, gauge_r, plate_at, plate_w,
          atlas_name, art, rpm_max, rpm_red, mph_max, inside: Builder | None = None, val=kit.VAL_CAR) -> dict:
    """The five cockpit members as {name: standalone bytes}, except the palette (the caller
    encodes it once every mesh is built). gauges = {"rpm": (x, y, z), "mph": (x, y, z)}: the dial
    centres, already in front of the dash.

    shell:  what the driver sees from OUTSIDE it (the hood ahead, dash boxes): kept with its own
            outward winding, so faces where two solids touch stay back-facing and hidden.
    inside: what the driver sits INSIDE (a cab's walls and ceiling): rewound toward the eye.
            Keep it small -- rewinding a face that touches another solid makes both surfaces draw
            in one plane, which z-fights (flickers) in game (the Doghouse's roof, 2026-10-10)."""
    if eye[2] > 0.07:
        raise ValueError(f"eye z {eye[2]} > 0.07: the car's centre must be ahead of the eye, or the game "
                         f"never draws c.mod")
    if len(atlas_name) > 12 or "_" in atlas_name:
        raise ValueError(f"{atlas_name!r} is not an 8.3 texture name")
    b = Parts()
    pivots = {}
    for which, cell in (("rpm", (0.0, 0.0)), ("mph", (0.5, 0.0))):
        x, y, z = gauges[which]
        gauge(b, (x, y, z), gauge_r, eye, cell)
        pivots[which] = (x, y, z - 0.004)
    plate(b, plate_at, plate_w, eye)
    seen = Builder().extend(shell).extend(toward(inside, eye) if inside is not None else Builder())
    cmod = _merge([seen.mesh(palette), b.mesh(atlas_name)])
    rk = rpm_max // 1000
    step = 2 if rk > 6 else 1
    tach = dict(top="RPM", caption="x1000", sub=None, major=rk, minor=rk * 2,
                labels=[str(k) if k % step == 0 else None for k in range(rk + 1)],
                red_from=rpm_red / rpm_max, face=art["face"], ink=art["ink"], red=art["red"])
    speedo = dict(top="MPH", caption=art["plate_text"].split()[0], sub=None, major=mph_max // 20,
                  minor=mph_max // 10, labels=[str(k * 20) if (k * 20) % 40 == 0 else None
                                               for k in range(mph_max // 20 + 1)],
                  red_from=None, face=art["face"], ink=art["ink"], red=art["red"])
    img = atlas(tach=tach, speedo=speedo, plate_text=art["plate_text"], plate_bg=art["plate_bg"],
                plate_ink=art["plate_ink"], swatches=art["swatches"])
    records = {"camera": tuple(eye), "wheel": tuple(wheel), "rpm pt": pivots["rpm"], "mph pt": pivots["mph"],
               "rpm dat": (SWEEP[0], SWEEP[1], float(rpm_max)),
               "mph dat": (SWEEP[0], SWEEP[1], round(mph_max * MPH, 3))}
    ve = {e.name.lower(): e for e in archive.read(val)}["cockpit.tab"]
    tab = cockpit_tab.build(envelope.build(ve.tag, ve.version, ve.payload),
                            {k: tuple(round(float(x), 3) for x in v) for k, v in records.items()})
    return {"c.mod": mod.build(cmod), "w.mod": mod.build(steering_wheel(atlas_name, R=wheel_R)),
            "Needle.mod": mod.build(needle(atlas_name)), "cockpit.tab": tab,
            atlas_name: tex.encode_to_tex(np.array(img).tobytes(), 256, mode="colorkey", wrap=1),
            "_atlas_img": img, "_records": records, "_shell": seen}


# ---------------------------------------------------------------- a look from the seat
def snapshot(png, eye, scene: Builder, *, extra=(), size=(800, 450), vfov=54.0, look=(0.0, 0.0, 1.0)):
    """A flat-shaded painter's render from the eye, culling back faces the way the game does.
    scene: Builder triangles (hex colours); extra: [(Builder, offset)] e.g. the steering wheel's
    stand-in. Good enough to judge what the driver sees before trying it in game."""
    W, H = size
    f = (H / 2) / math.tan(math.radians(vfov) / 2)
    e = np.asarray(eye, float)
    fwd = np.asarray(look, float); fwd /= np.linalg.norm(fwd)
    right = np.cross([0, 1.0, 0], fwd); right /= np.linalg.norm(right)
    up = np.cross(fwd, right)
    sun = np.array([0.3, 0.8, 0.5]); sun /= np.linalg.norm(sun)
    polys = []
    tris = list(scene.tris)
    for bld, off in extra:
        tris += [(tuple(np.add(a, off)), tuple(np.add(b, off)), tuple(np.add(c, off)), col) for a, b, c, col in bld.tris]
    for a, b, c, col in tris:
        P = np.array([a, b, c], float)
        n = np.cross(P[1] - P[0], P[2] - P[0])
        if np.dot(n, e - P.mean(0)) <= 0:
            continue                                            # back face: the game won't draw it
        rel = P - e
        cam = np.stack([rel @ right, rel @ up, rel @ fwd], axis=1)
        poly, near = [], 0.02                                   # clip at the near plane, as the game does
        for i in range(3):
            a, b = cam[i], cam[(i + 1) % 3]
            if a[2] >= near:
                poly.append(a)
            if (a[2] >= near) != (b[2] >= near):
                t = (near - a[2]) / (b[2] - a[2])
                poly.append(a + (b - a) * t)
        if len(poly) < 3:
            continue
        z = np.array([q[2] for q in poly])
        pts = [(W / 2 + f * q[0] / q[2], H / 2 - f * q[1] / q[2]) for q in poly]
        shade = 0.55 + 0.45 * abs(np.dot(n / (np.linalg.norm(n) + 1e-12), sun))
        rgb = tuple(int(int(col[k:k + 2], 16) * shade) for k in (1, 3, 5))
        polys.append((z.mean(), pts, rgb))
    im = Image.new("RGB", (W, H), (150, 190, 230))
    d = ImageDraw.Draw(im)
    for _z, pts, rgb in sorted(polys, key=lambda p: -p[0]):
        d.polygon(pts, fill=rgb)
    im.save(png)
