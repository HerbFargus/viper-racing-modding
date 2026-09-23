# Viper Racing (1998) — Runtime Behaviour

**Purpose:** what the game *does when it runs*, as opposed to what its files contain: **which detail
level (LOD) you actually see in each camera view** and **how the AI reacts to other cars**, both
measured in-game; the **command-line parameters** the executable accepts, read out of the binary; and
**how world objects are created and freed**, which is what the exit panic reports on; and **what the launcher does before the engine starts**, which is a separate program with its own flags. Also **what a surface above the road does to a car** (§9): the launch pad. Companions:
[VIPER_RACING_FILE_FORMATS.md](file-formats.md) (byte layouts) and
[VIPER_RACING_ASSET_TREE.md](asset-tree.md) (what's inside a `.car`/`.trk`).

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

## 2. Command-line parameters — the ENGINE's ✅ CONFIRMED (string table)

> These are read out of `race.bin`. The **launcher** parses a different set entirely
> (`-autoplay`, `-no3dfx`, `-nocanary`, `-safe`) — see §5. Neither list overlaps the other,
> so "which flags does Viper Racing take" has two answers depending on which binary
> you ask.

`race.exe`/`race.bin` parses its command line at startup. These flag names sit in one table in `.data`
at **`0x0D1804`**, immediately followed by the parser's own error and progress strings
(`"Can't change dir to %s"`, `"about to intro."`, `"skipped intro"`), which is how the table is
identified as the argument parser's.

| Flag | Address | What it does |
|------|---------|--------------|
| `-nointro` | `0x0D1804` | Skip the intro video (`intro.avi`). The parser's own `"skipped intro"` string sits just below. **Introduced by the official 1.1 patch** — see the history doc. ✅ |
| `-server:<addr>` | `0x0D180C` | Multiplayer: connect to / act as a server at the given address. Note the trailing colon — the value is appended. ✅ format / 🟡 semantics |
| `-location<...>` | `0x0D1814` | **Jumps the Blimp camera to a position.** Not a multiplayer parameter, as this table said until the debug cameras were found: the parser's neighbours are `"Can't scan blimp jump location, but will go to track."` and `"Can't parse location arg: \"%s\""`, and it degrades to starting at the track when the argument will not scan. ✅ present / ✅ purpose / 🟡 syntax |
| `-tri` | `0x0D1820` | Developer/diagnostic switch. ✅ present / ⚪ effect |
| `-grid` | `0x0D1824` | Developer/diagnostic switch. ✅ present / ⚪ effect |
| `-dedicated` | `0x0D3D68` | Run as a dedicated (headless) multiplayer server. Lives apart from the table above, checked separately. ✅ |

> **Where `-nointro` came from.** The 1.1 patch readme (19 January 1999) introduces it
> explicitly, and says why: *"The introductory movie causes all sorts of problems. It may
> even have lingering effects on gameplay, causing hangs and lockups. Trying to escape from
> the intro movie often causes the game to crash."* So it is a workaround for a bug MGI
> could not fix, not a developer convenience. See MODDING_HISTORY.md.

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

A warning for anyone re-checking this by string search: `-DEBUG` **does** appear in
`race.exe` and in both retail `race.bin` files — as the tail of `NON-DEBUG` in the
build banner (`Jan 25 1999 11:47:39 NON-DEBUG MSVC-4.0 Release`). That is a false
positive, not a flag. The launcher's `debug.bin` (§5) is a module filename, also not
a flag.

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
all five. **Confirmed in game on both retail pressings** — v1.1's `race.bin` and
v1.0's `race.exe`: the panic stops and ordinary object avoidance continues. That
is the first direct evidence that `headon_panic`, `passer` and `slow_interact`
really are independent rather than one behaviour with thresholds, and the two
pressings agreeing rules out the result being an artefact of one build.

> The signature is found by scanning for the prologue, so it locates the site
> correctly in any build. What it could not do until recently was choose the
> right FILE: on a v1.0 install it opened the `race.bin` sitting beside
> `race.exe`, which that pressing never loads, so the toggle reported success
> and changed nothing. See the note on the horn ball below — the same class of
> mistake, caught the same way.

Worth knowing when placing obstacles: this is a **car-to-car** response. Static
solids are handled elsewhere — `.sol` primitives reach the AI's own avoidance, so
an opponent will steer around a barrier that did not exist when its racing line
was generated (see §4.8 in the format reference).

Related, from the same map: `CenterLine::wrong_way()` in `ai:ideal.obj` and
`RaceDeity::do_wrongway()` in `physics:racedty.obj` — wrong-way detection reads
the centre line, which is `track.ild`, and is what raises the "press space to
reset" prompt. `AITrackIsReversed()` in `ai:driver.obj` shows reverse-direction
racing is a first-class mode, which is what `rdefault.ili` exists for.

### What the swerve is *not* ✅ RULED OUT

Worth recording because it cost four in-game cycles to establish, and the wrong
answer is the intuitive one.

The AI's **reactive** avoidance logs every decision it makes. `set_reason`
(`0x429500`) writes a label from the table at `0x4D74E8`, and the 24 call sites
cover the whole repertoire:

```
laptime slowdown · water_cut · offground_cut · panic_brake · meccaZERO · fouroff
begin · CONTACT-FLIP · CONTACT · hiatus · VerySlow · aftershock · enter_hot · MPH
bump · freeze · lonslam · squeezebrake · edgebrake · "lat would" · latslam r
latslam l · cold_apex
```

Every lateral one — `latslam r/l`, `squeezebrake`, `edgebrake`, `"lat would"` —
lives inside `0x42BA50`–`0x42BC8E`. **No-op'ing that entire function changed
nothing in game**: the cars still swerved away from an oncoming player.

So the oncoming swerve is **not** the reactive avoidance system. It is the AI's
**proactive line re-routing** — choosing a lateral position on the track to route
around an obstacle car — driven by `prox_info`, logging no reason at all, and
embedded in the main drive function tree rather than sitting behind a label.

Three tangents ruled out in the same dig, each of which looks promising from a
string search and is not the thing: the threat chain at `0x40E81E` is the
**ghost/replay** recorder (it sits next to `"ghostlap: ..."`), the cluster at
`0x439xxx` is **physics** (9.81, vector normalise), and `0x404E3D` is the
**player's** wrong-way banner.

> **If you pick this up again:** static disassembly is the slow way here, because
> offset search is defeated by struct aliasing — `0xEEC`–`0xEF8` are threat fields
> in the AI struct and a scratch position vector in the physics code. A live
> debugger with a breakpoint on steering writes, while driving oncoming, finds it
> far faster.

### The horn ball, and a warning about how patches get verified ✅ CONFIRMED IN GAME

The HACKS tab's horn ball reads two floats out of the engine's `.rdata` — the
velocity added to the ball (**31.111** stock) and the seconds enforced between
throws (**2.0**). `vrmod hornball` retunes both, confirmed in game on the v1.0
pressing: a 5× throw with a half-second cooldown behaves as asked.

**Where the ball goes** — read from `Ball::Throw` (`race.exe` `0x4412a0`, the symbolised 1998 build). The throw is refused inside the cooldown.
Otherwise the ball takes the car's frame and is placed **3.5 m ahead** along the car's forward axis (plus up
to another 3.1 m for a throw registered late within its 0.1 s window) and **0.5 m above the car's origin**,
which sits about 0.34 m above the road (measured below, from where a buried ball stops being caught).
Its velocity is that same forward axis times **the car's speed + 31.111**. Nothing aims it up: on flat
ground the ball leaves level and drops. The only ways to raise it are to pitch the car (a wheelie, a crest)
or to throw faster, so it drops less before arriving.

Ball drop below its launch height, by distance. Gravity is **9.81 m/s²**: `PhobDyno::Update` adds
`mass × −9.81` to every moving body's force each tick, so the drop is the same whatever the ball weighs.

| throw | 10 m | 20 m | 30 m | 50 m |
|---|---|---|---|---|
| stock, car stopped (31 m/s) | 0.5 m | 2.0 m | 4.6 m | 12.7 m |
| stock, car at 30 m/s (61 m/s) | 0.1 m | 0.5 m | 1.2 m | 3.3 m |
| 5×, car stopped (156 m/s) | 0.02 m | 0.08 m | 0.2 m | 0.5 m |

**Measured in game: the ball arrives 0.6–0.8 m off the road** after a few metres of flight, fired
at stock speed from a car stopped on a line 8 m before a row of hinged targets. Heads hinged at 0.2, 0.4 and 0.6 m tipped
back, meaning they were struck above the hinge. Heads hinged at 0.8 and 1.0 m tipped forward, struck below.
A matching row of plain posts fell from 0.8 m tall upward. Heads 1.4–2.6 m up needed a wheelie. Targets
meant for the ball should cover roughly 0.5–1 m off the road (file-formats.md §4.3).

**A faster ball misses thin targets: it tunnels.** Physics runs in fixed ticks of **16 ms (62.5 a second)**:
`PhysTaskUpdate` asks `TimerConditioner::GetTicks` how many are due, which is time owed × 62.5, and runs
`collide_phobs` then `update_phobs` once per tick. `PhysicsGetTime` is simply the tick count × 0.016. So the
ball doesn't sweep its path. It jumps from one tick's position to the next, and a collider only registers it
if one of those positions overlaps it. Observed in game: at raised throw speeds, targets get passed through
far more often than at stock, unless they're scaled up.

| throw | ball travel per tick |
|---|---|
| stock, car stopped | 0.50 m |
| stock, car at 30 m/s | 0.98 m |
| 3×, car stopped | 1.49 m |
| 5×, car stopped | 2.49 m |
| 5×, car at 30 m/s | 2.97 m |

A head-on pass through a capsule of radius `R` overlaps it along `2 × (R + 0.457)` of the path (0.457 m is
the ball's collision radius, below). A pass that isn't through the middle overlaps less. A shot can't skip
a target only while the travel per tick stays under that length:

| collider radius | fastest ball a head-on hit can't skip | from a standstill |
|---|---|---|
| 0.05 m (a stock pole) | 63 m/s | 2.0× stock |
| 0.25 m (a stock sign post) | 88 m/s | 2.8× stock |
| 0.6 m (a 1.2 m target) | 132 m/s | 4.2× stock |
| 1.2 m | 207 m/s | 6.7× stock |
| 3.5 m (a 7 m giant) | 495 m/s | 16× stock |

The car's own speed adds to the ball's. Size targets for the throw speed you play at, or play at stock: a
1.2 m target that stock never skips is skipped by some head-on shots from 5× even with the car stopped.

**The ball's collision size is a constant, and a patchable one.** The horn ball isn't loaded from any
file. `create_ball` (`race.exe` `0x4636a0`) builds its `PhobData` on the stack, tagged `BALL`, and
`Ball::Ball` turns field `+0x24` into the radius of its `SphereVolume` after multiplying it by `0.0254`.
The ball's physics is authored in **inches**. The value is `18.0`, so the collision sphere is **0.457 m**
in radius, half as big again as the drawn `ball.mod` (about 0.3 m). It's written as an immediate:
`mov dword [esp+0x28], 18.0`, whose float sits `0x5d` bytes after the `BALL` tag store. That layout
holds in both the v1.0 pressing's `race.exe` and its `race.bin`; the community builds haven't been
checked. The same record holds `3000`, `5000`, `0.6` and `5.0`, whose meanings are not yet read.

`vrmod hornball DATA --size MULT` sets it (0.25–10× stock), and the manager's horn-ball panel has a
slider for it. It's found by signature like speed and cooldown, and `--reset` puts it back. Only the
**collision** grows. The ball you see is the car's `ball.mod`, so a model meant to look the part (a
boulder, say) should be built to the radius the tool reports.

**The spawn point is its own setting.** `Ball::Throw` reads its 3.5 m-ahead and 0.5 m-up offsets from two
`.rdata` floats that nothing else in the image references. `--spawn-ahead` and `--spawn-up` set them in
metres, and the manager has sliders for both. Size never moves them. **Seen in game:** a 3× ball at the
stock spawn starts partly inside the road, and the game shoves it out, so it **bounces** as it launches.
That's a legitimate effect for a mod, which is why the two are kept apart. `--spawn-clear`, a button in
the manager, pushes both offsets out by however much the radius grew. That keeps the ball's back and bottom
where a stock ball's are, clear of the car and the road, so it flies level. For 3× that's 4.41 m ahead and
1.41 m up, and its centre flies about 0.9 m higher than stock.

**A ball spawned inside the road is launched out of it, and deeper means harder.** Seen in game, all at the
stock spawn height and throw speed:

| ball | radius | starts buried by (approx.) | what it does |
|---|---|---|---|
| 1× | 0.46 m | 0 | a normal level throw |
| 2–3× | 0.91–1.37 m | 0.2–0.7 m | a catapult arc: up, over and down |
| 10× | 4.57 m | ~3.9 m | fired skyward, and lands nowhere near where it started |

The mechanism, as far as it's read: every tick, `SphereVolume::CollideGround` asks the terrain how far the
ball is sunk (`TerrainGetSphereIntersection`, radius minus distance to the surface) and answers with an
impulse. That's built for a ball that has just touched down, a few centimetres deep. How the depth feeds
the impulse isn't traced. What the game shows is that the launch grows with how deep the ball starts, and
a bigger ball at the same height starts deeper. So **spawn height is the launch dial:** a big ball raised
until it's only slightly buried lobs gently, and a small ball sunk deeper launches hard. At 10× the ball also
starts wrapped around the car, since its back reaches about 1 m behind the car's origin, which may add to
the kick.

**Sink it all the way and it falls through.** The stock ball still bounces at a spawn height of −0.80 m and
drops out of the world below that. The terrain test only catches a ball that still pokes up through the
surface. So at the cutoff the ball's top is level with the road: origin height − 0.80 + 0.457 ≈ 0, which
puts **the car's origin about 0.34 m above the road**. That agrees with the level-flight gauge (spawned
0.84 m up, arriving 0.6–0.8 m after a little drop). A ball of radius *r* should stay catchable down to a
spawn height of about −(0.34 + *r*); only the stock ball's cutoff has been tried.

