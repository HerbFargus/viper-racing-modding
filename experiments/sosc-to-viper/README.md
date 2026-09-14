# Streets of SimCity → Viper Racing

Converting cars from *Streets of SimCity* (Maxis, 1997) into loadable *Viper
Racing* cars, as a test of whether the toolkit's model and texture paths are
good enough to take geometry that was never meant for this game.

They are. Seven cars convert, load and drive. What the exercise actually
measured, though, is something more useful than "it worked": **four conventions
that neither file format declares, and that no amount of reading either format
can tell you.** Every one of them was found from a picture — a screenshot of
the car in game, or the source game's own artwork — and every one produced a
plausible-looking file that was wrong.

## What transfers

| Transfers | Does not |
|---|---|
| Vertices, faces, UVs | Handling, gearing, sounds |
| Per-face texture and colour assignment | The cockpit |
| The vehicle skin out of the texture atlas | Damage model, wheels, physics |

A `.MAX` holds a mesh and nothing else, so the conversion forks a donor Viper
car and replaces its body: the result **looks** like a Streets of SimCity car
and **drives** like whatever it was forked from.

## The four conventions

None of these is written down in either format. Each one was found by looking
at the result.

**1. Winding.** Streets of SimCity renders two-sided, so its winding is
arbitrary — 101 of the Airhawk's 520 faces disagree with their neighbours, and
every face carries identical flags (`0x2002`), so nothing in the file says
which way is out. Viper culls backfaces: a wrongly wound face is simply not
drawn, and in game that is a hole you can see the track through.

**2. `wrap=1`.** The UVs are not confined to the unit square, so a
decal-clamped texture smears at the seams instead of repeating. (See the UV
section below — this turned out to be treating a symptom.)

**3. V is measured from the other end.** Unflipped, the Airhawk's yellow roof
surround renders along the bottom bumper and its tail lights sit mid-panel.
Negated, every feature lands where the game puts it. The tell was a rear view:
from the side it looks merely *odd*, and "odd" is not a diagnosis.

**4. Z is reversed.** The two games point their cars in opposite directions
along Z. Rendered at the angle where every stock Viper car shows headlights and
a grille, an unrotated SoSC car shows its rear window and number plate — in
game, a car driving backwards. The fix negates **both** X and Z, which is a
rotation (determinant +1) and so leaves winding alone; negating Z by itself is
a mirror and undoes convention 1.

## The defects found after it "worked"

The car loaded and looked right long before it was right. Three separate
things were wrong, and two of them were found only because someone played it
and sent a screenshot.

**The winding fix was making it worse.** The first pass decided each face
independently against the mesh centroid, which is a reasonable idea and fails
exactly where a car is concave: sills, wheel arches, underbody. Replacing it
with edge propagation — breadth-first over shared edges, so each connected
shell becomes self-consistent, then one signed-volume test per shell — showed
that **five of the seven cars needed zero flips and a sixth needed one.** On
those six, nearly every flip the centroid pass made was opening a hole rather
than closing one. Only the Airhawk genuinely needed reorienting, and it needed
it wholesale: 807 flips across five shells.

**The LOD chain was still the donor's car.** `carfork` renames a car's files
but does not rebuild its meshes, so LODs 1–7 remained Viper GTS-R geometry —
the car looked right up close and morphed into a Viper in the mirror. Because
the fork renames the textures too, nothing about the *names* gives this away;
only the shape does. `vrmod modlod` regenerates the chain from the converted
body, and `check_mesh.py` now compares every LOD's bounding box and material
set against LOD 0.

**Texture names have a length limit, and nothing says so.** Of the seven cars,
`azzaroni` loaded with no texture at all — flat paint colour — while the other
six were fine. The only thing that separated it was the name: its generated
textures were `azzaronit089.tex` at **16 characters**, where the next longest
were 15. Nothing in the retail data comes close (longest shipped member
`7scraped.tex`, 12; longest shipped material `effects.tex`, 11), nothing in the
community cars does either (longest material `whel955p.tex`, 12), and the
failure is silent: the car loads, drives, and renders in flat paint. Generated
names are now held to `NAME_LIMIT = 12`, the ceiling the working corpus
observes, via a short per-car code (`azzt089.tex`) rather than the full prefix.

