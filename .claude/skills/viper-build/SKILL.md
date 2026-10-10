---
name: viper-build
description: Build guide for new Viper Racing content -- custom cars, generated tracks, obstacles/props, horn balls and horn sounds -- with the vrmod toolkit and the build kit. Use whenever the user asks to design, mock up, build, rebuild or install a Viper Racing car, track, obstacle or track prop, or to change one that a previous build made.
---

# Building Viper Racing content

Paths are relative to the root of the viper-racing-modding repo (`experiments` branch, where `kit/` lives).

## Workflow (the user expects these steps in order)
1. **Scope with mockups first.** Before building, show a three.js mockup page (an Artifact) and let the user pick and adjust. Pets, cars and tracks all went: ideas → mockup → user picks → build. Keep options simple; don't add opt-in toggles for edge cases.
2. **Build on the kit.** Use `kit/` (README there), and start from the closest worked example in `experiments/pets/`: `build_cvd.py` for cars and obstacles on a stock track, `build_catsdogs.py` for a generated track. Port mockup geometry straight across, since `kit.shapes.Builder` and `kit.terrain.CatmullRom` match the JS. Keep every build script in the repo, never only in a scratchpad. Old one-offs (Coliseum, Ball Pit, Temple, Volcano) are in `experiments/pets/recovered/`.
3. **Check without the game**, then install:
   - `kit.tracks.render(trk, png, (x0, x1, y0, y1))` for tracks, and `vrmod.carshot.to_png(car, style="textured", shared_dir=INSTALL)` for cars. Look at the images.
   - Read back what you wrote: `kit.car.report()`, the `.cf`, obstacle counts.
   - Install into the v1.0-RC test install (`kit.INSTALL`).
4. **Report what's untested in game.** Nothing is confirmed until the user drives it. Save outcomes to memory.

## Rules that cost a test cycle when missed
- **Texture names are global.** The game caches textures by NAME. Two different `.tex` files under one name recolour each other: everything came out the wrong colour once. Give every car and track its own palette name, via `kit.shapes.Palette("xxpal.tex")`.
- **Texture names are 8.3**: at most 12 characters with `.tex`, no underscores. Textures are at most 256 px and square power-of-two. No texel may sit on RGB565 0x0000 (it's the colour key). There are about 119 textures in all, track plus cars, on the stock engine. Don't name a texture `<carprefix>.tex`; that's the paint slot.
- **Frames.** Source is (x east, y north, z up). Game is `trackgen.to_viper` = (-x, z, -y). Mockup is (x, y up, z south), and `mockup_to_source` = (x, -z, y). Obstacle X,Z come from `game()`. Car meshes are in the game frame: ground y=0, axle midpoint z=0, +z the nose.
- **Obstacles**: `obj obstacle ball|cube m.mod X,Z:YAW MASS`.
  - YAW is in degrees, MASS in pounds (50 is a nice knock, 10,000 crushes).
  - Centre the mesh on its own middle. A ball's collision radius is half the mesh height.
  - The game drops each obstacle 4 m at the start, so place them on level ground.
  - The obstacle's texture must be drawn by something on the track.
  - Cars + checkpoints + obstacles + wobbles ≤ 512 objects.
- **Jumps**:
  - Any near-vertical collision face acts as a wall, even for cars flying over it. Give every lip, and every landing-ramp back, a 35° back slope.
  - Only one floor per (x, z). Solid roofs over the road act as launch pads, so draw roofs only.
- **Water** is surface code 14 (`trackgen.WATER`). It's flat and floats the car, with no grip. The stock texture is `wat2.tex`.
- **Budgets**:
  - Collision triangles ≤ ~16,500. The build prints this; thin the ground lattice if it's close.
  - Drawn chunks ≤ 990 vertices; surfaces well under 600.
  - `Batch` stems must be unique.
  - Some segment must claim the world origin (`assemble` checks).
- **AI + obstacles** has crashed before. Ask whether a track is for AI or solo, and test solo first.
- **Cockpits** (`kit.cockpit`): the eye must sit behind the car's centre (z ≤ 0.07). Keep everything the driver sees from outside (the hood ahead, the dash) with its own outward winding as `shell`, and rewind only what they sit inside (cab walls, ceiling) as `inside`. Rewinding faces where two solids touch draws both surfaces in one plane, and they z-fight, flickering while you drive. Check with `snapshot()` and the coplanar scan in `experiments/pets/coplanar_check.py`.
- **Cars**: the fork-the-van recipe (`kit.car`). A Viper-sized body suits Val's whole `.cf` (`tune="val"`); tall or long bodies get `"indy"`. Rebuild from the donor every time. Backups must be `.bak` or go in `Backups/`, because the game loads every `.car`.
- **Installing tracks**: `kit.tracks.install(tra, slot)`.
  - The menu name is cut to the slot's width: Ridge Valley 12, Castlegreen / Rock Island / Sunset Mesa 11, Silverdale 10, Bemidji 7, Dundas 6.
  - The stock file is kept as `<slot>_AS_<name>.btr`, and `switcher.restore` puts it back.
  - The game must be closed.

## Where to look things up
- Format and engine reference: https://herbfargus.github.io/viper-racing-modding/ (source `docs/reference/`: `file-formats.md`, `runtime.md`). Search them for the specific thing; don't read them whole.
- Memory notes per project (`project_*.md`) record what was confirmed in game and what wasn't.
