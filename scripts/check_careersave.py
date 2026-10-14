"""Checks for the career save editor (vrmod/careersave.py), on synthetic career files.

    python scripts/check_careersave.py [path/to/Data]

WHAT THESE GUARD. A career file is a 16-byte header ('FNIC', version 2, size 0x674, the byte sum of the decoded body)
and the body xor'd with 0xa4. set_funds must change the funds and the checksum and nothing else (the game reads every
other byte back as its career), refuse what isn't an int32 amount, keep the first original in Backups\\, and refuse a
damaged file rather than "fix" it. Given a Data folder, it also lists the real careers (read only).
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import careersave as C  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def synth_body(name: bytes, funds: int, week: int, cls: int) -> bytes:
    body = bytearray(C.SIZE)
    body[0:len(name)] = name
    struct.pack_into("<i", body, C.OFF_FUNDS, funds)
    body[C.OFF_UPGRADES] = 1                               # the placeholder a new career sets
    body[C.OFF_UPGRADES + 5] = 1                           # one upgrade bought
    struct.pack_into("<i", body, C.OFF_WEEK, week)
    struct.pack_into("<i", body, C.OFF_CLASS, cls)
    for i in range(C.SIZE):                                # every other byte something, so a stray write shows
        if body[i] == 0 and i > 0x200:
            body[i] = (i * 7) & 0xFF
    return bytes(body)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        (data / "Config" / "career").mkdir(parents=True)
        f0 = data / "Config" / "career" / "career0.dat"
        f0.write_bytes(C.encode(synth_body(b"Tester", 75, 3, 1)))
        (data / "Config" / "career" / "career2.dat").write_bytes(b"FNIC" + b"\0" * 20)   # damaged
        cs = C.list_careers(data)
        check("lists the good slot, skips the damaged one", [c.slot for c in cs] == [0], str([c.slot for c in cs]))
        c = cs[0]
        check("reads name, funds, week, class, upgrades",
              (c.name, c.funds, c.week, c.career_class, c.upgrades) == ("Tester", 75, 3, 1, 1),
              f"{c.name} ${c.funds} week {c.week} class {c.career_class} {c.upgrades} upgrades")
        before = f0.read_bytes()
        c2 = C.set_funds(data, 0, 10_000_000)
        after = f0.read_bytes()
        changed = [i for i in range(len(before)) if before[i] != after[i]]
        check("set_funds: funds now 10,000,000", c2.funds == 10_000_000)
        check("set_funds changes only the checksum and the funds",
              all(12 <= i < 16 or C.HEADER + C.OFF_FUNDS <= i < C.HEADER + C.OFF_FUNDS + 4 for i in changed),
              f"bytes {changed}")
        check("the result decodes (checksum right)", C.decode(after)[C.OFF_FUNDS:C.OFF_FUNDS + 4] ==
              struct.pack("<i", 10_000_000))
        bk = list((data / "Backups").glob("career0.dat*"))
        check("first edit keeps the original in Backups", len(bk) == 1 and bk[0].read_bytes() == before,
              ", ".join(p.name for p in bk))
        C.set_funds(data, 0, 5)
        check("a second edit keeps the FIRST original", bk[0].read_bytes() == before)
        for bad in (-1, C.FUNDS_MAX + 1):
            try:
                C.set_funds(data, 0, bad)
                ok = False
            except C.CareerError:
                ok = True
            check(f"refuses funds {bad:,}", ok)
        for slot in (1, 7):
            try:
                C.set_funds(data, slot, 100)
                ok = False
            except C.CareerError:
                ok = True
            check(f"refuses slot {slot} (empty / out of range)", ok)
        try:
            C.decode((data / "Config" / "career" / "career2.dat").read_bytes())
            ok = False
        except C.CareerError:
            ok = True
        check("refuses a damaged file", ok)

    if len(sys.argv) > 1:
        for c in C.list_careers(sys.argv[1]):
            print(f"  (real) slot {c.slot} {c.name}: ${c.funds:,}, class {c.career_class + 1}, week {c.week}")

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
