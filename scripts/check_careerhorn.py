"""Check vrmod.careerhorn against every engine build on hand.

For each build: HackHornBall is found (the first of the one run of three hack getters) and reads "off"; turning it
on writes two NOPs over its hacks-on je (2 bytes, nothing else -- HackNoWalls and HackPaveTheWorld untouched) and
reads "on", the function then reading cmp / nop / nop / cmp / je; a second apply changes nothing; turning it off
restores every byte.

    python scripts/check_careerhorn.py [extra engine files...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402

from vrmod import careerhorn as H  # noqa: E402

ROOT = Path.home() / "Desktop" / "claude-code"
DEFAULTS = sorted((ROOT / "reference-files" / "executables" / "engine-builds").glob("race.bin-*.bin")) + \
           [ROOT / "game-files" / "installs" / "v1.0-RC" / "race.exe.vrmod-original"]
PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if ok else (PASS, FAIL + 1)
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def one(path: Path) -> None:
    print(f"\n--- {path.name}")
    stock = path.read_bytes()
    check("found, off", H.status_bytes(stock) == H.OFF, H.status_bytes(stock))
    blob = bytearray(stock)
    H.apply_bytes(blob)
    on = bytes(blob)
    at = H.site(on)[0]
    changed = [i for i in range(len(stock)) if stock[i] != on[i]]
    check("on after apply", H.status_bytes(on) == H.ON)
    check("2 bytes changed, at the je", changed == [at + H.AT, at + H.AT + 1], str(changed))
    ins = [i.mnemonic for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(on[at:at + 24], 0)][:5]
    check("cmp / nop / nop / cmp / je", ins == ["cmp", "nop", "nop", "cmp", "je"], " ".join(ins))
    check("the other two getters untouched", on[at + 0x20:at + 0x58] == stock[at + 0x20:at + 0x58])
    again = bytearray(on)
    H.apply_bytes(again)
    check("a second apply changes nothing", bytes(again) == on)
    rev = bytearray(on)
    H.revert_bytes(rev)
    check("off restores every byte", bytes(rev) == stock)


def main() -> None:
    for p in [p for p in DEFAULTS + [Path(a) for a in sys.argv[1:]] if p.is_file()]:
        one(p)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