**A big ball flying higher meets targets from above, and tips fewer.** Tested with a 3× ball at the clear
spawn against five hinged heads. Its centre crossed at about 1.4–1.6 m, against stock's measured 0.6–0.8 m.
- Heads whose colliders ended below that were struck on their rounded tops, and didn't tip.
- A head hinged 1.4 m up was struck too close to the hinge to tip.
- Heads it met on the capsule's straight side, 0.5 m or more above the hinge, tipped: a 1.2 m head on a
  1.0 m stick, the same with its collider extended 0.6 m past the head, and a 1.2 × 2.4 m panel on a
  0.5 m stick.

It isn't about mass: the size doesn't change the ball's weight (below). The rule for any ball: **a hinged
target tips when the ball's centre crosses the straight side of its collider at least ~0.5 m above the
hinge.**

The ball's record, as `PhobDyno` and `Ball::Ball` read it: mass `+0x08` = **3000 lb** (×0.4545 → 1,364 kg,
about a car's weight); inertia `+0x0c/+0x10/+0x14` = **5000 lb·ft²** each (×0.04228 → 211 kg·m²); radius
`+0x24` = 18 in. The last three fields, `+0x28` = 5000, `+0x2c` = 0.6 and `+0x30` = 5.0, go to the
collision sphere and aren't read yet.

