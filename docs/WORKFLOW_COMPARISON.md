# The old modding workflow and the new one, side by side

*Viper Racing* modding was built by a small group of people between roughly 1999 and 2010, out of
one-off utilities that each did a single job. Most were Windows-only, several survive as a single
binary with no source, and the sites that hosted them are gone. See
[MODDING_HISTORY.md](MODDING_HISTORY.md) for who wrote what.

This document compares the **process**, step for step: what building a track or a car took then, and
what it takes now. It is not a tutorial, and it is not a tool chart — the chart is in the history
document, and the formats are in [VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md).

**The bottom line.** Every stage of both pipelines now runs from one cross-platform Python library,
with one exception: the collision BSP (`.bpp`) still requires the original `nhmkworld`. Everything else — geometry, textures, surface codes, racing lines,
timing gates, the starting grid, packaging, installation — is `vrmod`. Both pipelines are confirmed
in game: a car with a custom model on 2026-09-07, a track generated from a centreline on 2026-09-09,
and a Bob's Track Builder track imported with its own geometry on 2026-09-10.

---

## 1. Building a track from a centreline

The old route needed 3DS Max to draw the line, vrTrackMaker to turn it into a driving model, two
batch files to compile, and `mkres` to pack. vrTrackMaker swept one fixed six-band cross-section and
emitted only surface codes 0, 10 and 16, so water and dirt had to be hand-edited into the generated
text afterwards — in **both** source files, or the track looked right and drove wrong.

| # | Step | Then | Now |
|---|---|---|---|
| 1 | Draw the centreline | 3DS Max → `.ase` spline | Any `.ase`, `.obj`, `.mod` or `.dof` — or recover one from an existing road surface |
| 2 | Sweep the road and verges | vrTrackMaker (fixed six-band section) | `vrmod trackgen` (`--road-width`, `--spacing`) |
| 3 | Assign surface codes | vrTrackMaker emitted 0/10/16 only; the rest hand-edited into both text files | Material-name convention, all five codes, written to both files from one list |
| 4 | Timing gates | vrTrackMaker | `vrmod trackgen --checkpoints` |
| 5 | Starting grid | vrTrackMaker | `vrmod trackgen --grid` |
| 6 | Racing lines | `mkilicc -nolat`, run three times over three hand-authored `.ili` sources | `ili.generate` — all three lines direct from the centreline |
| 7 | Compile the surface set | `mkfltoa` → `MKWORLD` → `.sol` `.obt` `.bsp` | `vrmod` writes `.obt` and `.bsp` natively; barriers via `--walls` → `MKWORLD` → `.sol` |
| 8 | Compile graphics and collision | `mkfltoa` → `nhmkworld` → `.grf` `.bpp` | `.grf` native; **`.bpp` still needs `nhmkworld`** |
| 9 | Track map image | MKSTAMP / tga2stp | `vrmod trackmap` |
| 10 | Sky | jpg2sky, four tiles by hand | `vrmod skyimport` — one panoramic TGA |
| 11 | Pack | `mkres @reslist.txt`, with a hand-maintained file list | `vrmod pack` — no list to maintain |
| 12 | Install into a track slot | Trackman | Mod manager, or `vrmod trk2tra` |

**What changed structurally.** The old chain's `reslist.txt` had to be edited by hand whenever a
texture was added, and a missing entry produced a track that crashed on load rather than one that
merely looked wrong. The two scene source files had to be kept identical by hand; `vrmod` writes both
from a single list of driveable objects, so they cannot diverge.

---

## 2. Converting a track that already exists

This is the route most modern tracks took: model in Bob's Track Builder, then carry the geometry and
the driving model down two separate branches that converge at the batch file. It was a hybrid because
neither tool could do the other's job — BTB knows nothing about Viper's surface codes or racing lines,
and vrTrackMaker, fed only a centreline, could produce a passable oval and nothing resembling a real
circuit.

**Then**

```
Bob's Track Builder ── .dof
   |
   +- Zmodeler:    import .dof, remap textures  -> .mod + .tex   the LOOKS
   |                                            -> .3ds
   +- 3DS Max:     import .3ds, draw a spline   -> .ase
   +- vrTrackMaker: import .ase                 -> fooland*.txt  the DRIVING
   |                                               .ili x4
   +- make-track.bat    -> .sol .obt .bsp .grf .bpp
   +- compile-track.bat -> <track>.tra
```

**Now**

```
Bob's Track Builder ── .dof
   |
   +- vrmod trackgen --keep-geometry
   |     chunks the mesh so the renderer will draw it
   |     roles from the exporter's own flags: surface / wall / prop / collider
   |     surface codes from material and texture names
   |     textures converted, resized and renamed
   |     centreline recovered from the road surface
   |     road width measured from the model
   |     barriers and collidable props become .sol solids
   |     racing lines, timing gates, starting grid
   |
   +- nhmkworld for .bpp; everything else native
   +- vrmod pack -> <track>.tra
```

Two commercial tools leave the chain: **Zmodeler** and **3DS Max**. The centreline no longer has to be
drawn by hand — it is recovered from the road surface by pairing its boundary edges through the mesh's
own triangle connectivity. That also means the road's real width is measured rather than assumed, and
that width sets the timing gates and the racing-line corridor.

