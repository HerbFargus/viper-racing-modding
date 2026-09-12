"""Check the horn-ball tuning writes where the GAME reads.

This exists because it once did not. The constants are named by virtual address
in the instructions that read them, and the conversion to a file offset was
`va - IMAGE_BASE` -- the RVA, not the offset. .rdata's PointerToRawData sits
0xe00 below its VirtualAddress in race.bin and 0x1600 below it in race.exe, so
every read and write landed a few kilobytes past the real constants. Still
inside .rdata, so nothing failed: apply() wrote there, read() read it back, and
the tuning looked applied while the game went on using the untouched originals.

The test that would have caught it is the one below: after apply(), the STOCK
values must no longer be present at the located offsets. A self-consistent
round-trip proves nothing when both ends share the same wrong address.

Run:  python scripts/check_hornball.py [Data-folder]
"""

from __future__ import annotations

import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import hornball, pe  # noqa: E402

DEFAULT_DATA = (Path.home() / "Desktop" / "claude-code" / "game-files"
                / "installs" / "v1.0-RC")

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    names = [n for n in hornball.ENGINE_NAMES if (src / n).is_file()]
    if not names:
        print(f"  no engine binary in {src}")
        sys.exit(1)
    print(f"source: {src}  ({', '.join(names)})\n")

    # --- the address conversion itself ---------------------------------
    blob = (src / names[0]).read_bytes()
    secs = pe.sections(blob)
    rdata = next((s for s in secs if s.name == ".rdata"), None)
    check("the image has an .rdata section", rdata is not None)
    check("its raw pointer differs from its RVA -- which is the whole bug",
          rdata.raw != rdata.rva, f"rva {rdata.rva:#x} vs raw {rdata.raw:#x}")
    va = pe.image_base(blob) + rdata.rva
    check("va_to_offset maps that section's start to its raw pointer",
          pe.va_to_offset(blob, va) == rdata.raw)
    check("the naive `va - image_base` would NOT",
          (va - pe.image_base(blob)) != rdata.raw,
          f"off by {rdata.rva - rdata.raw:#x}")
    check("an unmapped address returns None", pe.va_to_offset(blob, 0xF0000000) is None)

    for name in names:
        print(f"\n  --- {name} ---")
        tmp = Path(tempfile.mkdtemp(prefix="check_hornball_"))
        try:
            shutil.copy2(src / name, tmp / name)
            # The source is a real install, which may well be tuned -- these are
            # player-facing settings, not a pristine museum piece. Normalise the
            # COPY to stock so the assertions below have a known baseline, and
            # so reset() is compared against stock rather than against whatever
            # the player happened to have set.
            hornball.reset(tmp)
            blob = (tmp / name).read_bytes()
            co, sp = hornball._offsets(blob)
            cd = struct.unpack_from("<f", blob, co)[0]
            spd = struct.unpack_from("<f", blob, sp)[0]
            check("the located constants ARE the documented stock values",
                  abs(cd - hornball.STOCK_COOLDOWN) < 1e-4
                  and abs(spd - hornball.STOCK_SPEED) < 1e-3,
                  f"cooldown {cd}, speed {spd}")

            t = hornball.apply(tmp, speed_mult=5.0, cooldown=0.5)
            after = (tmp / name).read_bytes()
            check("apply() reports the new tuning",
                  abs(t.speed_mult - 5.0) < 1e-6 and abs(t.cooldown - 0.5) < 1e-6,
                  f"{t.speed_mult:.2f}x / {t.cooldown}s")
            # THE test: stock must be gone from where the game looks.
            now_cd = struct.unpack_from("<f", after, co)[0]
            now_sp = struct.unpack_from("<f", after, sp)[0]
            check("the stock values are GONE from the located offsets",
                  abs(now_cd - hornball.STOCK_COOLDOWN) > 1e-4
                  and abs(now_sp - hornball.STOCK_SPEED) > 1e-3,
                  f"now {now_cd} / {now_sp}")
            check("the file keeps its size",
                  len(after) == len(blob), f"{len(after):,}")
            # Not a byte COUNT: writing 0.5 over 2.0 changes one byte of the
            # four, because the exponents share bytes. What matters is that
            # every changed byte lies inside one of the two floats.
            fields = set(range(co, co + 4)) | set(range(sp, sp + 4))
            moved = {i for i, (a, b) in enumerate(zip(blob, after)) if a != b}
            stray = sorted(moved - fields)
            check("every changed byte lies inside the two located floats",
                  not stray,
                  f"{len(moved)} changed" + (f", STRAY at {[hex(s) for s in stray[:4]]}"
                                             if stray else ""))

            hornball.reset(tmp)
            back = (tmp / name).read_bytes()
            check("reset() restores the binary byte-for-byte", back == blob)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        for f in failures:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
