"""Silence the v1.0 RC's development-only module-ownership assertion.

WHAT IT IS. The Release Candidate carries a debug subsystem the shipped game
does not: every "unsafe" (single-entry) module is owned by the task that
registered it, and every call into one asserts that the caller still owns it.

    SingleBegin(name)   owner[slot] = TaskGetID();  name[slot] = name
    _SingleEnter(idx)   unsafe_check: panic unless TaskGetID() == owner[idx]
    _SingleEnd(idx)     owner[idx] = 0

When the assertion fires it calls LogPanic, which calls abend(), which faults
deliberately so the SEH handler writes except.log -- so a failed assertion is
fatal, not a warning.

WHY IT FIRES ON THE MOUSE. `owner == 0` does not mean "no owner known", it means
the module has been ENDED, and TaskGetName(0) returns NULL -- which printf
renders as the "(null)" in the message. So:

    Panic : "<main>" called module mouse owned by "(null)"
      abend +0x9 <- _LogPanic <- LogPanic <- unsafe_check <- _SingleEnter
      <- MouseQueueEvent +0x13 <- win32_event +0x20e

reads as: MouseEnd() had already run, and the window then received another mouse
message. win32_event dispatched it to MouseQueueEvent, which enters the module
at +0x0e and returns at +0x13 -- exactly the frame the crash log names. A
shutdown/transition race between the window still taking input and the module
having been torn down.

THIS IS NOT A GAME BUG, AND THAT IS THE JUSTIFICATION FOR THE PATCH. The whole
subsystem was compiled OUT of the release build: the panic format string is
present in the RC's race.exe and absent from v1.0's own race.bin, from v1.2.5
and from v1.2.6. The shipped game does not make this check at all, so the same
race presumably happens there and simply goes unremarked. Disabling the
assertion makes race.exe behave as MGI shipped, rather than inventing new
behaviour.

WHAT IT DOES. Writes a single `RET` at unsafe_check's entry, so the check
returns immediately and nothing panics. cdecl with a void return and the caller
cleaning the stack, so returning before the function's own `push esi` is safe.

SCOPE, STATED HONESTLY. This disables the assertion for EVERY unsafe module, not
only the mouse. A narrower patch is possible -- gate the call inside
MouseQueueEvent -- but it would need a code stub and would leave the assertion
live for modules whose races nobody has observed, which is a worse trade than
matching the build MGI actually released.

Located by PATTERN, never by offset. Builds without the subsystem report
ABSENT rather than failing, which is every build except the RC.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import safewrite

RACE_BIN = "race.bin"

# Engine binaries, live one first -- the v1.0 pressing runs race.exe and ships a
# dormant race.bin beside it. Only race.exe carries this subsystem at all.
ENGINE_NAMES = ("race.exe", RACE_BIN)

# unsafe_check's entry. Wildcarded at the two build-specific operands: the
# rel32 to TaskGetID and the address of the owner table.
#
#   mov  eax, [esp+4]            ; module index
#   push esi
#   lea  esi, [eax*8 - 8]        ; entry = table + idx*8
#   call TaskGetID
#   cmp  eax, [esi + <owners>]   ; still ours?
#   je   <return>
SIGNATURE = re.compile(
    rb"\x8b\x44\x24\x04\x56\x8d\x34\xc5\xf8\xff\xff\xff"
    rb"\xe8(....)\x3b\x86(....)\x74\x33", re.S)

RET = b"\xc3"

UNPATCHED, PATCHED, ABSENT, UNKNOWN = "unpatched", "patched", "absent", "unknown"


class ModAssertError(RuntimeError):
    """The assertion isn't where this patch expects, or the build has none."""


def _engine(data_dir: str | Path) -> Path:
    d = Path(data_dir)
    for n in ENGINE_NAMES:
        if (d / n).is_file():
            return d / n
    raise ModAssertError(f"no {' or '.join(ENGINE_NAMES)} in {d}")


def _site(blob: bytes) -> int:
    """File offset of unsafe_check's first byte. Raises if not exactly one."""
    hits = list(SIGNATURE.finditer(blob))
    if len(hits) != 1:
        raise ModAssertError(
            f"expected exactly one module-ownership assertion, found {len(hits)}")
    return hits[0].start()


def _patched_site(blob: bytes) -> int | None:
    """Where a RET has replaced the entry, if it has.

    The first byte is gone, so match the REST of the signature and check that a
    RET sits in front of it.
    """
    tail = SIGNATURE.pattern[len(rb"\x8b"):]          # drop the first opcode byte
    for m in re.finditer(tail, blob, re.S):
        start = m.start() - 1
        if start >= 0 and blob[start:start + 1] == RET:
            return start
    return None


def status(data_dir: str | Path) -> str:
    """UNPATCHED, PATCHED, ABSENT (this build has no such check) or UNKNOWN."""
    try:
        blob = _engine(data_dir).read_bytes()
    except ModAssertError:
        return ABSENT
    if SIGNATURE.search(blob):
        return UNPATCHED
    if _patched_site(blob) is not None:
        return PATCHED
    return ABSENT


def site(data_dir: str | Path) -> int:
    """File offset of the assertion, for reporting."""
    return _site(_engine(data_dir).read_bytes())


def apply(data_dir: str | Path) -> int:
    """Make unsafe_check return immediately. Returns the offset patched."""
    f = _engine(data_dir)
    blob = bytearray(f.read_bytes())
    if _patched_site(bytes(blob)) is not None:
        raise ModAssertError("already patched -- nothing to do")
    at = _site(bytes(blob))
    blob[at:at + 1] = RET
    backup = f.with_suffix(f.suffix + ".modassert-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    safewrite.write_atomic(f, bytes(blob))
    return at


def revert(data_dir: str | Path) -> int:
    """Put the original first instruction back. Returns the offset restored."""
    f = _engine(data_dir)
    blob = bytearray(f.read_bytes())
    at = _patched_site(bytes(blob))
    if at is None:
        raise ModAssertError("the assertion does not carry this patch")
    blob[at:at + 1] = b"\x8b"                        # mov eax, [esp+4]
    safewrite.write_atomic(f, bytes(blob))
    return at
