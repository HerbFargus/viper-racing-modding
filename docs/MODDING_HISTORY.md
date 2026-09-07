# Viper Racing Modding — History, Tools & Credits

*Viper Racing* (Sierra / Monster Games, 1998) grew a small but remarkably
dedicated modding community that kept the game alive for over two decades —
converting cars from other games, building tracks, patching the engine to run on
modern hardware, and passing format knowledge along in hand-written tutorials.

This document records **who did that work, the tools they built, and how the
game's file formats came to be understood.** It's the companion to
[`VIPER_RACING_FILE_FORMATS.md`](VIPER_RACING_FILE_FORMATS.md): that reference
describes *what the formats are*; this one describes *how the community learned
them and what they built* — the context that made a toolkit like `vrmod`
worth writing.

The short version: the formats were understood intimately, but almost entirely
**by hand** — a hex editor, a 3D modeller, and a scattering of single-purpose
command-line converters. `vrmod` is the first attempt to fold that manual
knowledge into one programmatic library.


## The people

- **Val** (Moose Jaw, Saskatchewan, Canada) — ran the community's central site
  (originally *vnovak*, created 9 December 2003; later mirrored at valsgames.com)
  and was its most prolific modder, responsible for on the order of 1,500 car
  conversions and most of the community's tracks. He also wrote the how-to
  tutorials the rest of the scene learned from (hex editing, NFS→Viper
  conversion, track-making, AI-name editing).
- **Frank P. Wolf** ("Frank Wolf") — a major car converter (Aston Martins,
  Ferraris, Porsches and more; ~155 cars) and toolmaker, author of the **CarMan**
  and **WheelMan** management programs. His car packages were also the ones that
  shipped with an anti-tamper "lock" (decoy directory entries).
- **Sucahyo** — produced the **2007 "1.2.4 beta" `race.bin`**, the community
  engine patch that raised the game's polygon and per-object vertex limits (the
  reason high-detail mods load at all). This is the lineage behind the
  widely-used community `race.bin` (v1.2.x).
- **Charlie Ward** (Brunswick, Maine) — modified `race.bin` in **2016** to fix
  the modern-GPU startup error (the game's video-memory check overflows on cards
  with several GB), building on a solution found by **beatcracker**. This lets
  the game start on any 32/64-bit Windows including 10/11.
- **Max** — a car modder ("Add-on cars by Max").
- …and the wider community of racers and converters who contributed cars,
  tracks, retextures, and testing over the years.


## The community toolchain

A capable but **entirely manual** set of tools. Where a binary survives in the
preserved archives it's marked ✓.

### Archive / packaging
- **rescrack.exe** ✓ — unpack a `.car` / `.res` / `.trk` archive into its loose
  members, plus a `reslist.txt`.
- **mkres.exe** ✓ — (re)pack an archive from a `reslist`.
- **extract.exe** ✓ — an alternate unpacker.

### Cars
- **CarMan / CarMan2 / AICarMan** ✓ (Frank Wolf) — install/activate/organise cars
  and set up the AI field.
- **WheelMan** (Frank Wolf) — wheel manager. **vrcarrenamer** ✓ — rename a car.
- **cf2txt** ✓ / **txt2cf** — convert the `.cf` physics file to and from editable
  text (hp, torque, mass, wheelbase, suspension…).
- **Viper Racing Tire Editor** ✓ — tyre/handling editor.
- **Zmodeler 1.07** — the free mesh editor at the heart of every car conversion
  (Need For Speed 4 / Sports Car GT → Viper), used with the **vrzmodtemplate** ✓.
  **3DS Max 3.1** — the professional alternative.

### Textures
- **mktex** ✓ / **tex2tga** ✓ / **tga2tex** ✓ — convert between the game's `.tex`
  and standard `.tga`. **GIMP** — the free image editor of choice.

### Sound
- **mksfx** ✓ — convert a `.wav` to the game's `.sfx`.

### Tracks
- **Bob's Track Builder (BTB)** — track authoring (with a BTB→Viper tutorial).
- **vrTrackMaker** ✓ — turn a path/spline into a track block.
- **MKWORLD / mkfltoa** ✓ — generate the surface + collision set
  (`.sol` / `.obt` / `.bsp` / `.grf` / `.bpp`) from a text scene description;
  **nhmkworld** ✓ — the graphic pass that adds objects to `.grf` / `.bpp`.
- **MKSTAMP / Stp2Tga / tga2stp** ✓ — the `.stp` menu screenshot and `Trackmap`.
- **MKTABLE / MKILI** ✓ — data tables / the AI racing line (`.ili`).
- **trkaitweaker** ✓ — AI tuning. **jpg2sky / sky-tga2tex** — the four skybox tiles.

### Engine patches & `race.bin` versions

Every modern install runs a community-patched `race.bin` (the game engine). The
version is shown in-game at the **Options screen, bottom-right corner**, and is
stored as a plain string inside `race.bin` itself (near offset `0x0D37FD` — e.g.
`1.2.4 BETA`, `v1.2.5 2016`).

