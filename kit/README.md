# kit: the Viper Racing build kit

Reusable helpers for generating cars, tracks and obstacles with `vrmod`. Each module was
written for a real build and lifted out once a second build needed it. The Cats vs Dogs
builds in `experiments/pets/` are the worked example and run entirely on the kit.

```python
import sys; sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\vrmod-experiments")
import kit                                   # also puts vrmod (the `main` checkout) on sys.path
from kit import shapes, terrain, car, sound, tracks, art
```

Paths come from `kit/__init__.py` and can be overridden with `VRMOD_REPO`,
`VIPER_INSTALL` and `VIPER_STOCK`.

| Module | What it gives you | First written for |
|---|---|---|
| `shapes` | `Builder` (tapered `box`, `pyr`, `cyl`, the same calls as the three.js mockups), `Palette` (flat colours in one 128 px `.tex`, **named per build**), `wheel`, `sphere`, `yarn_ball`, `tennis_ball`, `centred()` for obstacles | Cats vs Dogs |
| `terrain` | the three frames (`game`, `mockup_to_source`), `Batch` (chunked, pre-lit, solid or drawn-only, surface code), `delaunay`, `Line`, `CatmullRom` (the mockups' curve, with stations) | Ballroom, Coliseum, circuit |
| `car` | `CarSpec` + `build()`, the Willys recipe: fork the van, body/wheels/palette, Val's `.cf` with a `"val"` or `"indy"` tune, modlod, horn ball + `horn.sfx`, engine loops, cockpit, brake lights, and pruning every texture nothing uses (so none of the van's art ships); `report()` | Willys, Indy Jeep, Cats vs Dogs |
| `sound` | `voice()`, a source-filter synth for horn calls; `engine_set()`, synthesised engine loops; `to_pcm`, `wav_bytes` | Cats vs Dogs horns, the jeeps' engines |
| `cockpit` | 3D cockpits: `build()` (shell seen from outside + inside rewound toward the eye, generated dials, plate, wheel, needle, cockpit.tab), `snapshot()` (a look from the seat) | the jeeps, Cats vs Dogs |
| `tracks` | after `trackbuild.assemble`: `set_member`, `image_tex`, `stock_member`, `set_sky`, `cameras`, `closed_box`/`add_boxes`, `add_obstacles`, `finish` (.trk → map → .tra + .stp), `install`, `render` | Coliseum, Cats vs Dogs |
| `art` | `tile_noise`, `colourise`, `to_img`, `speckle`, and ready-made ground/road/sky textures | circuit |

The module docstrings hold the rules learned in game: slopes, budgets, obstacle and water
behaviour, texture naming. Read the one you're using.

The original one-off builders (Coliseum, Ball Pit, Temple, Volcano…) are preserved in
`experiments/pets/recovered/` with their provenance, for reference only.