One car is different: **`plane`**, one of the five cars in the HACKS tab's vehicle picker (`plane.car`
ships). With it, the ball gets the car's own velocity plus the forward throw, and is placed one unit
**below** the car. It's dropped rather than thrown: a bomb. Read from the code, not yet seen in game.

**It did not work before, and the way it failed is the point.** The constants are
named by *virtual* address in the instructions that read them, and the code
converted with `va - IMAGE_BASE`. That is the RVA, not the file offset —
`.rdata`'s `PointerToRawData` sits `0xe00` below its `VirtualAddress` in
`race.bin` and `0x1600` below in `race.exe` — so every read and write landed a
few kilobytes past the real constants.

Nothing failed. The target was still inside `.rdata`, so the write succeeded, and
the read came back from the same wrong place:

| | what the tool located | what the game reads |
|---|---|---|
| cooldown | 0.25 — as written | **2.0** — stock |
| speed | 194.44 — as written | **31.111** — stock |

A self-consistent round-trip, reporting tuning that was never in effect. It also
overwrote whatever did live there: two unrelated `.rdata` floats, `20.0` and
`4.0`.

> **The general warning.** A patch that reads back its own write proves only that
> it can find its own write. Three separate checks in this toolkit did exactly
> that — this one, a DPI flag that read back the registry value it had just set,
> and an audio check that confirmed a DLL's *filename* without noticing it was
> the wrong architecture to load. All three reported success while the game
> carried on unaffected. **Verify against what the game does, not against what
> you wrote**; here that means asserting the STOCK value is gone from the site
> the instruction points at.

---

## 4. Object lifetime — and what "Memory still allocated" means ✅ MEASURED

World objects ("phobs" — balls, barriers, scenery) are created **at level load**,
not lazily. A loader reads each record from the track file, a factory
binary-searches its 4-character type tag, and the object is constructed.

**Registration is two separate things, and only one of them is the one that
matters.**

| | what it does |
|---|---|
| `register_phob` (`0x4271C0`) | memory-pool accounting *only* — `[phob+0x34] = cursor`, then advances the cursor by the object's size |
| the **master object array** | pointer at `[0x50B1C0]`, count at `[0x50B6B0]` — what the engine actually iterates to **update, render and free** |

The load loop writes `objarray[count++]` **itself**, as it goes. The base
constructor does not, and neither does `register_phob`. So an object can be fully
constructed, correctly pooled, and still never be updated and never be freed.

**That is exactly what the exit panic reports.** `Memory still allocated: N bytes`
divides cleanly by the object size, and the quotient is how many objects never
reached the array:

```
3 extra balls, no registration at all   7,344 bytes  =  3 × 2,448
the same 3 after register_phob          3,672 bytes  =  3 × 1,224   (pool half freed,
                                                                     collider half not)
```

**Two diagnostics fall out of this**, and both are worth having:

- **If you see the panic, divide.** The byte count tells you how many objects
  leaked and, with the object's size, which kind.
