"""The build kit: reusable helpers for generating Viper Racing cars, tracks and obstacles.

Everything here was first written for a specific build (the Willys, the Coliseum, Cats vs
Dogs) and lifted out once a second build needed it. Import it from a build script with

    import sys; sys.path.insert(0, r"<repo>")      # the vrmod-experiments checkout
    import kit                                     # also puts vrmod on sys.path
    from kit import shapes, terrain, car, sound, tracks, art

Paths default to this machine's layout and can be overridden with environment variables:
  VRMOD_REPO     the vrmod checkout to import (default: the `main` worktree, viper-mod-manager)
  VIPER_INSTALL  the game folder builds install into (default: the v1.0-RC test install)
  VIPER_STOCK    a folder of untouched stock files (default: viper-racing-usa/Data)

`main` carries the newer mod.decimate / LOD code, so the kit imports vrmod from there; do not
mix modules from two checkouts (tex.encode_to_tex's keywords differ between them).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\seamus\Desktop\claude-code")
VRMOD_REPO = Path(os.environ.get("VRMOD_REPO", ROOT / "viper-mod-manager"))
INSTALL = Path(os.environ.get("VIPER_INSTALL", ROOT / "game-files" / "installs" / "v1.0-RC"))
STOCK = Path(os.environ.get("VIPER_STOCK", ROOT / "game-files" / "viper-racing-usa" / "Data"))

if str(VRMOD_REPO) not in sys.path:
    sys.path.insert(0, str(VRMOD_REPO))

DONOR_TRACK = STOCK / "bemidji.trk"                       # trackbuild.assemble's donor
DONOR_CAR = INSTALL / "Disabled" / "hmxvan.car"           # sounds, cockpit, brake strip
VAL_CAR = INSTALL / "Backups" / "Viper.car.boulder-backup"  # Val's "best handling" .cf