**Official (Sierra / Monster Games):**

| Version | Patch file | Notes |
|---|---|---|
| 1.0 | (retail) | base game, 1998 |
| 1.1 | `VIPER11` | lock-ups, Force Feedback, minor fixes |
| 1.2.1 beta | `VIPER121B` | beta |
| 1.2.3 beta | `VIPER123B` | last official patch; community builds fork from here |

**Community `race.bin` (unofficial, built on 1.2.3):**

| In-game string | Author / date | What it adds |
|---|---|---|
| `1.2.4 BETA` | Sucahyo, 4 Oct 2007 | 95,000-polygon track support; 20,000 vertices/object (≈100k-poly cars possible, though total per-scene vertex limits remain — ~14 AI cars at 20k each can still crash); the rear **spoiler** (`<car>S.mod`) visible without an `option.cfg` edit; the **mirror** visible in F1–F8 views |
| `v1.2.5 2016` | Val Novak, 20 Mar 2016 | Sucahyo's 1.2.4-beta **plus** Charlie Ward's modern-GPU / video-memory fix (from a DirectDraw solution by **beatcracker**), **plus** a scratchy-sound fix — the standard modern binary; runs on Windows 10/11 |
| `v1.2.6 2017` | Val Novak, 15 Nov 2017 | same as 1.2.5 but the extra rear wing is **no longer always shown** on the viper/AI cars (a 46-byte change to one visibility check) |

Notes for anyone cataloguing binaries:
- The pcgamingwiki "Viper Racing Unofficial Patch 1.2.4" (uploaded by *Blackbird*)
  is a **re-upload of Sucahyo's 2007 1.2.4-beta**, not a separate build.
- A file circulated as **`race.bin-25kvert-512tex-allmirror`** is **byte-identical
  to the 1.2.4-beta** (whose own readme still says 20,000 vertices) — the name
  over-promises. "512tex" most plausibly means the *number of textures loaded
  simultaneously* (a limit Sucahyo's notes mention raising), not a 512×512
  resolution, but it can't be confirmed from that mislabeled file.
- **ResolutionChanger.exe** (shipped in `Data/`) sets screen resolution
  independently of the `race.bin` version.

### Hex editor
- **XVi32** — the community's recommended editor. Nearly every "edit" that wasn't
  geometry was a hex edit here: the `<car>1.tab` spec sheet, texture-name strings
  inside a `.mod`, AI/track names in `english.lng`.


## How the formats were understood

The scene's format knowledge was real and deep, but it lived in **hex-editor
tutorials and muscle memory**, not code:

- **`<car>1.tab` (the "garage" spec sheet).** Val's 2015 hex-editing tutorial
  shows opening it in XVi32 and reading off `Name`, `0-60`, `top speed`, `engine`,
  `power max`, `torque max`, `redline`, etc. as plain text — the exact structure
  `vrmod` now parses to derive a car's display name and stats automatically.
- **`.mod` (meshes).** Editing here was limited to finding and renaming the
  **texture-name string** inside the file; actual geometry was always done in
  Zmodeler and re-exported.
- **`english.lng`.** AI driver names and track slot names were changed with a
  fixed-width, never-longer-than-the-original hex edit — the same constraint the
  modern switcher works within.
- **The engine.** Rather than being decompiled, `race.bin` was **binary-patched**:
  Sucahyo lifted the limits (2007), and Charlie Ward/beatcracker fixed the GPU
  check (2016). These are the two patches most modern installs still rely on.

So the community had mapped the *what* of these formats byte by byte. What it
never had was the *how at scale* — a way to read and write them programmatically
rather than one file at a time in a hex editor.


## Preservation & sources

The game's mods are, remarkably, preserved several times over:

- **Val's site**, captured on the Internet Archive as downloadable *items* (not
  just Wayback pages): "Val's Viper Racing Site Backup" (a full ~3 GB copy of the
  site, mods included) and a smaller later capture. Val also maintains
  valsgames.com, which points back to these.
- **A community "Complete CarPack / TrackPack" collection** on the Internet
  Archive (39 car-pack volumes + 6 track-pack volumes), sourced from Val's set.
- The original tutorials, tool binaries, and readmes are inside those captures.

One gap worth noting: those public archives are Val-centric. **Frank Wolf's ~155
cars are not in them**, and his original site is long dead — so aggregated
community collections may be their only surviving copy.


## Why `vrmod`

This project was built to find the underlying file types and coding structures
that made all of the above necessary in the first place — and, having found them,
to do in software what the community did by hand:

- read a car or track's real geometry, textures, physics, sounds, spec sheet and
  AI line directly, with no hex editor;
- render them in 3D in the browser;
- edit and write them back safely;
- and check an install for the very fixes (the GPU patch, the limit patch,
  resolution, audio) that this community discovered.

It stands entirely on the shoulders of the people above. Where their tools were
single-purpose and manual, `vrmod` aims to be one library that understands the
formats — so the next twenty years of keeping *Viper Racing* alive don't have to
start in a hex editor.
