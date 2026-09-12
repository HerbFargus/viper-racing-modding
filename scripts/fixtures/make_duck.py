"""Generates a very rough placeholder duck OBJ -- three overlapping primitives
(body, head, beak), enough to visually read as "a duck" and prove the Parts-
drawer OBJ-import/commit pipeline round-trips correctly. Not sculpted art."""
import math

verts = []
faces = []  # each face: list of 1-based vertex indices into `verts`


def add_uv_sphere(cx, cy, cz, rx, ry, rz, lat_steps=8, lon_steps=12):
    start = len(verts) + 1
    for i in range(lat_steps + 1):
        theta = math.pi * i / lat_steps  # 0..pi
        for j in range(lon_steps):
            phi = 2 * math.pi * j / lon_steps
            x = cx + rx * math.sin(theta) * math.cos(phi)
            y = cy + ry * math.cos(theta)
            z = cz + rz * math.sin(theta) * math.sin(phi)
            verts.append((x, y, z))
    for i in range(lat_steps):
        for j in range(lon_steps):
            a = start + i * lon_steps + j
            b = start + i * lon_steps + (j + 1) % lon_steps
            c = start + (i + 1) * lon_steps + j
            d = start + (i + 1) * lon_steps + (j + 1) % lon_steps
            if i != 0:
                faces.append((a, b, c))
            if i != lat_steps - 1:
                faces.append((b, d, c))


# Body: a squashed sphere sitting on the "ground" (y=0 is the ball's own pivot,
# matching how ball.mod's own origin -- the horn ball's rotation pivot -- works).
add_uv_sphere(0, 0, 0, 0.22, 0.18, 0.22, lat_steps=8, lon_steps=12)
# Head: smaller sphere, offset up and to one side (front)
add_uv_sphere(0, 0.22, 0.16, 0.11, 0.11, 0.11, lat_steps=6, lon_steps=10)
# Beak: a simple flattened pyramid poking out from the head
bx, by, bz = 0, 0.22, 0.16
beak_base = len(verts) + 1
verts += [
    (bx - 0.05, by + 0.02, bz + 0.08),
    (bx + 0.05, by + 0.02, bz + 0.08),
    (bx + 0.05, by - 0.03, bz + 0.08),
    (bx - 0.05, by - 0.03, bz + 0.08),
]
tip = len(verts) + 1
verts.append((bx, by - 0.01, bz + 0.16))
faces += [
    (beak_base, beak_base + 1, tip),
    (beak_base + 1, beak_base + 2, tip),
    (beak_base + 2, beak_base + 3, tip),
    (beak_base + 3, beak_base, tip),
]

lines = ["# placeholder duck -- generated for a vrmod workflow test, not sculpted art"]
for x, y, z in verts:
    lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
lines.append("usemtl duck")
for f in faces:
    lines.append("f " + " ".join(str(i) for i in f))

with open("duck.obj", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print(f"wrote duck.obj: {len(verts)} vertices, {len(faces)} faces")
