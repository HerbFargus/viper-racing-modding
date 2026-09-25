"""Tune the horn-ball -- the "hacks" toy that fires a ball out the front
of your car when you honk: how hard, how often, how big, and where it appears.

Viper Racing has a set of joke "hacks" toggled from the **HACKS tab in Options**,
which sits in the normal tab row beside GRAPHICS, SOUND, CONTROLS and DRIVING AIDS.
It is NOT hidden and needs no code: confirmed in game on both retail pressings, v1.0
and v1.1. The tab offers Horn Ball, Pave The World and Wheelie (with a key binding),
plus a vehicle picker listing the five stock cars. The horn-ball's two feelings are set by two floats
the launch routine reads: how fast the ball is thrown, and how long you must
wait between throws. This lets you dial both -- a gentle lob every couple of
seconds (stock) up to a rapid-fire cannon.

WHAT IT CHANGES, EXACTLY. Two 32-bit floats in the engine's .rdata
(race.exe on v1.0, race.bin on v1.1 and the community builds):

    speed     the velocity added to the ball in the car's facing direction
              (and the speed cap). Stock 31.111. Exposed here as a MULTIPLIER
              of that stock value, so 1.0x is stock and 5.0x throws five times
              as hard.
    cooldown  seconds the game enforces between throws. Stock 2.0. Smaller =
              fire more often.

Nothing else moves -- the two writes never change the file's length, and they
are independent of the compatibility patch set (which touches code, not these
constants), so the two features coexist.

LOCATED BY SIGNATURE, NEVER BY OFFSET. Like every other patch here, the two
constants are found by the instructions that reference them, because the
offsets move between builds:

  * cooldown: the launch routine compares `now - cooldown` against the ball's
    last-launch timestamp at [ball+0x478]. That `fcomp dword [ebx+0x478]` is a
    unique anchor; the `fsub dword [const]` right before it names the cooldown.
  * speed: the launch routine does `fmul dword [const]; fadd dword [ball+0x238]`
    (adding the boost into the ball's velocity). The `fadd dword [ebx+0x238]`
    anchors it; the `fmul dword [const]` immediately before names the speed.

SIZE is the third knob, and it lives somewhere else. The ball is not loaded from
any file: `create_ball` builds its PhobData on the stack, tagged 'BALL', and
Ball::Ball makes field +0x24 times 0.0254 the radius of its collision sphere --
the ball's physics is authored in INCHES. Stock is 18.0, a 0.457 m radius, half
as big again as the drawn ball.mod. It is an immediate operand,

    6A 40                push 0x40
    C7 44 24 28 <f32>    mov dword [esp+0x28], 18.0

found here by that pair after the unique `mov dword [esp], 'BALL'` tag store,
so it is located by signature like the others and changes one float in the
code section. Only the COLLISION grows. The engine never reads the radius when
drawing: create_ball hands `ball.mod` to a plain ModelObject, whose Draw is
mrModelDraw(model, frame) with no scale anywhere. So what you see is whatever
ball.mod is loaded, at the size it was built -- which is why the model is its
own knob (below).

MODEL SIZE scales the drawn ball.mod itself, and applies to EVERY horn ball the
install has: the shared one in race.res that stock cars and most mods fall back
on, and every car (in Data/ or Disabled/) that carries its own. A ball that
changed on only some cars would look like the slider doing nothing. It scales
each model about its own origin, which is where the collision sphere is
centred, and it writes only the vertex position floats, in place: the archive
is not rewritten, because read()/to_bytes() does not round-trip every real
archive (a stock-named Viper.car doesn't). The first change files each model's
original payload in Backups/ as `<archive>.hornball-model`, and every scale is
taken from that original, so 2x then 3x is 3x, not 6x, and 1x restores the
original bytes exactly. A model that has since been replaced (a new ball.mod
imported through the Parts drawer) no longer matches its filed original scaled
by any factor, so it becomes the new original rather than being overwritten.
Those files hold one member's payload, not a whole archive, so they are NOT
registered as restorable archive backups: nothing may ever copy one over the
archive it came from.

MASS is the fourth, stored beside the radius in the same record. create_ball
writes the phob's mass into field +0x08 -- 3000 -- with

    C7 44 24 08 <f32>    mov dword [esp+0x08], 3000.0

the only store of that shape between the 'BALL' tag and the radius, 0x4b bytes
after the tag in every build on hand (retail v1.0 race.exe, v1.1 race.bin, and
the 1.2.4/1.2.5/1.2.6 community builds). It is the same field `obj obstacle`'s
last number fills (parse_obstacle, which builds the inertias as size^2 x 10.75 x
mass): track obstacles written with a mass of 4 behaved like beach balls. Only
the mass is patched; the three inertias beside it (5000) share their register
with a ball-only contact value, so they are left alone -- a heavier ball spins
a little more freely, and hits harder.

THE SPAWN POINT is set separately, and size never moves it. Ball::Throw places
the ball 3.5 m ahead of the car's origin along its forward axis and 0.5 m above
it, two .rdata floats that nothing else in the image references. A bigger ball
spawned there starts partly inside the road, and the game shoves it out: seen in
game, a 3x ball at the stock spawn bounces as it launches. That is a legitimate
effect for a mod, so the two are independent knobs. Deeper launches harder: at the
stock height a 2-3x ball arcs like a catapult and a 10x ball is fired off the map;
sunk entirely below the road (under about -0.80 m for a stock ball) it falls
through instead. See runtime.md section 3. clear_spawn(size) gives the
offsets that keep a ball's back and bottom where a stock ball's are -- clear of
the car and the road -- for anyone who wants it to fly level. They are read by

    8B 44 24 18  D8 05 <abs32>    mov eax, [esp+0x18]; fadd dword [ahead]
    D9 45 28     D8 05 <abs32>    fld [ebp+0x28];      fadd dword [up]

each unique in the whole image, in race.exe and race.bin alike.

REVERSIBLE: the race.bin changes are six floats with known stock values, so
`reset()` simply writes them back, and puts every ball.mod back to its original. Builds that don't
carry the horn-ball launch code (or a future build whose launch differs) fail
the signature and report unavailable rather than guessing.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import archive, backups, pe, safewrite

RACE_BIN = "race.bin"
IMAGE_BASE = 0x400000

# Stock launch constants. All three confirmed community builds (v1.2.4/5/6) and
# the original share these -- they live in the same launch routine.
STOCK_SPEED = 31.11111068725586      # velocity boost + cap
STOCK_COOLDOWN = 2.0                 # seconds between throws

STOCK_RADIUS_IN = 18.0              # collision radius, inches (0.457 m)
STOCK_MASS = 3000.0                  # phob mass (the field `obj obstacle`'s last number sets)
STOCK_AHEAD = 3.5                    # spawn, metres ahead of the car's origin
STOCK_UP = 0.5                       # spawn, metres above it
INCH = 0.0254                        # Ball::Ball's scale from inches to metres

# Sane slider bounds. Speed and size are multipliers of stock; cooldown is seconds.
SPEED_MIN, SPEED_MAX = 0.25, 15.0
COOLDOWN_MIN, COOLDOWN_MAX = 0.05, 5.0
SIZE_MIN, SIZE_MAX = 0.25, 10.0
MASS_MIN, MASS_MAX = 0.1, 20.0       # x stock: 300 to 60,000
MODEL_MIN, MODEL_MAX = 0.25, 10.0    # x each ball.mod's own original size
AHEAD_MIN, AHEAD_MAX = -30.0, 30.0   # spawn, metres ahead of the car's origin; negative is
                                     # BEHIND it -- Ball::Throw just adds the value, so a ball
                                     # spawned behind still leaves at car speed + boost and
                                     # rolls up into the car from behind
UP_MIN, UP_MAX = -2.0, 10.0          # spawn, metres above it

# Instruction anchors (see module docstring). x87: D8 /r with a mod=00 disp32
# form is `<op> dword [abs32]`; /5=fsub (25), /1=fmul (0D).
_COOLDOWN_ANCHOR = bytes.fromhex("d89b78040000")   # fcomp dword [ebx+0x478]
_SPEED_ANCHOR = bytes.fromhex("d88338020000")      # fadd  dword [ebx+0x238]
_FSUB_ABS = 0x25                                    # fsub dword [abs32]  -> D8 25 <abs32>
_FMUL_ABS = 0x0D                                    # fmul dword [abs32]  -> D8 0D <abs32>
_BALL_TAG_STORE = bytes.fromhex("c74424004c4c4142")  # mov dword [esp+0], 'BALL'
_RADIUS_STORE = bytes.fromhex("6a40c7442428")        # push 0x40; mov dword [esp+0x28], imm32
_RADIUS_WINDOW = 0x80                               # create_ball is short; stock gap is 0x57
_MASS_STORE = bytes.fromhex("c7442408")             # mov dword [esp+0x08], imm32 (stock gap 0x4b)
_AHEAD_LOAD = bytes.fromhex("8b442418d805")         # mov eax,[esp+0x18]; fadd dword [abs32]
_UP_LOAD = bytes.fromhex("d94528d805")              # fld [ebp+0x28];     fadd dword [abs32]


class HornballError(RuntimeError):
    """The horn-ball launch code isn't where this build keeps it."""


