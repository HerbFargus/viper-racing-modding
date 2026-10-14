"""Check vrmod.upgradeunlock against every engine build on hand.

For each build: both shop checks are found once and read "off"; applying writes `mov cl, 1; nop` over each `set`
(6 bytes in all, nothing else) and reads "on"; a second apply changes nothing; revert restores every byte. A build
with only one site patched reads "unknown", and apply refuses it.

    python scripts/check_upgradeunlock.py [extra engine files...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402

from vrmod import upgradeunlock as U  # noqa: E402

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
    check("found once each, off", U.status_bytes(stock) == U.OFF, U.status_bytes(stock))
    blob = bytearray(stock)
    U.apply_bytes(blob)
    on = bytes(blob)
    sites = U._sites(on)
    changed = [i for i in range(len(stock)) if stock[i] != on[i]]
    check("on after apply", U.status_bytes(on) == U.ON)
    check("6 bytes changed, all at the two sets",
          len(changed) == 6 and all(any(at <= c < at + 3 for at, _ in sites.values()) for c in changed), str(len(changed)))
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for k, (at, _) in sites.items():
        ins = [f"{i.mnemonic} {i.op_str}" for i in md.disasm(on[at:at + 3], 0)]
        check(f"{k}: mov cl, 1; nop", ins == ["mov cl, 1", "nop "], "; ".join(ins))
    again = bytearray(on)
    U.apply_bytes(again)
    check("a second apply changes nothing", bytes(again) == on)
    rev = bytearray(on)
    U.revert_bytes(rev)
    check("revert restores every byte", bytes(rev) == stock)
    half = bytearray(stock)
    at = sites["buy"][0]
    half[at:at + 3] = U.UNLOCKED
    check("half patched reads unknown", U.status_bytes(bytes(half)) == U.UNKNOWN)


def main() -> None:
    paths = [p for p in DEFAULTS + [Path(a) for a in sys.argv[1:]] if p.is_file()]
    for p in paths:
        one(p)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
