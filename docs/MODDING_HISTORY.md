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
- **Eric "Zero"** — supplied the finding behind the **2017 `v1.2.6`** `race.bin`.
  Val's note shipped with that build credits him: *"According to Zero's information
  I modified my 2016 race.bin so as to not always show the extra rear wing in the
  viper.car and ai viper cars."* That is the last change anyone made to the engine,
  and it started with his diagnosis. He is also a car modder in his own right — the
  **2018 `Viper.car` and `ViperGT.car` retextures** (3D modifications, brakes and a
  rear spoiler built from scratch over the EA model) and a **2019 `ViperGT v2.0`**
  adding a full interior. His readmes are unusually careful about attribution, and
  are the source for several of the names on this page.
- **Dave Broske** and **Dave Pollatsek** (Monster Games) — the two MGI programmers
  who kept supporting the mod scene years after release. Community readmes thank
  them for a decade as *"both Dave's from MGI"* and *"Dave P. and especially
  Dave B."*, rarely spelling either out; Zero's 2018 readmes name both. Broske built
  the **1.2.3 beta** `race.bin` for the VRgt team — the binary every later community
  build is hex-edited from.
- **Matthias Walden** — toolmaker: the **Surface Modifier** and **UV Map Editor**
  for `.mod` files, the **ResEdit** tool, and the programmer behind the
  **Tire Editor**.
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
- **extract.exe** ✓ (Sucahyo) — **not an unpacker.** A multi-function track
  utility, recovered 2026-09-10 with its own readme: `.ase` → vertex text for
  mkflt, `.ase` → `.ili`, `.ase` → **wall quad objects**, `.ase` → a "pipeline"
  of walls down both sides of the road, **mod2quad** (wall quads from a `.mod`,
  with an added-height box), `.bpp` → `.mod`, `.ase` → `camera.tab`, and
  **injection of obstacle records into `track.obt`**. Its earlier description
  here as an unpacker was wrong.

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
- **vrTrackMaker** ✓ (Sucahyo, "VR simple Track Maker") — consumes a `.ase`
  centreline from 3DS Max and produces the **driving model**: collision surfaces
  with their material codes, walls, checkpoint gates, the four `.ili` racing
  lines and a speed profile. It also emits simple swept meshes, but in a modern
  BTB-based build those are a fallback — the visible track comes from BTB via
  Zmodeler. Fully specified in
  [VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md#vrtrackmaker--the-driving-model-not-the-track).
- **MKWORLD / mkfltoa** ✓ — generate the surface + collision set
  (`.sol` / `.obt` / `.bsp` / `.grf` / `.bpp`) from a text scene description;
  **nhmkworld** ✓ — the graphic pass that adds objects to `.grf` / `.bpp`.
  `vrmod` now writes `.bsp`, `.obt` and `.grf` itself, and packs the `.tra`, all
  confirmed in a track that loads and drives; only `.bpp` still needs these.
- **MKSTAMP / Stp2Tga / tga2stp** ✓ — the `.stp` menu screenshot and `Trackmap`.
- **MKTABLE / mkilicc** ✓ — data tables / the AI racing lines. `mkilicc -nolat`
  is run three times: `track.ili`→`track.ild` (the track-map line),
  `track-ai.ili`→`default.ili` (forward AI line) and
  `track-ai-reverse.ili`→`rdefault.ili` (**reverse** AI line).
  `vrmod` now generates these lines directly from a centreline
  (`ili.generate`), confirmed in a track that loads and drives — so neither
  `mkilicc` nor its `.ili` source format is needed for a generated track.
- **make-track.bat + compile-track.bat** ✓ — the two batch files that drive the
  whole build and then pack the `.tra` with `mkres @reslist.txt`. Reproduced
  verbatim in [VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md#how-a-track-is-actually-built).
- **trkaitweaker** ✓ — AI tuning. **jpg2sky / sky-tga2tex** — the four skybox tiles.

### Engine patches & `race.bin` versions

Every modern install runs a community-patched `race.bin` (the game engine). The
version is shown in-game at the **Options screen, bottom-right corner**, and is
stored as a plain string inside `race.bin` itself (near offset `0x0D37FD` — e.g.
`1.2.4 BETA`, `v1.2.5 2016`).

> That indicator arrived **with the second pressing**. The first pressing runs
> `race.exe`, which contains no version string at all, and its Options screen shows
> nothing in that corner — confirmed in game. See *The first pressing shipped a release
> candidate* below.

**Official (Sierra / Monster Games):**

| Version | Patch file | Notes |
|---|---|---|
| 1.0 | (retail, first pressing) | engine is `race.exe`, built **Oct 21 1998 08:49:56**. A **release candidate** — see below |
| 1.1 | `viper11.zip` **and** a retail repressing | both exist. The second pressing's engine is `race.bin`, built **Jan 25 1999 11:47:39**, readme dated 8 Feb 1999. Whether the downloadable patch performs the same `race.exe` → `race.bin` transition is **untested** |
| 1.2 beta | `viperpatch12beta.zip` | **probably never a distinct release** — see below. The URL is indexed but was never observed serving a file |
| 1.2.1 beta | `viperpatch121beta.zip` | Windows 2000 support, multiple controllers, an XP sound tweak. The **last patch MGI distributed themselves** |
| 1.2.3 beta | `Patch_1.2.3(Beta).zip` | built by **Dave Broske (MGI)** for the VRgt team and released by *them*, not by MGI. Every community build is hex-edited from this binary |

Monster Games' own server only ever hosted a handful of downloads: the Viper patches,
two NASCAR Heat patches and a Heat changelog. **No official car or track ever existed.**

##### Is there a 1.2 beta at all?

Probably not, and it is worth writing down so nobody spends another decade looking.

`viperpatch12beta.zip` appears in the Wayback index, which is why it gets cited as a lost
release. But a URL enters that index when a crawler **follows a link** to it — being
indexed is not evidence it ever served anything. Its capture history is one line:

```
viperpatch12beta.zip    2021-01-26   404          <- the only capture, ever
viperpatch121beta.zip   2005 404 · 2006 200 · 2007 200 · 2021 404
```

The 1.2.1 was retrieved successfully twice, in 2006 and 2007, with the same content
digest both times. The 1.2 was **never** seen served, in any capture, by anyone.

Two further things point the same way. A June 2002 thread on NTCompatible has someone
hunting specifically for "the Viper Racing 1.2 Beta patch" for days, on a compatibility
note's recommendation — and what he eventually finds, quotes the readme of, and declares
fixed is **`viper121beta.zip`**. Nobody in the thread produces a 1.2. And of the ten
distinct `race.bin` builds catalogued for this project, **none carries a `v1.2` stamp** —
they run 1.0, 1.1, 1.2.1, 1.2.3, 1.2.4, 1.2.5.

The likeliest reading is that "1.2 beta" is simply how people referred to the 1.2.1 beta,
or that a 1.2 existed so briefly it was replaced before anyone archived it. Either way,
the patch everyone has been hunting for is the one already in hand.

#### What 1.1 actually fixed — from the patch's own readme

The official patch survives as `viper11.zip` → **`viper11.exe`, 988,905 bytes, dated
26 February 1999**. It is a **16-bit NE executable** (a Wise "Sierra Patch Installation"),
with two consequences worth knowing: archivers cannot open it, and **it will not run on
64-bit Windows**, which dropped 16-bit support entirely. Its payload has to be recovered
by other means.

Inside is `race.res` **byte-identical to the second pressing's** — so the patch and the
repressing carry the same updated resources — and a readme dated **19 January 1999**
listing the fixes in MGI's own words:

| area | what 1.1 changed |
|---|---|
| replays | mouse bounds stayed at 640×480 in higher modes, putting the replay controls out of reach. Now set per video mode |
| force feedback | "very weak" on the Logitech FF wheel in particular — forces boosted |
| mirror | had a fixed size, so it shrank to nothing at 1024×768. Now scaled to the video mode |
| **`-nointro`** | **introduced by this patch.** "The introductory movie causes all sorts of problems. It may even have lingering effects on gameplay, causing hangs and lockups. Trying to escape from the intro movie often causes the game to crash." |
| **memory leak** | "Replay: Causes Crash on Exit From Program … the game will crash on exit, **reporting a memory leak**. This memory leak has been fixed." |
| replay audio | cars silent when the race ended while they were still "teleporting" |
| garage | locked up or hung the system on some machines |
| multiplayer | TAPI "too sensitive to non-compatible devices"; modem init "too forceful"; synchronisation hangs under packet loss; teleporting remote cars now transparent so they cannot be collided with |

Two of those are worth pulling out. **`-nointro` originates here** — the runtime reference
lists it among the engine's flags, and this is why it exists. And the *"crash on exit
reporting a memory leak"* is the **same panic class** a modern builder hits when objects
are created without reaching the engine's master object array (runtime reference §4):
MGI shipped a fix for it in 1999.

> What the patch does **not** contain is a game executable or a `race.bin`, and there is
> no room for one — `race.exe` alone is 2,404,451 bytes. How the engine changes above are
> actually delivered is **not established**.

> **A note on "official".** The Patches Scrolls — which mirrored these for decades — lists
> **1.1 as official** and both **1.2.1 beta and 1.2.3 beta as unofficial**. That is a
> classification by *support status*, not by origin: 1.2.1 was hosted on mgiracing.com
> itself and its readme is written in MGI's own voice ("we don't have service pack 2
> installed anywhere in the office yet"). The table above classifies by **where the file
> actually came from**, which is why 1.2.1 sits under official here and 1.2.3 — built by
> an MGI programmer but released by the VRgt team — sits on its own.

**Community `race.bin` (unofficial, built on 1.2.3):**

| In-game string | Author / date | What it adds |
|---|---|---|
| `1.2.4 BETA` | Sucahyo, 4 Oct 2007 | 95,000-polygon track support; 20,000 vertices/object (≈100k-poly cars possible, though total per-scene vertex limits remain — ~14 AI cars at 20k each can still crash); the rear **spoiler** (`<car>S.mod`) visible without an `option.cfg` edit; the **mirror** visible in F1–F8 views |
| `v1.2.5 2016` | Val Novak, 20 Mar 2016 | Sucahyo's 1.2.4-beta **plus** Charlie Ward's modern-GPU / video-memory fix (from a DirectDraw solution by **beatcracker**), **plus** a scratchy-sound fix — the standard modern binary; runs on Windows 10/11 |
| `v1.2.6 2017` | Val Novak, 15 Nov 2017, on a finding by **Zero** | same as 1.2.5 but the extra rear wing is **no longer always shown** on the viper/AI cars. **Measured: exactly 46 bytes differ** from 1.2.5 (`0x48b68`–`0xe2535`), same length and still 512-byte aligned — a hex edit, not a recompile |

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

### The first pressing shipped a release candidate

The retail v1.0 disc — Redump #61183, `Viper Racing (USA)` — boots to a title screen
carrying this, in green above the artwork:

```
Oct 21 1998 08:49:56 NON-DEBUG MSVC-4.0
feedback@mgiracing.com
Release Candidate 1:  CONFIDENTIAL
Copyright © 1998 MGI. All rights reserved.
```

`Release Candidate 1:  CONFIDENTIAL` and the feedback address appear **only** in v1.0's
`race.exe`. Neither `race.bin` — v1.0's or v1.1's — contains them.

**This is why the first pressing carries a symbol map.** `race.exe` has a ~1 MB overlay
holding a full linker map: **10,414 symbols across 296 object files** (`physics:control.obj`,
`ai:driver.obj`, `gx:gfx.obj`, `edit:modtool.obj`, `multi:server.obj`…). It also carries the
*reader* for it — `No mapfile present`, `Couldn't open exe: %s`, `Can't map view of file` —
so the binary **opens itself and symbolises its own crashes**:

```
Panic : Can't load options.def
trace: byte 0x88 of "?OptionsBegin@@YAXXZ"
trace: byte 0x72 of "?app_begin@@YAXXZ"
trace: byte 0x1b of "?AppMain@@YAXXZ"
trace: byte 0x120 of "_WinMain@16"
```

None of that was a gift to modders. It is an RC build with its diagnostics still switched
on, pressed to manufacturing.

**It also explains the second pressing.** Comparing the two discs file by file, 306 of the
files are identical and only 9 differ — but the executable is replaced outright, and the
engine moves out of it into `race.bin`:

```
v1.0  Data\race.exe    2,404,451 b   .text 890,368   + a 1 MB symbol-map overlay
v1.1  Data\Viper Racing.exe 388,608 b   .text  16,384   (a launcher; no map, no banner)
```

So February 1999 was not a tidy-up. **Sierra and MGI pressed a release candidate, and the
v1.1 disc replaced it with the actual release build** — banner gone, map gone, RC markings
gone, the CD check and environment gates moved into a proper launcher.

The irony is worth stating plainly: the artefact this community has reverse-engineered
against for twenty-five years — the binary long circulated as `ai-tweaker.exe`, which is
**byte-identical to v1.0's `Data\race.exe`** — reached the public through a manufacturing
mistake.

> **Practical consequence.** A *first* pressing gives you the symbol map, self-symbolising
> crash traces, and the RC title screen. A *second* pressing gives you none of it. If you
> are buying a disc to work from, the revision matters.

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

> **`reslist.txt` had two incompatible shapes, and that is why a "reorder" step existed.** An
> extracted track's list is one long whitespace-separated row (castle's is 62 entries on a single
> line); the track-building kit ships one entry per line (19 entries, 18 newlines). VRcarEditor's
> tutorial spells out the consequence — its REORDERRESLIST button "lines up the reslist.txt contents
> in a row in order for mkres.exe to recognize it". A hand-maintained list that two tools in the same
> chain disagreed about is the kind of failure `vrmod pack` removes by not needing a list at all.

### Archive / packaging
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **rescrack.exe** *(RESTools)* | Frank P. Wolf | Unpack `.car`/`.res`/`.trk` to loose members + `reslist.txt` | `vrmod unpack` |
| **mkres.exe** *(RESTools)* | Frank P. Wolf | Repack an archive from a `reslist` | `vrmod pack` |
| **mkcar.exe** *(RESTools)* | Frank P. Wolf | Build the `.car` itself | `vrmod pack` / `carfork` |
| **extract.exe** | Sucahyo | Multi-function track utility — `.ase`→vertex text/`.ili`/wall quads/pipeline, mod2quad, `.bpp`→`.mod`, `.ase`→`camera.tab`, obstacle injection into `track.obt` | `vrmod trackgen` (`--walls`, and `mesh_to_wall_quads` for mod2quad); `bpp2obj`; obstacle records not yet written |
| **VRcarEditor** | — (2008 tutorial by a community member) | A .NET front end that drives the car-stats chain: rescrack → cf2txt → *edit the text by hand* → mkcar → **reorderreslist** → mkres, thirteen steps across six tools to change one number. Carries no knowledge of the `.cf` fields itself | `vrmod cfdump` / `cfset` / `cfpatch` — one command, in place |
| **VR-ResEdit** | Matthias Walden | GUI front end for the archive command-line tools — browse, extract, import, rename and discard members of a `.car`/`.res`/`.trk`, with drag-and-drop and multi-select. v0.96, freeware. Supports both Viper Racing and Nascar Heat resource types | Mod manager + `vrmod unpack`/`pack`/`list` |
| **ViperMan** | — | Setup manager and launcher: edit `.csu` setups outside the game, copy/paste them between slots, tracks and installations, manage multiple installs, and launch Frank Wolf's utilities. Aware of tracks and cars disabled by TrackMan/CarMan. v0.5 beta | Mod manager (install/restore); setup editing — **none** |
| **mod2quadnoz.exe** | Sucahyo | Wall quads from a `.mod`, with a bottom/top height box; its 2016 tutorial documents the rule that **faces must be vertical** — no tilting, no horizontal parts — and suggested heights (guard rails +1.0, small billboards +2.0, big billboards +4.0, banner posts +8, one-storey buildings +10) | `trackgen.mesh_to_wall_quads` — same rule, reached independently |

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
| **Track Maker** | Sucahyo | Build a track from a 3DS Max ASE file | `vrmod trackgen` — generates the whole source set from a centreline |
| **vrTrackMaker** | Sucahyo | Consumes a **`.ase` spline exported from 3DS Max** and emits the MKWORLD source set. Emits only surface codes 0, 10 and 16, so water and dirt must be hand-edited into the generated text afterwards — in *both* source files | `vrmod trackgen` — all five surface codes, both files written from one list, and the centreline can be recovered from a road mesh instead of drawn in Max |
| **MKWORLD / mkfltoa / nhmkworld** | — | Generate the surface + collision set (`.sol`/`.obt`/`.bsp`/`.grf`/`.bpp`) from a text scene | `.obt`, `.bsp` and `.grf` written natively; barriers declared by `vrmod trackgen --walls` and compiled to `.sol` by MKWORLD — *partial*: **`.bpp` still needs `nhmkworld`** |
| **BPP-2-Mod Converter** | Sucahyo | `.bpp` ⇄ `.mod`: fix holes, add surface, read surface types, merge verts | `vrmod bpp2obj`, `bppinfo`, `bppsurface` (read + surface retag; no `.mod` → `.bpp` rebuild) |
| **Bad Poly Fix** | Sucahyo | Repair the "bad polys" that make holes after conversion | `vrmod collisioncheck` *detects*; no repair |
| **MKTABLE / MKILI** | — | Data tables / the AI racing line (`.ili`) | `ili.generate` writes all three lines from a centreline; `vrmod` writes the `.obt` table natively — *partial*: fields 12/13 (AI pacing) approximated |
| **trkaitweaker ("Track AI Tweaker")** | Sucahyo | Recompute the AI speed along a `.ili`/`.ild` from the path's curvature, with *mult*/*add* shaping cornering-vs-straight speed and *forward*/*backward lookup* setting how far ahead it brakes and how early it accelerates out. Also converts a Nascar Heat `track.ild` back to `fooland.txt` | **none** — but its readme is the only first-hand account of the AI model recovered, and it identifies what fields 12/13 are for (see the format reference) |
| **Empty `drivers.res`** | Sucahyo (circulated by Val, 2009/2014) | The stock file bakes 524 per-track `.ilg` AI lines, so on an add-on track the AI follows the *original* track's line — swerving off at the start, or crashing. Replacing it with an EMPTY archive makes the AI fall back to the track's own `default.ili` | `vrmod` can produce the exact file (`archive.to_bytes([])` is byte-identical); no command exposes it yet |

### Engine patches & install fixes
| Tool | Creator | Purpose | `vrmod` |
|---|---|---|---|
| **"High Poly race.bin" / 1.2.4 BETA** | Sucahyo (2007) | 95k-poly tracks; raised per-object vertex cap; spoiler visible without an `option.cfg` edit; mirror in F1–F8 | `vrmod patch --max-verts`; `vrmod doctor` reports the installed build and budget |
| **v1.2.5 (2016) / v1.2.6 (2017)** | Val Novak; GPU fix by Charlie Ward from beatcracker's solution | Modern-GPU video-memory fix, sound fix | `vrmod patch-vram`; `vrmod racebin` identifies the build |
| **4983A Spoiler Mod Patch** | Sucahyo | Force `<car>S.mod` spoilers to always show | Covered by the patched `race.bin` lineage above |
| **VR Resolution Changer** | — | Run at resolutions up to 1920×1200 | `vrmod resolution` (+ aspect-ratio correction) |
| **Lapman** | Frank P. Wolf (on findings by "Joe") | Change the 3/8/20 lap counts | **none** |
| **Optman** | Frank P. Wolf | Extra `options.cfg` settings (e.g. the spotter) | *partial* — `vrmod aifield` writes `options.cfg`, but only the field size |
| **Viper Racing (Infinity) View Extender** | Val Novak | Push the draw distance past the in-game slider — the 2012 original and a 2016 v2 (`.exe` plus an equivalent `.bat`) | `vrmod drawdistance --max` (by key, not by line number — see formats §5.2.2b) |

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
  Sucahyo lifted the limits (2007), Charlie Ward/beatcracker fixed the GPU
  check (2016), and Val Novak made the last edit in 2017 on a finding by Zero.
  The first two are what most modern installs still rely on.

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
- **[viper-racing-recovered](https://archive.org/details/viper-racing-recovered)** —
  an Internet Archive item holding material recovered from Wayback captures of
  the sites above: tools, patches, sky and texture packs, the track-making
  toolchain, and the site images. It ships a `MANIFEST.json` giving every file's
  original URL, byte count and SHA-256, so what came from where is checkable
  rather than asserted.
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