- **An object that draws but never moves is the same fault from the other side** —
  present in the world, absent from the array the update loop walks.

The practical rule for anything that creates objects at load: appending to the
array *during* the load loop corrupts it, because `[0x50B6B0]` is the loop's own
live index. The insertion has to happen after the loop has finished.

---

## 5. The launcher is a separate layer ✅ CONFIRMED (string table)

`Viper Racing.exe` is **not the game**. It is 388,608 bytes of which only **16 KB is
code**; the rest is resources. It imports `KERNEL32`, `USER32`, `ADVAPI32`, `WSOCK32`
and `VERSION` — and notably *not* `DDRAW`, `DSOUND` or `DINPUT`. The engine is
`race.bin`, and the launcher's job is to find it, decide the machine can run it, and
start it.

That means **there are two flag sets and two layers**, and §2 above covers only the
engine's. Everything here is read out of the launcher's `.data` section at `0x4740`
onward, in file order, so the grouping below is the program's own.

### The four launcher flags 🟡

```
-autoplay   -no3dfx   -nocanary   -safe
```

None of these appear in `race.bin`, and none of §2's engine flags (`-debug`,
`-dedicated`, `-grid`, `-nointro`, `-tri`) appear here. `-no3dfx` and `-safe` sit
directly beside the 3D-capability errors below, which is what they most plainly relate
to. **Behaviour is untested** — these are confirmed as strings the launcher carries, not
as verified switches.

### Where it looks for the game ✅

```
Software\Sierra On-Line\Viper Racing      ← registry key
  DataDirectory                            ← values
  CDDirectory
Data\        \Data        %sdata\%s        common.res
"Can't find data directory--Game may not be installed"
```

`common.res` is the file it checks to decide a directory really is the data directory.

### The user directory is a HARDCODED absolute path ✅ CONFIRMED (string + observed on disk)

