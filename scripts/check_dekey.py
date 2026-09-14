"""Checks for the transparency-marker sweep.

This one edits a user's game files, so the checks are mostly about what it must
NOT do. The interesting failure is not "it missed some" -- that shows up
immediately as a count -- it is "it touched something it had no business
touching", which shows up as a cactus turning into a solid rectangle three
tracks later.

    python scripts/check_dekey.py path/to/install
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, dekey, envelope, tex  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def flags_of(path: Path) -> dict[str, int]:
    out = {}
    for e in archive.read(path):
        if e.name.lower().endswith(".tex"):
            out[e.name.lower()] = e.payload[0]
    return out


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("check_dekey.py path/to/install")
    src = Path(sys.argv[1])
    originals = sorted(p for p in src.iterdir()
                       if p.suffix.lower() in dekey.SWEPT_SUFFIXES
                       and not p.name.lower().endswith(".bak"))
    if not originals:
        raise SystemExit(f"no .car/.trk/.res under {src}")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for p in originals:
            shutil.copy2(p, work / p.name)

        before = {p.name: flags_of(work / p.name) for p in originals}
        reports = dekey.sweep_tree(work, backup=False)
        lifted = sum(r.lifted for r in reports)

        # --- the sweep did what it said --------------------------------------
        remaining = sum(dekey.remaining_keys((work / p.name).read_bytes())
                        for p in originals)
        check("no key texel survives in an opaque texture", remaining == 0,
              f"{lifted:,} lifted across {len([r for r in reports if r.lifted])} files")

        # --- and nothing else ------------------------------------------------
        diffs = unexpected = grew = 0
        for p in originals:
            old = p.read_bytes()
            new = (work / p.name).read_bytes()
            if len(old) != len(new):
                grew += 1
                continue
            for i in range(len(old)):
                if old[i] != new[i]:
                    diffs += 1
                    if not (old[i] == 0x00 and new[i] == 0x40):
                        unexpected += 1
        check("no file changes size", grew == 0, f"{len(originals)} files")
        # The strongest statement available: the sweep's own tally and an
        # independent byte-by-byte diff of every file have to be the same
        # number. Either alone can be wrong in the same direction; together
        # they cannot.
        check("every changed byte is the nudge, and only the nudge",
              unexpected == 0 and diffs == lifted,
              f"{diffs:,} bytes differ, {unexpected} unexpected, sweep reported {lifted:,}")

        # --- the textures it must not touch ----------------------------------
        kept = broke = 0
        for p in originals:
            after = flags_of(work / p.name)
            for name, flags in before[p.name].items():
                if flags == 0x00:
                    continue
                kept += 1
                if after.get(name) != flags:
                    broke += 1
        check("colorkey and alpha textures keep their flags", broke == 0,
              f"{kept} of them across the install")

        untouched = 0
        for p in originals:
            old = {e.name.lower(): e.payload for e in archive.read(p)}
            new = {e.name.lower(): e.payload for e in archive.read(work / p.name)}
            for name, payload in old.items():
                if not name.endswith(".tex") or payload[0] == 0x00:
                    continue
                if new[name] == payload:
                    untouched += 1
                else:
                    broke += 1
        check("colorkey and alpha textures are byte-identical afterwards",
              broke == 0, f"{untouched} left exactly as found")

        # The one that motivated the flag test in the first place. Sunset Mesa's
        # cacti are colorkey billboards: 0x0000 is what makes them cactus-shaped
        # rather than square, and sweeping them would be the most visible
        # possible regression.
        cacti = [p for p in originals if "cactus.tex" in flags_of(p)]
        if cacti:
            p = cacti[0]
            old = next(e for e in archive.read(p) if e.name.lower() == "cactus.tex")
            new = next(e for e in archive.read(work / p.name)
                       if e.name.lower() == "cactus.tex")
            check(f"{p.name}'s cactus.tex is untouched",
                  new.payload == old.payload,
                  f"flags={old.payload[0]:#04x}, "
                  f"{dekey.remaining_keys(p.read_bytes()) and ''}"
                  f"still colour-keyed")
        else:
            print("  --    no cactus.tex in this install (Sunset Mesa not installed)")

        # --- running it twice ------------------------------------------------
        again = dekey.sweep_tree(work, backup=False)
        check("a second sweep is a no-op", sum(r.lifted for r in again) == 0,
              "idempotent")

        # --- the picture is still the picture --------------------------------
        worst = 0
        for p in originals[:6]:
            old = {e.name.lower(): e for e in archive.read(p)}
            new = {e.name.lower(): e for e in archive.read(work / p.name)}
            for name, e in old.items():
                if not name.endswith(".tex") or e.payload[0] != 0x00:
                    continue
                a = tex.decode_base_level(tex.parse(
                    envelope.build(e.tag, e.version, e.payload)))
                n = new[name]
                b = tex.decode_base_level(tex.parse(
                    envelope.build(n.tag, n.version, n.payload)))
                worst = max(worst, max((abs(x - y) for x, y in zip(a, b)), default=0))
        # 0x0040 decodes to (0, 8, 0): eight levels of green on a pixel that was
        # black. Anything larger means the sweep hit a pixel that was not on the
        # marker at all.
        check("no pixel moves further than the nudge", worst <= 8,
              f"largest channel delta {worst} (the nudge itself is 8)")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
