"""Turn off the AI's head-on panic swerve.

Drive at an AI car fast enough and it throws the wheel fully to one side rather
than picking a line past you. `AICar::headon_panic()` is a handler of its own,
separate from the ordinary `passer` / `slow_interact` paths, and this makes it
return without doing anything.

**How the function was found.** Its address is not in `race.bin`, which carries
no symbols -- the crash handler even says "No mapfile present". It is in the 1998
`ai-tweaker.exe` build circulated as an AI speed tweaker, which has the game's
own linker map embedded: 10,414 symbols across 296 object files. There,
`?headon_panic@AICar@@IAEXXZ` sits at section offset 0x301d0 of `.text`, and the
99 bytes of its body are identical in `race.bin` apart from six bytes, every one
of them inside an `e8` call displacement. The AI code did not change between 1998
and the 2016 community build.

So the site is located by SIGNATURE, not by address -- the 24-byte prologue,
which contains no relocations:

    83 ec 04              sub  esp, 4
    56                    push esi
    68 cd cc cc 3d        push 0.1f
    8b 81 0c 0f 00 00     mov  eax, [ecx+0xf0c]
    8b f1                 mov  esi, ecx
    89 81 d0 0f 00 00     mov  [ecx+0xfd0], eax

and the function ends by choosing between +1.0 and -1.0 on the sign of
`[esi+0xf18]` and handing that to a steering call -- the wheel going fully one
way or the other, which is what it looks like from the cockpit.

**Why a bare RET is safe here.** The mangled name says `IAEXXZ`: private,
`__thiscall`, returning void, taking NO arguments. `this` arrives in ECX and the
caller cleans nothing off the stack, so returning before the `sub esp, 4` leaves
the stack exactly as it was found.

What this does NOT do is stop the AI reacting to you at all. Ordinary avoidance
is a different code path and is untouched; so is `.sol` obstacle avoidance.
"""
from __future__ import annotations

import shutil
from pathlib import Path

RACE_BIN = "race.bin"

# The prologue, used to find the function. No relocations in it, so it is
# identical across every build examined.
SIGNATURE = bytes.fromhex(
    "83ec04"              # sub esp, 4
    "56"                  # push esi
    "68cdcccc3d"          # push 0.1f
    "8b810c0f0000"        # mov eax, [ecx+0xf0c]
    "8bf1"                # mov esi, ecx
    "8981d00f0000"        # mov [ecx+0xfd0], eax
)

ORIGINAL = SIGNATURE[:1]       # 0x83, the first byte of `sub esp, 4`
DISABLED = b"\xc3"             # ret

ENABLED, DISABLED_STATE, UNKNOWN, MISSING = "enabled", "disabled", "unknown", "missing"


class PatchError(RuntimeError):
    pass


def _site(blob: bytes) -> int:
    """File offset of headon_panic, found by its prologue."""
    at = blob.find(SIGNATURE)
    if at < 0:
        raise PatchError(
            "could not find AICar::headon_panic in this race.bin -- its prologue "
            "does not appear, so this is a build the signature does not cover")
    if blob.find(SIGNATURE, at + 1) >= 0:
        raise PatchError("the prologue appears more than once; refusing to guess")
    return at


def site(data_dir: str | Path) -> int:
    """Where the patch goes, for reporting. Raises if it cannot be found."""
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        raise PatchError(f"no {RACE_BIN} in {data_dir}")
    return _site(f.read_bytes())


def status(data_dir: str | Path) -> str:
    """Whether the panic is enabled, disabled, or something unrecognised."""
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        return MISSING
    blob = f.read_bytes()
    # A disabled build has a RET where the prologue's first byte was, so the
    # full signature no longer matches -- look for the rest of it.
    tail = SIGNATURE[1:]
    at = blob.find(SIGNATURE)
    if at >= 0:
        return ENABLED
    at = blob.find(tail)
    if at >= 0 and blob[at - 1:at] == DISABLED:
        return DISABLED_STATE
    return UNKNOWN


def apply(data_dir: str | Path) -> int:
    """Make headon_panic return immediately. Returns the offset patched.

    Copies race.bin to race.bin.headon-backup first, and refuses unless the site
    holds exactly the expected byte -- so it cannot be applied twice or damage a
    build it does not recognise.
    """
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        raise PatchError(f"no {RACE_BIN} in {data_dir}")
    blob = bytearray(f.read_bytes())
    state = status(data_dir)
    if state == DISABLED_STATE:
        raise PatchError("already disabled -- nothing to do")
    if state == UNKNOWN:
        raise PatchError(
            "this race.bin is neither patched nor recognised; refusing to write")
    at = _site(bytes(blob))
    if blob[at:at + 1] != ORIGINAL:
        raise PatchError(
            f"unexpected byte at the patch site ({blob[at]:#04x}); refusing to write")
    blob[at:at + 1] = DISABLED
    backup = f.with_suffix(f.suffix + ".headon-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    f.write_bytes(bytes(blob))
    return at


def revert(data_dir: str | Path) -> int:
    """Put the panic back. Returns the offset restored."""
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        raise PatchError(f"no {RACE_BIN} in {data_dir}")
    blob = bytearray(f.read_bytes())
    tail = SIGNATURE[1:]
    at = blob.find(tail)
    if at < 1 or blob[at - 1:at] != DISABLED:
        raise PatchError("this race.bin does not look patched -- nothing to revert")
    blob[at - 1:at] = ORIGINAL
    f.write_bytes(bytes(blob))
    return at - 1
