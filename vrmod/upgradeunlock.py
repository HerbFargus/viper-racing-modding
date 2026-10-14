"""All upgrades on sale in the career's upgrade shop, from the first week.

The shop sells an upgrade only once the career has reached its class: `career class + 1 >= the upgrade's class`
(CarUpgrade +0x64, 1..4; CareerInfo +0x124, 0..3). Two places decide it, the same test in each:

    UpgradeCatalog::MouseUp   a click buys the upgrade only when it's allowed in this class
    UpgradeCatalog::Draw      an allowed upgrade is labelled "Available" (or its price), the rest "Class N"

Both compute the test into `cl` with a `setge` / `setle` (3 bytes); this writes `mov cl, 1; nop` there, so every
upgrade is allowed in every class. The rest of the shop is untouched: an upgrade that needs another one first still
does, and every upgrade still costs its price (set a career's funds with careersave.py).

The sites are found by signature -- the CareerInfo class read, the increment, the compare and the set, with the
call between them in Draw as a wildcard -- once each in every build examined (v1.0 race.exe and race.bin, v1.1,
1.2.4 beta, 1.2.5, 1.2.6); anything else is refused before a byte is written. Opt-in: the player turns it on
(the Game page's Career panel); it is carried over when the patch set rebuilds the engine. The port does the same
when it finds the patch (viper-racing-port, career_shop.cpp, port_vrmod_has).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import backups, casefold, safewrite

ENGINE_NAMES = ("race.exe", "race.bin")        # live one first: v1.0 runs race.exe
BACKUP_SUFFIX = ".upgradeunlock-backup"
ON, OFF, UNKNOWN, MISSING = "on", "off", "unknown", "missing"

UNLOCKED = b"\xb1\x01\x90"                     # mov cl, 1; nop
_SET = {"buy": b"\x0f\x9d\xc1", "draw": b"\x0f\x9e\xc1"}   # setge cl / setle cl

# MouseUp: mov eax, [eax+124h]; inc eax; cmp eax, [edi+64h]; SET; add edi, 40h
_BUY = (re.escape(bytes.fromhex("8b8024010000403b4764")) + b"(%s)" + re.escape(bytes.fromhex("83c740")))
# Draw: mov edi, [eax+64h]; call CareerGetInfo; mov eax, [eax+124h]; inc eax; cmp edi, eax; SET; mov [esp+13h], cl
_DRAW = (re.escape(bytes.fromhex("8b7864e8")) + b"...." + re.escape(bytes.fromhex("8b8024010000403bf8")) + b"(%s)"
         + re.escape(bytes.fromhex("884c2413")))
SITES = {"buy": _BUY, "draw": _DRAW}


class PatchError(RuntimeError):
    pass


def _engine(data_dir: str | Path) -> Path:
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (f := casefold.find_file(d, n)) is not None:
            return f
    raise PatchError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def _sites(blob: bytes) -> dict[str, tuple[int, bool]]:
    """Each site's file offset (of the 3 set bytes) and whether it is unlocked. Raises unless each is found once."""
    out = {}
    for k, pat in SITES.items():
        rx = re.compile(pat % (re.escape(_SET[k]) + b"|" + re.escape(UNLOCKED)), re.S)
        ms = list(rx.finditer(blob))
        if len(ms) != 1:
            raise PatchError(f"the upgrade shop's {k} check is found {len(ms)} times in this engine, not once; "
                             "this is a build the signature does not cover")
        out[k] = (ms[0].start(1), ms[0].group(1) == UNLOCKED)
    return out


def status_bytes(blob: bytes) -> str:
    try:
        s = _sites(blob)
    except PatchError:
        return UNKNOWN
    states = {v[1] for v in s.values()}
    return UNKNOWN if len(states) != 1 else (ON if True in states else OFF)


def apply_bytes(blob: bytearray) -> None:
    for k, (at, unlocked) in _sites(bytes(blob)).items():
        if not unlocked:
            blob[at:at + 3] = UNLOCKED


def revert_bytes(blob: bytearray) -> None:
    for k, (at, unlocked) in _sites(bytes(blob)).items():
        if unlocked:
            blob[at:at + 3] = _SET[k]


def status(data_dir: str | Path) -> str:
    try:
        f = _engine(data_dir)
    except PatchError:
        return MISSING
    return status_bytes(f.read_bytes())


def apply(data_dir: str | Path) -> None:
    """Every upgrade on sale in every class. Backs the engine up once first; refuses a build it doesn't recognise."""
    f = _engine(data_dir)
    blob = bytearray(f.read_bytes())
    if status_bytes(bytes(blob)) == UNKNOWN:
        raise PatchError("the upgrade shop's checks aren't recognised in this engine (or are half patched); "
                         "nothing written")
    apply_bytes(blob)
    if bytes(blob) != f.read_bytes():
        backup = backups.locate(f, BACKUP_SUFFIX) or backups.path_for(f, BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copy2(f, backup)
        safewrite.write_atomic(f, bytes(blob))


def revert(data_dir: str | Path) -> None:
    """The class lock back, byte for byte."""
    f = _engine(data_dir)
    blob = bytearray(f.read_bytes())
    revert_bytes(blob)
    if bytes(blob) != f.read_bytes():
        safewrite.write_atomic(f, bytes(blob))