@dataclass
class Tuning:
    speed_mult: float        # x stock (1.0 == STOCK_SPEED)
    cooldown: float          # seconds
    speed_raw: float         # the actual float in the binary
    is_stock: bool
    size_mult: float | None = None   # x stock collision radius; None if not locatable
    radius_m: float | None = None    # the collision radius in metres
    spawn_ahead: float | None = None  # metres ahead of the car's origin
    spawn_up: float | None = None     # metres above it
    mass_mult: float | None = None    # x stock mass; None if not locatable
    mass: float | None = None         # the mass itself (stock 3000)
    model_mult: float | None = None   # x the drawn ball.mod's original size; None if none found


# Engine binaries, live one first -- the v1.0 pressing runs race.exe and ships a
# dormant race.bin beside it.
ENGINE_NAMES = ("race.exe", RACE_BIN)


def _race_bin(data_dir: str | Path) -> Path:
    """The engine binary this install actually runs."""
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise HornballError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def _find_const(blob: bytes, anchor: bytes, back: int, op2: int) -> int:
    """File offset of the float an anchored `D8 <op2> <abs32>` instruction reads.

    Scans back up to `back` bytes from `anchor` for the `D8 <op2>` opcode, reads
    its absolute address operand, and converts that VIRTUAL address to a file
    offset through the section table.

    The conversion used to be `va - IMAGE_BASE`, which is the RVA, not the
    offset: .rdata's PointerToRawData sits 0xe00 below its VirtualAddress in
    race.bin and 0x1600 below it in race.exe. That landed a few kilobytes past
    the real constants -- still inside .rdata, so every read and write succeeded
    and returned plausible floats, while the game went on reading the untouched
    originals. See pe.va_to_offset.
    """
    a = blob.find(anchor)
    if a < 0:
        raise HornballError("horn-ball launch signature not found in this build")
    for i in range(a - back, a):
        if blob[i] == 0xD8 and blob[i + 1] == op2:
            va = struct.unpack_from("<I", blob, i + 2)[0]
            off = pe.va_to_offset(blob, va)
            if off is not None and off <= len(blob) - 4:
                return off
    raise HornballError("horn-ball constant not found near its launch signature")