`MGI\Viper98\` sits next to those registry names in the string table, which makes it
look like another place the game *searches*. It is not. It is where the game **writes**,
and the binary carries the whole path as a literal:

```
C:\Program Files\MGI\Viper98\   |   Config Dir: %s
```

Not derived from the registry, not relative to the install, not affected by where you
put the game. `Win32GetUserDirectory` and `get_user_directory` are the functions behind
it (both named in the RC symbol map), and `Long User Directory (%d), I am scared.` is
the length guard.

**Observed in that folder after playing a v1.0 install kept elsewhere entirely:**

| file | what it is |
|---|---|
| `options.cfg` | the live settings — `realism`, `opponent_strength`, controls, video mode |
| `options.def` | the shipped defaults, copied here |
| `bemidji.sco` | the per-track score/record file (`RecordMgr`, `RecordFile`; `SCO file !exists or !legit; creating empty one`) |
| `ghostcar\` | saved ghost laps (`GhostBegin()`, `Ghost::submit`) |
| `paint0.tex` … `paint8.tex`, `exotic.tex`, `sedan.tex`, `sports.tex` | the runtime paint slots |

Three consequences worth knowing before testing anything:

- **Settings do not live with the install.** Two installs on the same machine share one
  `options.cfg`, so a setting changed while testing one build is still set when you run
  the other. Comparing builds means checking this folder, not the install folder.
- **Deleting and rebuilding an install does not reset anything.** A "clean" tree still
  starts with the previous run's settings, records and ghosts.
- **The registry key is a red herring for this.** `DataDirectory` and `CDDirectory`
  under `Software\Sierra On-Line\Viper Racing` are read by the launcher to find the
  *data*; they have nothing to do with the user directory, and setting them does not
  move it.

### It chooses between two engine modules ✅

```
debug.bin
race.bin
```

Stored adjacent, in that order. So the retail launcher will load an engine module named
**`debug.bin`**, which makes it a hook for running a second build without overwriting
`race.bin`. Whether that is unconditional, gated by `-safe`, or tried-then-fallback is
**not established**.

> This is *not* a debug switch. The "there is no `-debug` flag" finding in §2 stands —
> and be warned that a string search for `-DEBUG` hits the tail of `NON-DEBUG` in the
> build banners, which is a false positive, not a discovery.

### Single instance, and a "Canary" ✅ CONFIRMED (symbol name + failure string)

```
MGI Viper Racing 1998            MGI Viper Racing 1998 Canary
Viper Racing Window
```

Two named kernel objects differing only by the suffix. The canary is the launcher's
**tether to the engine, and it is the game's copy protection**: the launcher checks
the CD, creates the named semaphore, and spawns the engine, which refuses to run
unless that name already exists. The full mechanism — the `CreateSemaphoreA` call
site, the required `ERROR_ALREADY_EXISTS`, and what `-nocanary` actually does — is
documented once in **`VIPER_RACING_FILE_FORMATS.md` §5.2.5**; it is not repeated here.

One detail belongs to this section, because it explains the second binary on the
first disc. The function is named in the RC's own symbol map —
`check_for_canary_launch`, at `0x004123a0` — but the failure message
`"Sneaky user!  Where is my canary!"` sits in both `race.bin`s and in **neither**
v1.0 `race.exe`. On v1.0 *you* start the engine directly: there is no launcher to
have left a canary, so the build that ships as the game has no such check to fail.
See "v1.0 has no launcher at all" below.

### Everything it refuses to run on ✅

```
%s cannot run under Windows NT
%s cannot run without a mouse.
%s requires %d megabytes of memory (you have %d).
%s may not run optimally with %d megabytes of memory.
%s requires %d megabytes of virtual memory (you have %d).  Please free up disk space...
You only have %d megabytes of free disk space.
This game requires DirectX 5 or 6          This product requires DirectX 5.0 or better
%s\ddraw.dll
Your video card does not support 3D graphics
Your video card does not support 3D texture mapping
Your video card returned an error.  Are your video drivers up to date?
%s is not installed properly.  Run setup from the CD
You must have the %s CD inserted to play.
```

**The CD check lives here, in the launcher** — which is exactly why the widely
circulated no-CD build differs from MGI's official 1.2.1 executable by **three bytes at
`0x000C70`** (`83 EC 24` → `C3 90 90`, a function turned into an immediate `RET`). The
community never needed to touch `race.bin` for it.

It also explicitly refuses **Windows NT**, which is what the official 1.2.1 beta patch
was released to address.

### The crash path, including a mail sender ✅

```
%s has aborted (%d).  Let's check out the log.
notepad c:\log.log
Can't start game. (%s)
Our Apologies        Continue?
```

There is a log, at **`c:\log.log`**, and on an abort the launcher offers to open it in
Notepad. That connects to the `kernel:log.obj` symbols — `LogBegin`, `log_file_begin`,
`LogError`, `LogPanic` — visible in the linker map (see the format reference).

And the launcher carries a small **SMTP client** for mailing a report:

```
Can't start winsock      Can't create socket.      Can't bind socket (%d).
Can't get address for %s          Can't connect to %s (%d)
Can't parse host address from %s  Can't parse rcpt from %s
HELO lame.programmer.com
MAIL FROM: %s     RCPT TO: %s     Subject: %s
Twinkies for sale.
tried to send way too much!       Sending mail failed.
```

`HELO lame.programmer.com` and the placeholder subject `Twinkies for sale.` are
developer scaffolding that shipped at retail. This explains the otherwise puzzling
`WSOCK32` import in a program that does not itself do networking.

### v1.0 has no launcher at all ✅

The first pressing ships `Data\race.exe` (2,404,451 bytes) and nothing else runnable.
That binary **does** import `DDRAW`, `DSOUND`, `DINPUT`, `WINMM` and `TAPI32`, carries
890 KB of code, and contains **no `.bin` string anywhere**. Between the pressings the
engine moved out of the executable and into `race.bin`, leaving the 16 KB stub described
above — which is also where the 890 KB "missing" from the v1.1 executable went.

The build banners agree, and date both builds to the second:

```
v1.0  Data\race.exe   "Oct 21 1998 08:49:56 NON-DEBUG MSVC-4.0"
v1.0  Data\race.bin   no banner
v1.1  Data\race.bin   "Jan 25 1999 11:47:39 NON-DEBUG MSVC-4.0 Release"
v1.1  launcher        no banner
```

The compiled program stamps itself, and in v1.0 that is the `.exe`. Both were built with
**MSVC 4.0**, a 1995 compiler. `Oct 21 1998` matches the v1.0 disc readme date exactly.

#### Does a v1.0 install use `race.bin` at all? ✅ RESOLVED — no, nothing can load it

This mattered because it decides which retail build is the right test baseline. The
answer is that `race.exe` is live and `race.bin` is **unreachable**: present on disk,
named by nothing, loaded by no code path.

| | finding |
|---|---|
| Game executables on the v1.0 disc | exactly one, `Data\race.exe`. No `Viper Racing.exe` anywhere on it |
| `autoplay.exe` at the disc root | the autorun shell — references `setup.exe`, and neither `race.exe` nor `race.bin` |
| Occurrences of the string `race.bin` in v1.0 `race.exe` | **0** |
| Occurrences anywhere in a v1.0 install | **0** — only the v1.1 launcher ever names it |
| Patching each and launching | changing `race.exe` changes behaviour; changing `race.bin` changes nothing |

The "For" argument above is now settled in the opposite direction. `race.exe` carries
no version string, but it does carry `"Release Candidate 1:  CONFIDENTIAL"` — and that
is exactly what a v1.0 install prints on its title screen. That string exists **only**
in `race.exe`, so the running binary identifies itself. The Options screen shows no
version at all, which is consistent: the build that is live has none to show.

#### So why is there a second engine on the first disc?

Because it is the same engine built for the *other* architecture — the one that
arrives in v1.1. All three binaries are one program:

Percentages read **row into column**: what share of *this* file's strings also appear
in *that* one.

| | distinct strings | → found in `race.exe` | → found in v1.1 `race.bin` |
|---|---:|---:|---:|
| v1.0 `race.exe` | 18,484 | — | 25.1% |
| v1.0 `race.bin` | 4,928 | **95.3%** | **94.9%** |
| v1.1 `race.bin` | 4,960 | 93.5% | — |

The relationship is **containment, not symmetry**: each `.bin`'s strings are almost
entirely a subset of `race.exe`'s, while only a quarter of `race.exe`'s are found in a
`.bin`. That asymmetry is the whole story — `race.exe` is the same engine *plus*
13,784 strings nothing else has: the embedded linker map
(`Address  Publics by Value  Rva+Base  Lib:Object`) and debug formatters
(`CHAR %d`, `CSTR "%s"`, `FLOAT %f`). That is the Release Candidate instrumentation,
and it is why the crash handler can name its own functions (§4).

Add the canary asymmetry — `"Sneaky user!"` present in `race.bin`, absent from
`race.exe` — and the shape is clear. The v1.0 disc carries **two builds of one
engine**: the debug-instrumented one it actually runs, and a clean, launcher-partnered
`race.bin` with no launcher on the disc to partner it. v1.1 is where that second
architecture ships for real.

Which sharpens what the RC discovery actually means: MGI did not merely ship a
debug build by accident, they shipped it **instead of** the clean release build
sitting in the same folder.

#### The AI names prove it from the other end ✅ OBSERVED IN GAME

A v1.0 install fields opponents called **`E-1`, `E-2`, `E-3`…** where the release
gives them proper names. That is visible without any tooling, and it is the RC
build showing through.

Every binary carries the same opening roster — `Frank`, `Charles`, `Radar`, `Jerry`,
`Elaine`, `Kramer`, `George`, then `Taro`, `Miyuki`, `Shoichiro`, `Kenji`, `Takeshi`
and the rest, then `Mr. C1`–`Mr. C5`. What follows differs:

| build | after `Mr. C5` | tier placeholders present |
|---|---|---:|
| v1.0 `race.exe` — the RC, and what you run | `E-1 … E-16`, `I-1 … I-16`, `H-1 … H-16`, `C1-1 …` | **112 / 112** |
| v1.0 `race.bin` — dormant | `Easy`, `Intermediate`, `Hard` | **0** |
| v1.2.5 / v1.2.6 community (1.1 lineage) | `Easy`, `Intermediate`, `Hard` | **0** |

The prefixes are the difficulty and career tiers — **E**asy, **I**ntermediate,
**H**ard, **C1**–**C4** — matching `easy.res`, `medium.res`, `hard.res` and
`career1.res`–`career4.res`. So the RC shipped with an unfilled name slot per driver
per tier, 112 of them, and the release build has no such block at all.

This is independent of the string-table and canary evidence above, and it points the
same way: the `race.bin` sitting unused on the v1.0 disc is the **finished** build,
and the one the disc actually runs is the unfinished one.

---

## 7. Black renders as transparent, and it depends on the graphics card ✅ CONFIRMED IN GAME

The symptom is the same wherever it appears: **holes where black should be.** Speckled see-through
patches around the stock Viper's cockpit gauges. A black direction arrow that reads as a gap in its
sign on Sunset Mesa. See-through bands along the dark flank of a car. Nothing about it looks like a
texture problem — it looks like missing geometry, which is what sent a long stretch of this project
chasing winding order and backface culling before the cause turned up.

**The cause is the transparency marker being honoured in textures that never asked for it.** A `.tex`
stores RGB565, and a texel whose decoded colour is exactly black means "transparent". That is a real,
intended feature for `flags=0x01` colorkey textures — it is what makes Sunset Mesa's `cactus.tex`
cactus-shaped instead of a rectangle. The defect is that it applies to `flags=0x00` **opaque** textures
as well, where the flag says nothing should be keyed and the artists put ordinary black.

Exactly two raw values decode to black — `0x0000` and `0x0020`, because green's 6-bit field has an
insignificant low bit. The full rule, the evidence for it, and the correction to an earlier
over-wide version are in the format reference:
[§4.5 `.tex` — modding gotcha](file-formats.md#45-tex---tex-texture---confirmed-opaque-colorkey-mip-chain-layout-full-alpha--well-supported).

**Why it is a runtime note and not just a format one:** the same bytes render differently on AMD and
Nvidia hardware. Reported from running the game on both cards. So the file alone does not determine
what you see, and two people can disagree about whether an install is broken while looking at
identical data. Colour-key transparency was a Direct3D *render state* in 1998 that modern drivers
only emulate, and vendors emulate it differently — but whether the fault sits in the driver keying
black unconditionally, or in the game leaving that render state enabled, is **not resolved**.

**It is still fixable in data.** The driver decides whether black is keyed; the file decides whether
any texel is black for it to key. `vrmod dekey <install>` lifts every such texel to `0x0040` — RGB
`(0, 8, 0)`, indistinguishable from black on screen and not the marker — across an install:

- **1,162,454 texels in 21 of the 26 shipped assets** on a retail `Data` folder.
- Colorkey (`0x01`) and alpha (`0x02`/`0x03`) textures are left byte-identical; keying is the point in
  those, and sweeping `cactus.tex` would turn every cactus into a solid rectangle.
- Files are patched in place at byte offsets, never re-serialised, so nothing but a lifted texel moves.
- Reversible via `--revert`; `doctor` reports it at INFO (not a warning — it is only a defect if your
  card keys it) and offers the sweep as a fix action.

**Untested prediction:** on an AMD card the sweep should be a *visual* no-op, because nothing was being
keyed there to begin with. If it changes anything visible on AMD, the model above is wrong.

---

## 8. The engine has a debug HUD, and it writes a log ✅ CONFIRMED IN GAME

Both were shipped in the retail build and neither is mentioned anywhere in the game,
its manual, or the community's twenty-five years of documentation. Found by pressing
number keys while driving.

### 8.1 The overlay pages

**Number keys** cycle overlay pages while driving. Confirmed by observation, with the
engine's own format strings from `race.bin` beside each:

| Key | Page | Shows |
|-----|------|-------|
| `2` | **Physics** | telemetry, below |
| `3` | **Info** | the driving-line tool. Sub-keys are mnemonic: `H` help, `S` save ("global line"), `L` **line** — draws the `.ili` as a dotted path ahead of the car with a per-node readout |
| `4` | **LOD Factor** | the LOD multiplier, plus `FOG` and `LIGHT` toggles |
| `5` | **HUD off** | hides the overlay entirely — which is why it read as a blank page |
| `6` | **TV Camera** | `TV Camera: 0/7` with the camera's position and angles |

The LOD page documents its own controls in the string table:

```
?LOD Factor:  %4.1f
[=down ]=up '=1.0
```

`[` steps it down, `]` up, `'` resets to 1.0. **This is the only way to inspect a
generated LOD chain without driving away from the car** — relevant to `vrmod`'s LOD
generator, whose output was previously only visible at whatever distance the engine
chose to swap levels.

