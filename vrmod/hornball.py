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
code section. Only the COLLISION grows: what is drawn is whatever ball.mod the
car carries, so a model meant to look the part should be scaled to match
(read().radius_m gives the size to build to).

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

REVERSIBLE with no backup file: the changes are five floats, and stock is a known
constant, so `reset()` simply writes the stock values back. Builds that don't
carry the horn-ball launch code (or a future build whose launch differs) fail
the signature and report unavailable rather than guessing.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import pe, safewrite

RACE_BIN = "race.bin"
IMAGE_BASE = 0x400000

# Stock launch constants. All three confirmed community builds (v1.2.4/5/6) and
# the original share these -- they live in the same launch routine.
STOCK_SPEED = 31.11111068725586      # velocity boost + cap
STOCK_COOLDOWN = 2.0                 # seconds between throws

STOCK_RADIUS_IN = 18.0              # collision radius, inches (0.457 m)
STOCK_AHEAD = 3.5                    # spawn, metres ahead of the car's origin
STOCK_UP = 0.5                       # spawn, metres above it
INCH = 0.0254                        # Ball::Ball's scale from inches to metres

# Sane slider bounds. Speed and size are multipliers of stock; cooldown is seconds.
SPEED_MIN, SPEED_MAX = 0.25, 15.0
COOLDOWN_MIN, COOLDOWN_MAX = 0.05, 5.0
SIZE_MIN, SIZE_MAX = 0.25, 10.0
AHEAD_MIN, AHEAD_MAX = 0.0, 30.0     # spawn, metres ahead of the car's origin
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
    is_stock = (abs(speed - STOCK_SPEED) < 1e-3 and abs(cd - STOCK_COOLDOWN) < 1e-4
                and (size is None or abs(size - 1.0) < 1e-6)
                and (ahead is None or (abs(ahead - STOCK_AHEAD) < 1e-5
                                       and abs(up - STOCK_UP) < 1e-5)))
    return Tuning(speed_mult=mult, cooldown=cd, speed_raw=speed, is_stock=is_stock,
                  size_mult=size,
                  radius_m=radius_in * INCH if radius_in is not None else None,
                  spawn_ahead=ahead, spawn_up=up)


def size_available(data_dir: str | Path) -> bool:
    """True if this build's create_ball can be found, so the size can be set."""
    try:
        return _size_offset(_race_bin(data_dir).read_bytes()) is not None
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
    return _tuning(_race_bin(data_dir).read_bytes())


def apply(data_dir: str | Path, *, speed_mult: float | None = None,
          cooldown: float | None = None, size_mult: float | None = None,
          spawn_ahead: float | None = None, spawn_up: float | None = None) -> Tuning:
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
    return _tuning(blob)


def reset(data_dir: str | Path) -> Tuning:
    """Restore the stock ball: 1.0x speed, 2.0s cooldown, 1.0x size, and the
    spawn 3.5 m ahead and 0.5 m up."""
    spawn = spawn_available(data_dir)
    return apply(data_dir, speed_mult=1.0, cooldown=STOCK_COOLDOWN,
                 size_mult=1.0 if size_available(data_dir) else None,
                 spawn_ahead=STOCK_AHEAD if spawn else None,
                 spawn_up=STOCK_UP if spawn else None)