def _offsets(blob: bytes) -> tuple[int, int]:
    """(cooldown_offset, speed_offset) located by signature."""
    return (_find_const(blob, _COOLDOWN_ANCHOR, 24, _FSUB_ABS),
            _find_const(blob, _SPEED_ANCHOR, 12, _FMUL_ABS))


def _size_offset(blob: bytes) -> int | None:
    """File offset of create_ball's radius float, or None if this build differs.

    Requires the 'BALL' tag store to be unique and the radius store to follow it
    closely; anything else means a layout this was not written against, and
    guessing would write into code.
    """
    t = blob.find(_BALL_TAG_STORE)
    if t < 0 or blob.find(_BALL_TAG_STORE, t + 1) >= 0:
        return None
    r = blob.find(_RADIUS_STORE, t, t + _RADIUS_WINDOW)
    if r < 0:
        return None
    off = r + len(_RADIUS_STORE)
    value = struct.unpack_from("<f", blob, off)[0]
    if not (STOCK_RADIUS_IN * SIZE_MIN * 0.999 <= value <= STOCK_RADIUS_IN * SIZE_MAX * 1.001):
        return None
    return off


def _mass_offset(blob: bytes) -> int | None:
    """File offset of create_ball's mass float, or None if this build differs.

    The one `mov dword [esp+0x08], imm32` between the unique 'BALL' tag store and
    the radius store, holding a plausible mass. Two, none, or an implausible value
    means a layout this was not written against.
    """
    t = blob.find(_BALL_TAG_STORE)
    if t < 0 or blob.find(_BALL_TAG_STORE, t + 1) >= 0:
        return None
    r = blob.find(_RADIUS_STORE, t, t + _RADIUS_WINDOW)
    if r < 0:
        return None
    hits = [i for i in range(t, r) if blob[i:i + 4] == _MASS_STORE]
    if len(hits) != 1:
        return None
    off = hits[0] + len(_MASS_STORE)
    value = struct.unpack_from("<f", blob, off)[0]
    if not (STOCK_MASS * MASS_MIN * 0.999 <= value <= STOCK_MASS * MASS_MAX * 1.001):
        return None
    return off