**The author's own collision settings carry over — ✅ CONFIRMED in game.** Tick *Collide* on an
object in BTB and the car hits it in Viper. BTB writes the answer into the export three ways: the
object splits into its own `.dof` (so it groups by *properties*, and per-instance intent survives),
its `geometry.ini` flags gain bit 2, and for an object it emits a matching `objc*.dof` — an
untextured collision volume of vertical quads. Walls get no proxy because a wall's own mesh is its
collider. Either way the vertical faces become `.sol` solids.

The AI reads these solids too: an opponent met a barrier placed across the racing line — one that
did not exist when its line was generated — and steered around it. So adding obstacles does not
require the racing lines to be regenerated.

Flags, as measured: `2` Collide, `4` Driveable, `16` collision-only, `256|512` track structure.
rFactor's `.scn` does **not** carry the setting — its `CollTarget` is `True` on every object whatever
the checkbox says.

**A caveat worth stating.** BTB exports whatever the author modelled and nothing more. In the test
export that was a road plus a verge about 8 m wide, so leaving the road runs out of world quickly. The
import is faithful to the model; it does not invent terrain.

---

## 3. Building or converting a car

| # | Step | Then | Now |
|---|---|---|---|
| 1 | Model or convert the body | Zmodeler 1.07 with `vrzmodtemplate` (the NFS4 / Sports Car GT route) | Any modeller that exports OBJ → `vrmod obj2mod` |
| 2 | Inspect a mesh | Surface Modifier | `vrmod modinfo`, `vrmod mod2obj` |
| 3 | LOD chain (`<prefix>1..7.mod`) | By hand, one mesh per level | `vrmod modlod` |
| 4 | Textures | mktex / tga2tex, GIMP | `vrmod tga2tex` / `tex2tga`, or the in-app editor |
| 5 | Re-point a material at a new texture | Hex editor | `vrmod modretex` |
| 6 | Physics (`.cf`) | cf2txt → edit → txt2cf | `vrmod cfdump` / `cfset` / `cfpatch` (edits in place) |
| 7 | Tyres and handling | Viper Racing Tire Editor | `.cf` stats editor — *partial*, no tyre-specific UI |
| 8 | Cockpit (camera, wheel, gauges) | Hex editor | `vrmod cockpitdump` / `cockpitset` / `cockpitpatch` |
| 9 | Sounds | mksfx | `vrmod wav2sfx` / `sfx2wav` |
| 10 | Rename a car properly | vrcarrenamer | `vrmod carfork` (re-prefixes every internal reference) |
| 11 | Preview before installing | Load the game | `vrmod carview` / `shell` / `cockpitview`, in a browser |
| 12 | Install and activate | CarMan, CarMan2, AICarMan, WheelMan | Mod manager; `vrmod primarycar`, `vrmod aifield` |

**What changed structurally.** The old car chain's binding constraint was Zmodeler 1.07 — one specific
old version of one Windows editor, because it was the only thing that read and wrote `.mod`. Reading
and writing `.mod` directly removes that constraint: the modeller is the author's choice, and the
format is the interchange point rather than the tool.

---

## 4. Smaller jobs

| Job | Then | Now |
|---|---|---|
| Unpack / repack an archive | RESTools | `vrmod unpack` / `pack` |
| List an archive's contents | RESTools | `vrmod list` |
| Menu screenshot (`.stp`) | MKSTAMP, Stp2Tga, tga2stp | `vrmod trackmap`, `stp.py` |
| AI field size | AICarMan | `vrmod aifield` |
| Run on a modern GPU | Find and install a patched `race.bin` | `vrmod patch-vram`, `vrmod doctor` |
| Screen resolution | VR Resolution Changer | `vrmod resolution` (with aspect correction) |
| See further than the slider allows | View Extender (rewrote line 92 of `options.cfg` by number) | `vrmod drawdistance` (finds the key by name) |
| Identify a `race.bin` build | Ask on a forum | `vrmod racebin`, `vrmod doctor` |
| Inspect collision | BPP-2-Mod Converter | `vrmod bppinfo`, `bpp2obj`, `bppsurface` |
| Find collision/render mismatches | By playing | `vrmod collisioncheck` |

---

## 5. What still needs the old tools

Stated plainly, because a comparison that lists only wins is not much use:

- **`.bpp` — the collision BSP.** Still built by `nhmkworld` from the graphic scene file. This is the
  one step in either pipeline that cannot run without an original binary.
- **UV editing.** UVs round-trip through OBJ, but there is no equivalent of the **UV Map Editor**, or
  of Sucahyo's **Auto Image Tiler**, which rewrote a `.mod`'s UVs and texture references together.
- **AI tuning.** No equivalent of **trkaitweaker**. Racing lines are generated, but fields 12 and 13 —
  the AI's pacing hints — are approximated rather than reproduced, so AI braking on a generated track
  is not yet what a shipped track gets.
- **Collision repair.** `vrmod collisioncheck` finds mismatches; **Bad Poly Fix** repaired them.
- **Wheels.** The parts drawer covers wheel rows; **WheelMan** did more.

---

## 6. The shape of the change

The old workflow was a chain of programs, each owning one file format, most of them GUI, all of them
Windows. Its fragility was not that any one tool was bad — several were very good, and the community
got real work done with them for a decade. It was that the knowledge lived *inside the binaries*. When
a site went down, a format went with it.

The new workflow is one library that understands the formats, with a CLI, a desktop mod manager and a
browser viewer over the same code. None of that is better modding; it is the same jobs, done against
documented formats rather than through tools whose behaviour had to be inferred. The formats are
written down in [VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md), and that is the part
that outlives the software.
