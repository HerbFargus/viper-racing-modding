# Viper Racing (1998, Monster Games / Sierra) — Reverse-Engineered File Format Reference

**Purpose:** a from-source technical catalog of every resource type shipped with Viper Racing, built for
modders and tool authors — direct binary reverse-engineering of a redump-verified, untouched retail copy of
the game (USA, Rev 1 — [redump.info/disc/106242](https://redump.info/disc/106242)), covering every
`.trk`/`.car`/`.res` archive in `Data/`, verified byte-exact against the raw archive bytes. Every claim
below is tagged with a confidence level so you know what to trust blind and what to verify yourself before
building on it.

This intentionally covers **original, unmodified retail game data only.** Modernization installers,
existing mod tools, and modding pipelines are deliberately out of scope for this document — this is a pure
file-format reference.

**Confidence key**

| Tag | Meaning |
|---|---|
| ✅ CONFIRMED | Verified by direct binary inspection against multiple sample files, with byte-exact or near-byte-exact accounting for the data. |
| 🟡 WELL-SUPPORTED | Header fields/structure confirmed by inspection; some payload semantics inferred from strong circumstantial evidence (naming, value ranges, cross-references) but not byte-exact verified. |
| ⚪ HYPOTHESIS | Educated guess from file size/naming/position in the pipeline only. Unconfirmed. |
| ❓ UNKNOWN | Not investigated. |

---

## 1. The big picture

Viper Racing's engine (built by Monster Games) stores almost everything — meshes, textures, AI paths,
camera definitions, object placement, lighting configs — in one **universal binary envelope** (§2), then
groups a track's or car's full set of these resource files into a **package archive** (§3: `.trk`/`.car`/
`.res`) for shipping.

---

## 2. The universal container: "0SER" resources ✅ CONFIRMED

Every native binary resource file examined — `.mod`, `.ili`/`.ild`, `.ccs`, `.tab`, `.obt`, `.tex`,
`.stp`, `.grf`, `.sol`, `.bpp`, `.bsp` — opens with the **identical 20-byte envelope**:

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 4 | `"0SER"` | Fixed magic, literally "0SER" ASCII, identical in every file of every type sampled. Almost certainly short for "serialized [object]". |
| 0x04 | 4 | type tag | 4-byte FourCC identifying the resource type (see below). |
| 0x08 | 4 | int32 version | Small integer, 0–3 across the sample set; differs by type, constant within a type. |
| 0x0C | 4 | (reserved) | Always `00 00 00 00` in every sample. |
| 0x10 | 4 | `"!IGM"` | Fixed secondary marker in every file, every type. |
| 0x14+ | — | type-specific payload | See §4 for each type. |

**The type tag is byte-reversed on disk.** The engine is written in C on little-endian x86; a 4-character
constant like `'MINF'` declared in source (`x = 'MINF'`) is packed MSB-first into a 32-bit int
(`'M'<<24 | 'I'<<16 | 'N'<<8 | 'F'`), and when that int is `fwrite`'d on a little-endian machine, the bytes
land on disk in **reverse order** — `F N I M`. Reversing the 4 bytes of any tag you find in an
unfamiliar file recovers the mnemonic the original programmer typed. Confirmed tags recovered this way:

| Raw bytes on disk | Reversed (mnemonic) | Extension(s) | Meaning |
|---|---|---|---|
| `FNIM` | `MINF` | `.mod` | **M**esh **INF**o |
| `NILI` | `ILIN` | `.ili`, `.ild`, `.ilg` | "ILI" + pad letter (see below) |
| `0SCC` | `CCS0` | `.ccs` | "CCS" + version digit baked into the tag itself |
| `BATS` | `STAB` | `.tab`, `.obt` | **S**imple **TAB**le (shared by both extensions, §4.3) |
| ` XET` | `TEX ` | `.tex` | **TEX**ture (space-padded) |
| `PMTS` | `STMP` | `.stp` | **ST**a**MP** (2D sprite) |
| `FARG` | `GRAF` | `.grf` | **GRA**ph/**GRA**phics **F**ile |
| `LBOS` | `SOLB` | `.sol` | "SOL" + pad letter |
| `TPPB` | `BPPT` | `.bpp` | "BPP" + pad letter |
| `TPSB` | `BSPT` | `.bsp` | "BSP" + pad letter |
| `rDIA` | `AIDr` | `.adr` | **AI D**river |
| `TNDA` | `ADNT` | `.dnt` | "DNT" + pad letters |
| `SGPU` | `UPGS` | `.ugs` | **UPGS** — upgrade-shaped mnemonic |
| `XFSE` | `ESFX` | `.ens` | **E**ngine **SFX** |
| `0XFS` | `SFX0` | `.sfx` | "SFX" + version digit baked into the tag |
| `FRAC` | `CARF` | `.cf` | **CAR F**ile |

The pattern is consistent: where a real short word fit in 4 characters (`MINF`, `GRAF`, `STAB`, `STMP`,
`TEX `, `AIDr`, `ESFX`, `CARF`), they used it; otherwise it's the file extension in caps plus one or two
extra padding characters (`CCS0`, `SOLB`, `BPPT`, `BSPT`, `ILIN`, `ADNT`, `SFX0`). **Any new file type you
encounter that starts with `0SER` can be identified this way even with zero other context.**

The `!IGM` marker reverses to **`MGI!`** — almost certainly a signature: **M**onster **G**ames **I**nc.,
the studio that built the engine, with an exclamation point. It's a nice confirmation that the whole
family really is one in-house serialization layer rather than several unrelated formats that happen to
share a magic number.

---

## 3. The package layer: `.res` / `.car` / `.trk` ✅ CONFIRMED

Above the individual 0SER resource files sits an archive layer — a flat container that groups a track's,
car's, or shared-resource bundle's full member set into one file. Verified byte-exact against the real,
untouched retail files — all **26 archives** in `Data/` (8 `.trk`, 5 `.car`, 13 `.res`) reconstruct
member-for-member from the raw bytes with **zero mismatches**, including a 1,220-member archive
(`drivers.res`) checked entry-by-entry.

```
0x00  "0TSR"              archive magic (a distinct top-level family from the per-resource "0SER" envelope)
0x04  int32 entryCount
0x08  int32 coreCount       -- see formula below
0x0C  int32 coreBoundary    -- byte offset where "bulk" payload data begins; see formula below
0x10  entryCount × 36-byte directory entries:
         name[16]          null-padded filename, no path
         tag[4]            same reversed-FourCC convention as the resource envelope (§2)
         version[4]
         payloadSize[4]    size *excluding* the resource's normal 20-byte 0SER envelope
         reserved[8]       = 0 in every entry sampled
      → then entryCount payload blocks, back-to-back, in the SAME order as the directory:
         reserved[4] = 0, marker "!IGM"[4], then raw payload[payloadSize]
```

A standalone member file is normally `"0SER"+tag+version+reserved+"!IGM"+payload` — the 20-byte envelope
from §2, then payload. The archive just splits that envelope in half: `tag`+`version` live in the
directory entry, `reserved`+`!IGM` sit immediately before the payload. Reconstructing a standalone member
is literally "stitch the two halves back together" — confirmed by reconstructing members of `bemidji.trk`,
`viper.car`, and `drivers.res` this way in Python and diffing byte-for-byte against known-good extracted
copies, with zero mismatches.

**The two header ints, solved:** every archive splits its members into a **"core"** group and a **"bulk"**
group. Bulk is a **fixed set of three tag types** — `TEX ` (textures), `NILI` (AI-path variants:
`.ili`/`.ild`/`.ilg`), and `TNDA` (`.dnt` per-tier driver tuning) — whichever of those are present in a
given archive, *regardless of how many instances of each actually appear*. (An earlier pass at this
described the rule as "whichever tag has the highest occurrence count," which happened to fit the handful
of archives spot-checked at the time but doesn't generalize: several `.car`/`.res` archives have a
non-bulk tag with far more instances than any bulk tag present, and it's still correctly excluded from
"core." Brute-force testing every possible tag combination against all 26 real header values confirms the
fixed three-tag set is what actually reproduces every archive — verified end-to-end by building a working
unpack/repack tool around it and round-tripping all 26 archives byte-exact.) Given that:

- `coreCount` = number of entries whose tag is *not* one of the three bulk tags
- `coreBoundary` = `(16 + 36×entryCount)` + `8×coreCount` + `sum(payload sizes of core entries)` — the
  byte offset marking the end of the core resource block / start of the bulk block

Verified exactly this way across all 26 retail archives — zero exceptions.

**Ordering requirement, found via a real crash:** `coreBoundary`'s formula only describes the file's real
layout if every core-tagged entry's payload physically precedes every bulk-tagged entry's payload in the
directory/payload order — true of all 26 retail archives (confirmed directly: none of them interleave a
core entry after a bulk one), but not something a *tool* is free to ignore when adding a new entry.
Appending a new core-tagged member after an archive's existing bulk section (e.g. adding an owned override
of a previously shared/inherited part) computes a `coreBoundary` that no longer matches where the file's
bulk data actually starts — confirmed to crash the retail game, reading texture data tens of KB past its
real offset. Fix: an archive builder must stable-partition entries (core group first, bulk group after,
each group's own relative order preserved) before computing the header, not merely trust whatever order
its entries happen to arrive in.

**The loader also accepts a second layout, so a writer must preserve what it finds.** Alongside the split
above, archives exist whose header declares *no* bulk section at all — `coreCount == entryCount` and
`coreBoundary == file size` — with bulk-tagged entries left interleaved wherever they fall. The retail game
loads both without complaint. Stated generally, one rule covers each:

- `coreCount` = the number of entries preceding the first bulk-tagged entry
- `coreBoundary` = that entry's payload-start offset (= EOF when there is no bulk section)

What the loader does *not* tolerate is a `coreBoundary` matching neither, which is exactly what naively
appending to an already-split archive produces. So a tool should read whichever convention an archive
already uses and write it back unchanged, rather than always recomputing the tag-based split — doing so
reproduces every archive tested byte-exactly, while force-normalising one layout into the other rewrites a
large fraction of the file for no benefit and destroys the byte-exactness that makes an editing tool
auditable. (Files using the second layout are not retail; see §9.)

**The car's own filename is load-bearing, found via a second real crash.** Nearly every member of a `.car`
archive is named `<prefix><suffix>` — `Viper0.mod`, `viper0.sfx`, `viper.cf`, `vipere.ens`, `viperL.tab`,
etc. — where `<prefix>` is the car's short identifier (`viper`, `exotic`, `sedan`, `sports`, ...). The handful of
exceptions are fixed, car-agnostic names: `cockpit.tab`, `Needle.mod`, and the shared-default assets
(`ball.mod`, `horn.sfx`, `shift1.sfx`, `squeal.sfx` — see §5). Confirmed directly from a real crash log:
saving an edited copy of `viper.car` to a *different* filename (`viper_edited.car`, chosen specifically to
never overwrite the original) while leaving the archive's own members named `Viper0.mod` etc. made the game
panic — `ResourceGet("viper_edited0.mod") returning NULL!` / `Couldn't load ModelInfo viper_edited0.mod`.
The game derives which internal member names to look up from **the `.car` file's own filename on disk**,
not by reading anything stored inside the archive — renaming the *file* without renaming every
`<prefix><suffix>`-named *member* to match leaves the game looking for members that were never created.

**The prefix has a hard length limit: 10 characters — but 9 is the safe cap.** The archive's 16-byte name
field has to fit `<prefix>` *and* the longest real suffix in the same car (up to 6 bytes — `Viperd1.tex`'s
`d1.tex`). At a 10-char prefix the longest member (`<prefix>d1.tex`) is *exactly* 16 bytes, filling the field
with **no null terminator** — a state no shipped archive ever reaches (the longest member name in any retail
`.car`/`.res`/`.trk` is 12 bytes), so whether the engine's own filename lookup tolerates an unterminated
16-byte name is untested. A prefix of **≤ 9** keeps every member name ≤ 15 bytes, i.e. always null-terminated,
which is why the toolkit's car-fork / "Save as new car" cap the prefix at 9. No retail car exceeds 6.

**Renaming the prefix has to reach inside `.mod` payloads too, not just the archive's directory table.**
`.mod` meshes reference their own textures by material name (§4.2), and that name is matched literally
(case-insensitively) against a real archive entry — so a `.mod` still saying `VIPERD1.tex` after the archive
entry itself was renamed to (say) `viper_md1.tex` no longer resolves to anything. The car's own body-paint
material follows the identical prefix convention and is *never* a real archive entry either way (§5.3's
placeholder-swapped-at-runtime paint slot) — `viper.car`'s is literally `VIPER.tex`, `exotic.car`'s is
`Exotic.tex` — strongly suggesting the same dynamic-prefix mechanism that crashed the game over
`<prefix>0.mod` also governs which material the runtime paint-swap looks for, which would explain a renamed
car's body rendering as a flat fallback color rather than the player's chosen paint. A renaming tool needs
to re-parse and rewrite every `.mod`'s own material names in step with the archive-entry renames, not just
the directory table.

**A third, harder-to-fix dependency: `paintkit.res`'s per-car-shape paint canvases.** That shared archive
holds a dedicated `<prefix>.cvs` canvas for `exotic`, `sedan`, and `sports` — but *not* one for `viper`,
despite `viper` being the game's primary, title car. The simplest reading: `viper` is hardcoded as the
default case (using `paintN.cvs`, §5.3's player-selected paint slots, directly), while every other car shape
needs its own dedicated canvas to paint onto. Confirmed in-game: a renamed `viper.car` (`viper_edited`/
`viper_m`/etc.) opens the Paint Kit to a solid black canvas — there's no `<new-name>.cvs` for it to fall back
to, and it no longer matches the hardcoded `viper` special case either. Unlike the `.mod` material-name
issue above, there's no known fix that stays within a renamed copy — it would require synthesizing a whole
new `.cvs` canvas (262,180 bytes, presumably body-shape-specific UV-mapped pixel data) for a car identity
that never had one.

**Given three independent identity-tied dependencies found by three separate real bugs/crashes** (archive
member names, `.mod` paint-slot material names, and now the Paint Kit canvas) **— and no guarantee a fourth
isn't still out there — the more robust strategy for a tool that edits a car in place is to not rename it at
all.** Back up the original file, then write every edit back under the car's own real, unchanged filename.
Every one of these three problems disappears at once, rather than being patched individually as each new one
surfaces.

A **directory-listing manifest** (a flat, whitespace-separated list of member filenames, no paths or
offsets/sizes) is sometimes seen alongside an unpacked archive's contents — real sample:

```
aidef.ccs   bemidji.ccs   camera.tab   track.bpp   track.bsp   track.grf   track.obt
track.sol   Trackmap.stp  asph.tex     default.ili ... (etc.)
```

It's not itself embedded inside the compiled archive format in a form you need to parse — everything
needed to reconstruct the archive is in the directory table above.

`.trk` = track archive — on the retail disc: `bemidji`, `dundas`, `hastings`, `heaven`, `kenyon`, `limbo`,
`nfield`, `uptown` (named after internal track-zone identifiers, not the marketing names shown in the
game's track-select menu — see the confirmed mapping below). `.car` = packed car (`exotic`, `plane`,
`sedan`, `sports`, `viper`). `.res` = shared resource bundle (`common`, `drivers`, `ui`, `race`,
`postrace`, `paintkit`, `easy`/`medium`/`hard`, `career1`–`4` — the difficulty and career-stage `.res`
files turned out to just be repackaged sets of the 7 Viper LOD textures).

**In-game track name → `.trk` filename, ✅ CONFIRMED** (read directly from `english.lng`'s
`Tracks:<Slot>:Name` keys — see §5.5, which
lists the 8 built-in tracks by their in-game menu names):

| In-game name | `.trk` file |
|---|---|
| Bemidji | `bemidji.trk` |
| Castlegreen | `heaven.trk` |
| Silverdale | `uptown.trk` |
| Ridge Valley | `hastings.trk` |
| Dayton | `limbo.trk` |
| Dundas | `dundas.trk` |
| Sunset Mesa | `nfield.trk` |
| Rock Island | `kenyon.trk` |

Only `bemidji.trk` and `dundas.trk` happen to share their in-game name — every other file's internal name
is unrelated to what the game actually calls that track in the menu. Anyone editing a specific track by
its familiar name needs this table to find the right file.

---

## 3.5 Runtime asset resolution & shared assets ✅ CONFIRMED

Sections 2–3 describe how a resource sits *inside* an archive. This section covers how the
**engine finds a resource at load time** — which matters the moment a car or track mod is
actually raced, because it explains several behaviours that look like mod bugs but aren't.

**The resolution rule.** When the engine needs a member by name it looks in the **car's own
archive first, then the shared resource archives** (`race.res`, `common.res`, `postrace.res`,
`paintkit.res`, `ui.res`, in that order). Per-car members are addressed by a
`<carname>.car/<member>` path — i.e. **keyed by the car's own filename**. Two consequences:

- A car that ships its own copy of a shared asset **overrides** it; one that doesn't **falls
  back** to the shared default.
- Because per-car members are keyed by the car, **two cars may contain identically-named
  members without colliding** — each loads from its own archive. (Proof: every kart add-on
  names its textures `driver.tex` / `kart.tex` / `plate.tex`, yet each renders as a different
  character — impossible with a global name cache.)

### Shared default meshes (`race.res`)

| Member | Role |
|---|---|
| `ball.mod` | horn ball — **the runtime exception, see below** |
| `fwheel_1/2/3.mod`, `wheel_1/2/3.mod` | front / rear wheel meshes (style variants) |
| `arm_ll/lr/sl/sr/ul/ur.mod` | visible suspension control arms |
| `spin_l/spin_r.mod` | spinning-wheel effect |
| `brakelt.mod`, `diskglow.mod` | brake light, disc glow |
| `Xray.mod` | X-ray view mesh |

### Shared default textures

| Member | Archive | Role |
|---|---|---|
| `ucar.tex` | `race.res` | generic fallback body skin |
| `wheels.tex` | `race.res` | wheels |
| `effects.tex`, `effectsx.tex` | `race.res` | brake lights / FX |
| `envmap.tex` | `common.res` | reflection / environment map |
| `damage.tex`, `skid.tex`, `splash.tex`, `Xray.tex` | `race.res` | damage / skids / splash / X-ray |

Shared default **sounds** (`horn.sfx`, `squeal.sfx`, `shift1.sfx`, `crash1-3.sfx`, `road1/2.sfx`, …)
live in `race.res` under the same override rule.

### When assets overlap — or clash

- **Overlap (by design, safe).** Every shared file above is a *default*: a car's own version
  wins, otherwise the shared one is used. Clean per-car fallback, no collision.
- **No collision for per-car assets.** Bodies, cockpits, wheels, driver textures and skins are
  all keyed by car, so identical names in different cars don't clash.
- **⚠ The horn ball is the exception.** `ball.mod` is *not* resolved per-car — the engine
  hardcodes the bare name `ball.mod` in its obstacle system (the `horn_ball` hack tosses it) and
  loads it **once, globally**. In a multiplayer session there is effectively **one horn ball for
  everyone**, not each player's own — the single case where two cars both named `ball.mod` truly
  collide.
- **⚠ AI-field paint (a limitation, not a clash).** The whole AI field drives the **primary car**
  (`viper.car`'s identity). Stock viper's body uses a *paint slot* the engine recolours per AI
  slot (`Viperd<N>.tex`) — a field of varied colours. A mod made the primary car brings its own
  body texture, so the paint slot is bypassed and **every AI car shows one identical skin**.
  Re-tagging the body back to the paint slot restores per-AI colours, but those paints are
  UV-mapped for the viper body and map incorrectly onto a differently-shaped mod mesh.

**Why this is in a format reference.** These are exactly the behaviours a modder meets the first
time they race their car against a full field or online — identical AI cars, one shared horn
ball, garbled palette paint — and assumes they broke something. They didn't: it's how the engine
resolves shared vs. per-car assets.

---

## 4. Per-resource-type catalog

### 4.1 `FNIM` — `.mod` 3D mesh — ✅ CONFIRMED

Used for **every** rigid mesh in the game: car body LODs (`Viper0.mod`…`Viper7.mod`, one file per detail
level), car sub-parts (`Viperw.mod` = wheel, `Viperb.mod`, `Viperc.mod`, `vipers.mod`, `Needle.mod` =
speedometer needle, all verified to carry the identical `FNIM` tag), and track props (`checkpt1.mod`,
`ground.mod`).

```
0x00  "0SER" + "FNIM" + int32 version(=1) + reserved + "!IGM"     -- 20-byte envelope, see §2
0x14  int32 vertex count (V)
0x18  int32  (stale in-memory pointer; byte-identical junk across unrelated files — ignore)
0x1C  int32 material count (M)
0x20  int32  (stale pointer — ignore)
0x24  int32 face count (F)
0x28  int32 x4 (stale pointers/reserved — ignore)
0x3C  V × 32-byte vertex records:  float32 x,y,z, nx,ny,nz, u,v
      M × 32-byte material records: null-terminated texture filename, then — at a FIXED offset
            from the END of the 32-byte record, regardless of how long the filename is — 4 ×
            int16: vertex_start, vertex_end, face_start, face_end (see below)
      F × 8-byte face records: int16 a,b,c (CCW winding) + int16 pad(=0 always)
```

**Per-face material assignment is real, and is stored as contiguous ranges, not a per-face index.**
An earlier pass at this format found no per-face material index and assumed none existed. It's stored
in what was assumed to be junk trailing bytes on each material record instead: the last 8 bytes of
every 32-byte material record decode as 4 × int16 — `vertex_start, vertex_end, face_start, face_end`,
a half-open `[start, end)` range of vertex/face indices that material owns. These chain across a
`.mod`'s material list: material *i*'s `vertex_end`/`face_end` equal material *i+1*'s `vertex_start`/
`face_start`, and the last material's `vertex_end`/`face_end` equal V/F exactly. Verified byte-exact
against real files: every face's actual vertex indices were checked against its material's declared
vertex range across three real multi-material meshes (6, 3, and 7 materials) — zero violations across
all 389+45+363 faces checked. This is what makes the material list genuinely usable for splitting a
mesh into per-material groups (e.g. for OBJ export) without guessing.

No per-face material index exists as a separate field — the ranges above are the actual mechanism, and
the face "pad" field is always zero.

⚠️ **The `int16` fields impose two hard format ceilings on mesh size, independent of any engine limit.**
Face records store their three corner indices as `int16`, so a mesh can address at most **32,767 vertices** —
a larger mesh simply cannot be represented. And each material record's `vertex_end`/`face_end` are `int16`
too, capping a single material at **32,767 faces**; since an ordinary quad-tessellated surface has ~2 faces
per vertex, that ceiling is reached at only ~16k vertices unless the topology is leaner (a triangle strip is
~1 face per vertex and reaches the full ~32k). These are properties of the file format, not of a particular
`race.bin`. Stacked *below* that format cap is a separate, lower **engine** limit — and it has now been
found, measured, and confirmed in-game (see §5.2.4 for the full disassembly). The community-quoted figure
of "20,000 vertices" for v1.2.5 is **wrong**: the real per-object ceiling is **30,000 vertices**. The
mechanism is a single fixed vertex scratch buffer the engine `malloc`s once at startup — `malloc(960,000)`
at VA `0x45031a`, pointer kept in global `0x4dc72c` — into which the per-object transform loop copies each
vertex at `index × 32` bytes. 960,000 ÷ 32 = 30,000, so an object with more than 30,000 vertices writes
past the buffer and the game crashes with an access violation. (This is why the earlier "no `20000`
constant, no large static buffer" observation was correct yet pointed the wrong way: the sizing constant
is the *malloc byte size* `0xEA600` = 960,000, not the vertex count, and the buffer is on the heap, so it
never showed up as static-data growth.) The buffer is allocated once and **reused per object**, so the cap
is strictly per single mesh, and enlarging it costs a flat +88 KB of RAM regardless of how many cars are on
track. Confirmed empirically: a 32,000-vertex test mesh crashes at the copy instruction `0x4576be`, and
after the one constant is raised to `0x100000` (1,048,576 B) the identical mesh renders — lifting the
ceiling to **32,768 vertices, the int16 format cap**, beyond which face indices cannot reach anyway. **Retail
1.1's buffer is 32,000 bytes = exactly 1,000 vertices** — also below its widely-quoted "1,200". Both builds'
sites are found by the same allocation-context pattern (retail at `0x44f57a`, v1.2.5 at `0x45031a`), so the
patch is build-independent; it ships as the opt-in `vrmod patch --max-verts N` (default off, since the stock
cap suits every stock car).

Vertex positions are in **meters**, for cars and track props alike — cars and tracks are drawn in one
shared world, so a single scale applies throughout. `Viper0.mod` measures 4.43 × 1.92 × 1.10 against the
real Viper GTS's 4.45 × 1.92 × 1.12 m. **No conversion is needed to bring car parts into track space.**

### 4.2 `NILI` — `.ili` / `.ild` / `.ilg` AI driving line — ✅ CONFIRMED

`default.ili` = the AI racing line; `rdefault.ili` = reverse-direction variant; `track.ild` = a third line
variant (checkpoint/pit line). All three share the format — as does a fourth extension, `.ilg`, found in
> **`drivers.res` makes the AI drive the WRONG track on any add-on, and the community fix is to empty
> it — ✅ CONFIRMED.** The shipped file is 6,334,252 bytes holding 1,220 members: 524 `.ilg` AI lines,
> 695 `.dnt` tunings and `aidriver.adr`. Those `.ilg` lines are baked per track, so a new track
> installed into a stock slot inherits the *original* track's AI line — the AI swerves off the road at
> the start, or the game crashes outright on some tracks.
>
> Sucahyo's fix, circulated from 2009, is a `drivers.res` containing nothing at all: 16 bytes,
> `30 54 53 52` plus three zero counts, which is byte-for-byte what `archive.to_bytes([])` produces.
> With no baked lines to prefer, the AI falls back to the track's own `default.ili` / `track.ild`.
>
> **This is a prerequisite for any generated or imported track**, and it is invisible until AI cars
> are on track: geometry, collision, timing and the player's own car all behave correctly without it.

`drivers.res` on the retail disc: one AI-line variant per AI driver skill tier per track section
(`000vipr.ilg` … `6xxvipr.ilg`, paired with a same-tier `.dnt` file, §4.11 — hundreds of them, all
confirmed `NILI`-tagged and structurally identical to `.ili`/`.ild`).

```
0x00  "0SER" + "NILI" + int32 version + reserved + "!IGM"   -- envelope, see §2
0x14  int32 x2  (unused by the extractor; likely point-count/flags)
0x20  N × 68-byte records (17 × float32):
        field[1] = X (world space, meters)
        field[2] = Z (world space, meters) — same sign as the mesh data; see the note below
        field[5] = corridor half-width, meters — `track.ild` only; see below
        field[6] = target speed, m/s (a flat 100.0 in every `track.ild`)
        field[9] = cumulative arc-length distance from record 0 (meters)
        field[0]  = NOT a float: the runtime `next` POINTER — see below
        field[10] = NOT a float: `0xFF<kind><index16>`; `kind` names the LINE, and
                    the index is zeroed on load
        field[12] = distance to a block boundary ahead (meters) — engine never reads it
        field[13] = signed distance to a block boundary ahead (meters) — debug draw only
        field[16] = NOT a float: `0xFEEDBEEF`, the pool allocator's guard word
```

#### 4.2.1 The file is a raw memory dump of a circular linked list — ✅ CONFIRMED

This one fact explains most of the format's oddities, and it comes straight off
`MutableIdealLine::save` in the symbolised 1998 build:

```
push 0x494c494e          ; "NILI", version 3
call IdealLine::segloop_count
push 0xc                 ; 12-byte header: ..., ..., count
call FileWrite
loop:
  push 0x44              ; 68 bytes — the ILSeg node, verbatim
  push edi
  call FileWrite
  mov  edi, [edi]        ; follow ILSeg::next
  cmp  [esi+0x2c], edi   ; until back at the head
  jne  loop
```

The writer never serialises anything. It walks a circular linked list and dumps each
node's raw 68 bytes, `next` pointer included. So:

- **Field 0 is that `next` pointer.** In shipped files it holds real 1998 heap addresses
  — bemidji's `default.ili` runs `0x00302968`, `0x003029ac`, `0x003029f0`, exactly `0x44`
  apart, and the last record points back to `0x00302924`, the head. This is why X sits at
  field 1 rather than field 0. `fixup_res` relinks every node at load, so **whatever is
  stored there is discarded** — vrmod may write zeros.
- **Field 16 is the pool guard**, `0xFEEDBEEF` in every record of every shipped file.
- **Field 10's low 16 bits are zeroed on load** (`fixup_res` ends by clearing the low word
  of every record), so the index is scratch space, not input. The `kind` byte is `0` through
  `default.ili` and `1` through `rdefault.ili`, but in `track.ild` it runs `1`, `2`, `3` in
  **contiguous blocks** — bemidji is `1` for records 0–31, `2` for 32–71, `3` for 72–90.
  Those are the lap's **sectors**, which is what `CenterLine::get_next_checkpoint` walks.
  `fixup_res` confirms the reading: when it reverses a line it renumbers this byte, and it
  guards the renumbering with `cmp edx, 5`, so the format allows at most four sectors.
  (`vrmod`'s `ili.generate(sectors=True)` already writes it this way.)

`fixup_res` also holds the whole reverse-line construction, which is why `rdefault.ili`
never needed separate authoring: it reverses the record order, shifts field 8 by one
record, re-accumulates field 9, negates the direction vector in fields 3 and 4, and
renumbers the `kind` byte.

#### 4.2.2 Fields 12 and 13 — the engine does not read them — ✅ CONFIRMED (by exhaustion)

These were the last two unexplained fields, and the answer is that **nothing consumes
them**. Every function that walks the line was disassembled from the symbolised build:

| function | ILSeg fields it reads |
|---|---|
| `ILSeg::QuickEval` | 0, 1, 2 (lerps position toward `next`) |
| `ILSeg::QuickTan` | 0, 3, 4 (lerps the tangent, then normalises) |
| `IdealLine::get_rabbit_position` | 3, 4, 5, 6, 8 |
| `IdealLine::advance_bead` | 3, 4, 6, 7, 8 |
| `IdealLine::get_nearest_bead` | 8 |
| `ILSeg::__Curvature` | 3, 4 |

Fields 12 and 13 appear in none of them. Scanning the **entire** `.text` section for x87
access to an ILSeg's `+0x30`/`+0x34` returns exactly one hit on a line segment:
`ILSeg::__DrawLine`, which compares field 13 against `0x80000000` and picks one of two
colour globals — a debug-draw decision about the sign, nothing more. (The other 78 hits
are unrelated structs; `+0x30` is an unremarkable offset in `Wheel`, `Engine`,
`SphereVolume` and a dozen others.)

**What they nevertheless are.** Both are distances in metres that fall by exactly the step
(field 8) each record, over a shared, irregular block structure. Field 13 crosses zero and
goes negative; field 12 stays positive throughout. `field[12] - field[13]` is constant
within a block and changes at each boundary. Those boundaries are **corners**: mean
curvature at a boundary runs 1.5×–3.5× the track mean on every shipped centreline
(bemidji 1.58×, dundas 2.30×, hastings 1.66×, heaven 3.52×, kenyon 1.73×, nfield 2.02×,
uptown 1.50×). What the per-block constant *is* remains open — across 288 blocks it
matches neither the block's own length, its neighbours' lengths, nor the distance to the
block's curvature peak.

⚠️ An earlier reading in this project had these as "distance to the next and previous
checkpoint". The "previous" half is wrong: both look forward, and they share one block
structure rather than bracketing the record.

**Why this matters for generated tracks.** AI pacing is carried by field 6 (target speed)
and field 7 (curvature), both of which the follower does read. Fields 12 and 13 cannot be
the reason a generated track's AI brakes differently from a shipped one, and filling them
approximately costs nothing.

> **Does this apply to the game people run?** The analysis is from the 1998 symbolised
> build, so it was checked against both shipped `race.bin` builds. With absolute data
> addresses excluded (they move between builds), the bodies of `QuickEval`,
> `get_rabbit_position`, `copy_res_to_loop`, `save`, `__DrawLine` and `fixup_res` are
> byte-identical in retail v1.1 and community v1.2.5. `MutableIdealLine::copy_res_to_loop`
> does a flat `rep movsd` of all 17 dwords, so no field is filtered on the way in either.

> ### A 1998 build carries the game's own linker map
>
> `ai-tweaker.exe` — circulated as an "AI speed tweaker", run with **Ctrl-A** to tune each AI car per
> track per difficulty — is not a utility. It is a **1998-dated build of the game itself**
> (`Oct 21 1998 08:49:56`, 2,404,451 bytes against the shipping `race.bin`'s 1,314,816), and it has
> an **MSVC linker map embedded in it: 10,414 symbols across 296 object files**, with C++ mangled
> names and the source object each came from. The crash handler's familiar *"No mapfile present"*
> line is the shipping build looking for exactly this.
>
> This names structures this document had only measured. A sample against its open questions:
>
> | symbol | object | what it tells us |
> |---|---|---|
> | `parse_wobble(char const*)` | `world:world.obj` | the `.obt` wobble record has a dedicated parser |
> | `WobbleObject::WobbleObject(WobbleData*)` | `world:wob.obj` | wobbles are built from a `WobbleData` struct |
> | `Wobble::ResolveExternalImpulse` | `physics:obstacle.obj` | and they respond to being hit |
> | `IdealLine::load_res`, `nearest_node_to`, `get_nearest_bead`, `segloop_count` | `ai:ideal.obj` | the `.ili` reader; its records are **`ILSeg`**, a position along one is **`ILinePos`** |
> | `SphereVolume`, `CubeVolume`, **`MoveableSphereVolume`**, `CollisionVolume::ApplyForce` | `physics:volume.obj` | the `.sol` primitive classes — and some are *moveable* |
> | `BPPFinder::bpp_find(bpp_node*)`, `point_in_poly`, `test_poly` | `world:bpp.obj` | the `.bpp` traversal, over `bpp_tri`/`bpp_node` |
>
> The addresses are that build's, not `race.bin`'s, so they do not transfer directly — but the names,
> the class layouts they imply, and the module boundaries do. Anything in this document still marked
> unsolved (the `.sol` spatial tail, the `.bpp` writer, what `obj wobble`'s integer indexes) now has a
> named function to work from rather than a hex dump.
>
> The map is not reproduced here: it is derived from a copyrighted binary, and anyone holding a copy
> can extract it with a regex for `^\s*0001:[0-9a-f]{8}` over the file's printable strings.

**What the AI actually does with these lines**, from the readme of Sucahyo's `trkaitweaker` —
the only first-hand account of the AI's behaviour recovered so far:

> *"AI in viper racing driving using path defined either by some ilg or default.ili or rdefault.ili
> (reverse). This file define path, speed, and direction."*

Its two pairs of controls describe the model:

- **mult & add** — *"decide how fast the AI do on straight or on tight corner"*: the speed field is
  computed from the path's curvature through a multiplier and an offset.
- **forward lookup & backward lookup** — *"I limit the AI speed based from this two parameter. The AI
  action will be using the slowest speed needed on this range. For instance, if my algorithm detected
  a tight corner 20 meter ahead, then it will use that corner speed right now (as brake) if the
  forward lookup is more than 20 meter. Increase forward lookup if AI braking too late… increase
  backward lookup if AI accelerate too soon on corner exit."*

That is a direct description of the shape fields **12 and 13** carry: a distance ahead and a distance
behind, measured from each station, resetting in blocks. This document had them recorded as
"distances to the boundaries of a segmentation whose rule is not known" — the rule is a braking
lookahead, and the blocks are the stretches over which one corner governs the speed. `vrmod`
approximates them with distance-to-next-checkpoint, which is why generated lines drive but do not
brake like a shipped track.

He also notes the author-side tool: *"AI-tweaker (also known as debug version race.bin ctrl-A)"*,
which writes `aidriver.adr` — the single member inside `drivers.res` that is not an `.ilg` or `.dnt`.

> **Reported, partly corroborated:** the same readme says `track.sol` holds pit markers as the int32
> values 1000 (`pit_entry`), 1002 (`pit_exit`) and 1004 (`pit_reentry`), *"usually at begining or end
> of file"*. Searching the shipped files finds them clustered in the tail region past the primitives
> on heaven (1×1000, 2×1002, 2×1004 around offset 120k) and nfield (2×1000, 4×1002 around 143k), but
> not at all on bemidji, hastings, uptown or Kyalami — so the values are real but not universal.
> He also records that he never worked out how to edit `.sol`, and that `track.txt` carries a
> `pit_side` variable.

**Field 5 is a corridor half-width, not a sentinel — ✅ CONFIRMED in game.** In `default.ili` and
`rdefault.ili` it is `-20000.0` in every record of every track that shipped with the game, which reads
like an obvious "unset" marker and was recorded here as one. It is not. In `track.ild` it is *never*
`-20000`: it is a per-record distance in metres, either side of the line, inside which the game considers
the car to be on the track.

| Track | `track.ild` field 5 | | Track | `track.ild` field 5 |
|---|---|---|---|---|
| Kyalami | 12 | | jumper, limbo, maxi, Rainbow, Telly, dundas, hastings | 20 |
| nfield, sunretx | 15 | | bemidji, uptown | 30 |
| kenyon | 25, dipping to 17 for 3 records | | heaven | 25, dipping to 15 for 18 records |

The two tracks that vary it do so at a pinch point, which is what identifies the field: it is a driving
corridor, not the edge of the asphalt.

**The corridor is twice the road's half-width — i.e. the road's full width.** Measuring each track's road
texture against its own `track.ild` gives this cleanly on the two tracks whose asphalt texture covers the
road and nothing else: Kyalami, corridor 12.0 against a 6.14 m half-width (ratio 1.95), and kenyon, 25.0
against 13.20 m (1.89). The remaining tracks reuse their road texture on pit aprons and paddock, so the
same measurement there describes the paving rather than the road and the ratio falls apart (bemidji reads
83 m).

Sizing it too generously is not harmless. The game treats everything inside the corridor as track, so a
corridor of 20 m over a 12 m road leaves 14 m of grass either side that the game considers on-track, and
a reset drops the car there — on the grass, beside the road, exactly where the game thinks it belongs.

Writing `-20000` into `track.ild` gives every station a *negative* corridor, so the car is outside it
wherever it stands. The symptom is not subtle and does not look like a line problem: the track loads,
renders and drives, but "press space to reset" appears within seconds of the green flag and resetting
teleports the car off the map. Nothing in the geometry, collision, checkpoints or object table is wrong —
the game is correctly reporting that a corridor of width −20000 contains nothing.

> Worth recording as a method note: the `-20000` reading came from surveying only the tracks that shipped
> with the retail game, where the AI lines really are uniform. The community tracks (Kyalami, jumper,
> maxi, Rainbow, Telly) were built with `mkilicc` and carry different values in several fields —
> field 5 is `12`/`20` there even in the AI lines, field 7 is sometimes `NaN`, and field 3/4 is a unit
> tangent rather than the half central-difference bemidji uses. A constant across one publisher's tracks
> is a house style, not a format rule.

The stored cumulative-distance field was checked against the actual point-to-point 2D distance across all
21 sample files (7 tracks × 3 line variants at the time) with **zero mismatches**. Waypoints share the mesh's own coordinate space
directly: raycasting path points down onto the track geometry lands the overwhelming majority on the road
surface with **no axis flip applied**.

> Treat any claim that Z must be negated "to match exported geometry" with suspicion — that describes a
> *mirroring exporter*, not this format. Negating a single axis on export is a reflection, and it is
> unusually easy to miss: round-trips through the same tool stay exact, and mirrored geometry looks
> entirely plausible on symmetric subjects like an oval circuit. The reliable tell is rendered text —
> a mirrored scene renders trackside signage backwards.

**The track length the game displays is derived from `track.ild`, ✅ CONFIRMED.** There is no stored
length field anywhere in a track archive — `<track>.ccs` holds AI/handling tuning, `english.lng` carries
only the unit *labels* (`Miles`, `Mi`, `MPH`), and no value in any member correlates with track size. The
game computes it, and this reproduces the Track Info screen's figure **exactly for all 8 stock tracks**:

```
displayed miles = round( arcLength(track.ild) * 1.0151 / 1609.34 , 1 )
```

`track.ild` — not either racing line — is the length-defining one, which identifies it as the
timing/centre line. Solving each track independently for the scale factor that rounds to its displayed
figure leaves a single consistent window of **[1.0127, 1.0175)** across all eight, so this is one real
relationship rather than a curve fit; the ~1.5% is the true centreline running marginally longer than the
stored waypoints.

| Track | `track.ild` | ×1.0151 | Game shows |
|---|---|---|---|
| Bemidji | 1.444 mi | 1.47 | **1.5** |
| Silverdale (`uptown`) | 1.854 | 1.88 | **1.9** |
| Rock Island (`kenyon`) | 2.913 | 2.96 | **3.0** |
| Dayton (`limbo`) | 2.964 | 3.01 | **3.0** |
| Ridge Valley (`hastings`) | 3.235 | 3.28 | **3.3** |
| Dundas | 3.710 | 3.77 | **3.8** |
| Castlegreen (`heaven`) | 3.784 | 3.84 | **3.8** |
| Sunset Mesa (`nfield`) | 4.318 | 4.38 | **4.4** |

This doubles as the strongest confirmation that world units are **meters**: read as feet, Bemidji's lap
would be 0.43 miles against the 1.5 the game itself reports.

### 4.3 `STAB` — `.tab` / `.obt` generic ASCII-record table — 🟡 WELL-SUPPORTED

Both extensions share the identical `STAB` tag and outer structure — this is one generic "array of
text-encoded records" format used for two different purposes:

```
0x00  "0SER" + "BATS"(on disk) + int32 version(=0) + reserved + "!IGM"   -- envelope
0x14  int32 recordCount   (varies per file/track)
0x18  int32 fieldsPerRecord
0x1C  int32 (reserved, =0)
0x20  records begin — each record is human-readable ASCII, not raw binary numbers
```

Confirmed by extracting printable strings directly from the payload:

- **`camera.tab`** (broadcast camera definitions): `fieldsPerRecord = 7`. Each record is a keyword —
  `FIXED` or `PAN_ZOOM` observed — followed by 6 space-padded ASCII numeric fields (position X, Y-height,
  Z, then FOV/zoom-speed/hold-time-shaped values), e.g.:
  ```
  PAN_ZOOM   185   0.4   -160   0.8   5.0   0.0
  ```
  `recordCount` matched the number of camera keyword occurrences exactly in every sample checked.

**The complete `.obt` grammar — ✅ CONFIRMED from `race.bin`'s own parser.** The game's format
strings spell out every record it accepts, which is the only documentation this feature has: no
community tool or tutorial mentions it, and `wobble` appears nowhere outside the track archives and
the executable itself.

```
obj car       <x>, <z>
obj checkpoint <mesh> <x>,<z> <x>,<z>                        -- mesh is checkpt1.mod
obj obstacle  <ball|cube|prism> <mesh.mod> <x>,<y>:<z> <r>   -- e.g. cube ball.mod (the horn ball)
obj static    <box> <x,y,z> <x,y,z> <x,y,z>
obj wobble    <pole|flap> <int>
```

The physics object types it builds from these: `Ball`, `PhobStatic`, `Obstacle`, `Wobble`,
`CheckPoint`, `PlayCar`, `AICar`, `NetCar`, `GhostCar`. Wobble objects have their own pool —
`Too many wobjects allocated--increase MAX_OBJECTS`.

Three things follow that are not visible from the shipped data:

- **`obstacle` places a named mesh at a position with a radius.** That is per-instance collision with
  arbitrary geometry, authored directly in a file `vrmod` already writes — no `.sol`, no MKWORLD.
- **`flap` is a second wobble subtype that nothing ships.** Every `obj wobble` record in every track
  is `pole`.
- **Neither `obstacle` nor `static` appears in ANY shipped track.** They are parser-supported but
  unexercised, so they are an opportunity and an untested path in equal measure.

`obj wobble` is the one record carrying no coordinates, so its integer must reference something
placed elsewhere. The best candidate is the `.sol` TUBE list: across every track the wobble count is
≤ the TUBE count, the indices run contiguously from 0, and the only track with no wobble records
(limbo) is also the only one with no TUBEs. Untested.

- **`track.obt`** (placed-object table): `fieldsPerRecord = 1` in every sample (i.e. one big text field per
  record), `recordCount` matched the number of `obj ...` string occurrences exactly. Real extracted
  records from `bemidji/track.obt` — this is the starting grid and a checkpoint gate, verbatim:
  ```
  obj car 204.725693,-152.139893
  obj car 194.410416,-150.993958
  obj car 204.890503,-141.454208
  obj car 194.507629,-122.365044
  obj car 194.615616,-141.775482
  obj car 204.594894,-131.746994
  obj car 194.791122,-131.580704
  obj car 204.299088,-122.033829
  obj checkpoint flag 163.682877,-169.747467 233.451126,-166.574600
  obj checkpoint flag -159.395172,-190.721024 -229.369766,-192.606476
  ```
  Also present: `out\track.txt`, `map test.map`, `ai test.vf` — these read like leftover provenance/
  comment strings from whatever internal tool authored the original per-track source data, not consumed
  data. Records are stored in a fixed-size padded buffer (~257–261 bytes per record across every track
  sampled — remarkably consistent for what's ostensibly a variable-length string, suggesting a fixed
  `char[256]`-ish struct field rather than a packed/length-prefixed string).

This is genuinely one of the more modder-friendly formats in the game — the payload is literally text.

- **`<prefix>L.tab`** (per-car **LOD table**): another `STAB` use, `fieldsPerRecord = 3`, one record per
  LOD level. This is what drives the car's `Viper0.mod`…`Viper7.mod` detail chain (§4.1). Loaded by
  `sub_00466E70`, which builds the name `"%sL.tab"` (`0x4DF594`), reads it, stores `recordCount` on the
  ModelInfo and parses each record's fields (`atof` on field 0). If it can't be read the game logs
  `Can't load LOD table %s` (`0x4DF59C`). The three fields per record are **[switch distance (metres),
  a numeric flag, a render-options string]**. Real `viperL.tab` (v1.2.5), extracted verbatim — 8 records
  for the 8 meshes:

  ```
  LOD0  Viper0   10    0   alpha spec     <- highest detail; alpha + specular on
  LOD1  Viper1   15    0   alpha spec
  LOD2  Viper2   20    0   alpha spec
  LOD3  Viper3   60    0                  <- alpha/spec dropped from here out
  LOD4  Viper4   80    1
  LOD5  Viper5  100    1
  LOD6  Viper6  200    x                  <- flag "x" on the two farthest levels
  LOD7  Viper7 1000    x                  <- last level; beyond this the car is not drawn
  ```

  The distances are the FAR bound of each level, in metres (the game's one world scale, §7). Selection is
  **by camera distance**, not by which screen you are on: the same distance test governs every 3D context
  that draws the car through the standard object path — so a car 5 m ahead in a chase cam is LOD0-1 and the
  same car 300 m down the straight is LOD7, regardless of view. A global **"LOD Factor"** scalar scales the
  whole curve (default 1.0); a hidden debug overlay exposes it (`?LOD Factor: %4.1f` / `[`=down `]`=up
  `'`=1.0, at `0x40D3D0`), so the effective switch distance is `table_distance × LOD_factor`. The flag and
  options fields are read but their exact effect (mip/shadow toggle; `alpha spec` clearly gates
  alpha-blend + specular on the near levels) is inferred, not byte-traced — 🟡. **Modding note:** the
  stock chain is real reduced-detail meshes; the old community "LOD hack" of copying `Viper0` into all of
  `Viper1..7` satisfies the loader but gives **zero** performance benefit, since every level is then
  full-detail. Genuine decimation (see `vrmod moddecimate`) is what actually helps a heavy custom car in
  the near-camera pack.

### 4.4 `CCS0` — `.ccs` — semantics unconfirmed — 🟡 WELL-SUPPORTED (header only)

Fixed **160 bytes** in every single sample across every track — no exceptions. Every track ships an
`aidef.ccs` (same name everywhere) plus one or more evocatively-named zone files (`bemidji.ccs`,
`heaven.ccs`, `limbo.ccs`, `dundas.ccs`, `uptown.ccs`, `kenyon.ccs`, `288g_sim.ccs`, `lanc_sim.ccs`,
`vipe_sim.ccs`...) — these read like nicknamed track sections/corners. Every car also ships its own
`.ccs` file alongside its `.cf`/`.ens`/`.tab` files.

```
0x00  "0SER" + "0SCC"(on disk) + int32 version(=2) + reserved + "!IGM"   -- envelope
0x14  35 × float32   -- payload; all values fall in ~0.0–3.3 range
```

**Confirmed structural facts** (decoded by directly diffing real payload bytes across every retail
archive):

- All 5 car archives (`viper`/`sedan`/`sports`/`exotic`/`plane`) ship a **byte-identical** `.ccs`
  payload — every one of the 35 fields matches exactly across every car. Retail never differentiates
  this file by car.
- The shared per-track `aidef.ccs` genuinely varies, track to track — all 8 are distinct.
- Kenyon (`kenyon.trk`, in-game "Rock Island") is the only track with more than one zone-named `.ccs`
  file — it has 4 (`288g_sim.ccs`, `kenyon.ccs`, `lanc_sim.ccs`, `vipe_sim.ccs`) versus 1 for every
  other track.
- Fields 20–25 (a contiguous 6-value block) form a strictly monotonically decreasing sequence in
  **every** real sample checked — the shared car-default payload, all 8 `aidef.ccs` files, and all 4 of
  Kenyon's zone files (13/13). Some tracks reuse one specific sequence identical to the car-default
  payload (Kenyon among them); others (Bemidji, Dundas, Hastings, Heaven, Limbo, Nfield, Uptown) each
  carry their own distinct values in that block.
- A handful of fields (indices 1, 3, 26, 27, 28, 29) are hard constants across every retail sample
  checked — likely schema/version markers rather than live data.

Individual field semantics are **not decoded**. In-game differential testing (swapping `.trk`-bundled
`.ccs` variants and diffing visible behavior) was inconclusive: the eight retail tracks differ in too many
fields at once for any single field's effect to be isolated. Further work here is deferred until
purpose-built test tracks and tooling make controlled, single-variable comparisons possible.

### 4.5 `TEX ` — `.tex` texture — ✅ CONFIRMED (opaque, colorkey, mip chain layout; full-alpha 🟡 well-supported)

> **`flags` 0x03 is a FOUR-byte-per-pixel format — ✅ CONFIRMED by payload arithmetic.**
> The other flag values are two bytes per pixel; 0x03 is exactly double at every size, and never
> ships above 128×128:
>
> | base size | flags 0x00 / 0x01 / 0x02 | flags 0x03 |
> |---|---|---|
> | 16 | 748 | 1,496 |
> | 32 | 2,796 | 5,592 |
> | 64 | 10,988 | 21,976 |
> | 128 | 43,756 | 87,512 |
> | 256 | 174,828 | *never ships* |
>
> **ARGB4444 is 0x02, not 0x03.** Writing two bytes per pixel under 0x03 hands the game half the
> data it expects, and it panics with `tmap: unknown texture format` before anything renders — a
> load-time crash, not a visual fault. `vrmod` writes 0x00, 0x01 and 0x02; the four-byte 0x03
> layout is not yet decoded.
>
> **A tiling alpha texture is also a combination that never ships.** Across a full install: flags 0
> takes wrap 0 (×563) or 1 (×118); flags 1 takes wrap 0 (×95) or 2 (×1); flags 2 takes wrap 0 (×18)
> or 1 (×2); flags 3 takes wrap 0 only (×78). Reserve wrap 1 for opaque textures, which are the ones
> that tile along a road anyway.

> **Two limits that are not in the file format, and both fail silently.**
>
> **Names are 8.3.** All 244 distinct texture names in a full install are at most 12 characters —
> eight plus `.tex` (`asphalth.tex`, `pine3o15.tex`, `bboard01.tex`) — and not one contains an
> underscore. This is *not* the archive's limit: a `.tra` directory entry has a 16-byte name field,
> and a 16-character texture name packs, lists and reads back correctly through every tool here. In
> game the surface using it renders as flat untextured colour, with no crash, no warning and no
> placeholder.
>
> **Nothing is larger than 256.** Across those same 880 textures the sizes are 16, 32, 64, 128 and
> 256, and nothing above. An oversized texture does not look wrong or load slowly — it does not draw.
>
> Both were found the same way, and only after a track that raced perfectly rendered in flat colour:
> by surveying what the game ships rather than validating what a writer produced. A texture that
> round-trips byte-exactly through `tex.parse`/`tex.encode_to_tex` can still be one the game will not
> draw.


```
0x00  "0SER" + " XET"(on disk) + int32 version(=3) + reserved + "!IGM"   -- envelope
0x14  byte   flags bitfield: bit0 = colorkey transparency, bit1 = full alpha channel
                              (observed: 0x00 = opaque, 0x01 = colorkey, 0x03 = colorkey+alpha —
                               bit1 alone, 0x02, was never seen on a real in-game texture, only
                               produced synthetically — see below)
0x15  byte   1 for a texture drawn on 3D geometry, 0 for sky and 2D overlays — ✅ CONFIRMED by
              survey. Of all 880 textures in a full install, the only ones carrying 0 are sky1-4 on
              every track plus uptown's 2dtele.tex and oo1-4.tex; every road, kerb, grass and prop
              texture carries 1. It is NOT a mipmap flag — both groups ship full mip chains.
0x16  byte   (unconfirmed)
0x17  byte   wrap flag (0x01 observed only on tileable surfaces — asphalt, checker pattern, paint
              stripe; 0x00 on unique decals)
0x18  int32  **the COLORKEY** — the exact pixel value to render as transparent. 0 for plain opaque
              textures. (It coincides with the 1×1 mip level's value, which is why an earlier pass
              recorded it only as a duplicate of 0x20 — but its *function* is the colorkey, and
              decoders must key off it. See the note below.)
0x1C  int32  mip level count — also gives the base (full-resolution) width/height directly: every
              sample checked is square and power-of-two, and size = 2^(mipCount − 1)
              (mipCount=9 → 256px, 8 → 128px, 7 → 64px)
0x20  int32  redundant copy of the 1×1 (fully-downsampled) mip level's own pixel value — confirmed
              by comparing it against the actual last-mip-level bytes further down the payload
0x24+ padding, then the mip chain: smallest (1×1) first, largest (base level) LAST
```

**There is no separate width/height field.** An earlier pass at this treated the bytes at 0x14 as a
packed `int16 w, int16 h` pair, since the two 256×256 samples checked at the time (`asph.tex`,
`strpy.tex`) happened to share the same 4-byte value there — that was a coincidental fit for a square
texture, not a real field. Confirmed against a full decode of `asph.tex`: those bytes are
individually meaningful — flags=`0x00` (opaque, matching its alpha-less reference output) and wrap=`0x01`
(tileable, matching asphalt being a repeating road surface). Width/height come from `mipCount` instead,
which holds structurally across every other size checked (64/128/256px).

**Base-level pixel format, ✅ CONFIRMED byte-exact:** 16-bit little-endian RGB565, row-major, with the
base (full-resolution) mip level stored **last** in the chain, at payload offset
`payloadLength − width×height×2`. Confirmed by producing a full conversion from a real `.tex` file and
diffing it byte-for-byte against a reference decode of the same file — **whole-file identical**,
all 65,536 pixels exact. The 8-bit channel expansion has a specific quirk worth calling out: it's plain
left-shift, not the more common bit-replication —

```
r8 = r5 << 3
g8 = (g6 & 0x3E) << 2   -- note: the low bit of the 6-bit green sample is unused; green is
                            effectively 5 significant bits, like red/blue, just packed in a 6-bit slot
b8 = b5 << 3
```

That last detail (green's dropped low bit) only became clear by empirically deriving the raw-value →
output-value mapping from real pixel data — the more "obvious" bit-replication formula
(`(g6<<2)|(g6>>4)`) gets every pixel *close* but never exact.

**Full-alpha pixel format, 🟡 WELL-SUPPORTED:** textures with flags bit1 set (`0x02`/`0x03`) use the same
16-bit-per-pixel budget, but packed as **ARGB4444** instead of RGB565:

```
a8 = a4 << 4
r8 = r4 << 4
g8 = g4 << 4
b8 = b4 << 4
```

Confirmed by round-tripping a synthetic test image (solid color, a linear 8-step alpha ramp) through the
reference encoder in alpha mode and decoding the result: every R/G/B nibble matched `channel8 >> 4`
exactly, every A nibble matched the input ramp exactly, and the whole mip chain — including the redundant
1×1-level value duplicated into the header (offsets 0x18/0x20 above) — downsamples by consistent
pairwise averaging at every level.

One caveat keeps this at 🟡 rather than ✅: that synthetic test produced flags `0x02` (bit1 alone), but
**every real in-game alpha texture sampled has flags `0x03`** (both bits set) — passing both `/a` and `/t`
to the encoder did not reproduce `0x03`; it fell back to colorkey-only (`0x01`) behavior and silently
dropped the alpha switch. So it's not independently *byte*-confirmed whether real `0x03` textures use the
identical ARGB4444 packing — but decoding several real `0x03` textures this way (`ddg.tex`, `vip.tex`)
produces clean, sharp, uncorrupted images (a Dodge logo over a mesh grille; a Viper script logo), which is
strong circumstantial support even without a byte-exact reference to diff against.

**Colorkey-only textures (flags `0x01`, bit0 set / bit1 clear), ✅ CONFIRMED:** plain RGB565, byte-for-byte
identical to the opaque encoding, with exactly one special case — raw value `0x0000` is reserved as the
"this pixel is transparent" signal. Any real (opaque) pixel that would naturally quantize to `0x0000`
(any color whose R/G/B all round down to 0, not just literal black — e.g. RGB `(1,2,3)`) gets nudged to
`0x0040` instead (the smallest possible perturbation: green's LSB) so it doesn't collide with the
transparency marker.

> **Important correction — `0x0000` is the *encoder's* convention, not the format's rule.** That is what
> the reference encoder emits in colorkey mode, and it is why an implementation that hardcodes `0x0000`
> appears to work. Real
> retail content does **not** follow it: shipped track textures carry an arbitrary transparent value in the
> header at **0x18**, and it matches the image's dominant background exactly — `3ter.tex` `0x526A`
> (covering 51% of the image), `bnch.tex` `0x7B2A`, `fount.tex` `0x8410`, `orange.tex` `0x62A8`,
> `redwh.tex` `0x6B6D`. A decoder that only treats `0x0000` as transparent leaves those backgrounds fully
> opaque, so every cutout billboard — trees, banners, fences, signs — renders as a solid rectangle
> (`3ter.tex` alone is used by 191 chunks of one track). **Read the colorkey from 0x18 and treat both it
> and `0x0000` as transparent.**

> **Modding gotcha — near-black reads as transparent *in game even in an opaque texture* (flags `0x00`).**
> Confirmed in game (2026-09-07): a pixel is keyed transparent whenever its **5-bit red AND 5-bit blue
> are both zero** — not just literal `0x0000`. Both `0x0000` (RGB `0,0,0`) and `0x0020` (RGB `7,7,7`)
> render **invisible**, while `0x0841` (RGB `8,8,8`) is solid — so a non-zero *green* does **not** save it.
> This happens even when the texture is opaque with no colorkey bit set, so the behavior is **not** gated
> on the colorkey flag. (Observed across three solid-color materials; the exact predicate may be `R5==0 &&
> B5==0` or a low-value threshold — either way, lifting red and blue clears it.) Two consequences for tools
> and modders:
> - **Hazard:** a dark region whose red and blue both quantize to 0 will vanish unless you *want* a hole —
>   lift red and blue to at least `8` (e.g. RGB `8,8,8` → `0x0841`, an imperceptibly-dark but still-visible
>   black). `vrmod` does this automatically when it synthesizes a flat color from an OBJ material's `Kd`
>   (a near-black `Kd` would otherwise import as an invisible part).
> - **Intentional use:** conversely, painting a region pure `0x0000` black is a valid, flag-independent
>   way to punch a transparent hole through a piece — the same effect shipped content gets via the header
>   colorkey, but available with no mode/flag change. Importing a texture keeps its real pixels, so this
>   is unaffected by the `Kd`-swatch nudge above.

Confirmed cleanly: encoded a 16-color test image in colorkey mode covering
red/green/blue/white/black/gray/magenta/cyan/yellow and several near-zero colors, and diffed it
pixel-for-pixel against a plain (non-colorkey) encode of the identical image. All 16 pixels matched
exactly except the two that quantize to `0x0000` in the plain version, both nudged to `0x0040` in the
colorkey version — 16/16 predicted vs. actual, then independently re-verified by building a working
decoder+encoder from the rule and round-tripping the same test image. (An earlier, messier test that
varied a source alpha channel instead of RGB color produced a confusing, position-correlated pattern
unrelated to this rule — `/t` behaves differently, or extra, when the source has an alpha channel at
all; not investigated further. A plain 24-bit, no-alpha source is the reliable case.)

**Full mip chain layout, ✅ CONFIRMED:** the earlier "~50-byte unexplained gap" between where a naive
tight-packed pixel-count sum would place the base level and where it actually starts is fully solved. The
chain isn't uniformly tight-packed:

```
[start] 28 bytes, always zero — reserved/unused. The 1×1 mip level is NOT stored here or
        anywhere in the chain; its only storage is the duplicated header fields above
        (payload offsets 0x18 and 0x20).
        the 2×2 mip level, padded into a 4×4-pixel-sized slot (32 bytes): the 4 real pixels
        occupy the top-left 2×2 of what would be a 4×4 image (row-stride 4 pixels), the
        other 12 pixel slots zero-filled.
        every level from 4×4 up to (but not including) the base level, tight-packed, in
        ascending size order.
[end]   the base (full-resolution) level, tight-packed, LAST.
```

This reconciles the gap exactly, algebraically, for any image size: naive tight-packing assumes
1×1(2B)+2×2(8B)+⟨tight 4×4-and-up⟩ = 10B + ⟨tight 4×4-and-up⟩ before the base level; the real layout is
28B(reserved)+32B(padded 2×2 slot)+⟨the same tight 4×4-and-up⟩ = 60B + ⟨same⟩ — a constant **+50 bytes**
regardless of texture size or mip count. Verified against four samples spanning 8×8 to 256×256 (a
synthetic 8×8 file plus real 64×64/128×128/256×256 textures) — the predicted vs. actual base-level offset
matched exactly in every case, and this layout was then used to build a **working encoder** and verify it
against a real `.tex` file (see below), which is a much stronger confirmation than offset arithmetic alone.

**Encoding (pixels → `.tex`), ✅ CONFIRMED functionally correct:** re-encoding `asph.tga` (itself derived
from `asph.tex`) reproduces a file the same size as the real original, with the base level decoding to
**pixel-for-pixel identical colors**. It is not literally byte-identical — about half the raw 16-bit
samples differ from the real file by exactly one bit (green's low/"don't-care" bit, the same one the
decode formula already masks off, §4.5 above) — the real encoder sets that bit via some rounding rule
that provably has zero effect on the decoded color, and wasn't chased further. Box-filter (simple
average) downsampling was used for the smaller mip levels; this matches the real encoder's *box-average
values* everywhere it could be checked, though the exact rounding/dithering choices at the very smallest
levels aren't independently confirmed byte-exact the way the base level is. The full-alpha (ARGB4444)
encode direction round-trips within the expected 4-bit quantization tolerance.

### 4.5.1 `sky1-4.tex` — a track's sky — ✅ CONFIRMED (layout, from the bytes) / 🟡 rendering behaviour observed in game

Every track archive carries exactly four sky textures, `sky1.tex` … `sky4.tex`. They are ordinary
`TEX ` resources (§4.5) with nothing structurally special about them — opaque, no colorkey, `wrap = 0`,
with a full mip chain. Size is not uniform: **all eight stock retail tracks use 128×128** tiles (a
512×128 strip), while most community add-on tracks use **256×256** — which is itself evidence the game
accepts more than the stock content uses. What is worth recording is how the game *uses* them, because
it is not what the file layout suggests.

**They are four consecutive slices of one panoramic strip**, not four independent backdrops. Seam
continuity between adjacent slices — including `sky4` → `sky1`, which closes the loop — measures a mean
edge difference of only **1–7 out of 255** across every stock track. Composited in order they give a
1024×256 image whose bottom edge is the horizon.

**The strip spans roughly 90° and the game repeats it FOUR TIMES around the horizon.** It is not one
full turn, despite closing seamlessly as though it were. Two independent confirmations:

- **Observed in game:** turning a full circle shows **four** copies of any unique feature in the strip.
  Note this is a *behavioural* observation, not a fact recoverable from the files — nothing in the archive
  records how many times the strip is wrapped. It was seen on a patched install using an add-on track,
  because that track's sky carries an unmistakable landmark to count; re-checking it on an unpatched
  retail install would upgrade this from observed to confirmed.
- **From the art alone:** a strip feature that is nearly twice as wide as it is tall renders *round* in
  game. A perspective camera preserves angular aspect, so a single 360° wrap would require the strip to
  stand ~148° tall — past the zenith, which is impossible. Four repeats resolve it.

The practical consequence for authoring a sky: **what you draw is a 90° quarter-view that will be seen
four times.** It must tile seamlessly left-to-right, and anything distinctive in it — a sun, a landmark —
appears four times around the horizon. The stock skies are built accordingly.

Vertical placement is the one part not pinned down numerically. The strip's bottom edge sits at the
horizon, but its top edge angle could not be measured reliably from screenshots, because nearer terrain
occludes the strip's base — so the visible ground/sky boundary is *not* the horizon, and landmark heights
measured against it come out wrong. Matching a known feature's rendered **aspect** is the workable
approach; it survives unknown field-of-view and unknown resolution, where absolute positions do not.

### 4.6 `STMP` — `.stp` 2D sprite/"stamp" — ✅ CONFIRMED (uncompressed variant; a second, compressed variant remains ❓ UNKNOWN)

The game's general-purpose 2D image format, and by count one of the most common resources on the disc
(~211 instances). It carries **all** UI art (`ui.res`, `common.res`, `race.res`, `postrace.res`,
`paintkit.res`), every track's in-game minimap (`Trackmap.stp`), the per-track **menu screenshot** shown on
the track-select screen (`bemidji.stp`, `dundas.stp`, … inside `ui.res`), and `chekbg.stp`/`chekfg.stp` (the
checkpoint banner, which lives inside `dundas.trk`).

```
0x00  "0SER" + "PMTS"(on disk) + int32 version(=3) + reserved + "!IGM"   -- envelope
0x14  int32  width
0x18  int32  height  -- PER FRAME, not the height of the whole stored image
0x1C  int32  hotspot X   (cursors only; 0 otherwise — e.g. ball.stp is 12×12 with hotspot 6,6)
0x20  int32  hotspot Y
0x24  int32  frame count -- frames are stacked VERTICALLY, so the decoded image is
                            width × (height × frameCount). `awards.stp` is 32×32 with 6 frames,
                            i.e. a 32×192 strip.
0x28  256 × int16  RGB555 palette
0x228 256 × int16  RGB565 palette -- the same palette again in the other 16-bit display format of
                            the era. Either decodes correctly; pick one and expand 5→8 bits by
                            left-shifting 3 (which yields 248, not 255, for full white).
...   an unidentified region (1,512 bytes for a 180×120 stamp) — does not need to be understood
      to decode the image, because:
END   the pixel data occupies the LAST `height × frameCount × rowStride(width)` bytes of the payload,
      i.e. it is anchored to the END of the file, not to a fixed offset. 8-bit palette indices,
      stored TOP-DOWN.
```

**Row layout — the part that takes real care.** A scanline is *not* a flat run of `width` bytes. There is a
pad byte at every row-stream offset that is a multiple of 128 (offsets 0, 128, 256, …):

```
rowStride(w) = w + 1 + w/128          (integer division)
offsetOf(column k) = k + 1 + (k+1)/128
```

So a 180-wide row occupies 182 bytes, laid out as `pad + 127 indices + pad + 53 indices`.

Two failure modes here are worth calling out because both *look* like success:

- Decoding with no leading pad at all produces an image that is recognisable but wrong at column 0 and the
  last few columns.
- Decoding with only the leading pad (missing the every-128-bytes rule) produces an image that is **visually
  perfect except for a single bright vertical stripe at column 127**, and moves the mean error against a
  reference decode by so little (10.5 → 4.5 on a 0–765 scale) that an automated check will not flag it.
  This was caught by eye, not by metric.

**The compressed variant — ❓ UNKNOWN.** 149 of the 211 stamps on the disc decode with the layout above.
The other 62 — including `Trackmap.stp` and most UI buttons — have payloads far too small for it
(`Trackmap.stp` is 300×151 = 45,300 pixels in an 11,674-byte payload, ~0.26 bytes/pixel), so a second,
compressed encoding exists. There is no flag distinguishing the two in the header fields above; the
practical test is whether the computed pixel-block start is plausible.

**Loose `.stp` files.** The engine will also read a `.stp` as a loose file in `Data/` rather than from an
archive, provided it is **truncated so the file begins at `!IGM`** — i.e. the 20-byte envelope reduced to
its last 4 bytes. A loose 180×120 screenshot is therefore 24,400 bytes (`4 + 24,396`). Add-on tracks use
this to supply a menu screenshot (§9).

### 4.7 `GRAF` — `.grf` track/world geometry — ✅ CONFIRMED (99.95% of the payload accounted for)

> **Revised.** This section previously called the scene-graph header ❓ UNKNOWN and treated `.grf` as the
> one format whose structure was opaque — the reason the writer is a patcher rather than a builder. That
> was too pessimistic. Measuring a freshly compiled `.grf` accounts for **790,272 of 790,676 payload
> bytes**, and what remains is 404 bytes of per-chunk header that reads cleanly. The detail is under
> *The payload is almost entirely accounted for* below.

The main track mesh + material file, and one of the largest per-track resources (259 KB–749 KB in the
sample set). Envelope is `0SER`/`FARG`/version=3/`!IGM`.

**A `.grf` is a sequence of chunks, and each chunk is structurally a `.mod` mesh** (§4.1): vertices, then
material records carrying sub-ranges, then faces. Verified byte-for-byte against independent ground truth —
per-object reference meshes extracted from the same archives, which give each scenery object as a
standalone `.mod` and so allow every field below to be checked against real position/UV/face data rather
than inferred.

```
CHUNK = center record + N corner records + M material records + F face records

center record (16 bytes) -- the object's placement/pivot in world space; (0,0,0) for an object
                            modelled at its final position, non-zero for a template instanced at
                            many spots (e.g. the repeated crowd billboards)
  +0   float32 × 3   center X, Y, Z
  +12  int32         usually 0, but NOT reliably (real tail chunks carry e.g. 54 — do not validate on it)

corner record (32 bytes) -- one per face-corner, NOT deduplicated (a quad's two triangles yield 4)
  +0   float32 × 3   position MINUS center
  +12  int32   0                    (constant)
  +16  uint32  baked vertex colour  -- RGB VARIES per real shading; only the alpha byte (0xFF) is constant
  +20  int32   0xFF000000           (constant)
  +24  float32 × 2   U, V           -- this corner's own, un-shifted, NOT v-flipped

material record (32 bytes) -- identical to .mod's
  +0   null-terminated texture name (may be EMPTY: a leading NUL is legitimate and occurs in real
       files, e.g. b"\x00exy.tex" — treat the name as a label, never as a validity test)
  +24  int16 × 4  vertexStart, vertexEnd, faceStart, faceEnd

face record (8 bytes)
  +0   int16 × 3  corner indices, LOCAL to the chunk, same winding as .mod
  +6   int16 0    pad
```

**The material chain is the authoritative validator.** Material *i*'s `*_end` equals material *i+1*'s
`*_start`, and the last one's `vertexEnd` equals the chunk's corner count. That property both proves a
candidate chunk is real and computes its exact end, so chunk boundaries are derived rather than searched
for. A chunk routinely carries **several** materials; assuming one texture per chunk silently discards
every secondary material's geometry, which is enough to make whole categories of scenery invisible.

**The main header is a scene graph, and is not mapped.** Beyond the chunks, 10–16% of every real `.grf`
sits in variable-size node records in the gaps *between* chunks, threaded with pointers. A 40-byte gap is
exactly one node header `[count, nextPtr, 0, -1, 4, 0, 1, 0, K, 0]`; larger gaps prepend a variable-size
record (a 68-byte one carries floats that look like a bounding box). Gap sizes are discrete and all
multiples of 4 (40/60/72/76/96/108/112/144/268/280/400/568/760). The tempting rule "the last 40 bytes of
each gap is a node header" holds for only 30–50% of gaps, so this is a real reverse-engineering job, not a
small extension.

**Practical consequence — writing.** Because chunk extents are computed exactly and chunk parsing reaches
end-of-payload precisely (zero trailing bytes on all 8 stock tracks), a `.grf` can be edited by **patching
values in place** without understanding the scene graph at all: the header, the node records and every
pointer are copied through untouched. This supports changing any *value* (vertex positions, UVs, texture
names, face indices — so move/rotate/scale/retexture/remap an existing object) but no *size* (no adding or
removing vertices, faces or materials, and a face cannot be repointed into another chunk since its indices
are chunk-local). An unmodified round-trip is byte-identical on all 8 stock tracks (and on every add-on track
tested, §9). Building a `.grf` from scratch still requires the scene graph.

> **Negative zero.** Real corner records store `-0.0` offsets. Since parsing computes
> `position = center + offset`, a `-0.0` yields `position == center`, and writing back `position - center`
> gives `+0.0` — the same number with different bits, and hundreds of spurious diff bytes per file. An
> in-place writer must compare by **value** and skip unchanged fields rather than comparing bytes.

**`track.grf` is not always the whole visible scene.** Some tracks carry standalone `.mod` entries in the
same archive that must also be drawn (dundas has a `ground.mod`; four tracks carry a `checkpt1.mod`). Note
`checkpt1.mod` references `.stp` materials rather than `.tex`, and dundas's `ground.mod` has junk in the
head of its face array — since `.mod` face indices are read as **signed** int16, junk values above 32767
come back negative and sail past an upper-bound-only range check.

#### The payload is almost entirely accounted for

Measured against a track compiled today, so these are current numbers rather than 1998 ones:

| region | bytes | share |
|---|---|---|
| corners — 19,754 × 32 | 632,128 | 79.9% |
| faces — 19,740 × 8 | 157,920 | 20.0% |
| materials — 7 × 32 | 224 | 0.03% |
| **remaining** | **404** | **0.05%** |

**The 32-byte corner record decodes completely.** Only the leading position was previously identified,
which made the other 20 bytes per vertex look like opaque scene-graph data — and at 19,754 corners that
alone accounted for "half the file being unknown". It is not scene-graph data:

```
+00  float3   position, relative to the chunk centre
+12  u32      0
+16  BGRA     vertex colour -- baked lighting
+20  u32      00 00 00 ff, constant
+24  float2   UV
```

The colour reads as colour and not as a float because of how it varies: a generated track whose geometry
is flat has **exactly one** distinct value across all 19,754 corners (`ff ff ff ff`, white), while bemidji
has 36 distinct values and dundas 46 — greys like `fd fd fd ff` and `b3 b3 b3 ff`, always with alpha
`ff`. That is baked vertex shading, and it is why a generated track can simply write white.

**The per-chunk header is 56 bytes and carries the counts.** For the first chunk of a track whose chunk 0
holds 2,822 corners and 2,820 faces:

```
+00  i32  3           chunk type/version
+04  i32  225916      size or offset of what follows
+0c  i32  -1
+10  i32  2822        corner count
+18  i32  1
+20  i32  2820        face count
+24..+38  zero
```

Both counts appear verbatim. The file header at payload +0 has the same shape, with the first chunk
header beginning at +8.

✅ **`.grf` can now be written from nothing** — `grf.build()`. The 404 bytes were the per-chunk header,
and correlating it across 553 chunks of a compiled track resolves every field. The one that mattered is
`+04`: it holds the offset of the **next** chunk header, terminated by 0. The chunks are a linked list.

```
+00  i32  3          chunk type
+04  i32  offset of the NEXT chunk header, 0 at the end
+08  i32  0
+0c  i32  -1
+10  i32  corner count
+14  i32  0
+18  i32  1
+1c  i32  0
+20  i32  face count
+24  3f   chunk centre -- zero in every chunk nhmkworld writes
```

A chunk is that header, then corners (32 bytes each), then its material record (32), then faces (8 each:
three u16 indices local to the chunk, then a zero). The material record is the texture name NUL-padded,
with the corner and face counts repeated at +26 and +30. The file header is `i32 0, i32 0, i32 12` — 12
being the offset of the first chunk.

Checked against nhmkworld's own output for the same 553 meshes: **the same chunk count, the same payload
size to the byte (915,668), and an identical vertex set of 21,896 positions**. It is *not* byte-identical
and will not be — nhmkworld reorders vertices within a chunk, so the same geometry lands in a different
order — so the test asserts the geometry rather than the bytes. ✅ **A track carrying a `.grf` built this
way loads and drives in game**, which is the check that counts.

⚠️ One limitation. The chain built here is **flat**: every chunk points at the next. That is what
nhmkworld emits for a track made of many small uniform meshes, and such a track renders correctly. The
shipped tracks are not flat — bemidji has 446 chunks but only 2 in its chain — so there is a nesting this
does not reproduce. It has not been needed for generated tracks, but a general-purpose writer would have
to understand it.

### 4.8 `SOLB` — `.sol` — ✅ CONFIRMED — the track's **collision solids** (one enum field aside)

Envelope `0SER`/`LBOS`/version=2/`!IGM`. Not a mesh: an array of **collision primitives** — boxes, spheres
and tubes — which is the complement to `.bpp`'s triangle soup (§4.9). Static world surfaces live in the BSP;
discrete objects live here.

```
header (20 bytes)
  +00  u32  n_primitives
  +04  u32  n1
  +08  u32  0        +0c  u32  0
  +10  float?

primitive x n_primitives (224 bytes each)
  +00  float3x3  orientation
  +24  float3    position
  +30  i32       id            -1 throughout the stock tracks
  +34  FourCC    type          'BOX ', 'SPHR' or 'TUBE'
  +38  ptr       runtime, repaired at load
  +3c  ptr       a REAL VTABLE ADDRESS, serialised into the file
  +48  float     50000.0       class default, identical in every record
  +4c  float     0.2           class default, identical in every record
  +50  FourCC    the type again
  +54  i32       100
  +58..+64       four floats -- extents, type-specific
  +68  i32       0..3 for BOX
  +6c..+dc       zero (runtime workspace)

n1 x 2 bytes                 -- primitive-index list (see below)
tail                         -- spatial index (partially mapped)
```

**Per-type record layouts** (profiled across all eight tracks; `+00`..`+2f` is the same
orientation-matrix + centre preamble for every type, and `+48`/`+4c` are the compiled-in
`50000.0`/`0.2` class defaults in all three):

```
BOX  (1,739 records)   +58..+64  four floats -- half-extents / size
                       +68       i32 0..3  (small enum, meaning open; 3 dominates, 1,382 of 1,739)
SPHR (87 records)      +00..+20  identity orientation (a sphere needs none)
                       +24..+2c  centre     +58  radius (0.56 .. 6.6)
TUBE (931 records)     +14,+1c   +-1 orientation terms (axis-aligned)
                       +24..+2c  centre     +58  radius (0.05 .. 5)   +5c  length (1 .. 30)
                       +60..+7f  an EMBEDDED SPHR sub-record (own vtable, 'SPHR' tag at +74)
```

The TUBE result is the interesting one: a tube is a **capsule** — a cylinder that carries its own
cap-sphere as a nested primitive, which is why it uses more of the 224 bytes than a box or a bare sphere.

**Read from the loader at `0x42FEE0`**, which is where the sizes come from rather than from guessing:
`lea edx,[esi+0x14]` gives the 20-byte header; `shl ecx,3 / sub ecx,eax / shl ecx,5` computes
`n_primitives * 7 * 32` = **224-byte records**; `lea ecx,[edx+eax*2]` steps a **2-byte** table; and the
per-record loop advances by `add ebx, 0xe0` — 224, confirmed from the loop itself.

**Section 2 — the primitive-index list** (`n1` × `u16`). Every entry is a valid primitive index (all in
`[0, n_primitives)`, all primitives referenced, many-to-one — bemidji has 382 entries over 135 primitives).
This is the broadphase reference list: the spatial cells name the solids they contain by index here.

**Confirmed against a freshly compiled `.sol`, not just shipped ones.** Running MKWORLD over a scene
with 1,210 inline wall quads produced 1,201 BOX primitives — very nearly one per quad, so the compiler is
not merging colinear walls the way one might assume. Every field above read correctly at the documented
offsets, which is the strongest available check on §4.8: the layout was derived from the loader, and it
holds for a file written today rather than in 1998.

The same run says something new about the **tail spatial index**, and it rules out the obvious guess:

| track | primitives | `n1` | tail bytes |
|---|---|---|---|
| bemidji | 135 | 382 | 10,248 |
| kenyon | 170 | 403 | 12,808 |
| heaven | 440 | 1,838 | **32,648** |
| dundas | 602 | 1,498 | 26,984 |
| **fresh compile** | **1,201** | 1,899 | **10,952** |

The freshly compiled track has **more primitives than any shipped track and nearly the smallest tail**.
So the tail is not sized by primitive count — it is sized by how the solids are *distributed*. That fits a
spatial subdivision: our walls run in a thin ribbon along a single path and occupy few cells, while
heaven's are spread across the map. Anyone finishing this section should treat it as an occupancy
structure over space, not an array over primitives.

**These are serialised C++ objects.** The file contains live vtable pointers from the machine that built it,
which is why the loader re-establishes them per type: it dispatches on the FourCC to `0x42D9D0` (BOX),
`0x42C360` (SPHR) or `0x42D760` (TUBE), each of which writes the current build's vtable, then calls through
it. An unrecognised tag is not rejected — the record is disabled by setting `+0x30 = -1`.

⚠️ **The physical properties are compiled in per type, not stored per object.** The BOX constructor passes
constants `1.0` and `0.6` to a shared initialiser; `+0x48` (50000.0) and `+0x4c` (0.2) are class defaults
that got serialised, and they are byte-identical across **2,670 records in every stock and community track
examined**. So you cannot make an individual solid behave differently — heavier, bouncier, knock-over-able —
by editing `.sol`. Whatever governs non-rigid props is a different system; the strings `PhysTask`,
`phob_list` and `shm_PhysicsShmem` sit beside `track.sol` in `.data` and are the obvious lead.

**Section 3 — a loose quadtree over the XZ plane** ✅ CONFIRMED (from the walker at `0x421180`). An array of
8-byte nodes:

```
+0  u16  first    -- start index into section 2
+2  u16  last     -- end index (exclusive); the node's primitives are section2[first:last]
+4  u16  child    -- index of the FIRST of four contiguous child nodes; 0 = leaf
+6  u16  (unused, always 0)
```

The query walks it point-first: at each node it tests the query against every primitive in
`section2[first:last]` (via that primitive's vtable), then, if `child != 0`, picks one of the four children
`child+0..child+3` by which side of the region's X and Z midpoints the point lies, and descends. It is
"loose" because a node may hold primitives *and* have children — a solid too big for one quadrant sits in the
parent. This is the broadphase that keeps a collision query from testing all `n_primitives` solids.

Verified across four tracks: from the root, **100% of nodes are reachable, none malformed**, every range lies
within section 2, and the node count is exactly `4 × internal + 1` — the signature of a quadtree where every
internal node has four children. That relationship, plus `last` reaching exactly `n1`, means the whole `.sol`
file is now accounted for: header, primitives, the section-2 index list, and this tree.

⚪ Only one field remains unexplained: BOX's `+0x68` small enum (0..3).

### 4.9 `BPPT` — `.bpp` — ✅ CONFIRMED — the track's **collision BSP**

The single **largest** file in every track (1.0 MB–2.4 MB, dwarfing even `.grf`) and, until this pass,
completely unexplained. It is a **triangle soup plus a 2D BSP tree over the XZ plane** — the structure the
physics uses to answer "what is under / in front of the car". Envelope `0SER`/`TPPB`/version=2/`!IGM`.

```
header (20 bytes)
  +00  u32    n_triangles
  +04  u32    n_nodes
  +08  u32    0
  +0c  u32    0
  +10  u32    root node index

triangle × n_triangles (56 bytes each)
  +00  float3 normal          unit length
  +0c  float  d               plane, with the convention  n·v + d = 0
  +10  float3 v0
  +1c  float3 v1
  +28  float3 v2
  +34  u32    flag            per-triangle surface bits (see below)

node × n_nodes (28 bytes each)
  +00  float  a
  +04  float  b               splitting line in the XZ plane:  a·x + b·z + c
  +08  float  c
  +0c  i32    tri0            triangle index, -1 = none
  +10  i32    tri1            triangle index, -1 = none
  +14  i32    less            child node index, -1 = null
  +18  i32    greater         child node index, -1 = null
```

**The layout accounts for every byte of all eight stock tracks, exactly** — `20 + 56·n_triangles +
28·n_nodes == filesize`, with no slack and no padding:

| Track | Triangles | Nodes | Root | Size |
|---|---|---|---|---|
| bemidji | 10,431 | 34,712 | 4,561 | 1,556,092 |
| dundas | 11,120 | 37,020 | 1,920 | 1,659,300 |
| hastings | 12,694 | 41,334 | 11,690 | 1,868,236 |
| heaven | 7,299 | 22,449 | 3,429 | 1,037,336 |
| kenyon | 13,640 | 43,577 | 10,531 | 1,984,016 |
| limbo | 10,153 | 34,171 | 3,525 | 1,525,376 |
| nfield | 16,525 | 53,378 | 15,507 | 2,420,004 |
| uptown | 12,092 | 43,078 | 11,250 | 1,883,356 |

**The triangle record verifies as an identity, not a correlation.** Across bemidji's 10,431 records the
normal is unit to six decimal places — min and max both `1.000000` — and all 31,293 vertices satisfy
`n·v + d = 0` to a **maximum residual of 0.00006**. The opposite sign convention (`n·v − d`) gives a mean
error of 124, so the sign is settled too.

✅ **Round-trips byte for byte.** `vrmod/bpp.py` parses and rebuilds all eight stock `.bpp` files to
identical bytes — the same standard every other confirmed format in this document is held to. `tri0`/`tri1`
and the flag ride along as opaque integers, so the round-trip holds whether or not their meaning is known.
`vrmod bppinfo <track>` summarises one; `vrmod bpp2obj <track> <out.obj>` exports the collision mesh;
`vrmod bppsurface <track>` lists the surface codes, and `vrmod bppsurface <track> --set 10=20` rewrites them
(here grass→dirt), optionally within an XZ `--region`. Because the round-trip is byte-exact, retagging
touches only the one flag field per triangle — the collision *shape* is untouched, so it cannot introduce
the invisible-wall problem above; it only changes how the car behaves on contact (drag, dust, float).

**The triangle flag is a SURFACE CODE**, and the original build tools name the values. The community
track-tools archive ships the Monster Games pipeline with worked example inputs, and those inputs set the
codes in plain text:

```
modobject(road3.mod,               0, 0,  0, 0)
modobject(grassin3.mod,            0, 0, 10, 0)
modobject(grasswayout3.mod,        0, 0, 16, 0)
modobject(roads.mod,               0, 0,  0, 0) ;driveable on
modobject(grasses-stikky.mod,      0, 0, 10, 0) ;driveable on
modobject(grassout-bumpy-not-stikky.mod, 0, 0, 16, 0) ;driveable on
modobject(2dplanet2x.mod,          3, 0,  0, 0) ;not hittable-code3
```

The third parameter is the surface code written into every collision triangle the object generates, and it
matches the values measured in the shipped `.bpp` files exactly:

| code | meaning | stock triangles | stock tracks |
|---|---|---|---|
| 0 | asphalt / road ✅ (confirmed from engine code) | 72,103 | 8/8 |
| 10 | grass, "stikky" (grippy); also infield | 19,081 | 8/8 |
| 14 | **water** ✅ (confirmed from engine code) | 251 | ridge-valley, rock-island, silverdale |
| 16 | rumble strip / side apron — bumpy, low grip | 737 | castle, silverdale |
| 20 | 🟡 **dirt / loose surface** (strongly indicated, not proven) | 1,033 | dundas, ridge-valley, silverdale |
| 22 | ⚪ unknown | 225 | ridge-valley, silverdale |
| 12 | ⚪ unknown (own handler) | 192 | **sunset-mesa only** |
| 23 | 🟡 shares code 20's handler | 328 | **sunset-mesa only** |
| 3 | ⚪ unknown (as a surface code) | 4 | ridge-valley only |
| 13 | 🟡 grass variant (shares grass's handler) | — | none; one community track only |

#### Corroborated against 160 community tracks

A community corpus of 160 tracks (Val's collection, 459,535 collision triangles) was profiled for surface
codes. It uses the same palette and adds exactly one code the shipped tracks never use (13, in a single
track), which is itself evidence that the code space is small and fixed.

**Code 14 is water**, identified geometrically rather than from a tool, because water is the one surface that
must be flat and at a single height. In silverdale its 30 triangles are **100% horizontal across just two
distinct heights**; rock-island's 132 are 88.6% horizontal, ridge-valley's 89 are 83.1%. Road, by contrast,
is 4–27% horizontal over thousands of distinct heights. It appears in exactly three shipped tracks —
ridge-valley (confirmed in game: the car bobs and floats), rock-island (an island), silverdale — and the
community corpus settles it beyond argument. Ten community tracks use code 14, and the names alone tell the
story: **Oceans9, X-Isle, Carrier1**, Airfields, Dawn, High12, Lucas, Redvers, DDhigh13, RT-high14.
**Oceans9 is 99.9% code 14** — a boat-racing track made almost entirely of water, whose readme complains
that "the other racers' *boats* seem to sit at the start line". X-Isle's readme credits an "island raceway
idea".

#### ✅ The engine confirms 0 and 14, via the "Pave the World" hack

The Options → Hacks menu has a **Pave the World** toggle which removes the drag that grass and dirt apply to
the car. Following it settles two codes from the engine itself rather than from tooling.

The config key `pave_the_world` (`0x4D3140`) registers the variable `0x4EF838`; `0x40D170` is the accessor
`hacks_enabled && pave_the_world`; and it has exactly **one caller**, inside the contact-point physics at
`0x443148`:

```
cmp  dword [edi+0x19c], 0xE      ; is this contact's surface code 14?
je   skip                        ;   if so, leave it alone
call is_pave_the_world
test al, al
je   skip
mov  dword [edi+0x19c], ebx      ; otherwise overwrite it   (ebx = 0, from xor ebx,ebx at 0x44308D)
```

So `[edi+0x19c]` is **the surface code of a contact point**, carried from the `.bpp` triangle into the
physics. Three things follow directly:

- **0 is asphalt.** It is what "paving" writes, and the same function initialises the field to 0 at
  `0x442EF0`.
- **14 is water, confirmed from code.** It is the single value the hack refuses to overwrite — you cannot
  pave water, and the car must keep floating. The engine special-cases exactly the code the geometry and the
  community corpus both pointed at.
- **The surface code is the mechanism behind the "stikky" naming.** Paving is implemented by *rewriting the
  surface code to asphalt*, which is why the hack removes the drag from every off-track surface at once
  rather than adjusting a friction constant.

#### ✅ The engine's full surface-code table

`0x4435A0`, in the same contact-point physics, dispatches on the surface code through a two-level table:

```
mov  ecx, [edi+0x19c]              ; the surface code
cmp  ecx, 0x17                     ; 23 -- the maximum valid code
ja   default
mov  al, byte [ecx + 0x444368]     ; 24-entry table: code -> case
jmp  dword [eax*4 + 0x444344]      ; 9-entry table: case -> handler
```

**The code space is 0..23 and closed** — which is why the whole 160-track community corpus never produced a
value outside it. Nine cases resolve to six distinct handlers, and the grouping answers several open codes
by showing which behave identically:

| Handler | Codes | Effect type | Drag A | Drag B |
|---|---|---|---|---|
| `0x4435E9` | **0** (asphalt) | **0** | — | — |
| `0x443622` | **10, 11, 13, 15** | 5 | 0.8 | **2.5** |
| `0x44364E` | **12** | 5 | 0.9 | 0.1 |
| `0x443667` | **20, 23** | 5 | 0.9 | 0.1 |
| `0x443693` | 21 | 5 | 0.9 | 0.5 |
| `0x4435BA` (default) | 1–9, **14**, **16**, 17–19, **22** | 5 | 0.9 | 0.1 |

- **13 is a grass variant** — it shares grass's handler exactly. That resolves the one code the community
  corpus used which the shipped tracks never do.
- **23 shares a handler with 20**, so sunset-mesa's second mystery code behaves identically to the dirt
  candidate. If 20 is dirt, 23 is a dirt variant.
- **14 (water) and 16 (rumble) fall to the default path**, which is consistent: floating is handled
  elsewhere (the pave-the-world check special-cases 14), and a rumble strip is bumpy through geometry rather
  than through drag.
- **11, 15, 17–19, 21** are implemented but appear in no track, shipped or community.

**"Stikky" is literal, and grass is the stickiest surface in the game.** At `0x4433C0`:

```
if  surface == 10 (grass):   drag *= 9.0
elif surface != 0:           drag *= 3.0
else (asphalt):              drag  = 0
                             drag *= 0.3
```

Grass drags three times harder than any other off-track surface, and asphalt is exactly zero — which is
precisely what Pave the World achieves by rewriting the code to 0. Asphalt is also the only surface with
effect type 0; every other surface uses type 5, the dust and debris thrown up off-track.

🟡 **Code 20 is most likely dirt or another loose surface.** It is a primary *driving* surface, not runoff:
`8track` is 81.1% code 20 against 18.9% asphalt, `JCsSnow` — built for a snowmobile car mod — is 33.4% code
20 with no asphalt at all, and `Rallye22` uses it for a quarter of its surface. A figure-8 oval, a snow
track and a rally track all racing on the same code points at loose ground; in the shipped road courses it
would be the dirt runoff. No tool or text names it, so this stays a hypothesis.

`vrtrackmaker.exe`, the community track maker, emits **only codes 0, 10 and 16** and contains no water
vocabulary at all — which is why most community tracks use just asphalt, grass and rumble. Authors who wanted
water or dirt had to write the `modobject` codes by hand, since the pipeline's input is plain text — which
is exactly what the ten water tracks and ten dirt tracks in the corpus did. Its own
templates name them: `asphalt.mod → 0`, `grassl/infill.mod → 10`, `rumbll/sidel.mod → 16`.

⚠️ **Code 3 in the FIRST parameter means "generates no collision geometry"** and is unrelated to the surface
code in the third. `vrtrackmaker` writes `modobject(wallali.mod, 3, 0, 0, 0)` for every wall, and a
hand-written example uses it for scenery with the comment `;not hittable-code3`. Walls are drawn but produce
no `.bpp` triangles because their collision is authored separately as `.sol` solids.

#### How a track is actually built

The commands below are the *back half*. The front half — how geometry and a centreline become those two
text files in the first place — is documented under
[The modern workflow, end to end](#the-modern-workflow-end-to-end) further down, and it is the part no
recovered document describes.

The build is **two batch files**, not one: `make-track.bat` compiles, then hands off to
`compile-track.bat` which packs. Both survive, and both are reproduced verbatim below — this is the
critical link in the chain, and the step that determines whether a track works in Viper at all.

```bat
@echo off
color 0a
rmdir /s /q out
rmdir /s /q tra
del /s /q track.flt
del  /s /q mtrack.flt
ECHO PAUSING FOR 2 SECONDS
PING 1.1.1.1 -n 1 -w 2000 >NUL
md out
md tra
mkfltoa.exe foolandsurface.txt track.flt -viper
MKWORLD.EXE
echo IF YOU SEE NO ERRORS - CONTINUE
echo IF YOU DO - CAREFULLY READ THE DETAILS CAUSING THE ERROR
echo THEN "x" OUT OF THIS BATCH FILE UNTIL YOU FIX IT
pause
mkilicc -nolat track.ili            tra\track.ild
mkilicc -nolat track-ai.ili         tra\default.ili
mkilicc -nolat track-ai-reverse.ili tra\rdefault.ili
copy out\track.sol tra\track.sol
copy out\track.obt tra\track.obt
copy out\track.bsp tra\track.bsp
mkfltoa.exe foolandgraphic.txt mtrack.flt
nhmkworld.exe mtrack.flt
echo IF YOU SEE NO ERRORS - CONTINUE
echo IF YOU DO - CAREFULLY READ THE DETAILS CAUSING THE ERROR
echo THEN "x" OUT OF THIS BATCH FILE UNTIL YOU FIX IT
pause
copy out\track.bpp tra\track.bpp
copy out\track.grf tra\track.grf
copy camera.tab tra
copy aidef.ccs tra
copy trackmap.stp tra
xcopy /e /y mkresfiles tra
cd tra
CALL  compile-track.bat
```

…and `mkresfiles\compile-track.bat`, which produces the shipping archive:

```bat
:: REPLACE THE "trackname" BELOW TO THE NAME OF THE TRACK YOU ARE PUTTING TOGETHER.
mkres trackname.tra @reslist.txt
```

Several things follow from this that were not visible in the summary form:

- **The AI lines are compiled, and there are three of them.** `mkilicc -nolat` runs three times over three
  separate hand-authored inputs — and this settles what `rdefault.ili` is: `track-ai-reverse.ili` is the
  **reverse-direction racing line**. `track.ili` compiles to `track.ild` (the line the track map draws),
  `track-ai.ili` to `default.ili` (the forward AI line).
- **The surface pass must fully succeed before the graphic pass runs.** The two `pause` blocks are not
  decoration — the author put a hard stop between the passes precisely because a silent failure in the
  first produces a track that compiles and then misbehaves.
- **`MKWORLD.EXE` takes no arguments** — it picks up `track.flt` implicitly, which is why the `mkfltoa`
  output filename is fixed. `nhmkworld.exe` does take its `.flt` explicitly.
- **Not everything is generated.** `camera.tab`, `aidef.ccs`, `trackmap.stp` and every `.tex` are authored
  separately and copied in. Only `.sol/.obt/.bsp/.grf/.bpp` and the three `.ili`-derived files come out of
  the compiler.
- **The `.tra` is built by `mkres`, the same packer as `.car` and `.res`,** driven by a `reslist.txt` that
  fixes the member order:

  ```
  aidef.ccs  camera.tab  default.ili  rdefault.ili  track.bpp  track.bsp
  track.grf  track.ild   track.obt    track.sol     Trackmap.stp
  sky1-4.tex  grass.tex  asphaltv.tex  pine3o15.tex  bboard01.tex
  ```

  Which matches what `vrmod list` reports for a real track, and confirms the archive format documented at
  the top of this file is exactly what the original tools emit.

**`.bpp` and `.grf` are generated together, from the same source file.** The collision BSP is derived from
the visible geometry rather than authored separately — which is exactly why editing a compiled `.grf`
without regenerating `.bpp` leaves collision behind. `.sol` comes from the *surface* file instead, whose
`;Walls` block holds wall geometry written out **inline** as `object(wall.tga,1,0)` blocks of four `vert()`
and one `quad()` — not, as previously guessed here, BOX/SPHR/TUBE solid primitives.
`mkfltoa` converts to **OpenFlight** (`.flt`), a standard interchange format, so track authoring goes
through ordinary 3D tools rather than anything bespoke.

⚠️ **Every driveable object must be declared in BOTH source files, under the same name.** This is the
constraint that makes the two-file split workable, and it is stated in the shipped example source itself —
`eg-foolandsurface.txt`, lines 10–11, the same file this document already quotes for its `modobject`
examples:

```
;NOTE- ONLY DRIVEABLE SURFACE mod FILES ARE LISTED IN THE modobject LINES
;THEY MUST BE THE SAME AS THE DRIVEABLE NAMES IN THE foolandgraphic.txt
```

The tutorial says the same thing in a red annotation over a screenshot of the author's Notepad window,
which is where this was first noticed here — "MAKE SURE YOU ALSO PUT […] IN YOUR foolandgraphic.txt",
beside `modobject(road1.mod, 0, 0, 0, 0)` … `modobject(water1pond.mod, 0, 0, 14, 0)`, whose matching codes
in both files are what extends the rule from names to surface codes. But the comment above is the
authoritative source and was always in plain text; the screenshot only corroborates it.

The two files share a syntax but are **not** the same document. Running the generator (below) settles
their actual shapes:

| | `foolandsurface.txt` | `foolandgraphic.txt` |
|---|---|---|
| `path(center)` | **absent** | 1 block, 358 verts |
| `marker(checkN)` | 2, each with 2 verts | 1, **empty** |
| `modobject()` | 9 — driveable only | 13 — driveable + 4 walls |
| wall geometry | **inline** `object(wall.tga,1,0)` blocks | referenced as `.mod` |
| size | 247 KB | 14 KB |

The nine driveable entries are **identical in both files, name and surface code alike** — which is the
rule above, confirmed from the generator's own output rather than from a comment about it. The difference
is what each adds around them: the surface file carries the checkpoint gate lines and the collision walls,
the graphic file carries the centreline and the visible wall meshes. Divergence between the two copies is
the classic authoring failure where a track looks right but the car drives through or over the wrong
thing.

The same screenshots corroborate the surface-code table from a direction independent of both the engine
code and the geometry: an author naming a mesh `water1pond.mod` and tagging it **14** is the third
confirmation that 14 is water, and the most direct kind. `path(center)` is also confirmed as the track
centreline the rest of the build derives from — the annotation beside it reads "JUST A NOTE ABOUT THESE
'PATH' VERTS… YOURS WILL BE A LOT LONGER THAN THIS EXAMPLE IS."

#### The modern workflow, end to end

Everything above was reconstructed from recovered 1990s–2000s material. The question it leaves open is
whether a track can still be built *today*, on current tools — and it can. This is a working pipeline,
[documented by HerbFargus](https://github.com/HerbFargus/viper-racing-legacy-modding-tools/wiki/Creating-a-Custom-Track)
from tracks actually built with it:

```
Bob's Track Builder Pro   model the track                   ->  .dof
  Zmodeler                import .dof, replace textures     ->  .mod + .tex   the LOOKS
                                                            ->  .3ds          (on to Max)
  3DS Max                 import .3ds, draw the centreline  ->  .ase
  vrTrackMaker            import .ase                       ->  fooland*.txt  the DRIVING
                                                                .ili x4, aispeed.txt
  make-track.bat          mkfltoa -> MKWORLD / nhmkworld    ->  .sol .obt .bsp .grf .bpp
  compile-track.bat       mkres @reslist.txt                ->  <track>.tra
```

**This is a hybrid, and that is the thing to understand about it.** Two branches run from the same BTB
geometry and converge at `make-track.bat`: Zmodeler produces what the track *looks* like, and
vrTrackMaker — fed only a centreline — produces how it *drives*. Neither tool can do the other's job.
BTB knows nothing about Viper's surface codes, `.sol` walls or `.ili` racing lines; vrTrackMaker sweeps a
single fixed six-band cross-section and calculates no normals, so it can make a passable oval and nothing
resembling a real circuit.

The join is the `.ase` centreline, and it explains several things this document had recorded separately
without connecting:

- `path(center)`, the centreline block at the top of both source files, is that Max spline after
  vrTrackMaker has written it out. The "yours will be a lot longer than this example" annotation is
  describing a spline export, which is why the vert lists run to hundreds of entries.
- vrTrackMaker emits **only surface codes 0, 10 and 16** (documented above). Now it is clear *why* authors
  who wanted water or dirt had to hand-edit: those codes are not reachable from the generator, so the text
  it produces has to be edited after the fact — and per the rule above, edited in **both** files, or the
  track will look right and drive wrong.
- Zmodeler produces the `.mod` meshes and the `.3ds` in the same pass, which is what keeps mesh names
  consistent between the geometry and the `modobject()` lines that must reference them.

Two of these steps are the same commercial tools the original community used — 3DS Max, and Zmodeler for
the `.dof` import. `vrmod`'s `mod2obj` / `obj2mod` already covers the *looks* branch with free tools: any
modeller that can export OBJ can produce the meshes. What has no counterpart here is the **driving**
branch — centreline in, `fooland*.txt` plus the `.ili` set out. That is the concrete, bounded shape of any
future track-authoring work, and it is now specified on both ends: the input is an ordinary polyline, and
the output is a text format this document describes in full, with a reference implementation's exact
output to check against.

#### vrTrackMaker — the driving model, not the track

Sucahyo's **"VR simple Track Maker"** turns a bare spline into the MKWORLD source set. Read in isolation
it looks like a track generator, and it *can* be used as one — but that is not its role in the modern
pipeline, and mistaking the one for the other misreads the whole workflow.

**It is used as a hybrid.** The visible track is built in BTB and carried through Zmodeler into `.mod`
meshes and textures. That same geometry then goes to 3DS Max, where the centreline is drawn and exported
as `.ase`, and *that* is what vrTrackMaker consumes — so what it is really being asked to produce is the
**driving model**: the collision surfaces with their material codes, the walls, the checkpoint gates, the
AI racing lines and the speed profile. The wiki workflow makes this explicit by structure rather than by
statement: Zmodeler emits the game meshes **and** the `.3ds` for Max. If vrTrackMaker were generating the
track, those Zmodeler meshes would have nothing to do.

Its own design says the same. It sweeps one fixed six-band cross-section, calculates no normals, and by
its readme will "only create asphalt, wall, side, rumble and small part of grass" — adequate for a simple
oval, nowhere near a BTB-quality circuit. What it *is* good at is the part BTB knows nothing about: Viper
Racing's surface codes, `.sol` walls, and `.ili` racing lines.

The practical consequence is that its generated meshes are a **fallback, not the deliverable**. In a
hybrid build the author keeps its `foolandsurface.txt` / `foolandgraphic.txt`, the `.ili` set and
`aispeed.txt`, and points the `modobject()` lines at their own BTB-derived meshes — at which point the
both-files rule above stops being trivia and becomes the thing that makes or breaks the track, since the
names now have to be edited consistently across two files that the generator wrote for different meshes
entirely.

**What it does.** It sweeps a parameterised cross-section along the spline. The bands are fixed and named
in the UI — **Road, Wall, Side, Rumble1, Rumble2, Grass** — each with a *distance to centre* and a
*height*, which is exactly the vocabulary the surface codes use (Road→0, Side/Rumble→16, Grass→10) and
why the tool can only ever emit those three. Its own readme says so outright: it will "only create
asphalt, wall, side, rumble and small part of grass." **AI path generation is built in** — with forward
and backward lookup distances in metres — which is where `track-ai.ili` comes from; the readme notes that
`trkaitweaker.exe` is no longer needed as a result.

Its shipped defaults, read from the running application (a Delphi `TFmain`; the labels are `TLabel`s, so
they are drawn rather than exposed as controls):

| band | distance to centre | height | UV multiplier |
|---|---|---|---|
| Road | 6.000 | — | 1.000 |
| Wall | 0.010 | 1.000 | 4.000 |
| Side | 1.000 | −0.200 | 2.000 |
| Rumble1 | 0.300 | 0.100 | — |
| Rumble2 | 0.600 | −0.100 | 3.000 |
| Grass | 20.000 | 0.000 | 1.000 |

Banking multiplier `0.300`, max banking `5`°, "No banking" checked. Wall type is a four-way choice —
`all` / `corner` / **`corner outside`** (the default) / `none`. Thresholds: simplify `0.00001`, corner
`0.100`, wall `1`, rumble `1`. AI path: forward lookup `30` m, backward lookup `5` m, mult `0.15`, add
`0.005`.

*Process file* fills a grid whose columns are **x, y, z, dirangle, bankangle, length** — the simplified
centreline with a per-segment heading, bank angle and run length. Comparing that grid against the input
`.ase` shows the tool applies a coordinate change on the way in: a knot at
`(−7.5317, 186.3278, 0.0000)` in the `.ase` appears as `(7.532, 0.000, −186.328)`, i.e.
**x→−x, y→−z, z→y** — the 3DS Max Z-up frame converted to Viper's Y-up left-handed one. The
`path(center)` verts in `foolandgraphic.txt` are in the *original* `.ase` frame, so this conversion
happens for display and for the geometry it generates, not in the text it writes.

⚠️ **Line endings matter, and this has already damaged an archived file.** The tool is a Delphi program
that splits its input on CRLF. The copy of Sucahyo's own test spline `path10.ASE` held in the
[legacy-tools archive](https://github.com/HerbFargus/viper-racing-legacy-modding-tools) has been
**normalised to bare LF** somewhere in its archival history — 3,581 LF and zero CRLF — and in that state
the tool reads several lines as one value and dies with

```
'0.0000
    *SHAPE_VERTEX_KNOT  1  -6.4834  186.3442  0.0000
    ...' is not a valid floating point value.
```

Converting back to CRLF makes it parse cleanly. This is a preservation defect rather than a tool defect,
and it is a general hazard: **any text file in these archives that passed through a line-ending–normalising
step may be unusable by the original tools** even though it looks correct in an editor. `.ase` splines,
`fooland*.txt` sources, `reslist.txt` and the `.bat` files are all exposed to it.

For the record, `path10.ASE` is a 3DS Max ASCII export dated 13 March 2008 from a scene named
`kyalamimain.max`, holding one closed `*SHAPEOBJECT` named `linepath` with 3,759 knots. Its first knot is
`(−7.5317, 186.3278, 0.0000)` — identical to the first `vert()` of the `foolandgraphic.txt` shown in the
tutorial screenshots, so the archived test spline and the tutorial's worked example come from the same
source track, decimated with different thresholds.

**What it demands of the spline**, all of which will silently ruin a track if violated:

- the path must run **clockwise**, or polygons come out reversed;
- it must go in **one direction only** — a backward segment punches a hole, fixed by deleting vertex lines
  from the end of the `.ase`;
- it must be **dense**: normalise to 50.0 if needed, then to **1.0**;
- the **start/finish line must be straight**;
- the path must **never cross or overlap itself**; there is no overlap detection, and an overlap becomes a
  hole;
- export with **4-decimal precision and `.` as the decimal separator** — the readme warns to change
  regional settings first, since a comma separator makes the tool error out.

**The two-button workflow.** *Process file* reads the `.ase` and builds the path and its bank-angle table
— "by all means, DO NOT DELETE THE TABLE RECORD", since only the bank-angle column feeds the next stage.
*Write model* emits `foolandsurface.txt`. If the wall count exceeds 2,000, the readme's instruction is to
redo with a higher simplify threshold, keep *that* `foolandsurface.txt`, and re-run normally for
everything else.

⚠️ **Engine limits this readme records, which appear nowhere else:**

| Limit | Value |
|---|---|
| walls per track | **2,000** |
| vertices per track | **65,000** |
| polygons per track | **65,000** |

The 65,000-polygon ceiling is worth reading against the `race.bin` table in
[MODDING_HISTORY.md](MODDING_HISTORY.md): Sucahyo — who wrote both this tool and the 1.2.4-beta engine
patch — raised track support to **95,000 polygons** in that patch. These figures are stated without a
version, so read them as the constraint the tool was written against rather than a measurement of any
particular binary.

Two smaller notes from the same readme: normals are **not** calculated by the tool, and wall compilation
draws on `foolandsurface.txt` plus any `.mod` whose name carries a `wall` suffix. Its output track is
always named `generic.tra` — renaming happens afterwards, which is consistent with `compile-track.bat`
shipping with `trackname` as a literal placeholder to be edited.

#### What vrTrackMaker actually emits

Observed, not inferred: Sucahyo's own test spline `path10.ASE` was run through the tool and it wrote
**21 files** into the working directory. This is the set `make-track.bat` then consumes.

**The two scene sources** — `foolandsurface.txt` (247 KB) and `foolandgraphic.txt` (14 KB); shapes as
tabulated earlier.

**Fourteen meshes**, and their names are exactly the ones the shipped example sources reference, which
confirms those examples were themselves generated by this tool:

| meshes | surface code | texture |
|---|---|---|
| `asphalt.mod` | 0 | `asphalt.tex` |
| `sidel.mod`, `sider.mod` | 16 | `side.tex` |
| `rumbll.mod`, `rumblr.mod` | 16 | `rumble.tex` |
| `grassl.mod`, `grassr.mod` | 10 | `grass.tex` |
| `infill.mod`, `infilr.mod` | 10 | `grass.tex` |
| `wallcli/clo/cri/cro.mod` | — (first param **3**) | `wall.tex` |

Left/right pairs throughout, an `infil*` inner pair for the infield, and four corner walls (inner/outer,
left/right). The walls are emitted as `modobject(wallcli.mod, 3, 0, 0, 0)` — **first parameter 3, meaning
they generate no collision geometry**, exactly as documented above; their collision comes from the inline
`object(wall.tga)` quads in the surface file instead. Only codes **0, 10 and 16** appear, confirming from
the generator itself why water and dirt tracks required hand-editing.

The meshes reference `side.tex`, `rumble.tex` and `wall.tex`, which the shipped `mkresfiles` does not
contain — but that is not a gap. **`reslist.txt` is a per-track artifact, not a fixed manifest**:
`rescrack.exe` writes one out when it unpacks an archive, `ResClean.exe` maintains it, and `mkres` packs
from whatever it lists. The copy in `mkresfiles` is the demo track's. An author brings their own textures
and their `reslist` names them.

**Five AI/racing-line outputs** — `track.ili`, `track-ai.ili`, `track-ai-reverse.ili`, `track-reverse.ili`
(15,864 bytes each, all four with *different* hashes, so four genuinely distinct lines) plus
`aispeed.txt`, 396 lines of `distance, speed` pairs. The `.ili` files are already `0SER`/`NILI` archives;
`mkilicc` compiles them to the `.ild`/`.ili` members that ship inside the `.tra`.

Worth noting: **`make-track.bat` uses only three of the four `.ili` files.** `track-reverse.ili` and
`aispeed.txt` are generated but never referenced by the batch — either vestigial, or intended for a
hand-driven step the shipped batch does not perform.

✅ **Every generated mesh parses with this toolkit.** `vrmod modinfo` reads all fourteen, with vertex
counts from 660 to 3,695 — comfortably inside the 30,000-vertex per-object ceiling. That is a two-way
check: it validates our `.mod` parser against a generator we did not write, and validates that the
generator's output is well-formed.

#### The shipped tracks are codenamed

The filenames inside `Data/` are not the names players see. Confirmed by matching `.bpp` payload hashes
against the community decompiles:

| Name in game | File in `Data/` | | Name in game | File in `Data/` |
|---|---|---|---|---|
| bemidji | `bemidji` | | ridge-valley | `hastings` |
| castle | `heaven` | | rock-island | `kenyon` |
| dayton | `limbo` | | silverdale | `uptown` |
| dundas | `dundas` | | **sunset-mesa** | **`nfield`** |

Worth knowing before comparing tracks by name, and it makes the odd flags legible: sunset-mesa — the desert
track — is the only one using codes 12 and 23.

**The tree verifies by traversal.** Walking `less`/`greater` from the header's root index gives **zero
revisits on every track**, reaching 98–99.7% of all nodes at a maximum depth of 16–21 where a balanced tree
over that many nodes would be ~15. The unreached remainder is consistent with nodes retained but not linked.

#### Read from the code, not inferred

Three routines in `race.bin` confirm the layout directly (v1.2.5 addresses):

| VA | What it settles |
|---|---|
| `0x468AB0` | the loader. `lea eax,[esi+0x14]` — **the header is 20 bytes**. `mov ecx,[esi]` / `shl ecx,3` / `sub ecx,edx` / `lea eax,[esi+ecx*8+0x14]` — the first section is `n_triangles × 7 × 8` = **56-byte records**. It then converts the header's root *index* into a pointer and stores it back over `+0x10`. |
| `0x468B80` `fixup_tree` | `mov ecx, 0x1c` / `idiv` — **28-byte nodes**. Rewrites `+0x14` and `+0x18` from indices into pointers (`-1` → null), recurses on the first and iterates on the second, and **touches nothing else** — which is what proves `+0x00`…`+0x10` are values rather than relocatable indices. |
| `0x468CB0` | the traversal test: `fld [edx+4] · point.z` + `fld [edx] · point.x` + `[edx+8]`, compared against a constant — i.e. **`a·x + b·z + c`**, a line in the XZ plane. |

The function names itself: its diagnostics are `"fixup_tree: bogus data?"` and
`"node %d: less is outside range (%d < 0 | …)"`, alongside the loader's `"bad bpp version"` and
`"bpp not found: %s"`.

❌ **The earlier hypotheses were all wrong and are withdrawn** — baked lightmap atlas, per-vertex paint
buffer, heightfield sample grid. The size that made them plausible is simply what a per-triangle plane plus
a full BSP costs: 56 bytes per collision triangle and 28 per node adds up faster than the render geometry it
shadows. The note that "two header int32s don't obviously factor into the file size" was the whole answer
sitting in plain sight — they factor exactly, at 56 and 28 bytes.

⚠️ **`.grf` and `.bpp` are independent, and that is a real modding trap.** Nothing links a collision
triangle to a render triangle. Delete an object from `.grf` and it vanishes visually while its collision
triangles stay in the `.bpp` — the car then hits something that is no longer drawn. This is a known
community experience (cacti removed from a track's mesh, invisible collision left behind) and it follows
directly from the structure: any tool that edits track geometry must edit both files or it produces
invisible walls.

`vrmod collisioncheck` detects it, since both files share one world coordinate frame (verified: their
bounding boxes coincide). It matches each triangle in one mesh against the other by centroid proximity via a
voxel hash, and reports two failure modes: **collision without nearby geometry** (invisible walls) and
**geometry without nearby collision** (drive-through props).

- **Single-track scan.** A clean track has a large, expected baseline of one-sided triangles — off-track
  terrain has collision but no render, cosmetic detail has render but no collision — so the raw counts are
  not the signal. What is flagged is a *cluster* shaped like a standing object: a compact horizontal
  footprint (`xz_radius ≤ 10 m`) with vertical extent (`≥ 2 m`) and at least 6 triangles. Those thresholds
  are calibrated so that all ~167 collision-only terrain clusters across the eight stock tracks are
  excluded — a hit on a real track is a genuine mismatch, not terrain. The limit: a deleted prop whose
  collision footprint is only a few triangles is geometrically indistinguishable from a terrain bump on a
  single track, so this finds larger orphaned objects reliably but can miss a tiny one.
- **Diff against the original** (`--against`) removes that limit. Because the two versions share identical
  terrain, the baseline cancels and only the edit remains, so it catches a change of any size. Validated by
  deleting one prop's render geometry from a stock track: the diff flagged the resulting invisible wall
  **0 m from where the prop had been**, and a track diffed against itself reports nothing.

⚠️ **This also reframes `.bsp`.** That file is a 108-byte near-static stub in every track (§4.10), so it is
**not** the track's spatial partition — `.bpp` is. `.bpp` and `.sol` (§4.8) together are the collision layer.

⚪ **Open:** whether `tri0`/`tri1` are two coplanar triangles, a triangle plus a sibling link, or the ends of
a range. `fixup_tree` leaves them alone, so they are consumed as indices at query time; settling it means
reading the collision query rather than the loader.

### 4.10 `BSPT` — `.bsp` — ✅ CONFIRMED (a near-static stub; **not** the spatial partition)

⚠️ **Despite the name, this is not where the track's spatial partition lives.** It is a fixed 128 bytes in
every stock track — 108 of payload under the 20-byte envelope — while `.bpp` (§4.9) carries a full BSP tree
of tens of thousands of nodes. Anyone hunting for the collision structure should start there.

Fixed **128 bytes** in *every* sample across all 8 tracks, and **byte-for-byte identical** in 7 of the 8 —
only `castle/track.bsp` differs, by a single nibble (one header field reads `2` where every other track
reads `3`). The tail of the file decodes as float32 values on the order of ±100,000, i.e. bounding-box-
sized numbers for these open outdoor tracks (meters, consistent with everything else). The overwhelming
likelihood is that this is a **single-node/degenerate BSP root** — essentially "here's the world bounding
box" with no actual subdivision ever written out — rather than a real spatial tree per track. If true, that
implies the real spatial partitioning/culling structure the engine uses at runtime lives inside `.grf`
and/or `.sol` instead, and `.bsp` may be a vestigial/unused format from an earlier engine design. Treat
`.bsp` as low-priority for modding purposes — there doesn't appear to be meaningful per-track data in it.

### 4.11 `rDIA` — `.adr` AI driver definitions — 🟡 WELL-SUPPORTED (identity only)

Found in `drivers.res` as a single file, `aidriver.adr` (69,664-byte payload) — the "core" resource that
every per-tier `.dnt`/`.ilg` pair (§4.12) presumably indexes into or supplements. Reversed tag reads
"AIDr" — a clean match for "AI Driver." Header envelope confirmed (`0SER`/`rDIA`/version=2/`!IGM`); payload
not decoded. Given it's the one singleton in an archive otherwise made of hundreds of near-duplicate
per-tier records, this is likely the master driver roster/behavior table the tiered files parameterize.

### 4.12 `TNDA` — `.dnt` per-tier driver tuning — 🟡 WELL-SUPPORTED (identity only)

The bulk of `drivers.res`: ~695 files named `<3-char tier code>vipr.dnt`, each paired with a same-tier
`.ilg` AI-line file (§4.2). Reversed tag "ADNT" doesn't read as a clean word, but the naming and pairing
strongly suggest per-AI-skill-tier driving/tuning parameters (aggression, braking points, cornering
behavior) matched to that tier's own recorded line. Sizes cluster tightly by tier (e.g. ~1,200–1,800 bytes)
rather than varying with track size, consistent with a small fixed-shape parameter block rather than
geometry. Header envelope confirmed (`0SER`/`TNDA`/version=7 — the highest version number seen anywhere in
the catalog/`!IGM`); payload not decoded.

### 4.13 `SGPU` — `.ugs` car upgrade data — 🟡 WELL-SUPPORTED (identity only)

Found in `viper.car` as `viper.ugs` (5,948-byte payload). Reversed tag reads "UPGS" — read together with
the extension and filename, a strong hint this is car **upgrade slot/stat** data (performance part
options), though it wasn't cross-referenced against anything to confirm the specific field layout. Header
envelope confirmed (`0SER`/`SGPU`/version=1/`!IGM`); payload not decoded.

### 4.14 `0XFS` → `SFX0` — `.sfx` sound effect — ✅ CONFIRMED (PCM path; ADPCM path partially understood)

Car engine loops, horn, shift, and shared crash/UI cues (`race.res`/`common.res`/`ui.res` also carry many
non-car `.sfx`, e.g. `crash1.sfx`, `click.sfx`). Reverse-engineered by round-tripping controlled synthetic
WAV files through a reference encoder for the format, and cross-checking the result against all 4 real
samples in `viper.car`.

**Format:** the standard `0SER` envelope wraps a 20-byte WAV-`fmt`-chunk-shaped sub-header —

| Offset | Field | Notes |
|---|---|---|
| `0x00` | `int32 data_size` | length of the real sample data, **not** including the trailing pad below |
| `0x04` | `int16 format_tag` | `1` = PCM, `2` = Microsoft ADPCM (same codes as Windows `WAVEFORMATEX.wFormatTag`) |
| `0x06` | `int16 channels` | `1` (mono) in every real sample seen |
| `0x08` | `int32 sample_rate` | `44100` for the RPM-sweep engine loops, `22050` for the idle sample |
| `0x0C` | `int32 byte_rate` | `sample_rate × block_align` for PCM |
| `0x10` | `int16 block_align` | `2` for 16-bit mono PCM |
| `0x14` | `int16 bits_per_sample` | `16` in every real PCM sample seen |

— followed by 2 bytes at a fixed offset, then `data_size` bytes of raw sample data (PCM: signed 16-bit
little-endian mono — already exactly what a standard WAV `data` chunk would hold), then a **fixed
4096-byte trailing pad regardless of content length**. Confirmed identical in *size* (not content) across
all 4 real `viper.car` samples and two synthetic test files of very different lengths (40 and 6,000 bytes
of real data). In at least one synthetic sample the pad was confirmed to be uninitialized memory rather than meaningful
content — unrelated ASCII text turned up inside it.

Those 2 bytes were originally reported as a fixed literal `"da"` marker based on the 4 `viper.car` samples
alone. A broader check against `race.res`'s 16 shared UI/gameplay `.sfx` files (the fallback `horn.sfx`/
`shift1.sfx`/etc. every car uses unless it ships its own — see below) disproved that: 12 of the 16 do have
`"da"` there, but the 4 impact-type sounds (`crash1.sfx`/`crash2.sfx`/`crash3.sfx`/`squeal.sfx`) all have
`\x00\x00` instead, with every other header field — and the actual audio — still perfectly valid. A
consistent split (4/4 impact sounds vs. 0/12 everything else, not scattered) rather than noise, but its
real meaning isn't understood; not decode-relevant either way, since nothing needs it to extract the
sample data. Downgraded here from ✅ CONFIRMED to unverified-but-harmless.

**Real samples, all PCM:** `viper0.sfx`/`viper1.sfx`/`viper2.sfx` at 44,100 Hz and `viperi.sfx` (idle) at
22,050 Hz, all mono/16-bit — plus, from `race.res`, the 16 shared UI/gameplay sounds referenced above
(`horn.sfx`, `shift1.sfx`, `squeal.sfx`, `crash1-3.sfx`, `road1-2.sfx`, `scrape.sfx`, `splash.sfx`,
`go.sfx`/`ready.sfx` countdown cues, `cboth`/`cclear`/`cleft`/`cright.sfx` spotter-voice cues), all also
22,050 Hz mono/16-bit PCM. A car's own sound set is named `<prefix>0/1/2/i.sfx`: `i.sfx`
is the idle loop; `0.sfx` is the AI/other-player engine sound covering idle→9000 RPM; `1.sfx` is the local
player's own engine sound over the same range; `2.sfx` is a high-RPM-only layer (4000→9000 RPM, also usable
for a turbo hiss). `horn.sfx`/`shift1.sfx`/`squeal.sfx` are confirmed per-car overridable in practice too —
several third-party cars ship their own, distinct from `race.res`'s shared default, resolved the same
own-archive-first way as the horn ball mesh. On the authoring side, samples must be 16-bit mono, resampled
to the target rate, and trimmed to a zero-crossing loop point to avoid pops.

**ADPCM (`format_tag=2`) is not fully solved.** No real sample in the retail data uses it
(all 4 are plain PCM), but a synthetic test confirmed real, substantial compression (~4:1, matching
`bits_per_sample`'s implied 16→4 bit reduction) and exposed two real quirks: the `data_size`
field is unreliable for ADPCM output (it reports the original *uncompressed* size, not the true compressed
byte count — the real compressed length has to be derived as `payload_size − 22 − 4096`), and
`block_align=2` doesn't fit real Microsoft ADPCM's block structure (which needs at least a 7-byte block
header before any compressed nibbles), meaning this is either a simplified/non-standard 4-bit codec that
merely reuses Microsoft's `format_tag` constant, or `block_align` doesn't carry its usual meaning here. The
actual compressed-sample bit layout is unsolved.

### 4.15 `XFSE` — `.ens` engine sound crossfade parameters — 🟡 WELL-SUPPORTED (structure solved, field semantics inferred)

Found in every car archive as `<prefix>e.ens` (228-byte payload — the smallest confirmed-identity format
in the catalog). Reversed tag reads "ESFX." Structure fully solved by cross-car comparison (no reference
tool's own field labels have surfaced for this format the way they did for `.cf`, so this was worked out
from the raw bytes alone): the payload is a **fixed-size buffer, always exactly 228 bytes regardless of
content** — `int32 recordCount` followed by a fixed 8-slot array of 7-`float32` records (28 bytes each;
`4 + 8×28 = 228`). Only the first `recordCount` slots hold real data; the rest is uninitialized memory left
over from whatever tool originally wrote the file — confirmed exactly the same way as `.sfx`'s trailing pad
above: the byte math is exact for both a `recordCount=3` sample (real data ending at byte 88) and a
`recordCount=2` sample (ending at byte 60), and the "padding" bytes genuinely differ between two different
cars' `.ens` files while the real leading records are stable.

`recordCount` matches, record-for-record in order, the number of non-idle `.sfx` files (§4.14) that car
actually has (`<prefix>0/1/2.sfx`) — confirmed directly against real data: every sampled car with all three
`0/1/2.sfx` files has `recordCount=3`; a car confirmed to be missing `<prefix>2.sfx` specifically has
`recordCount=2`. Every field WITHIN a 7-float record is inferred from context and cross-car comparison
only, not confirmed: `[0]` is identical between a car's `0.sfx` and `1.sfx` records (plausibly a
pitch-reference "base RPM"); `[1]`/`[2]` are two small 0–2-range scalars (plausibly volume/pitch-scale);
`[3]`/`[4]` are an ascending RPM pair that varies per record/car (plausibly that layer's own crossfade
range); `[5]` sits close to (not exactly at) that car's redline; `[6]` is `10000.0` in every record on
every car sampled, including cars whose other fields differ, and reads as an engine-wide constant rather
than real per-car data.

Header envelope confirmed (`0SER`/`XFSE`/version=1/`!IGM`).

---

## 5. Plain (non-`0SER`) formats

### 5.1 `.tga` — Truecolor Targa — ✅ CONFIRMED

Every `.tex` ships with a same-named `.tga` source/editable counterpart in the sample set. Standard
uncompressed truecolor Targa, 24- or 32-bit, no RLE — including correct handling of the origin-corner
descriptor bits (top/bottom and left/right flips per the TGA image-descriptor byte).

### 5.2 The game executable — ✅ CONFIRMED (video mode, VRAM check, viewport/FOV, rasteriser crash, display scaling)

`Viper Racing.exe` (388,608 bytes) is only a launcher. **The engine is `race.bin`** — a complete PE image
(`MZ`, ImageBase `0x400000`, sections `.text` / `.rdata` / `.data` / `.idata` / `.rsrc`) carrying the
renderer, the resource loader, the physics and every diagnostic string. Two builds exist in the wild:

| Build | Size | Notes |
|---|---|---|
| Retail 1.1 (1998) | 1,300,480 | Ships on the disc |
| Community v1.2.5 (2016) | 1,314,816 | Raises polygon/vertex limits, fixes audio, breaks the built-in Benchmark |

v1.2.5 is a **rebuild, not a patch**: only 5.3% of bytes match at the same offset, `.text` grows 192 bytes,
`.data` 5,632, and `.idata` is merged. It cannot be reproduced as an edit to the retail build.

**Every address below is a retail 1.1 virtual address.** The two builds lay the same code out differently —
the resolution label table alone moves from file offset `0xde9a4` to `0xe2520` — so anything built on this
section must locate its sites by **byte pattern, never by offset**.

**Applying all of this is one command.** The patches below interact and their order matters — the symbol map
is generated by scanning `.text`, so it has to be built after every byte of code has settled — so
`vrmod/patchset.py` fixes the order once and always rebuilds from a pristine snapshot rather than layering:

```
vrmod patch <Data> --mode 1920x1080     # startup, rasteriser, FOV, resolution, symbols
vrmod patch <Data> --status             # what is installed, including the DPI setting
vrmod patch <Data> --revert             # back to the snapshot taken on the first run
```

Re-running with the same arguments produces byte-identical output, which is the property that matters: it
makes a patched binary reproducible instead of an artefact of the order someone happened to apply things in.
The DPI setting of §5.2.0 is `--dpi-aware`, kept opt-in because it is a Windows per-application setting
rather than a change to any game file.

#### 5.2.0 ⚠️ The display-scaling trap — read this before measuring anything from a screenshot ✅ CONFIRMED

On a high-DPI display **the game does not get the surface it asks for**, and every screenshot-based
measurement in this section is affected by it.

`race.bin` is DPI-unaware, as any 1998 binary is, so Windows reports the *virtualised* desktop size to it. On
a 3840 × 2160 panel at 250% scaling that is **1536 × 864**. The resolution patch (§5.2.2) can still tell the
game to use 1920 × 1080 and the game will comply in every respect it can observe: it sets
`vp2 0 0 1920 1080`, centres its projection on x = 960, places the tachometer at y ≈ 1000. But the surface it
actually draws into is 1536 × 864. Everything it draws right of x = 1536 or below y = 864 never appears.

The symptoms read convincingly as engine bugs:

| Symptom | Actual cause |
|---|---|
| The 3D view sits well right of centre | The projection centre, x = 960, lands at 960/1536 = **62.5%** of the visible width |
| The tachometer is missing entirely | It is drawn at y ≈ 1000, past the bottom of an 864-row surface |
| The whole picture looks magnified | The 1536 × 864 surface is upscaled to the capture size |

**How to detect it.** Compare a viewport rectangle the game *logged* against where it actually lands in a
screenshot. The rear-view mirror is ideal because the game logs its rect and it is small enough to measure
precisely. With `vp2 768 64 384 72` and a 1920-wide capture, the mirror measured at x 959–1442, y 79–171 —
**exactly 1.25× on all four edges**, and 1920 / 1.25 = 1536, the virtualised desktop width. Two independent
measurements agreed: the axis of symmetry between the front wheels sat at 0.6253 of frame width, against
960/1536 = 0.6250 predicted.

**The fix is a Windows setting, not a patch.** On the launcher: Properties → Compatibility → *Change high DPI
settings* → tick **Override high DPI scaling behavior**, *Scaling performed by:* **Application**
(equivalently, the `~ HIGHDPIAWARE` layer under `HKCU\…\AppCompatFlags\Layers`). The process then sees the
real desktop and can get the surface it asked for. ✅ **Verified on hardware:** with the override set, the
same build renders centred at 1920 × 1080 with a full HUD — measured axis **959.5 against a centre of
960.0** — where before it was cropped to the top-left 1536 × 864 of its own output.

> **Rule for anyone continuing this work: before treating a high-resolution rendering symptom as a game bug,
> check whether the requested mode exceeds the virtualised desktop size.** To recover the game's own
> coordinates from a screenshot taken without the override, divide by `capture_width / 1536`.

#### 5.2.1 The video-memory check — why the 1998 build won't start on a modern GPU ✅ CONFIRMED

At `0x44EF66`, before comparing the card's memory against its own tiers:

```
add  dword [esp+4], 0x96000      ; 81 44 24 04 00 60 09 00
cmp  dword [esp+4], 0x1E8480     ; 2,000,000
jae  ok
xor  eax, eax                    ; -> failure
```

`0x96000` is 614,400 = 640 × 480 × 2 — exactly one 16-bit framebuffer, the game allowing for its own front
buffer on top of what DirectDraw reported. Harmless in 1998. On a card reporting close to 4 GB the addition
wraps past 2³², the 2 MB comparison fails, and the game exits claiming a video-card error.

**The fix is to replace those eight bytes with NOPs.** The comparisons are unsigned (`jae`), so a large
figure passes easily, and the framebuffer allowance is meaningless on a card with gigabytes. This is
precisely what v1.2.5 does — those eight bytes are the only difference at this site. ✅ **Verified on
hardware:** a stock 1998 `race.bin` patched this way starts and races on a 4 GB card.

The same function classifies video memory into tiers **2 / 4 / 8 / 16 MB** at `0x50AF70`, using thresholds
2,000,000 / 4,000,000 / 8,000,000 / 16,000,000, and the tier then *disables* resolutions on small cards.
**16 is the maximum tier** and cannot simply be raised: a five-entry jump table is indexed by `tier − 2`
behind a range check `cmp ecx, 0xE`, and anything outside prints a message and calls exit. The startup log
line `vid: %d meg card (reported:%f)` reports both the tier and the true figure, e.g.
`vid: 16 meg card (reported:4095.937500)`.

#### 5.2.2 Screen resolution — the menu index carries the dimensions, not the label ✅ CONFIRMED

The game offers four modes, identified internally by a **menu index 1–4**:

| Index | Stock mode | Label slot | Availability flag |
|---|---|---|---|
| 1 | 512 × 384 | 3 | `0x50AF95` |
| 2 | 640 × 480 | 2 | `0x50AF96` |
| 3 | 800 × 600 | 1 | `0x50AF97` |
| 4 | 1024 × 768 | 0 | `0x50AF98` |

The labels are 12-byte NUL-padded ASCII strings (`"1024 x 768"`) in **descending** order, so
`slot = 4 − index`. A fifth whitelist entry, 320 × 200 (`0x50AF99`), has no menu index.

**The label is display-only.** The dimensions are compiled in as immediate operands at four separate sites,
and a resolution is only genuinely changed when all four agree:

| Site | VA | Form |
|---|---|---|
| DirectDraw enumeration whitelist | `0x44F140` | `cmp ecx, W` / `cmp dword [eax+8], H` → `mov byte [0x50AF94+index], 1` |
| Dimension getter (jump table on index) | `0x44E960` | `mov eax, W` / `mov ecx, H`, then the mode-set call with `esi = 0x10` (16 bpp) |
| Globals chain A | `0x447D74` | `mov dword [0x50AD8C], W` / `mov dword [0x50AD6C], H` |
| Globals chain B | `0x447E97` | The same pair again |

There are two globals chains because the game keeps **two independent video modes** — one for the frontend
and one for racing. They are stored in `Config/options.cfg` as `video mode` and `video_mode` respectively,
and the race mode is announced in the log as `setting driving video mode = N`.

⚠️ **The two keys use different numbering, which is an easy trap.** The frontend key holds a **label-table
slot** (0–3); the race key holds a **menu index** (1–4). They are related by the same `slot = 4 − index` as
the label table itself, so a config reading

```
video mode  1      -> slot 1  =  the second entry
video_mode  4      -> index 4 =  slot 0  =  the FIRST entry
```

has the menus at one resolution and the race at another. Two ways to get this wrong: reading the underscore
key as a slot points at the wrong mode entirely, and a regex like `video[ _]mode` matches whichever line
comes first — which is the frontend one, so a tool asking "what will I race at" silently answers with the
menu resolution. `vrmod`'s `doctor` reports both, converted.

The enumeration callback compares **only width and height — never the pixel format** — and silently
discards any mode not matching one of its five hardcoded pairs, however willing the driver was to provide
it. That, not the driver, is what confines the stock game to its four resolutions. Availability is read
back by `0x44E720`, which is just `mov al, byte [ecx + 0x50AF94]` (plus a VRAM-tier check for index 2). The
Options menu lists every index whose flag is set; on modern drivers 512 × 384 is not enumerated, so three
entries appear.

⚠️ **Index 2 is the startup gate.** `cmp byte [0x50AF96], 0` is what prints
`video card cannot do 640x480x16!` and exits, so repointing index 2 at a mode the driver does not offer
stops the game booting entirely. **Repoint index 4 instead** — an unavailable mode there merely drops out
of the menu and the game still runs.

**Results, verified on hardware** (patched onto index 4). Modes marked ⚠️ were measured *before* §5.2.0 was
understood, on a machine whose real surface was 1536 × 864 — "renders" is trustworthy for those, but their
HUD observations were measuring the cropped surface and have since been overturned:

| Mode | Pixels | Result |
|---|---|---|
| 1280 × 720 | 0.92 M | ✅ renders natively |
| 1280 × 1024 | 1.31 M | ✅ |
| 1600 × 900 | 1.44 M | ✅ |
| 1680 × 1050 | 1.76 M | ✅ ⚠️ recorded as "the practical maximum" — it is not |
| 1600 × 1200 | 1.92 M | ✅ ⚠️ recorded as "HUD near its limit" — there is no such limit |
| 1920 × 1080 | 2.07 M | ✅ **after the needle fix** (§5.2.4); crashed on every attempt before it |
| 1920 × 1200 | 2.30 M | ✅ **full HUD, dial at stock placement** — re-measured with the DPI override |
| **2048 × 1536** | **3.15 M** | ✅ **full HUD including the needle — the practical maximum, 4.9× stock** |
| 2560 × 1440 | 3.69 M | ❌ `create device` → `DDERR_INVALIDOBJECT` |

**The ceiling is a surface width of 2048**, not a pixel count. 2560 × 1440 fails while 2048 × 1536 succeeds
at *more* pixels, which rules out any total-size cap in that range and fits the classic legacy Direct3D
surface-dimension bound. The failure is Direct3D device creation, and the display mode itself is fine — the
log shows `try triple buffer` / `vid: triple buffer on` succeeding first.

⚠️ **The dialog that appears is misleading.** `This game requires DirectX 5 or 6` lives in
`Viper Racing.exe` (`0x48c7`), not in `race.bin`: it is the launcher's generic catch-all for *any* engine
startup failure and says nothing about DirectX versions. The real cause is always in `C:\log.log`.

So the game will render at roughly **4.9× its stock maximum pixel count**.

**A mode the driver does not enumerate simply vanishes from the menu**, with no error — the whitelist flag is
never set, the log has no `setting driving video mode` line, and the game exits cleanly. 2048 × 1152 behaved
exactly this way. Before probing a limit, check the mode is actually offered:

```powershell
Get-CimInstance CIM_VideoControllerResolution |
  Select-Object HorizontalResolution, VerticalResolution -Unique
```

**1920 × 1080 used to be the exception, and its story is worth keeping** because it misleads so effectively.
Every property of that mode tests fine in isolation — width 1920 (1920 × 1200 works), height 1080 (1200
works), 2.07 M pixels (2.30 M works), 16:9 (1280 × 720 and 1600 × 900 work), enumeration and refresh-rate
profile (identical to modes that work), colour depth (Windows reports 32 bpp for *every* mode, working ones
included), and the 16 MB surface budget (forcing double buffering changed nothing). Six hypotheses were
formed from those facts and all six were false. The mode was never the problem: it merely positions the
tachometer needle across row 1024, where a rasteriser bug smashes the stack (§5.2.4). With that fixed,
1920 × 1080 races normally.

The remaining limit is cosmetic: the HUD's **stamps** stop being drawn past roughly 1.77 M pixels — see
§5.2.3.

#### 5.2.2b Draw distance — the stored value is a fraction, not a distance ✅ CONFIRMED

`draw_distance` in `Config/options.cfg` ships as `0.500000`, which reads like half of something rather
than a distance, and it is. The string appears once in `race.bin`; the code that reads it stores to
`0x540344`, and the transform applied immediately afterwards is:

```
fld   dword [0x540344]        ; the value as written in options.cfg
fmul  dword [1700.0]
fadd  dword [300.0]
fstp  dword [0x540344]        ; what the renderer uses
```

so

```
effective = value * 1700 + 300
```

| `draw_distance` | Effective | What it is |
|---|---|---|
| `0.500000` | 1,150 | The shipped default (`options.def`) |
| `1.000000` | 2,000 | The in-game slider pushed all the way right |
| `100.000000` | 170,300 | What the View Extender writes — 85× the slider |

**Nothing clamps it.** This is the whole reason the extender works, and it is visible by comparison:
`detail_level` is read through the same path a few instructions later and *is* floored —

```
cmp   [detail_level], 0x3f000000     ; 0.5f
jge   ...                            ; else force it to 0.5
```

— while `draw_distance` gets no such treatment. Any positive value is accepted and scaled, so the
useful range extends far past what the menu can express. The floor is not 0 but **300 units**: the
`fadd` happens after the multiply, so nothing below that is reachable however small the value.

⚠️ **The game rewrites `options.cfg` on exit.** Change this with the game closed, and expect touching the
graphics tab in-game to put the slider's value back. The View Extender's instructions say the same
thing in capitals.

⚠️ **The old tool edited line 92 by number, and the key is not on line 92.** The 2016 batch file
(and the `.exe` beside it) does a literal `if %%a equ 92` line-number substitution. On every install
in this project's sample set the key is on line **91** or **83**. Run against a real v1.2.5 config it
overwrites `effects yes` and leaves this:

```
line 91: draw_distance 0.500000        <- the real setting, untouched
line 92: draw_distance 100.000000      <- written over "effects yes"
```

— a duplicated key, the first occurrence still at the default, and one graphics setting silently
gone. `vrmod drawdistance` finds the key by name and rewrites only that line's number, preserving the
file's CRLF endings and every other byte.

#### 5.2.2a Widescreen field of view — ✅ CONFIRMED (Vert−, and fixable)

**All of the game's aspect handling lives in one place**: the `D3DVIEWPORT2` it hands to
`IDirect3DViewport2::SetViewport2` (vtable slot `0x44`). The builder — `0x459640` on v1.2.5 — is short
enough to read whole:

```
fild  dword [esp+0x18]         ; dwHeight
mov   dword [esp+8],    0x2c   ; dwSize = 44  ->  D3DVIEWPORT2, not D3DVIEWPORT
mov   dword [esp+0x1c], -1.0   ; dvClipX
fidiv dword [esp+0x14]         ; / dwWidth    ->  r = height / width
mov   dword [esp+0x24],  2.0   ; dvClipWidth
mov   dword [esp+0x2c],  0.0   ; dvMinZ
mov   dword [esp+0x30],  1.0   ; dvMaxZ
fst   dword [esp+0x20]         ; dvClipY      = r
fmul  dword [2.0]
...                            ; two pushes shift esp by 8 before the last store
fstp  dword [esp+0x30]         ; dvClipHeight = 2r
call  dword [eax+0x44]         ; SetViewport2
```

giving a clip window of

```
dvClipX = -1.0   dvClipWidth  = 2.0        <- both hard-coded immediates
dvClipY =  r     dvClipHeight = 2r         <- r = dwHeight / dwWidth
```

⚠️ **Correction to an earlier reading in this section.** The ratio is **not** an overall FOV scalar.
`dvClipWidth / dvClipHeight` = `1/r` = `dwWidth / dwHeight`, so the clip window's aspect always equals the
pixel viewport's aspect and pixels stay square at any resolution. The **horizontal** field is pinned by the
constant `dvClipWidth = 2.0` and never changes; it is the **vertical** field that shrinks as the screen
widens. Stock widescreen is textbook **Vert−**: 1920 × 1080 shows exactly as much left-to-right as
640 × 480 did, and less top-to-bottom. The exaggeration test that suggested an overall scalar — substituting
2.0 and watching the camera pull back — is consistent with both readings and never distinguished them.

**The projection matrix is not involved.** Logging every `SetTransform` (`IDirect3DDevice2`, slot `0x68`)
through a race shows it is a per-camera *constant* with `_11 == _22` and `_31 == 0`: `1.274141` racing,
`1.400415` in menus, `±2.300737` for the mirror passes, unchanged by resolution.

**The ratio comes from the viewport, not the screen**, and the two differ: the HUD banner takes the top 64
rows, so the logged viewports are `0 64 640 416` and `0 64 1920 1016`, giving r = **0.65** and **0.529**.

The predictor is the aspect ratio, never the resolution: 1600 × 1200 is 2.9× the stock pixel count and
frames the car as 640 × 480 does, while 1280 × 720 has *fewer* pixels than 1280 × 1024 and crops it.

**Fix — true Hor+.** Keep the original vertical field and widen the clip window to match the screen:

```
R = max(R0, r)                               <- R0 = 0.65, the original
dvClipY = R     dvClipHeight = 2R
dvClipX = -R/r  dvClipWidth  = 2R/r
```

`dvClipWidth / dvClipHeight` is still exactly `1/r`, so pixels stay square — the patch only ever changes the
clip window's **size**, never its shape or its centre.

The `max` is what makes it safe, and clamping rather than pinning is the whole trick. This builder serves
*every* viewport the game sets, not just the race camera, and the rear-view mirror is a narrow one —
167 × 129, r = 0.77. Pinning R to 0.65 would zoom the mirrors in by 19% at **every** resolution, 640 × 480
included. With the clamp, any viewport at least as tall as the design aspect keeps R = r and comes out
byte-identical to stock:

| Viewport | r | Result |
|---|---|---|
| 640 × 416 main | 0.65 | every field stock — a **provable no-op** at the original resolution |
| 167 × 129 mirror | 0.77 | untouched, at every resolution |
| 1600 × 1200 main | 0.71 | untouched |
| 1920 × 1016 main | 0.53 | clip widened to 2.457 — **23% more world sideways** |

66 bytes, file size unchanged, implemented pattern-located in `vrmod/aspectfix.py`; both constants are found
**by value** in `.rdata`, or written into `.rdata`'s mapped slack when absent (v1.2.5 places 0.65 at
`0x4CE664`). The region is byte-identical between the retail and community builds apart from three operands.
The HUD is unaffected — it is drawn in screen space from a 640 × 480-era layout and still does not scale
(§5.2.3).

⚠️ **An earlier version of this patch was wrong in an instructive way.** It replaced the computed `r` with
the constant 0.65 and left `dvClipX` / `dvClipWidth` at their hard-coded −1.0 / 2.0. That fixes
`dvClipHeight` at 1.3 while the pixel viewport is 1.89∶1, so the clip window no longer matches the surface
and the image is **stretched horizontally by 23% instead of showing more world**. Everything grows wider and
anything away from the middle is pushed further out — which reads as the view drifting off-centre, but is a
stretch about a centre that never moved.

✅ **The "unexplained horizontal shift" recorded in earlier revisions of this section was not a game bug at
all — it was display scaling (§5.2.0).** The render pipeline is centred at every stage, verified four
independent ways:

| Stage | Measured | Centred? |
|---|---|---|
| View matrix | `_31 ≈ -0.000009` (floating-point noise off the car's heading) | yes |
| Projection matrix | `_31 = 0.000000`, `_11 == _22` | yes |
| Viewport rect | `dwX = 0`, `dwWidth = 1920` | yes |
| Clip volume | `dvClipX = -dvClipWidth/2` by construction | yes |

The viewport-centre globals `0x50D488` / `0x50D48C` and the half-dimension pair `0x50D498` / `0x50D49C` have
**exactly one reference each** in `.text` — the write inside `set_viewport` (`0x44DD90`) — so they are dead
and can be ruled out. And the scene really is transformed by Direct3D: the draw calls pass vertex type `2`
= `D3DVT_LVERTEX`, untransformed and pre-lit. A separate `D3DVT_TLVERTEX` path at `0x4537F5`, where the game
supplies screen-space coordinates itself and bypasses all of the above, is worth remembering for HUD work.

> **Method note worth keeping.** Three successive claims about this "shift" were made from eyeballed
> screenshot positions, and all three were wrong. The estimates were mutually contradictory — near-field
> objects appeared to grow as a fraction of the frame while far-field ones shrank, which is impossible for a
> single camera, and that contradiction was the signal that the measurements were noise. What settled it was
> measuring a landmark whose true coordinates the game itself had logged.

#### 5.2.3 The in-race HUD — 640 × 480 stamp art, clipped against the render target ✅ CONFIRMED (mechanism); the "pixel budget" is ❌ RETRACTED

> ⚠️ **Read §5.2.0 first.** This subsection previously described a HUD "pixel budget" of ~1.77 M pixels. It
> does not exist. Every measurement behind it was taken before the display-scaling trap was understood, on a
> machine whose real surface was 1536 × 864 while the game believed it was drawing at 1920 × 1200. With the
> DPI override in place the dial renders at stock placement at 1920 × 1200 **and** at 2048 × 1536 — 3.15 M
> pixels, nearly double the supposed cap. The mechanism below is read from code and stands; the numbers
> that were fitted to it are retracted in full further down.

The in-race HUD is built from **stamps** (§4.6) in `race.res`, drawn at **native pixel size and never
scaled** — which is why the tachometer measures ~128 px at every resolution:

| Stamp | Size | Role |
|---|---|---|
| `rpm.stp` | 128 × 128 | Tachometer |
| `mph.stp` | 128 × 128 | Speedometer |
| `status.stp` | **640 × 64** | Top banner — authored full-width for a 640 × 480 screen |
| `start.stp` | 200 × 78, 6 frames | Starting lights |

They are loaded at `0x403454`ff into globals — rpm `0x4EC798`, mph `0x4EC69C`, status `0x4EC804`, start
`0x4EC6C8` — and drawn through `0x44C350`, whose signature is `draw(stamp, x, y, frame, flags)` (cdecl).

**Placement is resolution-relative and correct.** The tacho is `x = 16, y = height − 144`, bottom-left
anchored; the gear digits sit at `height − 0x49` and `height − 0x50`. The whole HUD block is skipped when
the screen is narrower than 640 (`cmp dword [0x50AD8C], 0x280` / `jl`).

**But every stamp is clipped against a render-target rectangle rather than against the screen.** `0x448B70`
resets that rectangle from the surface's own dimensions:

```
[ecx+0x14] = 0            ; left
[ecx+0x18] = 0            ; top
[ecx+0x1C] = [ecx+8]      ; right  = surface width
[ecx+0x20] = [ecx+0xC]    ; bottom = surface height
```

and `0x44C350` clips with `visible_rows = min(bottom − y, stamp_height)`, clamped to zero — so an element
positioned past `bottom` disappears silently, with no error and no log line.

❌ **RETRACTED: there is no pixel budget.** Everything this subsection previously concluded past this point
was measuring the cropped surface of §5.2.0 rather than the game. Re-measured on hardware with the DPI
override in place, dial at **stock** placement (`y = height − 144`), nothing patched:

| Mode | Pixels | Dial | Old model's prediction |
|---|---|---|---|
| 1920 × 1200 | 2.30 M | ✅ renders | usable height `budget/1920` = 960 → **nothing** |
| 2048 × 1536 | 3.15 M | ✅ renders | usable height `budget/2048` = 864 → **nothing** |

Both render. The old model is falsified twice over, at the exact mode it was fitted to. There is no budget,
no clip-rect ceiling, and nothing to raise — the stamps were falling off a 1536 × 864 surface the whole time,
and a dial anchored near the bottom of a 1200- or 1536-row screen lands well past row 864.

The retracted material claimed a cap of roughly **1.77 – 1.84 M pixels** (≈3.5 MB at 16 bpp), derived by
relocating the tachometer through six placements at 1920 × 1200 and 1680 × 1050 and bisecting the clip
bottom to `(940, 960]`. It was internally consistent, reproduced across two tracks of very different
geometry, and retrodicted every observation then available. It was still wrong: every one of those runs
was cropped identically, so the "cap" was just the surface edge dressed up as a ratio.

⚪ **The failed constant hunt is worth keeping, because its failure was the clue.** `0x384000` and its pixel
form `0x1C2000` occur **zero times** in the file; every `0x380000` / `0x1C0000` hit is an unaligned
coincidence inside a VGA palette ramp or float data. Also searched with no result: the value in dwords
(`0xE0000`), in KB (`0xE00` / `0xE10`), in 64 KB blocks, and as an immediate in any push/mov/cmp/add form.
The search was exhaustive and it found nothing **because there was nothing to find**. A thorough negative
result against a well-specified target is evidence the target is wrong, not evidence the constant is
computed at runtime — which is the interpretation that was reached at the time, and it sent the
investigation on to hunting for whatever "re-sets the clip rect" instead of questioning the measurement.

✅ **What survives is the mechanism**, because it was read from code rather than inferred from screenshots:
stamps are clipped against a render-target rectangle, that rectangle is initialised from the surface's own
dimensions, and an element positioned past `bottom` disappears silently with no error and no log line. That
is exactly what a too-small surface will do to you, and it is why the symptom was so convincing.

✅ **There is now no HUD limit at all.** The last one was the rasteriser's 1024-entry edge table (§5.2.4) —
ours, not the game's — which bounded out the tachometer *needle* above roughly 1104 screen rows. Doubling
the tables lifted it, and 2048 × 1536 renders dial, needle and banner together. The only ceiling left on the
whole resolution patch is the driver's 2048-wide surface cap.

Two further facts constrain where it comes from: the surface allocator (§ above) stores the height
**unclamped**, so the cap is applied upstream of it; and the back buffer is wrapped at `0x44E60F` using
`[0x50AF80]` / `[0x50AFA4]` — the same globals the resolution patch writes — so the back buffer really is
full size and the HUD must be drawing to some other surface, not yet identified. **Raising the HUD ceiling
is consequently not a one-value edit**; it needs the render target identified in a live process, with a
debugger or by instrumenting `race.bin` to log its clip rect. The static constant search is exhaustive and
negative — it should not be repeated.

#### 5.2.4 The rasteriser crash, and other limits found in `race.bin`

- **Textures are limited to 256 px, and the limit is a fixed buffer layout, not just a size check** (this
  cap is present in **both** retail 1.1 and v1.2.5 — the community rebuild did not lift it). `get_mip_level`
  at `0x45BBD4` dispatches on size with `sub ecx, 0x10; cmp ecx, 0xF0; ja panic` (valid 16…256), then
  `mov dl, [ecx+0x45BCD0]` (a 241-byte size→case index table) and `jmp [edx*4+0x45BCB8]` (a 6-entry jump
  table). A second identical dispatcher sits at `0x45BFE4`. A 512 texture aborts with
  `get_mip_level: can't handle this size dest: %d`.

  But the handlers reveal the real constraint. Each is a three-line **accessor**, not an allocator — the 256
  case is `add esi, 0xAAEC; mov [eax], 0x100; ret`. The five offsets are compile-time constants forming a
  **smallest-first mip pyramid** inside a fixed per-texture buffer:

  | level | offset | delta = size²×2 |
  |---|---|---|
  | 16 | `0x000EC` | — |
  | 32 | `0x002EC` | 512 |
  | 64 | `0x00AEC` | 2,048 |
  | 128 | `0x02AEC` | 8,192 |
  | 256 | `0x0AAEC` | 32,768 |

  The 256 level ends at `0x2AAEC` = **174,828 bytes**, which is the size of the fixed texture-buffer slot
  every texture occupies regardless of its actual dimensions (the offsets are literals, not computed).

  **Scoping 512 (measured, superseding an earlier "~280 byte" estimate that counted only the dispatch):**
  because the pyramid is smallest-first, a 512 level slots in *after* the 256 level at `0x2AAEC` and the
  existing offsets do not move — so the ~10 sites that bake in `0xAAEC`/`0x2AEC`/`0xAEC` keep working. The
  engine-side patch is ~8 pattern-located sites: widen both `cmp ecx,0xF0` → `0x1F0`; relocate+extend both
  241→497-byte index tables into `.text` slack; add a 512 handler (`add esi,0x2AAEC; mov [eax],0x200`) and
  jump entry at both; and grow the buffer allocation `0x2AAEC` → `0xAAAEC` at its 2 sites. **Two real
  catches, though:** (1) the slot is fixed-size, so every texture's footprint quadruples 175 KB → 699 KB,
  which is wasteful and wants VRAM-tier testing on hardware; and (2) this is only the engine accessor — a
  real 512 texture also needs the `.tex` on-disk format and loader to carry the larger pyramid, and
  `vrmod/tex.py` to stop downscaling to 256 (it currently fits imports to the cap). ⚪ Feasible but a
  multi-day mini-project with on-hardware validation, not a quick win; not attempted.
- ✅ **The per-object vertex limit is a fixed heap buffer — found, measured, and raised in-game.** The
  community figure of "20,000 vertices" for v1.2.5 is wrong; the real ceiling is **30,000**. At startup the
  engine allocates one vertex scratch buffer:

  ```
  0045031a  push 0xEA600            ; 960,000 bytes
  00450325  call 0x413fc0           ; malloc
  0045032d  mov  [0x4dc72c], eax    ; keep the pointer in a global
  ```

  Four call sites in the mesh loader (near the FNIM loader at `0x450120`) pass that global as the destination
  to the per-object transform loop `sub_00456e00` (real entry `0x456e20`; `0x456e00` is a separate stub). The
  loop reads a material's `int16` `vertex_start`/`vertex_end` (from `[rec+0x18]`/`[rec+0x1a]`, exactly the
  §4.1 fields) and copies each vertex into the buffer at `index × 32` bytes — 32 being the `.mod` vertex
  stride. So the buffer holds 960,000 ÷ 32 = **30,000 vertices**, and vertex 30,000 writes at byte 960,000,
  one record past the end. The fault is the record-copy store:

  ```
  004576b5  mov eax,[edi+0x18] / mov [ebx+0x18],eax
  004576bb  mov ecx,[edi+0x1c]
  004576be  mov [ebx+0x1c],ecx      ; <-- EXCEPTION_ACCESS_VIOLATION when ebx runs off the buffer
  004576c1  fld [edi+0xc] / fmul [0x510a24] ...   ; then transforms the copied vertex
  ```

  This is why the earlier "no `20000` constant, no static-buffer growth" observation was right yet misleading:
  the sizing constant is the *malloc byte size* `0xEA600`, not the vertex count, and the buffer is on the heap.
  It is allocated **once and reused per object**, so the cap is per single mesh and enlarging it costs a flat
  +88 KB regardless of car count. **Confirmed on hardware:** a 32,000-vertex test mesh crashed at `0x4576be`;
  after `0xEA600` → `0x100000` (1,048,576 B) the *identical* mesh rendered, lifting the ceiling to **32,768
  vertices — the int16 face-index cap of §4.1**, the true maximum since faces cannot address more.
  This ships as the opt-in **`vrmod patch --max-verts N`** (default off): it finds the sole `push imm32`
  whose immediate is a multiple of 32 in a plausible vertex range and is immediately followed by
  `call`/`mov [glob],eax` (the malloc-and-store), so it locates the site on both builds without hard-coded
  offsets. **Retail 1.1's buffer is 32,000 B = exactly 1,000 vertices** (site `0x44f57a`), also below its
  quoted 1,200. ⚠️ **A test mesh must reference a texture that exists in the
  target car** — a *missing* texture makes this engine deref NULL and crash (`ResourceGet(...) returning NULL!`
  then an access violation), which is not "renders white" and briefly masqueraded as the vertex crash here.
  One downstream consideration if this raise is exposed as an option (and why it may still be **opt-in**):
  more high-vertex cars — e.g. AI cars chosen via `AIcarman` — cost rendering *throughput* on this 1998
  pipeline, worst in the near-camera pack, mitigated by the LOD chain (`Viper0.mod`…`Viper7.mod`). But
  crucially, that cost is **graceful slowdown, not a crash** — traced and confirmed: rendering is
  **per-object immediate mode with no scene-wide geometry buffer.** The object render loop at `0x450db0`
  does, per object, `mov eax,[0x4dc72c]` (this same vertex buffer) → `call 0x456e00` (transform into it) →
  `call 0x453650` (draw) → next object, reusing the buffer. `0x453650` ends in `call [eax+0x78]` on the D3D
  device — `IDirect3DDevice2::DrawIndexedPrimitive` (slot `0x78`; `push 4` = `D3DPT_TRIANGLELIST`, `push 2` =
  `D3DVT_LVERTEX`). So every object is transformed-then-drawn before the next overwrites the buffer; nothing
  accumulates all visible geometry, so a full grid of heavy cars cannot overflow a shared buffer — it just
  runs slower. The only hard geometry cap is this per-object buffer (per single mesh). The "95,000-polygon
  track" figure is a *separate* track-load-time cap on the track's own geometry (loaded once, not a per-frame
  car budget), and is not even a literal constant (no `95000` appears in either binary — it is computed or
  approximate).
- **The built-in Benchmark is broken on v1.2.5** (the only community build tested — earlier ones are
  untested, so treat the affected range as unknown). It plays `Data/bench.rpl`, which is the 1998
  replay shipped on the disc; the replay index format changed, so it reports
  `Bad replay version (idx calculation method changed)`, and the failure path then unloads resources that
  are still referenced (`"Viper0.mod" still used by 8`) and dies with `EXCEPTION_ACCESS_VIOLATION`. This
  removes the obvious way to measure fill rate.
- ✅ **The tall-resolution crash: a stack overflow in the triangle rasteriser — solved and fixed.** The
  filled-triangle routine (`0x44A280`) carves two edge tables from a `0x2000` __chkstk stack frame, at
  `[esp+0x10]` and `[esp+0x1010]`. At four bytes per scanline each holds exactly **1024 entries**.
  **Two separate places index them by scanline, and both bound the index against the render surface's height
  instead of against the table.**

  The **edge walker** (`0x44A420`) records one x per scanline:

  ```
  test ebx, ebx / jl skip           ; y >= 0
  mov  eax, [render_target]
  cmp  dword [eax+0xC], ebx         ; y < SURFACE HEIGHT
  jle  skip
  mov  dword [edi + ebx*4], eax     ; indexes a 1024-entry table
  ```

  The **fill loop** (`0x44A3C7`) reads one x from *each* table per scanline:

  ```
  test edi, edi / jl next           ; y*4 >= 0
  mov  eax, [render_target]
  cmp  dword [eax+0xC], esi         ; y < SURFACE HEIGHT
  jle  next
  mov  ecx, [esp + edi + 0x10]      ; table A[y]
  mov  eax, [esp + edi + 0x1010]    ; table B[y]
  ```

  No shipped mode exceeded 768 rows, so neither ever mattered. Past row 1024 they diverge from the tables in
  different ways, and they need different fixes.

  **Overflowing the WRITE crashes.** It runs off the stack frame: overflowing the lower table spills
  harmlessly into the upper one, while overflowing the upper one destroys saved registers and return
  addresses — after which execution jumps through the wreckage. **That is why the reported EIP is a small
  value like `0x4E` that changes between runs: it is garbage, not an address in the program.** The game's own
  trace confirms it — `trace: Can't find 0x4e in mapfile`.

  **Overflowing the READ is harmless to memory but not to the picture.** At y ≥ 1024 table A's index reaches
  past its own 4096 bytes into table B, so the span is built from two unrelated x values and the row is
  filled edge to edge. The symptom is **long horizontal streaks in the triangle's colour across the whole
  screen** — red, because the triangle in question is the tachometer needle, and they clear as soon as you
  drive because the needle swings up out of that band. Fixing only the write turns the crash into these.

  The trigger is the **tachometer needle**, drawn as geometry rather than as a stamp, centred at
  `y = height − 0x50` with radius `0x32`, so it reaches about `height − 30`. At 1920 × 1080 that is row 1050.
  Confirmed by prediction rather than by fitting: with the pivot forced to 960 the needle reaches 1010 and
  the game runs; at 980 it reaches 1030 and it crashes. Width is irrelevant — the same geometry crashes at
  1600 wide too. Modes that appear to survive worse overruns (1600 × 1200 reaches row 1170) do so by stack
  layout luck, which is characteristic of this kind of corruption.

  **The fix bounds both sites by the table as well as by the surface.**

  The edge walker has no room for a second test, so its surface check is replaced outright — eight bytes,
  size unchanged:

  ```
  cmp  ebx, 0x400
  jge  skip
  ```

  Safe because it can only ever *refuse to record* an edge, and drawing is clipped independently: `0x449A00`
  tests every pixel against all four clip-rect fields and the plot routines honour it, so nothing is drawn
  out of bounds just because an edge was not recorded.

  The fill loop is different — dropping *its* surface check would let it hand rows past the bottom of a short
  surface to the span drawer, a wider bet than this patch needs to make. So its ten bytes become a jump to a
  28-byte stub in `.text` slack that keeps **both** tests:

  ```
  0044a3cb  jmp  stub
  stub:     cmp  esi, 0x400          ; the table bound
            jge  skip
            mov  eax, [render_target] ; the surface bound, kept
            cmp  dword [eax+0xC], esi
            jle  skip
            jmp  0x44a3d5            ; draw the span
  skip:     jmp  0x44a3f4            ; next scanline
  ```

  Rows past the bound therefore contribute no edges and are not filled. Both sites are pattern-located in
  `vrmod/needlefix.py`, the bound is a parameter, and the patch is idempotent per site.
  **✅ Verified on hardware: 1920 × 1080 crashed on every prior attempt, races with a full HUD after the
  first half, and is free of streaks after the second.**

- ✅ **The 1024-entry limit itself is liftable, and has been lifted.** Bounding by the table makes tall
  resolutions *safe*, but nothing below row 1024 is drawn — and the needle pivots at `height − 0x50`, so
  above roughly 1104 screen rows it vanished entirely: at 2048 × 1536 the dial rendered and the pointer did
  not. `vrmod/tablefix.py` doubles the frame instead. The layout, once the prologue has run, is

  ```
  base+0x0000   pushed ebp, edi, esi, ebx      16 bytes
  base+0x0010   edge table A                   4096 = 1024 entries
  base+0x1010   edge table B                   4096 = 1024 entries
  base+0x2010   the return address
  base+0x2014   arguments
  ```

  so `0x2000` covers exactly the two tables, and growing it to `0x4000` gives **2048 entries each** — enough
  for any screen the 2048-wide surface cap allows. That means moving table B and every argument:

  | Site | Change |
  |---|---|
  | `mov eax, 0x2000` | → `0x4000` (the `__chkstk` request) |
  | `add esp, 0x2000` | → `0x4000` (the epilogue) |
  | `[esp+0x1010]`, `[esp+0x1028]` | → `+0x1000` (table B, 6 references) |
  | `[esp+0x20xx]` | → `+0x2000` (arguments, 15 references) |

  Table A stays at `[esp+0x10]`. No instruction changes length — every displacement that moves is already
  disp32 — so the function keeps its 409 bytes and every branch inside it stays correct. Cost: 8 KB more
  stack per call, on a 1 MB stack. **✅ Verified on hardware at 2048 × 1536: dial, needle and banner all
  present, no streaks.**

  ⚠️ **The hard part is knowing which displacements are arguments.** esp moves constantly here — pushes
  before each call, `add esp` after — so a raw displacement means nothing on its own, and *tracking* esp
  through the function does not work either, because it branches and a linear walk desynchronises. What
  makes it tractable is that the displacements fall into two bands with a **0xff8 gap**: everything
  frame-local is at most `0x1028`, every argument is at least `0x2020`. The patch asserts that gap, and the
  exact 21-reference multiset, before writing a byte.

- ⚠️ **Register allocation differs between the two builds, and it has broken two patterns here.** The two
  builds are independent compiles, so the same code uses different registers:

  | | v1.2.5 | Retail 1.1 |
  |---|---|---|
  | Fill loop's index register | `test edi, edi` (SIB `0x3c`) | `test ebp, ebp` (SIB `0x2c`) |

  A pattern matching `test edi, edi` finds the fill loop on one build and nothing on the other — which is
  exactly what happened, and the fill-loop fix silently did not apply to retail until it was caught. The
  same issue in the SIB byte found 20 of 21 stack references instead of 21. **Match on shape, never on
  registers.** `needlefix` now identifies its two sites by a property that survives register allocation: the
  edge walker tests and compares the *same* register, the fill loop does not.

- **The crash handler can be given symbols, and it is worth doing.** It looks for a map appended to its own
  file: it calls `GetModuleFileName`, opens and memory-maps itself, walks the section headers to find where
  the last section ends, and treats everything beyond that as the map. Stock `race.bin` is exactly 1,300,480
  bytes and its last section ends there — zero trailing bytes, hence `No mapfile present`. The format is an
  MSVC 4.0 public-symbols line parsed with `sscanf(line, " 0001:%x %s %x", &secoff, name, &addr)`, all three
  conversions required, parsing stopping at a line containing `FIXUPS`. Lookup keeps the nearest preceding
  symbol and prints `trace: byte 0x%x of "%s"`, so a small byte offset means the address really is inside
  that function. `vrmod/mapfile.py` generates one by treating every target of a direct `call rel32` in
  `.text` as a function start (~2,950 of them) and appends it; the image is untouched, so every patch site
  and the loader are unaffected. This turned an unreadable trace into a named frame in one step and is what
  made the bug above tractable.

- **Audio pitch tracks frame rate.** The engine sound becomes warbly and high-pitched as the renderer falls
  behind, which makes it a usable informal performance signal while testing resolutions.
- **Retail 1.1 has a constant DirectSound crackle on modern Windows; v1.2.5 fixed it in code.** Distinct from
  the pitch-tracks-framerate effect above — this is a persistent crackle/stutter present at *every* resolution
  (confirmed at 640×480, where the renderer is not behind at all) and on a bare retail 1.1 (VRAM-startup fix
  only, no other patches), so it is inherent to the retail build, not introduced by any patch here. The game
  drives its `.sfx` effects through DirectSound (`init_directsound`, a primary + secondary buffer, then
  `Play`); legacy DirectSound is emulated since Windows Vista, and retail's buffer-streaming trips it.
  Comparing retail 1.1's `WaveBegin` against v1.2.5's, the **initialisation is near-identical** — same API
  sequence (`DirectSoundCreate → SetCooperativeLevel(4) → GetCaps → CreateSoundBuffer(primary) →
  SetFormat(primary) → CreateSoundBuffer(secondary) → Play`), same cooperative level, byte-identical secondary
  `DSBUFFERDESC`, same rate builder — the only visible difference is that v1.2.5 adds a **44.1 kHz** path
  retail lacks (retail offers only 11,025 / 22,050 Hz). Since the sample rate is not the culprit (11,025
  crackles the same as 22,050), v1.2.5's actual fix lives in its continuous mixer-feed code (`DSoundMixer`),
  not in setup — which is why it cannot be ported as a small byte patch across the two independent compiles.
  **The clean, general fix (confirmed in game): a drop-in DirectSound wrapper.** `DSOUND.dll` is a *static*
  import, and Windows resolves static imports app-directory-first (it is not a KnownDLL), so a local
  `dsound.dll` shadows the system one with no binary edit. Dropping **dsoal** (`dsound.dll` +
  `dsoal-aldrv.dll`, the **32-bit** build — the game is a 32-bit process) into the `Data` folder beside
  `race.bin` reimplements DirectSound on OpenAL Soft / WASAPI and **eliminates the crackle on retail 1.1**.
  It is non-invasive, reversible (delete the two DLLs), and build-agnostic — the same fix works for any
  DirectSound-era game. So the practical answer is either **use v1.2.5** (its audio is already fixed) or
  **drop the dsoal wrapper in** (fixes retail 1.1 too); the in-engine port is unnecessary.
- **Command-line switches.** The two binaries carry separate switch parsers — see §5.2.5, which lays out
  the launcher→engine flow. The crash handler prints `No mapfile present`; supplying a `race.map` (or the
  appended map of §5.2.4) makes it symbolise stack traces.

#### 5.2.5 The launcher, the engine, and the "canary" tether ✅ CONFIRMED

The game is **two programs, each with its own command-line parser**, and only one thread binds them.

```
Viper Racing.exe  (the launcher)
  ├─ parses its OWN switches:  -autoplay  -no3dfx  -nocanary  -safe
  ├─ checks the CD                         (GetDriveTypeA; "You must have the %s CD inserted to play.")
  ├─ creates the canary semaphore          ("MGI Viper Racing 1998 Canary")
  ├─ chooses the engine at 0x401000:       debug.bin  if a debug flag is set, else  race.bin
  └─ spawns it, forwarding its command line via the format string "%s%s %s"
                                             ( <data-dir>\<engine> <args> )
race.bin  (the engine)
  └─ parses its OWN switches:  -Bob  -DEBUG  -DZV  -FLIP  -Line  -TIM  -dedicated
                               -effect  -hlV  -impulse  -tPV  -truncating  -volume
```

So the switches are **not** one namespace. The four launcher switches are consumed by the launcher and never
reach the engine; the thirteen engine switches are parsed by `race.bin` itself. Because the launcher
**forwards its command line** (`%s%s %s` = directory, engine name, arguments), an engine switch appended to
the launcher rides through to the engine — which is how they are used in practice, since players start the
launcher rather than the engine.

Two details fall out of the spawn path:

- **`debug.bin`.** The engine name is chosen at `0x401000`: `debug.bin` when a debug flag is set, otherwise
  `race.bin`. The debug engine did not ship, but it is why `race.bin` still carries `-DEBUG` and its cluster
  of diagnostic switches — they were driven from this launcher during development.
- **To default a switch in a patch, patch the parser that owns it.** An engine switch is patched in
  `race.bin` (self-contained); a launcher switch in the launcher. No tether is involved either way — the
  single exception being `-nocanary`, which sits on the protection boundary below.

**The canary is the one tether.** The launcher enforces the disc, then passes a token to the engine so the
engine knows it came through that check. The token is a **named semaphore**, not a file or registry key:

1. The launcher checks the CD, creates the semaphore `"MGI Viper Racing 1998 Canary"`, and spawns the engine.
2. `race.bin` at `0x411FA0` calls `CreateSemaphoreA(NULL, 0, 1, "MGI Viper Racing 1998 Canary")` then
   `GetLastError()`. It **requires** `ERROR_ALREADY_EXISTS` (`0xB7`) — it insists something else already
   created that name. If nothing did, it shows a message box titled `MGI` reading
   **`Sneaky user!  Where is my canary!`** and refuses to run.

`-nocanary` is a launcher switch that skips *creating* the semaphore — a developer switch for exercising the
failure path, since with it set the engine's own check fails and the game will not start. The semaphore
carries no disc data itself; it is purely a "you came through the front door" flag.

⚠️ **This is the game's copy protection, so this section documents the mechanism, not a way around it.**
The legitimate path is the intended one — a real disc (or a mounted image of your own copy) satisfies the
launcher, the launcher makes the canary, and the engine runs. Patching the engine to stop requiring the
canary would let it run without the launcher's disc check, which is circumvention; it is also pointless once
the ordinary launcher path works.

#### 5.2.6 The physics task and "phobs" ✅ CONFIRMED (architecture)

Physics runs as a **separate task** communicating over shared memory: the strings `PhysTask`,
`shm_PhysicsShmem`, `phob_list` sit together in `.data`, and a watchdog prints
`Physics has not dropped off a packet in %d seconds`. The simulated world is a list of **phobs** — physics
objects — and every dynamic thing in a race is one.

A factory at `0x4228F0` constructs a phob from a **FourCC type tag**, dispatching to a per-type constructor;
an unrecognised tag prints `Unknown phob type: %x`. The nine types (tag read big-endian, as written):

| Tag | Meaning |
|---|---|
| `BALL` | the horn ball (the HornBall hack's object) |
| `ACAR` `GCAR` `NCAR` `PCAR` | car variants — AI / ghost / network / player |
| `CHKP` | checkpoint gate |
| `OBST` | obstacle |
| `STAT` | static, fixed collider (the `PhobStatic` string) |
| `WOBL` | **wobble — a movable, knock-over object** |

Phobs are **not stored in track files** — no tag appears in any track archive. They are deserialised from a
byte stream (`0x422840` reads the tag and record through the buffered readers at `0x4c63xx`/`0x4c64xx`),
which is the replay/network path: `PhysReplay`, `physrepl::replay_frame` and the shared-memory packets are
how the physics task's object set is saved and synchronised. The static world geometry the car drives on
lives in `.bpp`/`.sol`; the phobs are the live, moving population layered on top.

**`WOBL` is the knock-over mechanism**, and its constructor proves the point: a `STAT` phob allocates
**0x6c = 108 bytes** (shape and transform — a fixed collider), while a `WOBL` phob allocates
**0x4b4 = 1,204 bytes**, eleven times larger — the room a rigid body needs for velocity, orientation and
integration state so it can topple and settle. This is the "a sign knocks over instead of stopping you dead"
behaviour: such props are `WOBL` phobs, categorically different from the rigid `.sol` solids (whose per-object
mass is a fixed class default, §4.8) and from `STAT` phobs. There is no per-object mass field to edit in a
file, because these objects are not in a file — they are created and driven by the physics task.

⚪ Where a track's `OBST`/`WOBL` instances are spawned from (car/mod content, or a scene step at load) is a
runtime question beyond the file formats, and is not traced here.

### 5.3 Audio

- `.mod` in this game is **not** an Amiga/ProTracker tracker module — every `.mod` file sampled, including
  ones at the root of `reference-files/` that could plausibly be confused for one, carries the `0SER`/
  `FNIM` mesh envelope (§4.1; explicitly re-verified for `Needle.mod`, `Viperb.mod`, `Viperc.mod`,
  `Viperw.mod`, `vipers.mod` in this session — all meshes, not music). This is a real naming collision worth
  flagging loudly for anyone approaching this game with prior modding experience elsewhere.
- Game audio/music itself was not present in the sample set and not investigated.
- `.sfx` (sound effects) and `.ens` (per-car engine sound crossfade parameters) are both fully identified
  `0SER` formats with real confirmed structure — see §4.14 and §4.15 respectively, promoted out of this
  section once their internals were solved.

### 5.4 Car config

- `.cf` — compiled car physics/stats config, tag `FRAC` → reversed `CARF`, version=6. ✅ **CONFIRMED —
  field layout solved.** A fixed-layout struct of named `float32` fields (plus one `int32`, `num_gears`),
  payload-relative and 4-byte aligned: mass and centre of mass, dimensions and track widths, engine torque
  curve, transmission ratios, per-corner suspension, brakes, and drag/aero. **85 fields** recovered
  byte-exactly by cross-referencing an independent field-name/value listing against the raw bytes
  against the raw bytes of `viper.cf` — every field matched a unique aligned offset with no ambiguity, once
  ties between identically-valued fields were broken by declaration order and surrounding contiguous
  offsets. Not every byte is named: several stretches (notably right after `fuel_capacity`, and a short run
  before `cm_height`) remain unidentified and must be preserved untouched when rebuilding.

### 5.5 The remaining loose files in `Data/`

Inventoried from the retail `Data/` folder. Several have since been opened — `race.bin` most substantially,
which turned out to be the engine itself and now has its own section (§5.2) — and the rest are flagged here
so they aren't forgotten:

| File | Size | Guess |
|---|---|---|
| `race.bin` | 1.3 MB | ✅ **Opened — it is the game engine**, a full PE executable, not a container. `Viper Racing.exe` is only a launcher. See §5.2 for the video-mode selection, the VRAM check, the viewport/FOV handling and the texture limit. |
| `bench.rpl` | 149 KB | ✅ **Identified** — the benchmark replay, dated September 1998 and shipped on the disc. Its index format predates v1.2.4, so the community builds cannot load it and the in-game Benchmark crashes (§5.2.4). Internal structure not mapped. |
| `english.lng` | 37 KB | 🟡 **Partly opened** — it is a UI string table, holding dotted key/value pairs in plain ASCII, e.g. key `Tracks:Bemidji:Name` followed by its value `Bemidji`, then `Tracks:Bemidji:Description`. Values are editable **in place** (overwrite, space-pad to the original width) and the game accepts the result; the length/terminator encoding is not yet mapped, so values cannot safely be *grown*. This is how the eight track slots' in-game display names are set — see below. |
| `options.def` / `tune.def` | 2.1 KB / 271 B | ✅ **Plain ASCII** key/value lines, one setting per line (`sky_texture yes`, `video mode 2`). `options.def` holds the shipped *defaults*; the live settings the game reads and writes are `Config/options.cfg` in the same format — a distinction worth respecting, since reading the `.def` reports the factory value forever. |
| `intro.avi` | 45.6 MB | Standard video container, out of scope for this catalog. |

**Track slot names.** The game ships exactly **eight** track slots, and the internal filename does not
match the name shown in-game — a persistent source of confusion when working with track files. The
mapping, read from `english.lng`'s `Tracks:<Slot>:Name` keys:

| `.trk` file | In-game name |
|---|---|
| `bemidji` | Bemidji |
| `dundas` | Dundas |
| `hastings` | Ridge Valley |
| `heaven` | Castlegreen |
| `kenyon` | Rock Island |
| `limbo` | Dayton |
| `nfield` | Sunset Mesa |
| `uptown` | Silverdale |

Each slot's menu screenshot is a separate 180×120 `.stp` named after the *file* (`bemidji.stp`, …) stored
inside `ui.res`, while its minimap is the `Trackmap.stp` inside the track archive itself (§4.6).

---

## 6. Coordinate systems & units cheat sheet

| Domain | Units | Notes |
|---|---|---|
| Everything: car meshes, track geometry, AI paths (`.ili`/`.ild`), object placement (`.obt`) | **meters** | One shared scale — cars and tracks are drawn in the same world, so they cannot differ. `Viper0.mod` measures 4.43 × 1.92 × 1.10 against the real Viper GTS's 4.45 × 1.92 × 1.12 m. Cross-checked against the game's own Track Info screen: it reports Bemidji as **1.5 miles**, and that track's three stored driving lines measure 2,268 / 2,113 / 2,324 units — 1.41 / 1.31 / 1.44 miles read as meters (a centreline runs slightly longer than any driving line). Read as feet the same lap would be 0.43 miles, which the game's own figure rules out. **No conversion between car and track space.** |
| AI path Z-axis | **same** as the mesh data — no flip | Confirmed by raycasting path points onto the track geometry, which lands them on the road surface unflipped. A flip is only ever needed to compensate an exporter that mirrors an axis. |
| LOD levels | `Viper0.mod` (highest detail) … `Viper7.mod` (lowest) | 8 levels total, one file per LOD. Switch distances live in the per-car `<prefix>L.tab` (§4.3): viper's are 10/15/20/60/80/100/200/1000 m, scaled by a global LOD Factor. Selection is by camera distance, not by screen. |
| Texture color depth | 16-bit RGB565 (base level, §4.5) | ✅ Confirmed byte-exact. |
| Sky strip angular width | **~90°, tiled 4× around** (§4.5.1) | The four `sky*.tex` are one strip, not one full turn. Confirmed by counting four copies of a unique feature while turning a full circle in game. |

---

## 7. Suggested next steps, roughly in order of value

The package layer (§3) is now fully solved — the biggest gap from the previous pass — so the priority list
has shifted almost entirely to *payload* internals.

1. **Disassemble `race.bin`'s resource loader.** ⚠️ Note the correction: `Viper Racing.exe` is only a
   launcher — the engine, and everything worth disassembling, is `race.bin` (§5.2). A disassembly pass has
   already solved the video-mode, VRAM and HUD paths there, so the approach is proven: load it as a normal
   PE at ImageBase `0x400000`, find a diagnostic string, scan for the 4-byte little-endian VA that
   references it, and disassemble backwards from the reference. Every remaining ⚪/❓ item in §4 (`.sol`,
   `.adr`, `.dnt`, `.ugs`, `.grf`'s scene-graph header, `.stp`'s compressed variant) is parsed by exactly this binary at load
   time — and `.bpp` (§4.9) is now a worked example of exactly this method paying off — searching for the `"0SER"`/`"0TSR"` strings and the FourCC constants from §2 as call-site anchors
   should get you to the real struct layouts fast, far faster than continued black-box guessing. Also worth
   it specifically for `.tex`: confirming whether real `flags=0x03` alpha textures truly use the same
   ARGB4444 packing a synthetic `flags=0x02` test confirmed (currently only visually, not byte-exactly,
   verified). (`.ens` and `.sfx`'s PCM path no longer need this — both solved black-box, see §4.14/§4.15.)
2. **`.grf`'s scene-graph header is now the biggest track-side unknown.** `.bpp` (§4.9) and `.sol` (§4.8)
   are both solved — the collision layer is fully mapped — so the remaining gap in a track is the `.grf`
   scene-graph/instancing header, which is what would be needed to add or remove geometry rather than edit
   values in place (see §4.7). The loader-reading template that cracked `.bpp` and `.sol` applies here too.
3. **`.ccs` field mapping** — deferred until custom test tracks and tooling exist to isolate single-field
   changes with a controlled before/after comparison; ad hoc in-game and cross-track diffing so far has
   been inconclusive or confounded.
4. **`.dnt`/`.adr` field mapping** — now that we have the full `drivers.res` directory (§4.11/4.12), cross-
   referencing `.dnt` values against observable AI driver behavior (aggression, braking, tier-to-tier
   speed differences) at different skill levels could crack this fairly quickly with the game running.
5. **Finish `english.lng`'s string table** (§5.5) — confirmed to be a dotted key/value ASCII table and
   editable in place, but the length/terminator encoding is unmapped, so values can't be lengthened.
   Mapping it would lift the current cap on in-game track names.
6. **Audit the rest of the drawing code for the same shape** (§5.2.4). Three separate bugs in this one
   rasteriser came from the pattern "bounded by the surface, indexes a fixed-size table", and the third was
   found only because the second left visible streaks. Nothing else in the drawing code has been checked for
   it, and `0x449A00`'s clip test is the natural next place to look.
7. **512 × 512 textures** (§5.2.4) — feasible but a multi-day mini-project, not the "~280-byte" quick win an
   earlier estimate suggested. The engine side is ~8 pattern-located sites (both `get_mip_level`
   dispatchers, both index tables, the buffer allocation), but the 256 limit is a **fixed per-texture buffer
   layout**, so it quadruples every texture's footprint (175 KB → 699 KB) and needs the `.tex` format,
   loader, and `tex.py` (which currently downscales to 256) to carry the larger pyramid too. Wants
   on-hardware VRAM testing. It is the one enhancement **neither** retail nor v1.2.5 provides, which is what
   makes it worth considering despite the cost.
8. **`.sfx`'s ADPCM path (`format_tag=2`)** — the compressed-sample bit layout itself, not just the header
   (§4.14). Genuinely deferred rather than solved: no real sample in the retail data uses it, so there's no
   real-world payoff, only a synthetic test case to validate against.

---

## 9. Sources and method

**Primary source.** Every format claim above was derived from a redump-verified, untouched retail copy of
the game (USA, Rev 1), by direct binary inspection of the `.trk`/`.car`/`.res` archives in `Data/`. Where a
claim is marked ✅ CONFIRMED it is backed by byte-exact accounting against those raw bytes — typically a
full parse→rebuild round-trip reproducing the original file byte-for-byte.

**One documented claim is behavioural, not structural.** The sky strip's 4× wrap (§4.5.1) cannot be
recovered from the files at all — nothing in an archive records it — so it rests on watching the running
game instead, and is labelled accordingly. The *layout* half of that section (four tiles forming one
continuous strip, and their seam continuity) is measured from retail bytes like everything else.

**§5.2 was derived differently, and its provenance is worth stating plainly.** The executable section rests
on two legs: static disassembly of `race.bin` (capstone, x86-32, PE mapped at ImageBase `0x400000`), and
**running the patched game on real hardware and photographing the result**. Claims marked ✅ there are ones
where a patch was applied and the outcome observed in a race — not ones that merely look right in a
listing. Print Screen is the measuring instrument.

⚠️ **That instrument is not trustworthy by default, and this was the single most expensive mistake in the
section.** The assumption above — "an exclusive-fullscreen game switches the display mode, so a capture comes
back at the true render size" — is false on a high-DPI display, where the game silently draws into a
virtualised surface and the capture shows that surface upscaled (§5.2.0). It produced an entire phantom
finding (a horizontal shift in the projection) plus a probably-phantom one (the HUD pixel budget), and it
survived three rounds of measurement because the numbers *were* consistent — consistently measuring the wrong
thing. **Calibrate the instrument before trusting it:** find something whose true screen rectangle the game
logs, measure where it actually lands, and only then measure anything else.

Two methodological lessons are embedded in that section and are worth repeating, because both cost real
time here. First, **a control that cannot fail proves nothing** — early "successful" resolution tests were
stock modes that had never been edited, which made a patch that changed nothing look like it worked.
Second, when several tests fail, **check whether they share an input before theorising about the
environment**: three consecutive failures turned out to be the same menu index rather than three
independent limits, and two hypotheses (colour depth, aspect ratio) were built on that mistake before it
was caught. The measurements that finally settled the HUD budget worked because each run changed exactly
one variable while holding a known-good value on the other axis.

**A third lesson, learned expensively.** The executable work in §5.2 produced a long run of confident,
plausible, wrong explanations — colour depth, aspect ratio, a height cap, a memory budget, a DirectDraw
failure, a text-renderer bug, and two different versions of the rasteriser story. Every one was reasoned
from a correct reading of real code, and every one was false. What actually solved it was **bisection on
the running game**: disable half the suspect code, race, keep the half that still crashes, repeat. Nine runs
took it from "1920 × 1080 is unexplained" to a single call, then a parametric sweep of one coordinate took
it to a single constant. Two further hazards are worth naming because both produced convincing fiction:
disassembling from an address without checking **instruction alignment** (x86 self-synchronises into
readable garbage — a "function" that begins `shr ebp, 1` is a misalignment, not a discovery), and
disassembling the **wrong build** (crash logs come from the installed v1.2.5; most static analysis here is
retail 1.1, and the same address is unrelated code in each). When a crash is reproducible and the suspect
region is bounded, bisect the binary rather than read it.

**Independent cross-checks.** Several conclusions were additionally checked against outside
implementations of the same format. These were used to *corroborate* conclusions already reached from the
bytes, never as a source of format facts, and none of them is required to reproduce anything documented
here. They're named so the provenance of those specific claims is auditable.

| Cross-check | Corroborated |
|---|---|
| Per-object mesh extraction (3DSimED) | §4.7's `.grf` chunk record layout — each scenery object dumped as a standalone `.mod` to compare position/UV/face data against. |
| A reference `.tex` encoder (`mktex.exe`) | §4.5's colorkey nudge rule, the ARGB4444 alpha packing, and mip-chain downsampling. |
| A reference `.stp` encoder/decoder (`MKSTAMP.EXE`, `Stp2Tga.exe`) | §4.6's palette and row layout. Note the encoder only ever emits the uncompressed variant, so it cannot reveal the compressed one. |
| A reference `.sfx` encoder (`mksfx.exe`) | §4.14's PCM path and the ADPCM observations. |
| A car-renaming utility (`vrcarrenamer.exe`) | §3's 10-character car-prefix ceiling, which it hard-codes in its own validation. |
| A `.cf`-to-text converter | §5.4's 85 field names and their real-world values. |
| A track-management utility | The slot-to-display-name table in §3, which is otherwise read from `english.lng` directly. |

**Formats used outside the retail data.** These are **not** game data and are not covered by this
reference; they're defined here only so that passing mentions elsewhere resolve.

| Name | What it is |
|---|---|
| `.tra` | Add-on track distribution format used by the modding community. Byte-for-byte the same `0TSR` container as `.trk` (§3), differing only in using the no-split header layout. Installed by swapping it over one of the eight retail track slots. |
| Loose `<track>.stp` | A menu screenshot shipped beside an add-on track, in the truncated `!IGM` form described in §4.6, rather than packed into an archive. |
| Third-party `.car` packs | Vehicle conversions repackaged with community tools. Their only significance here is that they are the files exhibiting §3's no-split archive layout. |

---

## 8. File type index (quick reference)

| Ext | Tag (on disk → reversed) | Contains | Confidence |
|---|---|---|---|
| `.mod` | `FNIM` → `MINF` | 3D mesh (car parts, track props), all LODs | ✅ solved |
| `.ili` / `.ild` / `.ilg` | `NILI` → `ILIN` | AI driving line / checkpoint line / per-AI-tier line | ✅ solved |
| `.tab` | `BATS` → `STAB` | Broadcast camera definitions (ASCII records) | 🟡 well-supported |
| `.obt` | `BATS` → `STAB` | Placed objects: grid slots, checkpoint gates (ASCII records) | 🟡 well-supported |
| `.ccs` | `0SCC` → `CCS0` | Config, 35 floats, fields undecoded; identical across all cars, varies per track | 🟡 header only |
| `.tex` | ` XET` → `TEX ` | Compiled texture — opaque and colorkey round-trip (decode+encode) and full mip chain layout solved; full-alpha well-supported | ✅ / 🟡 mixed |
| `.stp` | `PMTS` → `STMP` | 2D sprite ("stamp"): all UI art, track minimaps, track-select screenshots, cursors, multi-frame strips | ✅ decoded (149/211 files); a 2nd compressed variant ❓ |
| `.grf` | `FARG` → `GRAF` | Track/world geometry + material bindings | ✅ read, in-place write, **and build from nothing** (`grf.build`); confirmed in game (§4.7) |
| `.sol` | `LBOS` → `SOLB` | **Collision solids** — BOX/SPHR/TUBE primitives (§4.8) | 🟡 well-supported |
| `.bpp` | `TPPB` → `BPPT` | **Collision BSP** — triangle soup + 2D BSP over XZ. Largest per-track file (§4.9) | ✅ confirmed |
| `.bsp` | `TPSB` → `BSPT` | Near-static 128-byte stub; likely vestigial | ✅ identified as stub |
| `.adr` | `rDIA` → `AIDr` | AI driver definitions (master/core record) | 🟡 identity only |
| `.dnt` | `TNDA` → `ADNT` | Per-AI-tier driver tuning parameters | 🟡 identity only |
| `.ugs` | `SGPU` → `UPGS` | Car upgrade slot/stat data | 🟡 identity only |
| `.tga` | (none — plain Targa) | Editable texture source | ✅ solved |
| `.res` / `.car` / `.trk` | `0TSR` | Archive container — directory + payload blocks | ✅ solved |
| `.cf` | `FRAC` → `CARF` | Compiled car physics/stats — 85 named fields, read+write | ✅ layout solved (some reserved runs unnamed) |
| `.sfx` | `0XFS` → `SFX0` | Sound effect: envelope + WAV-fmt-shaped header + raw PCM + fixed 4096-byte pad, PCM path solved; ADPCM header understood, sample bit layout not | ✅ / 🟡 mixed |
| `.ens` | `XFSE` → `ESFX` | Per-car engine sound crossfade parameters: fixed 228-byte buffer, recordCount + up to 8 7-float records, structure solved, field semantics inferred | 🟡 well-supported |
| `.bin` | `MZ` (PE executable) | `race.bin` — **the game engine itself**, not a container; `Viper Racing.exe` is only a launcher. Video-mode selection, VRAM check, viewport/FOV handling, texture limit (§5.2) | ✅ / ⚪ mixed |
| `.def` / `.cfg` | (none — plain ASCII) | `options.def` / `tune.def` shipped defaults; `Config/options.cfg` the live settings the game reads and writes | ✅ solved |
| `.lng` | (none — plain ASCII) | `english.lng` — dotted key/value UI string table, editable in place; length encoding unmapped so values can't be grown (§5.5) | 🟡 well-supported |
| `.rpl` | (unknown) | `bench.rpl` — the Sept 1998 benchmark replay; identified, internals not mapped. the index format changed at some point before v1.2.5, which crashes loading it (§5.2.4) | 🟡 identity only |

---

*Compiled from direct binary analysis of two sample sets: a redump-verified, untouched retail copy of the
game (USA, Rev 1 — [redump.info/disc/106242](https://redump.info/disc/106242)), covering all 26
`.trk`/`.car`/`.res` archives from its `Data/` folder, verified byte-exact against the raw archive bytes;
and an earlier extracted sample set (`reference-files/`: 8 tracks — bemidji, castlegreen, dayton, dundas,
ridge-valley, rock-island, silverdale, sunset-mesa — plus the stock Viper car).*