def _spawn_offsets(blob: bytes) -> tuple[int, int] | None:
    """File offsets of Ball::Throw's (ahead, up) spawn floats, or None.

    Each load must be unique in the image and sit inside the launch routine,
    just after the speed anchor -- the same routine, so the same build.
    """
    a = blob.find(_SPEED_ANCHOR)
    if a < 0:
        return None
    out = []
    for pat in (_AHEAD_LOAD, _UP_LOAD):
        h = blob.find(pat)
        if h < 0 or blob.find(pat, h + 1) >= 0 or not 0 < h - a < 0x120:
            return None
        va = struct.unpack_from("<I", blob, h + len(pat))[0]
        off = pe.va_to_offset(blob, va)
        if off is None or off > len(blob) - 4:
            return None
        out.append(off)
    return out[0], out[1]


def _tuning(blob: bytes) -> Tuning:
    co, sp = _offsets(blob)
    cd = struct.unpack_from("<f", blob, co)[0]
    speed = struct.unpack_from("<f", blob, sp)[0]
    mult = speed / STOCK_SPEED
    so = _size_offset(blob)
    radius_in = struct.unpack_from("<f", blob, so)[0] if so is not None else None
    size = radius_in / STOCK_RADIUS_IN if radius_in is not None else None
    sp_off = _spawn_offsets(blob)
    ahead, up = ((struct.unpack_from("<f", blob, sp_off[0])[0],
                  struct.unpack_from("<f", blob, sp_off[1])[0]) if sp_off else (None, None))
    mo = _mass_offset(blob)
    mass = struct.unpack_from("<f", blob, mo)[0] if mo is not None else None
    is_stock = (abs(speed - STOCK_SPEED) < 1e-3 and abs(cd - STOCK_COOLDOWN) < 1e-4
                and (size is None or abs(size - 1.0) < 1e-6)
                and (mass is None or abs(mass - STOCK_MASS) < 1e-3)
                and (ahead is None or (abs(ahead - STOCK_AHEAD) < 1e-5
                                       and abs(up - STOCK_UP) < 1e-5)))
    return Tuning(speed_mult=mult, cooldown=cd, speed_raw=speed, is_stock=is_stock,
                  size_mult=size,
                  radius_m=radius_in * INCH if radius_in is not None else None,
                  spawn_ahead=ahead, spawn_up=up,
                  mass_mult=mass / STOCK_MASS if mass is not None else None, mass=mass)


# ---------------------------------------------------------------- the drawn model
BALL_MOD = "ball.mod"
MODEL_BACKUP = ".hornball-model"     # one member's payload: never a restorable archive backup
_VERTS = 0x28                        # payload offset of the vertex block (mod.VERTEX_BLOCK_START)
_STRIDE = 32                         # x, y, z, nx, ny, nz, u, v


def ball_archives(data_dir: str | Path) -> list[Path]:
    """Every archive that could supply a horn ball: the shared .res files, and every
    car in Data/ and Disabled/. Backups never qualify -- they aren't *.res/*.car."""
    d = Path(data_dir)
    found = []
    for folder, pats in ((d, ("*.res", "*.car")), (d / "Disabled", ("*.car",))):
        if folder.is_dir():
            for pat in pats:
                found += sorted(folder.glob(pat), key=lambda q: q.name.lower())
    return [f for f in found if f.is_file()]


def _positions(payload: bytes) -> list[tuple[float, float, float]]:
    n = struct.unpack_from("<i", payload, 0)[0]
    return [struct.unpack_from("<3f", payload, _VERTS + i * _STRIDE) for i in range(n)]


