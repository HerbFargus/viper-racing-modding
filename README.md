# Viper Racing Mod Manager

A desktop app for modding *Viper Racing* (1998): browse and 3D-preview your cars
and tracks, edit their textures, swap tracks into the game's slots, set up the AI
field and the default car, add modern resolutions, and check your install for the
fixes it needs to run well on a modern PC.

It's a thin native window (via [pywebview](https://pywebview.flowlib.org/)) around
the `vrmod` toolkit's local web UI. Everything the app does is also available from
the `vrmod` command line for power users.

## Running from source

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

The app opens on a landing screen; choose your Viper Racing **Data** folder (the
one containing `race.bin` and your `.car` files) and it remembers it next time.
Use **Change folder** in the header to switch installs.

## Building the standalone .exe

With the venv set up (above), plus PyInstaller (`pip install pyinstaller`):

```bash
.venv\Scripts\python -m PyInstaller --noconfirm viper-mod-manager.spec
```

Produces a one-folder build in `dist\ViperModManager\` — ship the whole folder;
`ViperModManager.exe` is the launcher. The spec bundles `vrmod/assets/`
(three.js + slot icons), capstone's native lib, and pywebview's backend. To see
a startup traceback while debugging a build, flip `console=False` to `True` in
the spec.

## Command line (power users)

The `vrmod` package is self-contained (pure standard library apart from
`capstone`). Run any tool directly, e.g.:

```bash
.venv\Scripts\python -m vrmod.cli switcher "C:\path\to\Viper Racing\Data"
```

## Layout

- `app.py` — desktop entry point (pywebview window + native folder picker).
- `vrmod/` — the modding toolkit: parsers/builders, the CLI, and the web UI
  (`switcher_ui.py`) the window hosts.
- `requirements.txt` — runtime dependencies.

## Status

- Phase 1 (desktop shell) — done.
- Phase 2 (offline-ready) — done: three.js r128 is bundled at `vrmod/assets/three.min.js`
  and inlined into the viewers at build time, so the 3D views work with no internet.
- Phase 3 (packaging) — done: `viper-mod-manager.spec` builds a one-folder
  `dist\ViperModManager\` (three.js, slot icons, capstone.dll, and pywebview's
  backend all bundled; launches windowed). See "Building the standalone .exe".
