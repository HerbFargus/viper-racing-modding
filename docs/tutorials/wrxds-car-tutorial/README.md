# Car Creation / Conversion Tutorial (wrxds.mine.nu) — archived copy

A complete **19-step tutorial on building or converting a car for
Viper Racing**, recovered from the Internet Archive and kept here verbatim.

## Why this is in the repo

The original lived at `http://wrxds.mine.nu/tutorial/` — a machine that started
life in 2003 as *"Impreza's Viper Racing Dedicated Server"*, run by
**BlasterMaster555**, and which also hosted the FTP archive Val's site linked as
*"accumulated from 1998"* (`ftp://wrxds.mine.nu/vrmods/`). The host outlived the
game, becoming a Live for Speed and then a Minecraft server, but it kept the
tutorial online throughout.

The site is gone. The FTP directory listing was never captured at all. The
tutorial pages **were**, and this is a copy of them, because everything else this
project has learned about the community's documentation is that links die and
only what someone wrote down survives.

It is also **the source that was missing**. This repo's history doc already
listed the tools this tutorial describes — Zmodeler 1.07, XVi32, the
`rescrack`/`mkres`/`mktex`/`mksfx` set, `vrzmodtemplate` — details you cannot get
from a binary, only from documentation like this. But no source was ever cited,
and the connective tissue was lost: that the converters are **one suite**
(Frank P. Wolf's **RESTools**), that it includes **`mkcar`**, and where it was
distributed. Archiving the source fixes that.

## What it covers

The 17 steps (plus 3a/3b and 12a) run the whole pipeline: gathering reference,
preparing and exporting the meshes, the dashboard, RESTools, textures, sounds,
performance, the car's long name, packing, then a full second pass of fixes
including the brake lights.

It independently corroborates work done here from the binaries — step 15 has the
brake lights using `effects.tga` with *"Alpha Glow with Illumination Effect"*,
which is the shared `effects.tex` in `race.res` and the `<prefix>b.mod` slot;
step 8's "long name" is the `<prefix>1.tab` field whose layout had to be derived
from scratch; and the whole workflow of unpacking `sedan.car` to use as a
template is what `vrmod carfork` automates.

## Contents

- `index.htm` and `step_*.htm` — 20 pages, links rewritten to point at
  these local copies
- `images/` — 41 screenshots and diagrams
- `files/` — 3 original downloadable assets: basicfiles.zip, brakelt.mod, effects.tga

## What could not be recovered

Twelve images were never captured by the Wayback Machine and are gone:
`almostlinedup.jpg`, `cockpittabexplained.jpg`, `clickimport.jpg`,
`firstnameunited.jpg`, `SELon.jpg`, `lineduponx.jpg`, `saveasmod.jpg`,
`materialeditorpulldownmenu.jpg`, `texturewindow.jpg`, `crossectionwheel.jpg`,
`soundproperties.jpg`, `loopingplayback.gif`. The pages referencing them are
intact; only the illustrations are missing.

Everything the tutorial offered for download **did** survive, including
`brakelt.mod` — the game's default brake-light mesh, 380 bytes, which still
parses cleanly with this toolkit (8 vertices, 4 faces).

## The images carry text the pages do not

These tutorials teach through annotated screenshots — Notepad windows, hex
editors, modeller dialogs, with instructions written in red over the picture.
That text is invisible to search and to every earlier survey of this material,
so the archived images were run through OCR (upscaled 300% and normalised
first, which is what turns garbled digits into exact coordinates).

It paid for itself on Sucahyo's **vrTrackMaker**, whose UI exists only as
screenshots: the cross-section bands it sweeps along a spline (Road, Wall, Side,
Rumble1, Rumble2, Grass), its banking and threshold controls, and its built-in
AI-path lookup distances. That is what specified the one stage of track
authoring this project had recorded as a gap — see
[VIPER_RACING_FILE_FORMATS.md](../../VIPER_RACING_FILE_FORMATS.md) under
"vrTrackMaker, the stage in the middle".

`foolandsurface.jpg` also recovered the MKWORLD scene format verbatim —
`marker(check1)`, `vert(-2.5187, -325.5298, 0.0000)`,
`modobject(sider.mod, 0, 0, 16, 0)`. One caution against over-crediting this
technique, though: the rule that driveable objects must appear in *both* source
files was noticed here first in a screenshot annotation, but it turned out to be
a plain-text comment in `eg-foolandsurface.txt`, a file already held and already
cited. OCR corroborated it; it did not discover it.

The rest was corroboration rather than discovery: the `tut02x` series is Hex
Workshop over `tf550f.mod` (a format this toolkit already reads in full), and
the `zmod15june*` series is ZModeler's UI, confirming the "VR Track creation"
workflow the tool chart already lists.

## Provenance

- Original: `http://wrxds.mine.nu/tutorial/` by **BlasterMaster555**
- Source: Internet Archive Wayback Machine, 2013 capture (with 2012/2011
  fallbacks for pages the 2013 crawl missed)
- Retrieved: 2026-09-09
- Reproduced here unaltered except for stripping the Wayback toolbar and
  rewriting links to the local copies.

Credit is the author's. This copy exists so the work is not lost with the host.
