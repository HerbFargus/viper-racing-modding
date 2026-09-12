# Test fixtures

Generators for the deliberately-crude assets used to prove an import pipeline actually
replaced something, rather than appearing to. Both are stdlib-only and write into the
current directory.

| script | writes | proves |
|---|---|---|
| `make_duck.py` | `duck.obj` — 183 verts, 272 faces | the Parts-drawer OBJ import/commit round-trip. Three overlapping primitives, enough to read as "a duck" at a glance |
| `make_quack.py` | `quack.wav` — 0.35 s, 22050 Hz mono 16-bit | the WAV import/commit round-trip through `wav2sfx` / `from_wav_bytes` |

The crudeness is the point. A fixture has to be **unmistakable at a glance** so that a
successful import can't be confused with the original asset still being in place — a
real duck model or a sampled quack would leave you guessing whether the commit landed.
`make_quack.py` in particular is a buzzy descending tone chosen to sound nothing like
the `horn.sfx` it replaces.

```bash
python scripts/fixtures/make_duck.py
```