**Doubling the unresolvable faces was a bad trade.** Where edge propagation
cannot orient a face — 26 of them on the Airhawk, 4 on the van, 2 on the
Ferrari, none elsewhere — the first mitigation emitted the face twice, once
each way, so neither winding could be culled. Two coplanar triangles then fight
for the depth buffer. The speckled band reported along the Airhawk's flank
appeared on the one car with a meaningful number of twins, and the measurement
agrees: doubling took the Airhawk from **5 inconsistent edges of 609 (0.8%,
inside the stock band) to 10 of 616 (1.6%)**, because a twin pair makes new
conflicts with its neighbours. It is off by default; `double=True` keeps it.

**The UVs were outside the unit square.** This was the see-through patch along
the flank, and it is the one worth remembering. The raw conversion put the
Airhawk's v at 1.0–2.0 and the police car's at 1.0–3.0 — the same texel as
0.0–1.0 for any sampler that wraps. Every renderer used to check the work wraps
unconditionally, **including this project's own**, so the car rendered clean in
every tool while the game showed a hole.

The oracle that settled it was the shipped cars: surveyed across `viper.car`,
`sedan.car`, `exotic.car`, `4x4cos.car` and `sports.car`, **not one vertex sits
outside the unit square** (exotic has a single vertex a hundredth over, from
rounding). Whatever the engine does with out-of-range UVs, Monster Games never
asked it to. `unit_uvs()` now shifts each face back as a unit — per face, not
per vertex, or a face straddling the boundary tears — and squeezes the handful
that span more than a full repeat. All seven cars now match stock exactly.

The black-as-colour-key theory that this replaced was tested and is wrong:
stock opaque textures carry 0x0000 pixels freely (`Sedan.tex` 9.3%,
`Exotic.tex` 8.9%) and those cars render solid.

## Files

| | |
|---|---|
| `max2obj.py` | `.MAX` → OBJ. Written against [CahootsMalone's format notes](https://github.com/CahootsMalone/maxis-mesh-stuff) |
| `build_car.py` | One vehicle → one `.car`: fit, wind, normalise UVs, build textures, fork the donor |
| `build_fleet.py` | All seven, plus `modlod` and a count assertion |
| `check_mesh.py` | Winding, orientation, UV range and LOD chain, calibrated on the shipped cars |
| `check_formats.py` | The two format walks, each required to end exactly where the file says |

## Reproducing

Neither game's files are in this repository. You need a Streets of SimCity
install extracted to a directory holding `GEO/SIM3D2.MAX` and `BMP/SIM3D.BMP`,
and a Viper Racing install to fork donor cars from.

```
python experiments/sosc-to-viper/check_formats.py <sosc_dir>
python experiments/sosc-to-viper/build_fleet.py <sosc_dir> <viper_install> <out_dir>
python experiments/sosc-to-viper/check_mesh.py <viper_install> <out_dir>/*/*.car
```

`check_formats.py` passes 11/11 against the retail data: all 531 models across
the three `.MAX` files read exactly the face count their table declares, and
the atlas walk lands exactly on the file size.

`check_mesh.py` passes 28/28. It did not always: with face doubling on, the
Airhawk failed at 10 inconsistent edges of 616, and that failure is what
identified doubling as the wrong mitigation rather than something to widen the
threshold around. Without it the Airhawk sits at 5 of 609 (0.8%), inside the
band the shipped cars occupy.

## Known residuals

- The Airhawk keeps 5 inconsistent edges of 609 that the source mesh cannot
  resolve. That is inside the stock band, but they are real.
- 96 faces each on the van and the police car span slightly more than one
  texture repeat (1.01) and are squeezed by 1% to fit the unit square.
- Damaged variants (`STREETS_D*` in `SIM3D3.MAX`) are not wired into Viper's
  damage model.
- The tracks are untouched. These are semi-open-world maps with no racing
  line, so a converted track needs a driving path invented for it.
