"""Two engine bug fixes every install gets: obstacles wake on a restart, and the AI survives
losing its racing line.

Both are documented in docs/reference/file-formats.md ("How an obstacle lives"). In short:

**Obstacle wake.** `Obstacle::Reset` puts an obstacle back at its spawn but leaves its sleep state
alone, and the physics clock keeps running across a restart -- so an obstacle that had settled is
reset ASLEEP and hangs at its spawn, 4 m up, until something hits it. `Reset` ends `ret; mov edi,
edi` immediately before `Obstacle::Perturb` (the wake-up), so NOPing those 3 bytes makes every reset
fall straight through into one. ecx still holds the obstacle there: `PhobDyno::Reset` never touches
it. Same bytes in every build.

**AI bead guard.** When an AI car's position goes NaN (a bad collision normal; it happens with
objects in the road), `get_nearest_pair` finds no segment, the car's place on its racing line -- the
"bead" -- is left NULL, and the next `IdealLine::advance_bead` reads through it and the game dies
(`advance_bead`+0x43, `mov ecx, [esi]`). The guard puts a NULL bead back at the head of the line
(`+0x2c`, t = 0) before it is read; the AI finds its place again over the next frames.

  * race.exe (v1.0) opens `advance_bead` with 32 bytes of profiler calls, and the guard replaces
    them in place. The profiler handle is set to -1, which makes the prof_stop at the end a no-op.
  * race.bin (1.0 disc, 1.2.4 beta, 1.2.5, 1.2.6) was compiled without the profiler, so its first
    two loads (`mov eax,[ecx+8]; mov esi,[ecx+4]`, 6 bytes) become a jump to a 26-byte stub in the
    .text slack, which does the check, repeats the loads and jumps back. The slack is found with
    needlefix's allocator, which only ever takes all-zero space, so the two stubs cannot collide.

Both sites are found by signature, and each must match exactly once or nothing is written -- the
same rule as headon. Neither fix changes anything when things go right, so the patch set applies
them to every install with no option to turn them off.
"""
from __future__ import annotations

import re
import shutil
import struct
from pathlib import Path

from . import backups, needlefix, pe, safewrite

ENGINE_NAMES = ("race.exe", "race.bin")        # live one first: v1.0 runs race.exe
BACKUP_SUFFIX = ".enginefix-backup"

FIXED, STOCK, UNKNOWN, MISSING = "fixed", "stock", "unknown", "missing"
FIXES = ("obstacle_wake", "ai_bead_guard")


class EngineFixError(RuntimeError):
    pass


# ---- obstacle wake ---------------------------------------------------------------------------------
# Obstacle::Reset, from its prologue to the start of Obstacle::Perturb. The only relocation is the
# call to PhobDyno::Reset. WAKE_AT is the offset of the `ret; mov edi, edi` that gets NOPed.
_WAKE = (re.escape(bytes.fromhex("568bc157b90c0000008db0780400008d7838f3a58bc8e8")) + b"...."
         + re.escape(bytes.fromhex("5f5e")) + b"(%s)" + re.escape(bytes.fromhex("568bf1c681ac04000001")))
WAKE_STOCK_BYTES, WAKE_FIXED_BYTES = bytes.fromhex("c38bff"), b"\x90\x90\x90"
WAKE_AT = 0x1d
WAKE_STOCK = re.compile(_WAKE % re.escape(WAKE_STOCK_BYTES), re.S)
WAKE_FIXED = re.compile(_WAKE % re.escape(WAKE_FIXED_BYTES), re.S)

# ---- AI bead guard, race.exe form ------------------------------------------------------------------
# advance_bead's prologue: the four profiler calls carry absolute addresses, so they are wildcards.
_EXE_HEAD, _EXE_TAIL = bytes.fromhex("83ec28535657558bf9"), bytes.fromhex("8b47088b770433ed")
EXE_STOCK = re.compile(re.escape(_EXE_HEAD) + b"\xff\x15....\x68....\xff\x15...."
                       + re.escape(bytes.fromhex("8944243083c40433dbff15")) + b"...." + re.escape(_EXE_TAIL), re.S)
