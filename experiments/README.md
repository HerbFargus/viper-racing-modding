# Experiments

Work that used the toolkit rather than being part of it. Each directory is a
self-contained investigation: the scripts that did it, the checks that decide
whether it still works, and a write-up of what was actually established.

Nothing here is imported by `vrmod`, nothing here ships in the executable, and
none of it is needed to use the toolkit. It is kept because the conclusions
came from measurements, and a conclusion whose measurement you cannot re-run is
just an assertion.

| Experiment | Question | Answer |
|---|---|---|
| [`sosc-to-viper/`](sosc-to-viper/) | Can a car from another 1998 game be converted into a loadable Viper Racing car? | Yes — seven of them, though four undeclared cross-game conventions had to be found from screenshots first |
| [`sosc-arena/`](sosc-arena/) | Can a Streets of SimCity scenario city be rebuilt, at true scale and in its own art, as a drivable Viper Racing track? | Yes — the Continuous Fire arena loads, laps and drives, cows included, though four conventions that no preview can show (render-chunk size, a mirrored axis, backface winding, the transparency marker) each had to fail in game first |
| [`baked-lighting/`](baked-lighting/) | Can a flat palette-coloured car get believable shading without adding geometry? | Yes — ambient occlusion and a key light baked into a texture atlas (body, cockpit, wheels), as long as the body is lightened before the bake and the LODs are built after it |

## Running them

Every script takes the paths it needs as arguments. None of them contain game
files, and none of them will find your install on their own — these experiments
read assets from two commercial games, and neither game's data is in this
repository or ever will be.
