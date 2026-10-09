# Baked lighting

**Question:** can a car made of flat palette colours get believable shading in an engine that only draws
textured, unlit-looking triangles, without adding geometry?

**Answer:** yes. Bake ambient occlusion and a key light into a texture atlas: every face keeps its
vertices, and only its UVs and texture change. The Willys jeep (2026-10-09) is the worked case: the
baked body, cockpit and wheels are all confirmed in game.

## The scripts

| script | does | writes |
|---|---|---|
| `bake_light.py <in.car> <out.car> [px/m=40]` | the body, `<prefix>0.mod` | `wjlt0.tex` … and the baked body into all 8 LOD slots |
| `bake_cockpit.py <in.car> <out.car> [px/m=80]` | the cockpit `<prefix>c.mod`: palette faces only, the dash (gauges) kept as it is | `wjck0.tex` … |
| `bake_wheels.py <in.car> <out.car> [px/m=120]` | `wheel_1-3` / `fwheel_1-3`, which must be one identical mesh | `wjwh0.tex` |
| `toon.py <in.car> <out.car>` | an earlier try: an inked cartoon outline (inverted hull) plus inner lines | `wjink.tex` |

`bake_light.py` and `toon.py` both find each face's colour by sampling its texture at the UV centroid
(`toon.face_colours`), so they assume a palette texture: one flat colour per face.

How it works (`bake_light.bake`):
- **Charts.** Faces are grouped into charts: edge-connected, the same colour, normals within 35° of the
  seed face.
- **Packing.** Each chart is projected flat and shelf-packed onto 256 × 256 pages.
- **Painting.** Each face is painted `colour × (0.35 + 0.65 × ao) × (0.78 + 0.32 × max(0, n · key))`.
- **Occlusion.** `ao` is the open fraction of a cosine-weighted hemisphere: 32 rays per welded vertex,
  hits counted within 0.6 m, interpolated across the face.

## The recipe that worked

Order matters: **lighten, then bake, then build LODs.**

1. **Lighten the body for the stock engine.** Decimate the palette body to about 3,600 vertices
   (`vrmod.mod.decimate`). Race load costs LOD 0 × (LODs 1-4) per copy of the car (viper-mod-manager's
   runtime.md, section 13), and baking adds vertices: chart edges split points, so the jeep's 3,598 became
   4,261.
2. **Bake the body:** `bake_light.py`.
3. **Build the LODs from the baked body:** `vrmod modlod`. It drops whole parts per level, which atlas
   seams can't block, so the levels still shrink: 4,261 / 3,627 / 3,506 / 3,330 / 2,193 …, about 0.17 s
   of load per copy.
4. **Bake the cockpit and the wheels:** `bake_cockpit.py` (50 px/m fits the jeep on 4 pages) and
   `bake_wheels.py` (90 px/m fits one page). Then `vrmod modlod` again for the far wheel models.

Baking first and decimating after doesn't work. Hundreds of charts on 4 pages put most points on a
material boundary or a UV seam, which decimation won't tear. The 11,040-vertex baked body stalled at
5,762 vertices per LOD and hung race loading for 7 s with 8 of them.

## What was established

- **Wheels get occlusion only.** A wheel spins, so a baked key light would turn with it. `bake_wheels.py`
  uses a flat light level equal to the key light's average over all directions (0.78 + 0.32 / 4), so the
  wheels match the body.
- **The cockpit is lit by the body too.** Its occlusion rays hit the body's LOD 0 as well as the cockpit,
  so the windscreen frame and body sides shade the interior. Mean openness is 0.26 (0.31 against the
  cockpit alone), against the body's 0.54. An open cabin really is that much shadier.
- **Texture rules.** Atlas pages follow the engine's rules (viper-mod-manager memory, file-formats.md):
  8.3 names, at most 256 px, a `.tex` material suffix, and no pure-black texels (the colour key), which
  is why `bake_light` clips to 1.
- **Cost.** The jeep carries 12 textures this way (4 body + 4 cockpit + 1 wheel + the dash and two others).
- **Reproducible.** The scripts are deterministic (fixed ray seed): rerunning on the same input gives
  byte-identical output.