EXE_GUARD = bytes.fromhex(
    "c744242cffffffff"      # mov dword [esp+2Ch], -1   the profiler handle: prof_stop(-1) returns at once
    "31db"                  # xor ebx, ebx              as the original did
    "837f0400"              # cmp dword [edi+4], 0      a NULL bead?
    "7509"                  # jne ok
    "8b472c"                # mov eax, [edi+2Ch]        yes: back to the head of the line
    "894704"                # mov [edi+4], eax
    "895f08"                # mov [edi+8], ebx          at t = 0
    + "90" * 7)             # ok:
assert len(EXE_GUARD) == 32
EXE_FIXED = re.compile(re.escape(_EXE_HEAD + EXE_GUARD + _EXE_TAIL), re.S)

# ---- AI bead guard, race.bin form ------------------------------------------------------------------
# advance_bead without the profiler: sub esp,24h; push x3; xor ebx,ebx; [mov eax,[ecx+8]; mov esi,
# [ecx+4]]; push ebp; mov edi,ecx; xor ebp,ebp; ... fmul [const]; mov ecx,[esi]; add ecx,4
_BIN_HEAD = bytes.fromhex("83ec2453565733db")
_BIN_LOADS = bytes.fromhex("8b41088b7104")
_BIN_TAIL = (re.escape(bytes.fromhex("558bf933ed89442414885c2413d9442414d80d")) + b"...."
             + re.escape(bytes.fromhex("8b0e83c104")))
BIN_STOCK = re.compile(re.escape(_BIN_HEAD + _BIN_LOADS) + _BIN_TAIL, re.S)
BIN_FIXED = re.compile(re.escape(_BIN_HEAD) + b"\xe9(....)\x90" + _BIN_TAIL, re.S)
BIN_STUB_BODY = bytes.fromhex(
    "83790400"              # cmp dword [ecx+4], 0      a NULL bead?
    "7509"                  # jne ok
    "8b412c"                # mov eax, [ecx+2Ch]        yes: back to the head of the line
    "894104"                # mov [ecx+4], eax
    "895908"                # mov [ecx+8], ebx          at t = 0 (ebx was just zeroed)
    "8b4108"                # ok: mov eax, [ecx+8]      the two loads the jump replaced
    "8b7104")               #     mov esi, [ecx+4]
BIN_STUB_LEN = len(BIN_STUB_BODY) + 5            # + jmp back
BIN_AT = len(_BIN_HEAD)


def _one(rx: re.Pattern, blob: bytes, what: str) -> re.Match | None:
    ms = list(rx.finditer(blob))
    if len(ms) > 1:
        raise EngineFixError(f"{what}: the signature matches {len(ms)} times; refusing to guess")
    return ms[0] if ms else None


def _f2va(blob: bytes, off: int) -> int:
    va = pe.offset_to_va(blob, off)
    if va is None:
        raise EngineFixError(f"file offset {off:#x} is in no section")
    return va


def _va2f(blob: bytes, va: int) -> int:
    off = pe.va_to_offset(blob, va)
    if off is None:
        raise EngineFixError(f"address {va:#x} is in no section")
    return off


def _bin_stub_at(blob: bytes, m: re.Match) -> int:
    """File offset of the stub a fixed race.bin jumps to, checked to be ours."""
    src = m.start() + BIN_AT
    target_va = _f2va(blob, src) + 5 + struct.unpack("<i", m.group(1))[0]
    at = _va2f(blob, target_va)
    if blob[at:at + len(BIN_STUB_BODY)] != BIN_STUB_BODY:
        raise EngineFixError("advance_bead jumps somewhere that is not this module's stub")
    return at


# ---- per-fix state, on bytes -----------------------------------------------------------------------
def _wake_state(blob: bytes) -> str:
    if _one(WAKE_FIXED, blob, "Obstacle::Reset"):
        return FIXED
    return STOCK if _one(WAKE_STOCK, blob, "Obstacle::Reset") else UNKNOWN


def _guard_state(blob: bytes) -> str:
    if _one(EXE_FIXED, blob, "advance_bead") or _one(BIN_FIXED, blob, "advance_bead"):
        return FIXED
    if _one(EXE_STOCK, blob, "advance_bead") or _one(BIN_STOCK, blob, "advance_bead"):
        return STOCK
    return UNKNOWN


