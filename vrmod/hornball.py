"""Tune the horn-ball -- the "hacks" toy that fires a ball out the front
of your car when you honk.

Viper Racing has a set of joke "hacks" toggled from the **HACKS tab in Options**,
which sits in the normal tab row beside GRAPHICS, SOUND, CONTROLS and DRIVING AIDS.
It is NOT hidden and needs no code: confirmed in game on both retail pressings, v1.0
and v1.1. The tab offers Horn Ball, Pave The World and Wheelie (with a key binding),
plus a vehicle picker listing the five stock cars. The horn-ball's two feelings are set by two floats
the launch routine reads: how fast the ball is thrown, and how long you must
wait between throws. This lets you dial both -- a gentle lob every couple of
seconds (stock) up to a rapid-fire cannon.

WHAT IT CHANGES, EXACTLY. Two 32-bit floats in race.bin's .rdata:

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

REVERSIBLE with no backup file: the change is two floats, and stock is a known
constant, so `reset()` simply writes the stock values back. Builds that don't
carry the horn-ball launch code (or a future build whose launch differs) fail
the signature and report unavailable rather than guessing.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

RACE_BIN = "race.bin"
IMAGE_BASE = 0x400000

# Stock launch constants. All three confirmed community builds (v1.2.4/5/6) and
# the original share these -- they live in the same launch routine.
STOCK_SPEED = 31.11111068725586      # velocity boost + cap
STOCK_COOLDOWN = 2.0                 # seconds between throws

# Sane slider bounds. Speed is a multiplier of STOCK_SPEED; cooldown is seconds.
SPEED_MIN, SPEED_MAX = 0.25, 15.0
COOLDOWN_MIN, COOLDOWN_MAX = 0.05, 5.0

# Instruction anchors (see module docstring). x87: D8 /r with a mod=00 disp32
# form is `<op> dword [abs32]`; /5=fsub (25), /1=fmul (0D).
_COOLDOWN_ANCHOR = bytes.fromhex("d89b78040000")   # fcomp dword [ebx+0x478]
_SPEED_ANCHOR = bytes.fromhex("d88338020000")      # fadd  dword [ebx+0x238]
_FSUB_ABS = 0x25                                    # fsub dword [abs32]  -> D8 25 <abs32>
_FMUL_ABS = 0x0D                                    # fmul dword [abs32]  -> D8 0D <abs32>


class HornballError(RuntimeError):
    """The horn-ball launch code isn't where this build keeps it."""


@dataclass
class Tuning:
    speed_mult: float        # x stock (1.0 == STOCK_SPEED)
    cooldown: float          # seconds
    speed_raw: float         # the actual float in the binary
    is_stock: bool


def _race_bin(data_dir: str | Path) -> Path:
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        raise HornballError(f"no {RACE_BIN} in {data_dir}")
    return f


def _find_const(blob: bytes, anchor: bytes, back: int, op2: int) -> int:
    """File offset of the float an anchored `D8 <op2> <abs32>` instruction reads.

    Scans back up to `back` bytes from `anchor` for the `D8 <op2>` opcode, reads
    its absolute address operand, and converts to a file offset (rawptr==VA for
    every section of this image, so VA - IMAGE_BASE is the offset)."""
    a = blob.find(anchor)
    if a < 0:
        raise HornballError("horn-ball launch signature not found in this race.bin")
    for i in range(a - back, a):
        if blob[i] == 0xD8 and blob[i + 1] == op2:
            va = struct.unpack_from("<I", blob, i + 2)[0]
            off = va - IMAGE_BASE
            if 0 <= off <= len(blob) - 4:
                return off
    raise HornballError("horn-ball constant not found near its launch signature")


def _offsets(blob: bytes) -> tuple[int, int]:
    """(cooldown_offset, speed_offset) located by signature."""
    return (_find_const(blob, _COOLDOWN_ANCHOR, 24, _FSUB_ABS),
            _find_const(blob, _SPEED_ANCHOR, 12, _FMUL_ABS))


def _tuning(blob: bytes) -> Tuning:
    co, sp = _offsets(blob)
    cd = struct.unpack_from("<f", blob, co)[0]
    speed = struct.unpack_from("<f", blob, sp)[0]
    mult = speed / STOCK_SPEED
    is_stock = (abs(speed - STOCK_SPEED) < 1e-3 and abs(cd - STOCK_COOLDOWN) < 1e-4)
    return Tuning(speed_mult=mult, cooldown=cd, speed_raw=speed, is_stock=is_stock)


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
          cooldown: float | None = None) -> Tuning:
    """Write new tuning. Only the given knobs change; the other is left as-is.
    Values are clamped to the slider bounds. Returns the tuning now in the file.
    """
    f = _race_bin(data_dir)
    blob = bytearray(f.read_bytes())
    co, sp = _offsets(blob)
    if speed_mult is not None:
        m = max(SPEED_MIN, min(SPEED_MAX, float(speed_mult)))
        struct.pack_into("<f", blob, sp, STOCK_SPEED * m)
    if cooldown is not None:
        c = max(COOLDOWN_MIN, min(COOLDOWN_MAX, float(cooldown)))
        struct.pack_into("<f", blob, co, c)
    f.write_bytes(blob)
    return _tuning(blob)


def reset(data_dir: str | Path) -> Tuning:
    """Restore the stock throw (1.0x speed, 2.0s cooldown)."""
    return apply(data_dir, speed_mult=1.0, cooldown=STOCK_COOLDOWN)
