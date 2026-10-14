"""The horn ball in career mode, opt-in.

The horn ball is a hack: `HackHornBall` is `hacks on && horn_ball`, and career mode turns the hacks off for as long
as it runs (`CareerDo` calls `HackDisable`), so the ball never throws in a career race whatever the Hacks screen
says. Turned on, this NOPs `HackHornBall`'s first test -- the hacks-on `je`, 2 bytes -- so the ball follows its own
option everywhere: in career races too when the horn ball is on (and also when the hacks as a whole are off). The
other hacks stay off in career. Turned off, the `je` goes back: career as shipped.

    cmp byte [hacks on], 0      80 3d <addr> 00
    je  no                      74 0c          <- 90 90
    cmp byte [horn_ball], 0     80 3d <addr> 00
    je  no                      74 03
    mov al, 1 / ret / no: xor al, al / ret

`HackHornBall`, `HackNoWalls` and `HackPaveTheWorld` are three copies of that 24-byte shape, 0x20 apart, in that
order, sharing the hacks-on flag, in every build (v1.0 race.exe and race.bin, v1.1, 1.2.4 beta, 1.2.5, 1.2.6); the
patch takes the first of the run of three, and refuses a build without exactly one such run. Opt-in from the Game
page's Career panel (or `career --hornball on|off`), carried over when the patch set rebuilds the engine. The port
does the same when it finds the patch (viper-racing-port, root_screens.cpp, port_vrmod_has).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import backups, casefold, safewrite

ENGINE_NAMES = ("race.exe", "race.bin")        # live one first: v1.0 runs race.exe
BACKUP_SUFFIX = ".careerhorn-backup"
ON, OFF, UNKNOWN, MISSING = "on", "off", "unknown", "missing"

STOCK_BYTES, ON_BYTES = b"\x74\x0c", b"\x90\x90"
AT = 7                                         # the je, after cmp byte [hacks on], 0 (7 bytes)
_HACK = rb"\x80\x3d(....)\x00%s\x80\x3d....\x00\x74\x03\xb0\x01\xc3\x32\xc0\xc3"
_STOCK = re.compile(_HACK % re.escape(STOCK_BYTES), re.S)
_ON = re.compile(_HACK % re.escape(ON_BYTES), re.S)


class PatchError(RuntimeError):
    pass


def _engine(data_dir: str | Path) -> Path:
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (f := casefold.find_file(d, n)) is not None:
            return f
    raise PatchError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def site(blob: bytes) -> tuple[int, bool] | None:
    """(HackHornBall's file offset, on?): the first of the one run of three hack getters 0x20 apart that share a
    hacks-on flag (the other two always stock), or None."""
    starts = {}
    for rx, on in ((_STOCK, False), (_ON, True)):
        for m in rx.finditer(blob):
            starts[m.start()] = (m.group(1), on)
    runs = [o for o in starts if o + 0x20 in starts and o + 0x40 in starts and o - 0x20 not in starts
            and starts[o][0] == starts[o + 0x20][0] == starts[o + 0x40][0]
            and not starts[o + 0x20][1] and not starts[o + 0x40][1]]
    if len(runs) != 1:
        return None
    return runs[0], starts[runs[0]][1]


def status_bytes(blob: bytes) -> str:
    s = site(blob)
    return UNKNOWN if s is None else (ON if s[1] else OFF)


def apply_bytes(blob: bytearray) -> None:
    s = site(bytes(blob))
    if s is None:
        raise PatchError("HackHornBall isn't recognised in this engine; nothing written")
    if not s[1]:
        blob[s[0] + AT:s[0] + AT + 2] = ON_BYTES


def revert_bytes(blob: bytearray) -> None:
    s = site(bytes(blob))
    if s is not None and s[1]:
        blob[s[0] + AT:s[0] + AT + 2] = STOCK_BYTES


def status(data_dir: str | Path) -> str:
    try:
        f = _engine(data_dir)
    except PatchError:
        return MISSING
    return status_bytes(f.read_bytes())


def apply(data_dir: str | Path) -> None:
    """The horn ball in career races (following its option). Backs the engine up once first."""
    f = _engine(data_dir)
    blob = bytearray(f.read_bytes())
    apply_bytes(blob)
    if bytes(blob) != f.read_bytes():
        backup = backups.locate(f, BACKUP_SUFFIX) or backups.path_for(f, BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copy2(f, backup)
        safewrite.write_atomic(f, bytes(blob))


def revert(data_dir: str | Path) -> None:
    """Career as shipped: the horn ball off in career races (the je back, byte for byte)."""
    f = _engine(data_dir)
    blob = bytearray(f.read_bytes())
    revert_bytes(blob)
    if bytes(blob) != f.read_bytes():
        safewrite.write_atomic(f, bytes(blob))