def status_bytes(blob: bytes) -> dict[str, str]:
    return {"obstacle_wake": _wake_state(blob), "ai_bead_guard": _guard_state(blob)}


def apply_bytes(blob: bytearray) -> dict[str, str]:
    """Apply both fixes in place. Idempotent; refuses a build it does not recognise."""
    done = {}
    state = status_bytes(bytes(blob))
    if UNKNOWN in state.values():
        bad = ", ".join(k for k, v in state.items() if v == UNKNOWN)
        raise EngineFixError(f"not a recognised engine build ({bad} not found); nothing written")

    if state["obstacle_wake"] == STOCK:
        at = _one(WAKE_STOCK, bytes(blob), "Obstacle::Reset").start() + WAKE_AT
        blob[at:at + 3] = WAKE_FIXED_BYTES
        done["obstacle_wake"] = f"Obstacle::Reset falls through into Perturb (at {at:#x})"
    else:
        done["obstacle_wake"] = "already fixed"

    if state["ai_bead_guard"] == STOCK:
        m = _one(EXE_STOCK, bytes(blob), "advance_bead")
        if m:
            at = m.start() + len(_EXE_HEAD)
            blob[at:at + 32] = EXE_GUARD
            done["ai_bead_guard"] = f"advance_bead guard in place of its profiler calls (at {at:#x})"
        else:
            m = _one(BIN_STOCK, bytes(blob), "advance_bead")
            src = m.start() + BIN_AT
            try:
                stub, stub_va = needlefix._slack(blob, BIN_STUB_LEN)
            except needlefix.NeedleFixError as ex:
                raise EngineFixError(f"no room for the advance_bead stub: {ex}") from None
            src_va = _f2va(bytes(blob), src)
            back = struct.pack("<i", (src_va + 6) - (stub_va + BIN_STUB_LEN))
            blob[stub:stub + BIN_STUB_LEN] = BIN_STUB_BODY + b"\xe9" + back
            blob[src:src + 6] = b"\xe9" + struct.pack("<i", stub_va - (src_va + 5)) + b"\x90"
            done["ai_bead_guard"] = f"advance_bead jumps to a guard stub (at {src:#x} -> {stub:#x})"
    else:
        done["ai_bead_guard"] = "already fixed"
    return done


def revert_bytes(blob: bytearray) -> None:
    """Undo both fixes in place (whatever is applied), restoring the stock bytes.

    race.exe's guard can't be undone byte by byte -- it overwrote profiler calls whose absolute
    addresses aren't kept -- so that build is refused before anything changes; restore it from the
    backup, or let the patch set rebuild from its snapshot.
    """
    if _one(EXE_FIXED, bytes(blob), "advance_bead"):
        raise EngineFixError(
            "race.exe's guard replaced its profiler calls, whose absolute addresses this module "
            "does not keep; restore the engine from its backup (or the patch set's snapshot) instead")
    m = _one(WAKE_FIXED, bytes(blob), "Obstacle::Reset")
    if m:
        at = m.start() + WAKE_AT
        blob[at:at + 3] = WAKE_STOCK_BYTES
    m = _one(BIN_FIXED, bytes(blob), "advance_bead")
    if m:
        stub = _bin_stub_at(bytes(blob), m)
        blob[stub:stub + BIN_STUB_LEN] = bytes(BIN_STUB_LEN)
        src = m.start() + BIN_AT
        blob[src:src + 6] = _BIN_LOADS


# ---- on an install -----------------------------------------------------------------------------------
def engine(data_dir: str | Path) -> Path:
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise EngineFixError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def status(data_dir: str | Path) -> dict[str, str]:
    try:
        f = engine(data_dir)
    except EngineFixError:
        return {k: MISSING for k in FIXES}
    try:
        return status_bytes(f.read_bytes())
    except EngineFixError:
        return {k: UNKNOWN for k in FIXES}


def apply(data_dir: str | Path) -> dict[str, str]:
    """Apply both fixes to the install's live engine, backing it up once first."""
    f = engine(data_dir)
    blob = bytearray(f.read_bytes())
    done = apply_bytes(blob)
    if bytes(blob) != f.read_bytes():
        backup = backups.locate(f, BACKUP_SUFFIX) or backups.path_for(f, BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copy2(f, backup)
        safewrite.write_atomic(f, bytes(blob))
    return done
