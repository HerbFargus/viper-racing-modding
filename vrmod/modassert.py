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

THIS IS NOT A GAME BUG, AND THAT IS THE JUSTIFICATION -- BUT STATE IT PRECISELY.
The module-safety subsystem is NOT absent from the released builds. They keep
its strings and they keep a FATAL panic for the safe-module path: `_MultiEnter`
pushes `Task "%s" called module "%s" after module ended.` straight into
LogPanic, in the RC and in every release alike. That check is real, it is fatal,
and this patch does not touch it.

What the releases do is compile the SINGLE-ENTRY guard away. Follow what
MouseQueueEvent actually calls:

    v1.0 race.exe (RC)   0x415000  _SingleEnter -> unsafe_check -> the check runs
    v1.0 race.bin        0x415090  c3           -- a bare RET, does nothing
    v1.2.5 community     0x414ee0  c3           -- a bare RET, does nothing

`_SingleEnter` and `_SingleLeave` are empty functions in the shipped builds. So
the released game does not merely fail to panic here, it performs no
single-entry check at all -- and this patch reproduces that rather than
approximating it. `unsafe_check` has exactly TWO callers, `_SingleEnter` and
`_SingleLeave`, which are precisely the pair the releases compiled to RETs, so
returning from it gives the same semantics by a different byte.

(The earlier version of this note claimed the whole subsystem was compiled out,
which is wrong: only the single-entry half is, and `_MultiEnter`'s panic stays
live everywhere.)

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