The Physics page reads, field for field:

```
R: %1.0fF  E: %1.0f                                   two temperatures
s: %5.2f t: %5.2f b: %5.2f c: %5.2f                   raw input axes:
                                                      steer, throttle, brake, clutch
%3.0f MPH  V:%3.0f MPH %5.0f RPM (%c) DIST %4.0f'     speed, velocity, revs,
                                                      GEAR, distance in feet
LAT %5.2f G  LONG %5.2f G  TOT %5.2f G AERO %5.2f G   four-axis accelerometer
(%6.1f %6.1f %6.1f)                                   world position
%1.0f                                                 printed four times, one per
                                                      wheel, as coloured discs
```

A separate **aero** G channel is a notable thing for a 1998 title to be computing, and
it is sitting behind an undocumented keypress. The per-wheel discs are most likely tyre
temperature — the only other Fahrenheit value on the page is the `R:` line — but that is
inference, not measurement; watching them under cornering load would settle it.

`L` renders the racing line as a dotted trail along the road with a live readout
(`n 6.500 m    110.000 mph`), which makes the Info page a **ground-truth oracle for the
`.ili` format**: park on a waypoint, read the page, compare against the parsed record.
Nothing else can settle what those fields mean. See `ili.py` for the first thing it
already calls into question -- the page reports metres and mph, while the parser
documents feet.

