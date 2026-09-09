# Viper Racing (1998) — Runtime Behaviour

**Purpose:** what the game *does when it runs*, as opposed to what its files contain. Two things live
here: **which detail level (LOD) you actually see in each camera view**, measured in-game, and the
**command-line parameters** the executable accepts, read out of the binary. Companions:
[VIPER_RACING_FILE_FORMATS.md](VIPER_RACING_FILE_FORMATS.md) (byte layouts) and
[VIPER_RACING_ASSET_TREE.md](VIPER_RACING_ASSET_TREE.md) (what's inside a `.car`/`.trk`).

**Confidence key** (same as the format reference): ✅ CONFIRMED · 🟡 WELL-SUPPORTED · ⚪ HYPOTHESIS.

---

## 1. Which LOD you actually see, per camera view ✅ MEASURED

Every car carries **8 body detail levels** (`<prefix>0.mod` … `<prefix>7.mod`) and the engine picks one
by **camera distance**, against the car's own `<prefix>L.tab` table (format: formats §4.3).

Measured directly by building a **LOD-visualiser car** — each of the 8 body levels painted a distinct
solid colour, so the car's on-screen colour *is* its live LOD. With the global LOD factor at its default
1.0, the viper's own `L.tab` bands apply as written: **≤10 = 0, ≤15 = 1, ≤20 = 2, ≤60 = 3, ≤80 = 4,
≤100 = 5, ≤200 = 6, ≤1000 = 7 metres.**

| View | Key | LOD seen | Notes |
|------|-----|----------|-------|
| Car showcase (menu) | — | **0** | close-up |
| Cockpit | F1 | **0**\* | your own body isn't drawn — you're inside it |
| Bumper | F2 | **0**\* | own body not drawn |
| X-ray chassis | F3 | **0**\* | own body not drawn (transparent view) |
| Rear view | F4 | **0**\* | own body not drawn (looking back) |
| Near chase | F5 | **0** | |
| Chase | F6 | **1** | |
| Far chase | F7 | **2** | |
| Rear chase | F8 | **0 ↔ 1** | sits right on the ~10 m band edge — visibly flickers between them |
| Overhead | F9 | **1** | |
| Aerial | F10 | **3** | |
| TV cameras | F11 | **0–7** | 10 broadcast cameras at widely varying distances — sweeps the whole chain |
| Starting grid / roster | — | **3** | |

\* inferred: the view doesn't render your own body, but the camera is at/in the car, so LOD0 by distance.

### What this tells you

- **Selection is purely distance-based.** The F8 flicker at a band edge proves it: a "view" only sets a
  camera *behaviour*, and the LOD follows the instantaneous camera-to-car distance. There is no
  per-view LOD override.
- **The car you drive lives in LOD 0–2** across every normal driving view.
- **LOD 3 is the one people forget.** It's what the **starting grid / car roster** uses, and the aerial
  view — the most-seen "far" level for your own car, in a screen you look at every single race.
- **LOD 4–7** are seen mainly via **TV cameras** and as **distant traffic**. Rarely the subject, but on
  screen constantly for the rest of the pack.

> **Why this matters for custom cars.** A hand-built or forked car often has a real LOD0 and leftovers
> from its donor at the lower levels. Because the roster uses **LOD3**, such a car looks correct while
> you drive it and then **reverts to the donor car** in the pre-race roster, in replays and TV cameras,
> and as distant traffic — i.e. across most of its actual on-screen time. This is exactly the failure
> the toolkit's LOD-chain generator (`vrmod modlod`, or "Generate LOD chain" in the car view) exists to
> fix: it builds real reduced-detail levels that carry the body's own textures.

### The "12th view"
The manual advertises "12 perspectives" but lists only F1–F11. The Sep-17 Alpha *debug* executable had a
**free-camera mode**; that is the likely twelfth, compiled into that build but not wired up in retail. ⚪
Retail effectively has the eleven F-key views above.

---

## 2. Command-line parameters ✅ CONFIRMED (string table)

`race.exe`/`race.bin` parses its command line at startup. These flag names sit in one table in `.data`
at **`0x0D1804`**, immediately followed by the parser's own error and progress strings
(`"Can't change dir to %s"`, `"about to intro."`, `"skipped intro"`), which is how the table is
identified as the argument parser's.

| Flag | Address | What it does |
|------|---------|--------------|
| `-nointro` | `0x0D1804` | Skip the intro video (`intro.avi`). The parser's own `"skipped intro"` string sits just below. ✅ |
| `-server:<addr>` | `0x0D180C` | Multiplayer: connect to / act as a server at the given address. Note the trailing colon — the value is appended. ✅ format / 🟡 semantics |
| `-location<addr>` | `0x0D1814` | Multiplayer location parameter. ✅ present / 🟡 semantics |
| `-tri` | `0x0D1820` | Developer/diagnostic switch. ✅ present / ⚪ effect |
| `-grid` | `0x0D1824` | Developer/diagnostic switch. ✅ present / ⚪ effect |
| `-dedicated` | `0x0D3D68` | Run as a dedicated (headless) multiplayer server. Lives apart from the table above, checked separately. ✅ |

### Single-character "programmer flags" 🟡

The parser also accepts **single-letter** switches, compared character-by-character rather than against
string literals — which is why they don't appear in the table above. Their existence is confirmed by the
parser's own error message:

```
cmdline: Invalid programmer flag '%c'          @ 0x0D1844
```

A **directory-changing** flag is in this class: `"Can't change dir to %s"` (`0x0D182C`) and
`"changed directory."` (`0x0D1888`) sit inside the same routine, so a switch that points the game at a
different data directory exists and is exercised at startup. 🟡

### There is no `-debug` flag ✅

Worth stating plainly, because it comes up: the retail executable has **no debug switch**. The debug
overlays people have seen (the LOD readout, TV-camera and physics pages) are from the **Sep-17 Alpha
debug build**. Their *renderer* code is still present in retail, but the calls into it are compiled
out — they are dormant, not flag-gated, so no command line will bring them back. Adding them requires
patching the binary, not passing an argument.

---

*Measured against a redump-verified retail copy; flag addresses read directly from `race.bin` (v1.2.5).
Semantic labels carry the confidence tag shown. 🐍*
