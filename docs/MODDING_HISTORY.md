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
- **M. Walden** — toolmaker: the **Surface Modifier** and **UV Map Editor** for
  `.mod` files, and the programmer behind the **Tire Editor**.
- **Matthias Nyberg** ("Matt") — the tyre/handling expertise behind the **Tire
  Editor**, and the source of the finished tyre sets it could apply.
- **Maurizio** — author of **VRDSC**, which advertised a dedicated server to the
  VRgt RaceFinder.
- **BlasterMaster555** ("Impreza") — ran `wrxds.mine.nu`, from 2003 a Viper
  Racing dedicated server, and wrote the community's most complete **car
  creation / conversion tutorial** (19 pages). His machine also hosted the FTP
  archive Val's site linked as "accumulated from 1998". Archived copy:
  [`docs/tutorials/wrxds-car-tutorial/`](tutorials/wrxds-car-tutorial/).
- **Max** — a car modder ("Add-on cars by Max").
- …and the wider community of racers and converters who contributed cars,
  tracks, retextures, and testing over the years.


## The community toolchain

A capable but **entirely manual** set of tools. Where a binary survives in the
preserved archives it's marked ✓.

### Archive / packaging — Frank Wolf's **RESTools**

Most of the converters below were not loose utilities but one suite, **RESTools**
by Frank P. Wolf, distributed from his own site (`members.aol.com/racingwolf999/`)
— the same address his cars and CarMan came from. The wrxds tutorial (see
*Preservation & sources*) walks through using them and names the set.

- **rescrack.exe** ✓ — unpack a `.car` / `.res` / `.trk` archive into its loose
  members, plus a `reslist.txt`.
- **mkres.exe** ✓ — (re)pack an archive from a `reslist`.
- **mkcar.exe** — build the `.car` itself. Named in the tutorial's step 4
  alongside `mktex`/`mkres`/`mksfx`; no surviving binary located yet.
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
- **Bob's Track Builder (BTB)** — track authoring (with a BTB→Viper tutorial); the
  Pro edition is still sold on Steam, though the tutorial targets the original.
