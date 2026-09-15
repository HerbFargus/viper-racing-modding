# Streets of SimCity arena → Viper Racing track

Rebuilding a *Streets of SimCity* scenario city as a textured 3D model, at true
scale and in the game's own art, as the first half of turning it into a *Viper
Racing* track. The target is the **Continuous Fire** scenario ("Arena Death
Match"), which loads `Cities/Arena.sc2`.

**Status: phase 1, the preview, is done.** The arena matches the game in
screenshots taken side by side: roads, floor panels, the diagonal edges, the
berm and islands, the sand and grass pattern, the dark grass patches, the
towers and the cows. **Phase 2, exporting it as a Viper track, has not
started.**

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
