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

## 3. How the AI reacts to other cars ✅ MEASURED

The AI classifies an encounter by how fast it is closing, and a head-on approach
has its own handler — it is not the overtaking code with different numbers. From
the linker map embedded in the 1998 `ai-tweaker.exe` build (see the format
reference), all in `physics:aicar.obj` and called from `AICar::Update`:

```
AICar::headon_panic()                        -- the head-on case, on its own
AICar::in_path(Point2D const&, float, ILinePos&, float*)
AICar::fast_interact(ProxerDelta const*)     -- closing fast
AICar::slow_interact(ProxerDelta const*)     -- closing slow
AICar::passer(ProxerDelta const*)            -- ordinary overtaking
AICar::checker / dont_push / dont_check / add_contact
```

**Measured in game**, driving the wrong way into the field on stock bemidji
(1.5-mile lap, 7 AI cars at 131–159 mph):

- the swerve fires **a little over 2 seconds before contact**;
- **every** car does it, each as it reaches that threshold, not just the nearest;
- it is **independent of what the car is doing** — mid-corner or flat on a
  straight makes no difference;
- but it **does not really happen at low speed**.

Sweeping the player's speed against AI running a steady ~120–130 mph:

| player | closing speed | reaction |
|---|---|---|
| 40 mph (18 m/s) | ~165 mph (74 m/s) | none |
| 50 mph (22 m/s) | ~175 mph (78 m/s) | swerves, noticeably muted |
| 60 mph (27 m/s) | ~185 mph (83 m/s) | the full swerve, ~2 s ahead |

One thing follows firmly: a pure time-to-contact test cannot be the whole story,
because it would still fire at 40 mph, merely closer. Something about speed
decides whether the behaviour is available at all.

**Watching a whole pack settles the shape of it.** At a steady 50 mph the leading
car panics, while the ones behind slow down and take the ordinary avoidance path,
bouncing off each other. At one fixed player speed some cars panic and some do
not — which no single graded response produces. The "muted" reaction in the table
above was a **mixture** of two discrete behaviours across the pack, not a smaller
version of one, and `fast_interact`, `slow_interact` and `headon_panic` being
three separate functions is what that looks like from the inside.

It also points at the scale being **closing** speed rather than the player's,
since what differs between the panicking car and the calm ones behind it is their
own speed.

Re-run with the field cut to **two cars**, removing the chance that a follower is
reacting to the car ahead rather than to the player:

- hold 40 mph — nothing happens at all;
- **accelerate from 40 to 50 on the approach — the panic fires partway through
  the acceleration**;
- at full speed it fires a clear 2+ seconds out.

The middle case is the informative one. Firing *during* the acceleration, at a
speed rather than at a place, rules out a pure distance-or-time trigger and shows
the condition is evaluated continuously: it becomes true as the speed crosses a
threshold while the cars are already closing.

So the model is **a speed threshold AND a proximity condition, whichever is
satisfied last**. Well above the threshold the ~2 s proximity is what you wait
for; right at it, the speed is.

**The threshold is on the approaching car's own speed, not the closing speed.**
Two observations settle it between them:

| | player | AI | closing | panic? |
|---|---|---|---|---|
| the 40 mph hold above | 40 mph | ~125 mph | **~165 mph** | no |
| driving hard at a car that has just reset | fast | slow | **~150 mph** | yes |

The closing speeds are comparable — higher, in fact, in the case that does *not*
panic — so closing speed cannot be what is tested. What differs is how fast the
car doing the approaching is going. A slow car being charged down panics; a fast
car being crawled at does not.

That also explains the pack behaviour without needing the follower confound: the
cars behind were not calm because *they* had slowed, they were calm because
nothing about the player had changed.

So the working model is **a speed-dependent choice between ordinary avoidance and
a panic swerve, the panic firing about 2 s before contact**, with the switch
somewhere between 40 and 60 mph of the approaching car's own speed. The 2 s itself is eyeballed, and remains untested against the
possibility that it is a fixed distance that merely looked like a time in a
narrow speed band.

**What the panic is.** Its five calls resolve through the same linker map to the
whole manoeuvre:

```
Car::SetBraking (0.1f)      10% brake
Car::SetEBrake  (1.0f)      handbrake FULL ON
Car::SetThrottle(0)         throttle closed
Car::SetClutch  (0)         clutch out
Car::SetSteering(+/-1.0f)   full lock, the sign from [esi+0xf18]
```

A deliberate handbrake spin, then — not an avoidance line that overshoots. The
car stamps the handbrake, lifts, dumps the clutch and throws full lock.

`vrmod headon --disable` writes a single `RET` at the function's entry, skipping
all five. **Confirmed in game:** the panic stops and ordinary object avoidance
continues — the first direct evidence that `headon_panic`, `passer` and
`slow_interact` really are independent rather than one behaviour with thresholds.

Worth knowing when placing obstacles: this is a **car-to-car** response. Static
solids are handled elsewhere — `.sol` primitives reach the AI's own avoidance, so
an opponent will steer around a barrier that did not exist when its racing line
was generated (see §4.8 in the format reference).

Related, from the same map: `CenterLine::wrong_way()` in `ai:ideal.obj` and
`RaceDeity::do_wrongway()` in `physics:racedty.obj` — wrong-way detection reads
the centre line, which is `track.ild`, and is what raises the "press space to
reset" prompt. `AITrackIsReversed()` in `ai:driver.obj` shows reverse-direction
racing is a first-class mode, which is what `rdefault.ili` exists for.