- **vrTrackMaker** ✓ (Sucahyo, "VR simple Track Maker") — sweeps a parameterised
  cross-section (Road / Wall / Side / Rumble1 / Rumble2 / Grass) along a `.ase`
  spline from 3DS Max to produce the MKWORLD source set, and generates the AI
  path too. Fully specified in
  [VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md#vrtrackmaker-the-stage-in-the-middle).
- **MKWORLD / mkfltoa** ✓ — generate the surface + collision set
  (`.sol` / `.obt` / `.bsp` / `.grf` / `.bpp`) from a text scene description;
  **nhmkworld** ✓ — the graphic pass that adds objects to `.grf` / `.bpp`.
- **MKSTAMP / Stp2Tga / tga2stp** ✓ — the `.stp` menu screenshot and `Trackmap`.
- **MKTABLE / mkilicc** ✓ — data tables / the AI racing lines. `mkilicc -nolat`
  is run three times: `track.ili`→`track.ild` (the track-map line),
  `track-ai.ili`→`default.ili` (forward AI line) and
  `track-ai-reverse.ili`→`rdefault.ili` (**reverse** AI line).
- **make-track.bat + compile-track.bat** ✓ — the two batch files that drive the
  whole build and then pack the `.tra` with `mkres @reslist.txt`. Reproduced
  verbatim in [VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md#how-a-track-is-actually-built).
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


## Master chart — every known tool, and its `vrmod` counterpart

Consolidated from the sections above, from **vrgt.com's downloads page** (see
*Preservation & sources*), and from the community binaries that still ship inside
`Data/`. **Creator** is listed only where a source actually names one. The last
column is the honest state of `vrmod`'s coverage — including where there is none,
since that is the clearest map of what is left to build.

Two kinds of software are kept apart deliberately:

- **Part A — community tools:** one-off utilities written *for Viper Racing*, by
  the people above. These are the fragile part of the record. Several exist only
  as a single surviving binary, and the sites that hosted them are gone.
- **Part B — third-party software:** general-purpose commercial or free
  applications the workflow leaned on. Not Viper-specific, not at risk, and
  mostly still obtainable — but you can't reconstruct how a car was actually
  built without knowing which ones were in the chain.

---

## Part A — community tools (Viper Racing–specific)

### Archive / packaging
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **rescrack.exe** *(RESTools)* | Frank P. Wolf | Unpack `.car`/`.res`/`.trk` to loose members + `reslist.txt` | `vrmod unpack` |
| **mkres.exe** *(RESTools)* | Frank P. Wolf | Repack an archive from a `reslist` | `vrmod pack` |
| **mkcar.exe** *(RESTools)* | Frank P. Wolf | Build the `.car` itself | `vrmod pack` / `carfork` |
| **extract.exe** | — | Alternate unpacker | `vrmod unpack` |

### Cars
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **CarMan / CarMan2** | Frank P. Wolf | Activate/deactivate cars; CarMan2 v2 did whole sets and 17 at once | Switcher (car enable/disable via `Data/Disabled`) |
| **AICarMan** | Frank P. Wolf | Set up the AI field | `vrmod aifield` |
| **WheelMan** | Frank P. Wolf | Wheel manager | Parts drawer (wheel rows) — *partial* |
| **vrcarrenamer** | — | Rename a car | `vrmod carfork` — does the re-prefixing a plain rename can't |
| **cf2txt / txt2cf** | — | `.cf` physics ⇄ editable text | `vrmod cfdump` / `txt2cf` / `cfset` / `cfpatch` |
| **Viper Racing Tire Editor** | M. Walden (programmer), Matthias Nyberg (tyre data) | Tyre/handling tuning, exact accel/decel times | `.cf` stats editor — *partial* (no tyre-specific UI) |
| **Surface Modifier** | M. Walden | Modify `.mod` surface look; split a `.mod` into objects by texture | `vrmod modinfo` + material-preserving OBJ export — *partial* |
| **UV Map Editor** | M. Walden | Edit UV/texture alignment on `.mod` models | **none** — UVs round-trip through OBJ but aren't editable in-tool |
| **Auto Image Tiler** | Sucahyo | Stitch textures *and* rewrite the `.mod` UVs + texture refs to match | **none** |

### Textures & sound
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **mktex / tex2tga / tga2tex** *(mktex: RESTools)* | Frank P. Wolf (mktex) | `.tex` ⇄ `.tga` | `vrmod tex2tga` / `tga2tex`, plus in-app import/export |
| **jpg2sky ("JPG 2 SKY")** | Sucahyo | Split one image into the 4 sky tiles | `vrmod skyexport` / `skyimport` (one panoramic TGA, both ways) |
| **MKSTAMP / Stp2Tga / tga2stp** | — | `.stp` menu screenshots and `Trackmap` | `stp.py`, `vrmod trackmap` |
| **mksfx** *(RESTools)* | Frank P. Wolf | `.wav` → `.sfx` | `vrmod wav2sfx` / `sfx2wav` |

### Tracks
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **Trackman** | Frank P. Wolf | Install add-on tracks into the 8 game slots | Switcher track install/restore; `vrmod trk2tra` produces the `.tra` it consumes |
| **Track Maker** | Sucahyo | Build a track from a 3DS Max ASE file | **none** — track *authoring* is out of scope so far |
| **vrTrackMaker** | Sucahyo | Consumes a **`.ase` spline exported from 3DS Max** and emits the MKWORLD source set. Emits only surface codes 0, 10 and 16, so water and dirt must be hand-edited into the generated text afterwards — in *both* source files | **none** — this stage, plus the spline generation feeding it, is the one real gap left in track authoring |
| **MKWORLD / mkfltoa / nhmkworld** | — | Generate the surface + collision set (`.sol`/`.obt`/`.bsp`/`.grf`/`.bpp`) from a text scene | **none** — the hard part of track editing (see below) |
| **BPP-2-Mod Converter** | Sucahyo | `.bpp` ⇄ `.mod`: fix holes, add surface, read surface types, merge verts | `vrmod bpp2obj`, `bppinfo`, `bppsurface` (read + surface retag; no `.mod` → `.bpp` rebuild) |
| **Bad Poly Fix** | Sucahyo | Repair the "bad polys" that make holes after conversion | `vrmod collisioncheck` *detects*; no repair |
| **MKTABLE / MKILI** | — | Data tables / the AI racing line (`.ili`) | `ili.py` reads; `vrmod trackmap` draws from `track.ild` — *partial* |
| **trkaitweaker ("Track AI Tweaker")** | — | Make AI drive add-on tracks competently (also Nascar Heat) | **none** |

### Engine patches & install fixes
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **"High Poly race.bin" / 1.2.4 BETA** | Sucahyo (2007) | 95k-poly tracks; raised per-object vertex cap; spoiler visible without an `option.cfg` edit; mirror in F1–F8 | `vrmod patch --max-verts`; `vrmod doctor` reports the installed build and budget |
| **v1.2.5 (2016) / v1.2.6 (2017)** | Val Novak; GPU fix by Charlie Ward from beatcracker's solution | Modern-GPU video-memory fix, sound fix | `vrmod patch-vram`; `vrmod racebin` identifies the build |
| **4983A Spoiler Mod Patch** | Sucahyo | Force `<car>S.mod` spoilers to always show | Covered by the patched `race.bin` lineage above |
| **VR Resolution Changer** | — | Run at resolutions up to 1920×1200 | `vrmod resolution` (+ aspect-ratio correction) |
| **Lapman** | Frank P. Wolf (on findings by "Joe") | Change the 3/8/20 lap counts | **none** |
| **Optman** | Frank P. Wolf | Extra `options.cfg` settings (e.g. the spotter) | *partial* — `vrmod aifield` writes `options.cfg`, but only the field size |

### Multiplayer & community infrastructure (historical)
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **VRgt RaceFinder** | VRgt team | Server browser + chat for online racing | n/a — the service is gone |
| **VRDSC** | Maurizio | Advertise a dedicated server to the RaceFinder | n/a — pairs with `race.bin`'s `-dedicated` flag (runtime doc §2) |

### No prior equivalent
Parts of `vrmod` answer to nothing in the historical toolchain, because the
community did these by hand or not at all: the **3D viewers** (car, cockpit,
track, parts), **`vrmod doctor`** (install health), **`carshot`/`gallery`**,
the **cockpit calibration** tools (`cockpitdump`/`cockpitset`), the **LOD-chain
generator** (`modlod`), **`carfork`**, and the **horn-ball tuning** (`hornball`).

> **What the gaps say.** Every "none" above is in track *authoring* — mesh
> generation, collision building, AI-line tuning, UV work. That is not an
> accident of effort: the community needed **four separate tools** for one track
> (Track Maker, BPP-2-Mod, Bad Poly Fix, Track AI Tweaker) because the visual
> mesh, the collision BSP, the solids and the AI lines all have to stay mutually
> consistent. `vrmod` reads all four layers today but writes only textures — and
> closing that gap is a design problem, not a parsing one.

---

## Part B — third-party software (general-purpose)

Not written for Viper Racing, and not at risk of being lost — but the workflow is
unreconstructable without them. A car conversion was **modelled** in one of these
and only then pushed through the community converters in Part A.

| Software | Role in the workflow | Status | `vrmod` relationship |
|---|---|---|---|
| **Zmodeler 1.07** | *The* mesh editor of the scene — nearly every car conversion (NFS4 / Sports Car GT → Viper) passed through it, with the **vrzmodtemplate** as its starting point | Free at the time; the old 1.x line is what the template targets | `vrmod mod2obj` / `obj2mod` replaces the import/export step, so any modeller works |
| **3DS Max 3.1** | The professional alternative; also what **Track Maker** consumed, via its `.ASE` export | Commercial, long superseded | `mod2obj` / `obj2mod` (OBJ instead of ASE) |
| **Blender** | The modern equivalent, and the practical target today | Free, current | Direct: the OBJ round-trip is designed so a mesh opens and re-imports cleanly |
| **3DSimED** | Racing-sim model editor/converter. **Reads Viper Racing `.mod` files directly** (confirmed by loading a car mod), so it opens both ends of the old conversion pipeline: the sims cars were converted *from*, and Viper itself | Commercial, current | Overlapping, not dependent — 3DSimED imports `.mod` natively; `vrmod` goes via `mod2obj`/`obj2mod` so any modeller works. Either is a valid path onto the geometry |
| **GIMP** | The image editor of choice for skins and track textures | Free, current | `vrmod tex2tga` / `tga2tex` produce/consume what it edits; the app does import/export in-place |
| **Bob's Track Builder (BTB)** | Where a modern track starts: model it here, export `.dof`. The tutorial screenshots show **v0.8.0.0**; the pipeline below uses **Pro** | Split three ways — see below. **Bob's Track Builder Pro is on Steam and current**; the tutorial-era line is not | **none** — but no longer a dead end: the route from here to a finished track still runs, see below |
| **XVi32** | The hex editor behind nearly every non-geometry edit: the `<car>1.tab` spec sheet, texture-name strings inside a `.mod`, names in `english.lng` | Free, still available | Superseded — those three edits are now `cfset`/`carfork`/the switcher |

#### Bob's Track Builder is three different products, and only one is still available

Worth spelling out, because "BTB" in a 2000s-era tutorial does not mean the BTB you can buy today:

| Version | Exports to | Status |
|---|---|---|
| **BTB** (the original, `0.8.0.0` in the tutorial screenshots) | generic mesh; the Viper path was community-built on top | superseded |
| **BTB Evo** | GTR2, GTL, Race07 | **lost** — never reached Steam, the vendor disabled purchase, no working download is known to exist anywhere. Last updated 2014, XP-era |
| **[Bob's Track Builder Pro](https://store.steampowered.com/app/993270/Bobs_Track_Builder_Pro/)** | current sims | **available now, on Steam** |

The developer's current focus is Race Track Builder, which targets Assetto Corsa only.

There was never an official Viper Racing exporter in any version. BTB contributes the *geometry*, which is
then carried through Zmodeler and 3DS Max before reaching the MKWORLD source files. The full route is
[documented by HerbFargus](https://github.com/HerbFargus/viper-racing-legacy-modding-tools/wiki/Creating-a-Custom-Track)
from tracks built with it, and written up step by step in
[VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md#the-modern-workflow-end-to-end):

```
BTB Pro  ->  .dof  ->  Zmodeler  ->  .mod + .3ds  ->  3DS Max (spline)  ->  .ase
         ->  vrTrackMaker  ->  MKWORLD source set  ->  make-track.bat  ->  the track
```

So the position is much better than this chart used to imply. **Track authoring is not a dead end and not
a research problem — it is a working pipeline that still runs**, with a purchasable modeller at the front
and recovered tools at the back. What `vrmod` lacks is the middle: the spline-generation and vrTrackMaker
stages, i.e. `.ase` spline plus mesh set in, MKWORLD source files out. That is a bounded piece of work with
both ends specified, which is the concrete shape any future track-authoring scope would take.

> **The honest summary of Part B:** the community's real "editor" was a
> general-purpose 3D package plus a hex editor. Everything in Part A existed to
> bridge between those and the game's formats. `vrmod` collapses that bridge —
> which is why its Part B column is mostly "any modeller you like".



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
- **[viper-racing-legacy-modding-tools](https://github.com/HerbFargus/viper-racing-legacy-modding-tools)** —
  a curated republication of that material on GitHub, organised as *Car Tools*,
  *Car Mods*, *Track Tools* and *Track Mods*, sourced from Val via vnovak.com.
  Its wiki also carries the
  [modern track-building workflow](https://github.com/HerbFargus/viper-racing-legacy-modding-tools/wiki/Creating-a-Custom-Track),
  which is the only description of the front half of that pipeline anywhere —
  it is not in Val's tutorials, the wrxds tutorial, or the tool readmes.

### vrgt.com — the other hub, mostly lost

Alongside Val's site, **vrgt.com** was a central gathering point for the scene:
the VRgt mod, online championships, the RaceFinder, and a downloads page that
hosted much of the toolchain above. It also ran **dedicated forums for car and
track modding** — the place where a lot of this knowledge was originally worked
out in public.

It went offline around **2019** and was never archived as a whole. What survives
is Wayback captures and whatever individuals kept; the forum threads in
particular appear to be **gone**. The downloads page is one of the pieces that
did survive, and it is the source for several attributions in the chart above
(FPWolf's Trackman/Lapman/Optman, M. Walden's `.mod` tools, Sucahyo's track
utilities) that are recorded nowhere else here.

> Its loss is the reason this document exists in the form it does. Much of what
> follows was re-derived from the binaries rather than read from a tutorial,
> because the tutorials are no longer there to read.

**How much was lost, precisely.** The forum's front page survives in the Wayback
Machine (captured 20 May 2019, weeks before the site went dark), and it carried
its own statistics — so the scale is not a guess:

> *"Our users have posted **9,734 Posts** in **913 Topics** in 14 Forum(s)"* —
> **311 forum members**. Running Web Wiz Forums 7.01.

| Board | Topics | Posts | Last post |
|---|---:|---:|---|
| General | 420 | 3,356 | 31 Mar 2019 |
| **Editing → Cars** | **175** | **2,344** | 5 Jan 2019 |
| **Editing → Tracks** | **94** | **1,474** | 17 Dec 2015 |
| Screenshots | 34 | 793 | 29 Dec 2011 |
| Races | 64 | 494 | 17 Oct 2015 |
| Best LapTimes | 14 | 465 | 16 Jan 2008 |
| VRgt RaceFinder | 33 | 208 | 12 Jan 2011 |
| Drifting Virtually | 7 | 111 | 29 Oct 2009 |
| Drivers | 26 | 101 | 5 Jul 2011 |
| Other programs | 9 | 41 | 8 Jan 2011 |
| Drifting IRL | 7 | 28 | 19 Jul 2007 |

The two **Editing** boards alone — the ones that held the car- and track-modding
knowledge — account for **269 topics and 3,818 posts**, roughly **39% of
everything ever posted there**. Not one of those threads is retrievable: the
front page was captured, the threads behind it were not.

Two further details the capture preserves. The board list shows 11 boards while
the statistics count **14 forums**, and the page legend includes *"No Access"* —
so three boards (the empty **Development** category among them) were private.
And the last posts in **Cars** (Jan 2019) and **General** (Mar 2019) show the
place was still *active* right up to the end; it didn't fade out, it simply
stopped being hosted.

The capture also quietly corroborates this document's attributions: the last
posters include **sucahyo**, **val5662** (Val) and **Matt** — the same people
credited above for the engine patch, the tracks, and the Tire Editor.

### wrxds.mine.nu — the tutorial that survived

Where vrgt's forums are gone, one substantial piece of documentation came
through intact: the **Car Creation / Conversion Tutorial** at
`http://wrxds.mine.nu/tutorial/`, by **BlasterMaster555**. Nineteen pages
covering the whole pipeline — meshes, dashboard, RESTools, textures, sounds,
performance, the car's long name, packing, and a second pass of fixes down to
the brake lights.

The same host carried the FTP archive (`ftp://wrxds.mine.nu/vrmods/`) that Val's
site pointed at as *"accumulated from 1998"*. That listing was **never captured**
— the files and their names are gone. The tutorial pages were, and are now kept
in [`docs/tutorials/wrxds-car-tutorial/`](tutorials/wrxds-car-tutorial/) with
their images and the assets they offered for download.

It matters twice over. It is the era's best surviving account of how a car was
actually built; and it is **the missing citation** for parts of this very
document. The tool list above — Zmodeler 1.07, XVi32, `vrzmodtemplate`, the
`rescrack`/`mkres`/`mktex`/`mksfx` set — is documentation-derived knowledge, not
anything recoverable from a binary, but no source was recorded for it. Reading
the tutorial supplied what had been lost in the retelling: that those converters
are **one suite** (Frank P. Wolf's **RESTools**), that it includes **`mkcar`**,
and where it was distributed.

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
