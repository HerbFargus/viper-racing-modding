# Recovered track builders

Builder scripts for the generated tracks of September 2026 (Coliseum, Ball Pit, Ballroom, Boulder Run, the Temple tracks, Volcano/Burninator and the crater track), recovered on 2026-10-10. The scratchpads they lived in were deleted, so they were rebuilt from session transcripts.

**Source transcript:** every file comes from `C:\Users\seamus\.claude\projects\C--Users-seamus-Desktop-claude-code\606df7fb-513d-4aa0-a951-92dd331daf04.jsonl`. "Line" means the JSONL line number.

## How they were rebuilt

Every file operation in that transcript that targeted `<scratchpad>/<dir>/` was replayed in order, into a sandbox:
- `Write` and `Edit` tool calls;
- `cat > file <<EOF` heredocs;
- Python patch heredocs (`p.read_text()`, `sub(old, new)`, `p.write_text()`);
- `python patch_*.py` runs;
- `sed -i` edits;
- `cp a.py b.py` copies.

Two quirks of the Bash tool had to be reproduced:
- **It collapses `\\` to `\`.** Without that step, one Coliseum patch came out differently from the original.
- **`write_text` writes CRLF.** Edits normalise line endings, as the Edit tool does.

**Verification:**
- Every failed replay step also failed in the original session: an AssertionError or Traceback in its tool result.
- Every `Read` of these files in the transcript (13 reads, mostly of `build_coliseum.py`, plus one of `build_canyon.py`) matches the replayed state line for line at that point.
- All files pass `py_compile`. `build_coliseum` and `build_ballpit` import against the current vrmod main.

**Left out:** versioned backups (`*_v1.py` and so on), `mock_*` mockups, one-off `patch_*.py` scripts (already applied) and `_try` files. The sibling-directory layout (`dome/`, `ballroom/`, `circuit/` and so on) is kept, because the builders import each other through `HERE.parent / "<dir>"`.

## Before running anything

- **The scripts write into the game install.** They add `sys.path` entries for `C:\Users\seamus\Desktop\claude-code\viper-mod-manager`. Their `main()` writes the `.trk` next to the script and a `.tra` into `game-files\installs\v1.0-RC` (`DATA`). Several also wrote straight into a slot.
- **Importing a module is safe.** Every builder keeps its build behind `if __name__ == "__main__"`.
- **They were written against vrmod as of 2026-09-25.** `box_from_segment(..., open_ends=0)` exists only on the experiments branch (`vrmod-experiments/vrmod/sol.py`), not on main.

## Files

The "Created" column gives the line and the kind of operation that created each file. "Later changes" lists the replayed operations after that, ending at the last line that touched the file. Edits made by `python patch_*.py` runs were replayed but are not always counted; this mostly affects `circuit/build_river.py` and `volcano/build_volcano.py`.

| File | Created (line, op) | Later changes | What it is |
|---|---|---|---|
| `ballpit/build_ballpit.py` | 140743 (Write) | 4 pypatch; last at 141330 | Ball Pit builder (final v3: 200 x r5 balls, .sol rim wall + invisible ceiling) |
| `ballpit/render_ballpit.py` | 140802 (cat>) | 1 pypatch; last at 141529 |  |
| `ballroom/build_airoof.py` | 137690 (cat>) | none; last at 137690 |  |
| `ballroom/build_ballroom.py` | 136833 (Write) | 2 pypatch, 2 Edit; last at 138408 | shared helpers: Batch (chunked, pre-lit meshes), ball_mesh, white-room ball ladder |
| `ballroom/build_bigballs.py` | 137107 (cat>) | 1 sed, 1 pypatch; last at 137293 |  |
| `ballroom/build_bigballs_mass.py` | 137235 (cat>) | none; last at 137235 |  |
| `ballroom/build_overlap.py` | 137412 (Write) | 1 sed; last at 137429 |  |
| `ballroom/build_texlimit.py` | 145921 (Write) | none; last at 145921 |  |
| `ballroom/render_ballroom.py` | 136866 (Write) | none; last at 136866 |  |
| `ballroom/render_bigballs.py` | 137135 (cat>) | none; last at 137135 |  |
| `ballroom/render_overlap.py` | 137429 (cat>) | 1 sed; last at 137448 |  |
| `boulders/build_boulderlab.py` | 141175 (Write) | 2 sed; last at 141263 | Boulder Lab 1 (slope lanes, distance boards) |
| `boulders/build_boulderlab2.py` | 141728 (Write) | 1 pypatch; last at 142635 | Boulder Lab 2/3 |
| `boulders/build_canyon.py` | 142780 (Write) | 19 pypatch, 5 sed; last at 145503 | Boulder Run canyon (final: cave + U half-pipe, flush quicksand, per-waypoint ild corridor) |
| `boulders/render_canyon.py` | 142821 (cat>) | 2 pypatch; last at 143006 |  |
| `boulders/render_canyon2.py` | 143006 (pypatch) | none; last at 143006 |  |
| `boulders/render_canyon3.py` | 144491 (cat>) | 4 sed; last at 145329 |  |
| `boulders/render_canyon_top.py` | 142868 (pypatch) | none; last at 142868 |  |
| `boulders/render_lab.py` | 141206 (cat>) | none; last at 141206 |  |
| `boulders/render_lab2.py` | 141804 (cat>) | 1 sed; last at 141824 |  |
| `circuit/art.py` | 122197 (Write) | 4 pypatch; last at 122781 | shared texture helpers: tile_noise, colourise, to_img, speckle |
| `circuit/bead_sim.py` | 124150 (Write) | none; last at 124150 |  |
| `circuit/build_circuit.py` | 121965 (Write) | 1 pypatch; last at 122038 | shared helpers: DONOR (bemidji.trk), game() frame transform, Line (arc length / at / nearest), terrain |
| `circuit/build_launchlab.py` | 123440 (Write) | 1 sed, 4 pypatch; last at 124179 |  |
| `circuit/build_offroad.py` | 122488 (Write) | 5 pypatch; last at 122756 | off-road course (build_river.py started as a copy of it) |
| `circuit/build_river.py` | 122804 (cp<build_offroad.py) | 2 cp<build_offroad.py, 7 pypatch; last at 123404 | river course builder; provides delaunay() used by every later builder |
| `circuit/build_scenic.py` | 122296 (Write) | 1 pypatch; last at 122424 |  |
| `circuit/build_temple.py` | 125267 (Write) | 1 pypatch; last at 126926 | Temple drag strip (launch pads, idol wobbles) |
| `circuit/build_temple_arena.py` | 125726 (Write) | 6 pypatch; last at 126867 | Temple arena (giant knockable totems) |
| `circuit/build_temple_hall.py` | 125517 (Write) | 5 pypatch; last at 126823 | Temple ring-hall with hidden trap tiles |
| `circuit/build_temple_rotunda.py` | 126908 (Write) | 1 pypatch; last at 129531 | Temple Rotunda (circular arena off the origin) |
| `circuit/clean_car.py` | 127817 (Write) | none; last at 127817 |  |
| `circuit/design.py` | 121865 (Write) | 2 pypatch; last at 121899 |  |
| `circuit/engine_sfx.py` | 127799 (Write) | none; last at 127799 |  |
| `circuit/hall_art.py` | 125491 (Write) | 2 pypatch; last at 125582 |  |
| `circuit/make_boulder.py` | 125382 (Write) | none; last at 125382 |  |
| `circuit/make_rumble.py` | 126968 (Write) | 1 pypatch; last at 126990 |  |
| `circuit/preview.py` | 121904 (cat>) | 1 Write, 1 sed; last at 121935 |  |
| `circuit/temple_art.py` | 125209 (Write) | 1 pypatch; last at 125237 |  |
| `dome/build_coliseum.py` | 137833 (Write) | 22 pypatch, 1 sed, 29 Edit; last at 140418 | Coliseum builder (final v16: 115 m gap jump, raked stands, glow_tiles floor, 60 balls, roof .sol shell) |
| `dome/measure_bemidji.py` | 137771 (Write) | none; last at 137771 | measures stock Bemidji road width / banking / radii |
| `dome/render_coliseum.py` | 137975 (cat>) | 6 pypatch; last at 140487 | offline renders of the Coliseum (menu view used for the gallery .stp) |
| `friction/boulder_sim.py` | 142396 (cat>) | none; last at 142396 | obstacle-ball physics model decoded from race.exe |
| `friction/dis.py` | 142263 (cat>) | none; last at 142263 |  |
| `lava/build_crater.py` | 130827 (Write) | 1 pypatch; last at 130843 | volcano crater lava-jump track |
| `lava/lava_art.py` | 130797 (Write) | 2 pypatch; last at 130957 | crater textures + sky |
| `lava/render_views.py` | 130891 (Write) | 2 pypatch; last at 131351 | numpy offline perspective renderer used by several render scripts |
| `targets/build_bigball_gauge.py` | 121293 (Write) | none; last at 121293 |  |
| `targets/build_gauge.py` | 120399 (Write) | none; last at 120399 |  |
| `targets/build_hinge_gauge.py` | 120439 (Write) | none; last at 120439 |  |
| `targets/build_range.py` | 120474 (Write) | none; last at 120474 |  |
| `targets/build_sticks.py` | 120184 (Write) | 1 Edit; last at 120199 | disc/stick/turn mesh helpers; imported by build_circuit |
| `targets/build_targets.py` | 119673 (Write) | 1 Write; last at 120020 | hinged target wobbles; imported by build_circuit |
| `volcano/build_volcano.py` | 131130 (Write) | 11 pypatch; last at 136169 | Volcano/jungle (Burninator) builder, final with dragon, monks, cottages, respawn detour |
| `volcano/check_respawn.py` | 136093 (Write) | 1 pypatch; last at 136153 |  |
| `volcano/dragon_set.py` | 133541 (Write) | 1 sed, 1 cat>>, 1 pypatch; last at 134123 | dragon, fireball, monk and cottage meshes |
| `volcano/jungle_art.py` | 131277 (Write) | none; last at 131277 | jungle textures |
| `volcano/render.py` | 131162 (Write) | 5 pypatch; last at 136197 |  |
| `volcano/volcano_art.py` | 131095 (Write) | 1 Edit; last at 131101 | volcano textures |