def _with_positions(payload: bytes, pos) -> bytes:
    out = bytearray(payload)
    for i, (x, y, z) in enumerate(pos):
        struct.pack_into("<3f", out, _VERTS + i * _STRIDE, x, y, z)
    return bytes(out)


def _scale_of(current: bytes, original: bytes) -> float | None:
    """The factor `current` is `original` scaled by, or None if it isn't a scaled copy
    at all (a different model, or anything but the positions changed)."""
    if len(current) != len(original):
        return None
    a, b = _positions(current), _positions(original)
    if len(a) != len(b) or not b:
        return None
    if _with_positions(current, b) != original:            # anything else differs
        return None
    ref = max(b, key=lambda q: abs(q[0]) + abs(q[1]) + abs(q[2]))
    big = max(abs(ref[0]), abs(ref[1]), abs(ref[2]))
    if big < 1e-9:
        return None
    k = next(ca / ra for ca, ra in zip(a[b.index(ref)], ref) if abs(ra) == big)
    if k <= 0:
        return None
    tol = 1e-4 * max(1.0, big * k)
    for (x, y, z), (ox, oy, oz) in zip(a, b):
        if abs(x - ox * k) > tol or abs(y - oy * k) > tol or abs(z - oz * k) > tol:
            return None
    return k


def _model_state(f: Path, data_dir: Path) -> tuple[bytes, int, int, bytes, float] | None:
    """(archive bytes, payload offset, size, original payload, current scale) for one
    archive's ball.mod, or None if it carries none."""
    data = f.read_bytes()
    try:
        span = archive.payload_span(data, BALL_MOD)
    except ValueError:
        return None
    if span is None:
        return None
    off, size = span
    current = data[off:off + size]
    bk = backups.locate(f, MODEL_BACKUP, data_dir)
    original = bk.read_bytes() if bk else None
    k = _scale_of(current, original) if original is not None else None
    if k is None:                              # never scaled, or since replaced: this IS the original
        return data, off, size, current, 1.0
    return data, off, size, original, k


def model_available(data_dir: str | Path) -> bool:
    """True if any archive in the install carries a ball.mod to scale."""
    d = Path(data_dir)
    return any(_model_state(f, d) is not None for f in ball_archives(d))


def model_scale(data_dir: str | Path) -> float | None:
    """The drawn ball's size as a multiple of its original: race.res's shared ball if
    it has one, else the first car that carries its own. None if there's none."""
    d = Path(data_dir)
    shared = [f for f in ball_archives(d) if f.name.lower() == "race.res"]
    for f in shared + [f for f in ball_archives(d) if f not in shared]:
        st = _model_state(f, d)
        if st is not None:
            return st[4]
    return None


def set_model_scale(data_dir: str | Path, mult: float) -> list[Path]:
    """Scale every horn ball's drawn model to `mult` x its original, about its own
    origin. Returns the archives written. Only the vertex position floats change."""
    d = Path(data_dir)
    m = max(MODEL_MIN, min(MODEL_MAX, float(mult)))
    written = []
    for f in ball_archives(d):
        st = _model_state(f, d)
        if st is None:
            continue
        data, off, size, original, k = st
        if abs(k - m) < 1e-6:
            continue
        bk = backups.locate(f, MODEL_BACKUP, d)
        if bk is None or bk.read_bytes() != original:
            safewrite.write_atomic(backups.path_for(f, MODEL_BACKUP, d), original)
        payload = original if m == 1.0 else _with_positions(
            original, [(x * m, y * m, z * m) for x, y, z in _positions(original)])
        out = bytearray(data)
        out[off:off + size] = payload
        safewrite.write_atomic(f, bytes(out))
        written.append(f)
    return written


def size_available(data_dir: str | Path) -> bool:
    """True if this build's create_ball can be found, so the size can be set."""
    try:
        return _size_offset(_race_bin(data_dir).read_bytes()) is not None
    except HornballError:
        return False


def mass_available(data_dir: str | Path) -> bool:
    """True if this build's create_ball mass store can be found, so the mass can be set."""
    try:
        return _mass_offset(_race_bin(data_dir).read_bytes()) is not None
    except HornballError:
        return False


def spawn_available(data_dir: str | Path) -> bool:
    """True if Ball::Throw's two spawn offsets can be found, so they can be set."""
    try:
        return _spawn_offsets(_race_bin(data_dir).read_bytes()) is not None
    except HornballError:
        return False


