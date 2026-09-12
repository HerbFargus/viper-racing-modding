# Viper Racing (1998) — Runtime Behaviour

**Purpose:** what the game *does when it runs*, as opposed to what its files contain: **which detail
level (LOD) you actually see in each camera view** and **how the AI reacts to other cars**, both
measured in-game; the **command-line parameters** the executable accepts, read out of the binary; and
**how world objects are created and freed**, which is what the exit panic reports on; and **what the launcher does before the engine starts**, which is a separate program with its own flags. Companions:
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
| `-location<addr>` | `0x0D1814` | Multiplayer location parameter. ✅ present / 🟡 semantics |
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
MGI\Viper98\
Data\        \Data        %sdata\%s        common.res
"Can't find data directory--Game may not be installed"
```

`common.res` is the file it checks to decide a directory really is the data directory.

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

### Single instance, and a "Canary" ⚪

```
MGI Viper Racing 1998            MGI Viper Racing 1998 Canary
Viper Racing Window
```

Two instance names differing only by the suffix, alongside the `-nocanary` flag. Purpose
unknown; the pairing suggests an alternate build or mode the launcher can be told to
skip.

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

> **Open question, and it decides which retail build is the right test baseline.** Does
> a v1.0 install use `race.bin` at all? Against: its only launcher never mentions a
> `.bin`. For: `race.exe` carries **no version string** while `race.bin` carries
> `"v1.0"`, and the Options screen displays a version — so if a v1.0 install shows
> `v1.0` bottom-right, `race.bin` must be live. Neither `race.bin` is a DLL and neither
> exports anything, so whatever loads it is not `LoadLibrary`.