The TV Camera page is directly useful for track authoring. It reports the live camera
position and angles in the same units `camera.tab` stores, so a camera can be placed by
flying to the spot and reading the numbers off. Note that **`camera.tab` is the same STAB
container as `cockpit.tab` but with SEVEN fields per record and a leading type name**
(`FIXED`, `PAN_ZOOM`, `CHASE` — the engine's own `fixed`/`pan_zoom`/`chase`):

```
FIXED     194  4.5  -196   2  33  -9
PAN_ZOOM  185  0.4  -160   0.8 ...
```

`cockpit_tab.parse()` hardcodes four fields and rejects it with
`unexpected fieldsPerRecord 7`.

### 8.1b Free-roam: the Blimp camera ✅ CONFIRMED IN GAME

**F12** drops into a free-flying camera, steered with the numpad. It is not a debug
leftover — the engine ships **twelve named camera views** in its UI string table:

```
Cockpit  Bumper  Rear  Chase  NearChase  FarChase  RearChase
Overhead  Aerial  Blimp  TV  Chassis
```

`Chassis` is the F3 X-ray. `Blimp` is this one, and it has real error handling behind it
(`Can't scan blimp jump location, but will go to track.`), which is also what finally
identifies the engine's `-location` command-line flag — see §2, where this table had it
wrong as a multiplayer parameter.

For track work this is the most immediately useful thing in §8: it flies anywhere, and
page `6` reports the camera's position and angles in `camera.tab`'s own units while it
does so. Fly to a spot, aim at what you want framed, read the six numbers off the HUD,
and that is a `camera.tab` record.

**The controls ✅ CONFIRMED IN GAME:**

| Key | Does |
|-----|------|
| numpad `4` / `6` | **yaw** left / right — the view swings round in place and the world sweeps past horizontally. A *pan*, in camera terms |
| numpad `8` / `2` | **pitch** — **inverted**: `8` looks *down*, `2` looks *up*. A *tilt* |
| numpad `7` / `9` | **roll** — the horizon rotates clockwise / anticlockwise. A *dutch angle* |
| numpad `1` / `3` | **strafe** left / right — the camera slides sideways without turning. A *truck* or *crab* |
| `A` / `Z` | **dolly** in / out — moves the camera along its view axis, rather than a true zoom, which would narrow the field of view and leave the position alone. Page `6`'s position readout is the way to be certain |

That pitch inversion is worth knowing before you spend twenty minutes fighting it.

This page is also what settled `camera.tab`'s rotation format (§4.3 of the format
reference). Holding a heading while pitching up and down shows the first and third
fields moving in equal and opposite amounts — the signature of an axis-angle vector
rather than three Euler angles, which is not something the shipped data alone makes
obvious.

### 8.2 The log ✅ CONFIRMED — it is running right now

The engine writes to `log\` beside the executable, unprompted, on a stock install:

| File | Contents |
|------|----------|
| `log.log` | the main diagnostic stream |
| `timer.log` | a frame-timing histogram, `[%+2.2d]: %d [avg: %d]` |
| `except.log` | exceptions |
| `career.log` | career progress |

The string table also names `log.cfg` and a `logger` with installable hooks
(`LogUninstallHook: 0 of %d funcs matches 0x%x`), so the stream is probably
configurable; no `log.cfg` ships, and what it accepts is not known.

**`log.log` names every asset the engine fails to resolve**, which is ground truth of a
kind nothing outside the engine can produce:

```
ResourceGet("airhawk1.tex") returning NULL!
tex not found: airhawk1.tex
```

That example is not a broken conversion — no mesh references `airhawk1.tex`. It is the
**AI paint-slot probe**: the engine asks for `<prefix><N>.tex` per grid slot, stock
`viper.car` answers with `viperd1..4.tex`, and a car that ships none gets one identical
skin across the whole AI field. That limitation was already described in the format
reference from watching races; here the engine states it outright, by name, once per slot.

It also logs the video path (`vid: 16 meg card`, triple buffering, `DDERR_WRONGMODE`
surface losses), object counts, achievable frame rate, and missing setup files
(`Can't open Config\setups\bemidji.csu--using default`).

**This is better evidence than static analysis** for anything that resolves at load time.
`doctor` reasons about missing assets by inspecting archives; the log says what the engine
actually asked for and did not get.

### 8.3 Things named in the binary that never shipped

Sitting beside the overlay strings, unexercised by any UI:

- **A settings block** with sections `GLOBAL MULTI SOUND CONTROL GAME PHYSICS` — the same
  format as `options.def`, which already carries `[GX] [SOUND] [GLOBAL] [CONTROL]` but has
  no `[GAME]` or `[PHYSICS]`. Its keys are `car_index`, `show_car_status_info`,
  `throttle_boost`, `grip_boost`, `gravity_factor`, `horn_ball`, `no_walls`,
  `pave_the_world`. The last three are the shipped HACKS tab; **the first four have never
  surfaced anywhere.** Whether they are read from a `.def` on a release build is untested.