def clear_spawn(size_mult: float) -> tuple[float, float]:
    """(ahead, up) that keep a ball of this size clear of the car and the road.

    Both stock offsets pushed out by however much the radius grew, so the ball's
    back and bottom sit where a stock ball's do. A 3x ball: 4.41 m ahead, 1.41 m
    up. Its centre -- and so its flight -- is higher by the same amount.
    """
    grow = STOCK_RADIUS_IN * INCH * (float(size_mult) - 1.0)
    return STOCK_AHEAD + grow, STOCK_UP + grow


def available(data_dir: str | Path) -> bool:
    """True if this race.bin carries the horn-ball launch code we can tune."""
    try:
        _offsets(_race_bin(data_dir).read_bytes())
        return True
    except HornballError:
        return False


def read(data_dir: str | Path) -> Tuning:
    """Current horn-ball tuning. Raises HornballError if unavailable."""
    t = _tuning(_race_bin(data_dir).read_bytes())
    t.model_mult = model_scale(data_dir)
    if t.model_mult is not None and abs(t.model_mult - 1.0) > 1e-6:
        t.is_stock = False
    return t


def apply(data_dir: str | Path, *, speed_mult: float | None = None,
          cooldown: float | None = None, size_mult: float | None = None,
          spawn_ahead: float | None = None, spawn_up: float | None = None,
          mass_mult: float | None = None, model_mult: float | None = None) -> Tuning:
    """Write new tuning. Only the given knobs change; the others are left as-is.
    Values are clamped to the slider bounds. Returns the tuning now in the file.
    """
    f = _race_bin(data_dir)
    blob = bytearray(f.read_bytes())
    co, sp = _offsets(blob)
    if size_mult is not None:
        so = _size_offset(blob)
        if so is None:
            raise HornballError("this build's create_ball is not where the size "
                                "patch expects it; speed and cooldown still work")
        m = max(SIZE_MIN, min(SIZE_MAX, float(size_mult)))
        struct.pack_into("<f", blob, so, STOCK_RADIUS_IN * m)
    if mass_mult is not None:
        mo = _mass_offset(blob)
        if mo is None:
            raise HornballError("this build's create_ball mass is not where the patch "
                                "expects it; speed and cooldown still work")
        m = max(MASS_MIN, min(MASS_MAX, float(mass_mult)))
        struct.pack_into("<f", blob, mo, STOCK_MASS * m)
    if spawn_ahead is not None or spawn_up is not None:
        spawn = _spawn_offsets(blob)
        if spawn is None:
            raise HornballError("this build's ball spawn is not where the patch "
                                "expects it; speed and cooldown still work")
        if spawn_ahead is not None:
            struct.pack_into("<f", blob, spawn[0],
                             max(AHEAD_MIN, min(AHEAD_MAX, float(spawn_ahead))))
        if spawn_up is not None:
            struct.pack_into("<f", blob, spawn[1],
                             max(UP_MIN, min(UP_MAX, float(spawn_up))))
    if speed_mult is not None:
        m = max(SPEED_MIN, min(SPEED_MAX, float(speed_mult)))
        struct.pack_into("<f", blob, sp, STOCK_SPEED * m)
    if cooldown is not None:
        c = max(COOLDOWN_MIN, min(COOLDOWN_MAX, float(cooldown)))
        struct.pack_into("<f", blob, co, c)
    safewrite.write_atomic(f, blob)
    if model_mult is not None:
        set_model_scale(data_dir, model_mult)
    return read(data_dir)


def reset(data_dir: str | Path) -> Tuning:
    """Restore the stock ball: 1.0x speed, 2.0s cooldown, 1.0x size and mass, the
    spawn 3.5 m ahead and 0.5 m up, and every ball.mod back to its original."""
    spawn = spawn_available(data_dir)
    return apply(data_dir, speed_mult=1.0, cooldown=STOCK_COOLDOWN,
                 size_mult=1.0 if size_available(data_dir) else None,
                 mass_mult=1.0 if mass_available(data_dir) else None,
                 model_mult=1.0 if model_available(data_dir) else None,
                 spawn_ahead=STOCK_AHEAD if spawn else None,
                 spawn_up=STOCK_UP if spawn else None)
