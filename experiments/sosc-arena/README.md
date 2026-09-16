# Streets of SimCity arena → Viper Racing track

Rebuilding a *Streets of SimCity* scenario city as a textured 3D model, at true
scale and in the game's own art, as the first half of turning it into a *Viper
Racing* track. The target is the **Continuous Fire** scenario ("Arena Death
Match"), which loads `Cities/Arena.sc2`.

**Status: it loads, drives and laps in Viper Racing.** Phase 1, the preview,
matches the game in screenshots taken side by side: roads, floor panels, the
diagonal edges, the berm and islands, the sand and grass pattern, the dark
grass patches, the towers and the cows. Phase 2, the track, is confirmed in
game (2026-09-15) -- see "The track" below for what is still open.

## Running it

```
python arena.py <sosc_dir> <city.sc2> <out_dir>
```

`<sosc_dir>` is your own Streets of SimCity install (the folder holding `GEO/`
and `BMP/`). The script writes `arena.obj`, `arena.mtl`, the textures it pulled
out of your install, and a copy of `view.html` into `<out_dir>`. Serve that
folder (for example `python -m http.server --directory <out_dir>`) and open
`view.html`: drag to orbit, right-drag to pan, keys 1–4 for preset views.

Nothing in this directory contains game data, and the output folder should
never be committed — it is full of it.

| File | Does |
|---|---|
| `sc2.py` | Reads a SimCity 2000 `.sc2` city: altitude, water, terrain slopes, buildings, zones |
| `arena.py` | Builds the city as an OBJ from the `.sc2` and the SoSC install |
| `view.html` | A three.js viewer for the result, lit so flat ground shows its texture's true colour |
| `route.py` | The lap: the perimeter ring as a route line, with the timing gates and the starting grid |
| `arena_track.py` | The city plus the route, assembled into a loadable `.trk` |

## The track

```
python route.py       <sosc_dir> <city.sc2> <out_dir>          # the lap, and a map of it
python arena_track.py <sosc_dir> <city.sc2> <work_dir> <donor.trk> <out.trk>
```

`donor.trk` is a stock track, which supplies the configuration, the sky and the
cameras. Installing means copying the result over one of the eight stock track
slots **and emptying `drivers.res`** -- the stock file bakes an AI line per
track, so on an add-on the AI drives the old track's line and can crash the
game (`vrmod`'s `doctor.empty_drivers_res` writes the empty archive and keeps a
backup).

**The lap** (the user's decisions): clockwise round the perimeter ring, 2,930 m,
733 stations every 4 m. Start/finish mid-side on the north side, at the far end
of the 32 m flat at the bottom of that side's dip; the grid's eight slots sit on
that flat in rows 8 m apart, which is tighter than trackgen's default 10 m
because the flat is short. Gates at the start and just past each corner, five in
all: a gate AT a dip would sit on the ramp junction, where a car coming up from
the arena floor may or may not cross it, while a gate past a corner cannot be
reached without driving that corner -- so a shortcut across the floor always
misses one. No barriers; the floor is drivable.

**What the toolkit does, and what this had to do itself.** `trackgen` and
`trackbuild` write every member natively -- no MKWORLD, no `nhmkworld`. Three
things did not fit a city:

- **Its own textures.** `trackbuild.assemble` maps every material onto a member
  of the DONOR archive, which is right for a generated track and wrong here.
  Each texture is handed a donor stand-in to satisfy that map, and its payload
  replaced afterwards with SoSC's own art.
- **Its own `.sol`.** `assemble` builds barrier boxes at one height for the
  whole track. A 1.9 m cow and a 43.75 m tower cannot share that.
- **Its own gates and grid**, per the lap above.

### What broke, and what each one taught

Every one of these looked fine in the preview and failed in the game.

**A render chunk is not a `.mod` object.** The 5,000-vertex ceiling everyone
quotes is per `.mod`; a `.grf` render chunk's limit is far lower. No chunk in
any shipped track exceeds 864 vertex records (nfield's biggest is 148, every
track's median is 4). The first build ran to 3,492 and the game died with an
access violation while loading. Chunks are now split until each is under 480,
whatever that does to the count -- 556 chunks is well inside stock range.

**`mod.read_obj` mirrors Z.** It is the inverse of `to_obj`, for round-tripping
a `.mod` through a modeller. `arena.py` writes world coordinates directly, so
that mirror put the city at negative Z while the route, gates and grid stayed
positive: in game the car spawned 1,300 m away, fell through empty sky at 0 mph,
and the world rendered as nothing. `read_arena_obj()` negates Z back and swaps
the winding with it, since a mirror turns every face inside out.

**Viper culls backfaces, and the preview hid it.** `arena.py` emits its tile
quads in the order whose normal points DOWN, and `view.html` draws double-sided,
so the ground looked right in every preview and was invisible in game. Measured
against the shipped tracks, ground faces there are up (bemidji 1,055 up against
3 down). All 14,396 ground faces are now turned; the props keep SoSC's own
winding, which is arbitrary in a game that renders two-sided.

**Naming cannot tell a prop from the ground.** Classifying by texture name put
the towers' own geometry in the collision tree -- 8,374 fragments where a tower
body at 97 m sat above the berm at 55 m -- and the fix for that nearly dropped
the dark grass patch (`p5c52`) as a prop, which would have left holes in the
ground. `arena.py` now records which materials its models, trees and cows use,
and that is what decides.

**The colour-key trap, again.** A texel whose colour quantises to raw `0x0000`
sits on the reserved transparency marker, and drivers honour it in opaque
textures too: the cows' black markings rendered as holes. The finished archive
goes through `dekey.sweep_bytes`, which lifted 11,431 texels in the cow hide
and 476 in `p136`, and leaves colorkey and alpha textures alone.

**Collision volumes have to be measured, not guessed.** The first tower box was
6 m square and 18 m tall against a tower that is 14.58 m square and 43.75 m
tall, so a car clipped its corners and drove through everything above 18 m.

**Not our bug:** `lost surface on flip` / `DDERR_WRONGMODE` /
`EXCEPTION_ACCESS_VIOLATION in end_deferred_surfs` is the 1998 DirectDraw
renderer losing its surfaces when the display mode changes. Alt-tabbing does
that, on this track and any other.

### Scale, checked three ways

The arena is at true SoSC scale, and the question came up because the towers
loom in Viper's chase camera. Viper's world units are metres: its stock car
measures 1.81 x 4.43 x 1.10 m against a real Viper GTS's 1.92 x 4.45 x 1.17.
SoSC's units are confirmed by its own furniture -- a trash can 0.92 m, a phone
booth 1.50 m, a one-tile lot exactly 16.00 m. The cow model is
1.85 x 2.74 x 1.92 m and every one of the 200 instances in the built world
measures the same (their footprints differ only because each is turned at a
random angle). The towers really are 43.75 m tall, 48 m apart, beside a 16 m
road. What differs between the two games is the camera, not the world.

### Knockable cows

40 of the cows -- the ones nearest the racing line -- are `obj obstacle` records
rather than `.sol` tubes, and a car can shove them around. See the format
reference for the record itself; what matters here:

- **A tube and an obstacle at the same spot cancel out.** The tube stops the car
  before the obstacle registers, so a knockable cow must NOT also have one. The
  other 160 keep their tubes and stay solid.
- **`obj obstacle` builds a `Ball`** -- a free rigid body that drops under
  gravity, the horn ball's own machinery. It is the right mechanism for
  something that should tumble away and the wrong one for something rooted in
  the ground, which is why every knockable object the game ships is a sign or a
  chevron panel held by a `wobble` instead.
- **The shape word matters, and only a drive shows it.** With `ball` a hit cow
  keeps rolling away across the arena; with `prism` it topples and settles where
  it fell, which is what a cow should do. Same record, same mesh, one word --
  `prism` is the default for that reason alone.
- **The object budget is real.** `number of objects` runs 218-275 on the stock
  tracks, was 207 with four obstacles here and 253 with fifty, and the engine
  panics with `Too many objects allocated--increase MAX_OBJECTS`. 40 is a
  deliberately conservative first number; the log's own count is how to find the
  ceiling.
- **The mesh is resolved by name** from the track's own archive: `cow.mod`, one
  cow centred on its origin, tag `FNIM` version 1.

### Open

- The props keep SoSC's arbitrary winding, so some tower and tree faces are
  see-through.
- The minimap and the cameras are the donor's, not this track's.
- The off-track corridor is 16 m (the road's full width) and untested against a
  car that drives out onto the arena floor deliberately.
- **Anchored knock-over objects** (`obj wobble`) would suit a cow better than a
  rolling ball does, and the record's binding to its `.sol` tube is now known --
  but its MODEL has to be declared in the `.grf` scene graph, which is not
  decoded. See the format reference.
- How many of the 200 cows can be knockable before the object pool runs out.

## What was established

All of it was found by comparing a render with an in-game screenshot. Most of
it was wrong at least once first.

**Scale.** A SimCity 2000 tile is 16 m, and SoSC meshes use 262,144 units per
metre (the one-tile building lot measures exactly 16.00 m). One terrain level
is 7.9167 m, measured from a rail model, not guessed.

**The `.sc2` axes are transposed.** Stream position *n* is tile
`x = n // 128, y = n % 128`. Reading it row by row mirrors the city across its
diagonal, which a symmetric arena will not reveal.

**Roads are textures, not meshes.** SoSC draws SC2K road tiles as flat quads
with `SIM3D.BMP` textures: #78 straight, #80 T-junction, #81 crossing, #79
diagonal. The arena floor is crossings throughout, and the grey floor panels
belong to #81's corners — a tile joins its neighbours' kerbs only on the sides
where there is no road.

**The diagonal edges (tile ids 35–38) are not bends.** Here they draw the
floor's corners and the island edges, all with #79. Its turn cannot be fixed
per tile id: each tile turns #79 so its pavement faces the corner with no road
beside it. Comparing single pixels to find that side tied (149 against 149) and
picked the wrong quarter; comparing the average brightness of whole corners
does not.

**Terrain shape.** Slopes are a low-poly halfpipe, not a plane: gentle on the
first level, steeper above it. Each terrain corner has exactly one height, so
tiles never crack apart. Roads ignore all of this and run in straight ramps.
Slopes get broad, low bumps (8 m facets, ±0.8 m) that stay drivable.

**Ground texture comes from two terrain sheets in `SKY.BMP`.** Page #4
(identical to `TILED1.BMP`) is an 8×8 sheet of 32 px cells: water, rubble,
dirt, grass and sand, each set followed by transition art. Page #5 is a second
sheet, and its cell 52 is the **dark grass patch** — a whole tile of grass with
a blue-grey blob in it, scattered through plain grass (about 12% of it here).

**Sand is a matter of height.** Open ground above the city's base level is sand
and everything else is grass. Built tiles keep a grass lot, because SoSC's
building base is textured with the solid grass cell.

**The sand edge has teeth, and which way they point depends on where it
is.** Along the berm, sand teeth hang into the grass. On the four islands,
grass teeth bite into the sand. Each tile picks the sheet cell that best fits a
3×3 pattern of sand and grass points around it:

- **Berm:** a corner point is sand if any tile around it is sand, and an edge
  point only if both tiles beside it are.
- **Islands:** the other way round, with every neighbour counted. An island is
  a sand patch that fills at least half of its bounding box. That sets them apart
  from the L-shaped strips roads cut off the berm, which fill about a sixth.

Two matching gaps had to be closed:

- **Missing directions.** The sheet does not draw every edge facing every way,
  and where no cell fit, a whole berm face fell back to a straight line. Cells
  are tried in all four quarter turns, since sand and grass have no grain.
- **Solid cells winning.** A tooth covers too little of a tile to beat a solid
  cell, so island edge tiles with grass directly beside them may not take
  solid sand.

**Cows are required.** They are object #162 in `GEO/SIM3D1.MAX`, which is not
in its name table. SoSC spawns them at runtime anywhere, roads included, so 200
are scattered at random.

**Preview lighting.** The first viewer lighting drew the grass about 1.5× too
bright, which read as "the game's grass is darker". The texture was right. The
lights are now set so flat ground renders at its texture colour.

## References

- The SimCity 2000 file notes at http://djm.cc/simcity-2000-info.txt, for the
  `.sc2` chunk layout.
- [alekasm/SC2KRender](https://github.com/alekasm/SC2KRender): **reference
  only**. It has no licence, so nothing here is copied from it. It confirmed the
  axis order, the altitude bit split and the building-corner nibble.
- [CahootsMalone/maxis-mesh-stuff](https://github.com/CahootsMalone/maxis-mesh-stuff),
  for the `.MAX` mesh notes, the units per metre and the object numbering the
  cow is found by.

The mesh, palette and texture-atlas readers are shared with
[`../sosc-to-viper/`](../sosc-to-viper/).