- **A ghost-car system**: `.gcf` files under `%sghostcar\`, `ghost.tab`, `ghost.best`,
  version/track/realism matching, and a `GhostCar` entry in the physics object taxonomy
  (`PhobStatic Obstacle Wobble CheckPoint PlayCar AICar NetCar GhostCar`). No ghost feature
  exists in the game.
- **Two more driving-line extensions**, `.ilq` and `.ilg`, beside the known `.ili`. Tracks
  ship `default.ili` and `rdefault.ili` (forward and reversed) and nothing else, so these
  are likely what the Info page's "save"/"global line" writes.
- `\coffee\vc\ghosts\` — a hardcoded UNC path to a developer machine named *coffee*.
- **Music.** The binary carries `music_volume` (in `menu:moptions.obj`, so a real options
  entry) and a `?music_test@@YAXXZ` in the sound module — and there is no music. Nothing in
  the game ships any: the largest audio in any archive is `road1.sfx` at 177,710 bytes, the
  road noise, and no `.res` holds a single file long enough to be a song. Nor is it CD
  audio: `race.exe` imports `winmm` for `timeGetTime` and `timeKillEvent` only, with no
  `mciSendStringA`, `mciSendCommandA`, `waveOutOpen` or `auxGetVolume` anywhere in it, so
  there is no path by which it could play a Redbook track.

  Which makes `road1.sfx` the only way to get music into this game, and is why a car's own
  road noise is worth overriding: it is the one continuously-playing sound that accepts
  arbitrary length (see file-formats.md §3.5). It pitch-shifts with road speed, which is
  either a bug or a feature depending on the track.

### 8.4 broske was on the original team

`race.bin` contains the assertion message:

```
BGHook(): (!inserted) ?!?!  Tell broske "You're lame."
```

This is in the **shipped 1998 binary**, not a community patch. The patch-lineage note has
broske as the author of the 1.2.3 "developer gift" build that every community `race.bin` is
hex-edited from; this places him inside the engine source years earlier, writing assertions
against his own subsystem. The same region carries `Can't create SCO! Grak! This is
impossible!` and a bare `dolt.`

---

## 9. A surface above the road launches the car ✅ CONFIRMED IN GAME

Put a drivable surface above the road, and a car driving under it is thrown into the air.
The first time this turned up it was an accident: the edge of a generated bridge deck,
9 m above the water beside it, launched any car that drove into it. It was then built on
purpose as a set of **launch pads**, over three test tracks in the bemidji slot:

| set | pads | what happened in game |
|---|---|---|
| 1 | 0.25–8 m tall, 10 m long, full road width | every pad launches; the launch grows with height |
| 2 | 10–65 m tall, 10 m long, outer half and then outer quarter of the road | still launches, with diminishing returns; a launched car can come down **on top of** the pad and sit there |
| 3 | 20 m tall, 2.5–160 m long, outer quarter | longer pads keep pushing for longer; driving through fast only glances a pad, slowing down gives a bigger launch |

### How it works: the wheels take whatever surface is at their position ✅ CONFIRMED (disassembly + in game)

From `Wheel::Update` (`0x448a60` in the symbolised 1998 build, `physics:wheel.obj`):

1. Each tick, each wheel asks `TerrainGetHeight` for the surface at its own (x, z). It gets
   the one surface the collision tree holds there, **even when that surface is above the
   wheel**. The only rejection is a surface steeper than a normal·up of 0.1 (about 84°), plus
   surface code 14 (meaning not checked).
2. The distance from the wheel down to that surface becomes suspension compression. A
   surface above the wheel reads as a very large compression, and compression is **clamped
   at the suspension's travel + 3.0 m**.
3. From travel − 0.0254 m (1 inch) onwards a bump stop adds its own force, and the wheel also
   applies a bump-stop impulse (`get_impulse_magnitude` → `PhobDyno::ApplyImpulse`).
4. The wheel's total upward force is **capped at 17,800 N** (`0x468b1000`) before
   `Car::ApplySuspensionForce` applies it.
5. With damage on, a bump-stop impulse above **2,892.5** (`0x4534c7ff`) flags the wheel broken.

So every pad pushes equally hard in any one tick, whatever its height. What differs is how many
ticks it pushes for. The push lasts while a wheel is under the pad's footprint **and** below its
top:

- **Crossing speed** sets the time over the footprint (length ÷ speed): slow = bigger launch.
- **Height** is only a ceiling. Once the car rises past the top, the push stops, and if it is still
  over the footprint it lands on the pad. Past the point where a car can clear the top while
  crossing, extra height adds nothing: set 2's diminishing returns.
- **Length** sustains the push, up to that same ceiling: set 3.
- **Width** decides whether the car lifts level. A pad narrower than the car pushes one side's
  wheels only, and the roll that follows throws the car off before a long lift can build. Set 3's
  5 m strips did exactly that.

Rough scale, as an estimate not a measurement: four wheels at the cap on a Viper-weight car is
about 3.8 g net upward. A car that rises all the way through a pad of height H leaves its top at
about √(2·37·H) m/s and climbs roughly 3.8 × H further.

⚪ **Open: why Ridge Valley's bridge is a wall and not a launch.** Driving into the side of the
big bridge on `hastings` stops the car dead, with the deck ~50 m above the water. Height alone
doesn't explain it: set 2's 50 m and 65 m pads both launch. What differs there is unchecked,
e.g. its surface codes and the two long `.sol` rail boxes along the deck.

### Keep AI cars off launch pads, or the game crashes 🟡 WELL-SUPPORTED

Set 1 spanned the whole road, and a race crashed with an AI car in the trace:

```
EXCEPTION: Task "BGTask" @ 00421883 : EXCEPTION_ACCESS_VIOLATION
trace: byte 0x43 of "?advance_bead@IdealLine@@IAEXXZ"
trace: byte 0x45 of "?update_car_info@IdealLine@@QAEXABUPoint2D@@0@Z"
trace: byte 0x46 of "?update_line_info@AICar@@IAEXXZ"
trace: byte 0x13f of "?Update@AICar@@UAEXXZ"
```

An AI car that goes off course is put back by `AICar::reset` / `teleport_to_track`. That calls
`IdealLine::reset_bead_position` on the car's own racing line, and the pointer it stores can end up
null. The next `advance_bead` then reads through it. The lookup (see file-formats.md §4.2.3 for the
same function at race start) goes null in two ways:

- no segment claims the point, which for a finite position only happens exactly on a segment
  boundary; or
- the Newton walk along the line that follows passes **10,000 m** and gives up. Simulated on the
  test track, that needs a car more than ~5 km from the line; stock kenyon behaves the same.

So the car's position had gone non-finite (NaN or infinity) or kilometres off, not merely a long
way away. It is an AI car, not the player: `PlayCar` and `AICar` are separate subclasses of `LocalCar`,
and the player's car never runs this code. Which contact produces the non-finite
value is not pinned down (the bump-stop impulse divides; so does the wheel-break path). The crash
stopped once the AI was kept off the pads: moving the pads to the outer half of the road, with the
AI's line shifted 5 m into the inside lane, held for 0.25–8 m pads. At 10–65 m that crashed again,
and the outer quarter (10 m clear of the AI's line) has run without a crash since.

### Building one

A launch pad is two meshes over a hole in the road:

- **The pad:** a quad raised to the pad's height, with the ROAD surface code, textured with a
  colour-keyed texture that is entirely black, so it collides and draws nothing. The collision
  tree holds one surface per point, so the road faces under it have to be cut out, and any part of
  that cut the pad doesn't cover put back as road.
- **The marking:** a quad just above the road, drawn but not solid (NO_COLLISION), so drivers can
  see where the pad is.

Keep it off the AI's line, with room to spare: the AI line is generated from the centreline,
so shift the centreline passed to `trackbuild.assemble()` over the stretch with pads.
