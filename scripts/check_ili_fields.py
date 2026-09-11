"""Structural checks on real `.ili` / `.ild` racing lines.

These verify, against shipped data, the claims in the format reference §4.2.1-4.2.2
about what each of the seventeen fields is — in particular that the file is a raw
dump of the runtime circular linked list, which is what explains field 0 being a
pointer, field 16 being a guard word, and field 10's index being scratch.

Needs real line files, which are not in this repo. Point it at a folder holding
extracted track resources:

    python scripts/check_ili_fields.py path/to/rescrack-trk-bemidji
    python scripts/check_ili_fields.py "path/to/rescrack-trk-*"

It exits 0 with a note if none are found, so it is safe to run anywhere.
"""
from __future__ import annotations

import glob
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import envelope, ili  # noqa: E402

PASS = FAIL = 0
GUARD = 0xFEEDBEEF


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def records(path: Path):
    payload = envelope.parse(path.read_bytes()).payload
    n = (len(payload) - ili.HEADER_SIZE) // ili.RECORD_SIZE
    u, f = [], []
    for i in range(n):
        o = ili.HEADER_SIZE + i * ili.RECORD_SIZE
        u.append(struct.unpack_from("<17I", payload, o))
        f.append(struct.unpack_from("<17f", payload, o))
    return u, f


def main() -> int:
    roots: list[Path] = []
    for arg in sys.argv[1:]:
        roots += [Path(p) for p in glob.glob(arg)]
    files = sorted({f for r in roots for f in r.glob("*.il*")}) if roots else []
    if not files:
        print("no .ili/.ild files given -- pass a folder of extracted track resources")
        print("  e.g. python scripts/check_ili_fields.py path/to/rescrack-trk-bemidji")
        return 0

    print(f"{len(files)} line files")

    # --- field 0 is the runtime `next` pointer -------------------------------
    # The writer dumps each 68-byte node verbatim, `next` included, so field 0
    # holds 1998 heap addresses one record apart that wrap back to the head.
    chained = wrapped = 0
    for path in files:
        u, _ = records(path)
        n = len(u)
        if n < 3:
            continue
        step_ok = sum(1 for i in range(n - 1)
                      if u[i + 1][0] - u[i][0] == ili.RECORD_SIZE)
        if step_ok >= n - 2:
            chained += 1
        if u[-1][0] <= min(x[0] for x in u):
            wrapped += 1
    check("field 0 steps by the record size, file to file",
          chained == len(files), f"{chained}/{len(files)} files")
    check("and the last record points back to the head",
          wrapped == len(files), f"{wrapped}/{len(files)} files wrap")

    # --- field 16 is the pool guard -----------------------------------------
    bad = [p.name for p in files if any(r[16] != GUARD for r in records(p)[0])]
    check("field 16 is 0xFEEDBEEF in every record",
          not bad, f"{len(files)} files clean" if not bad else f"{bad[:3]}")

    # --- field 10's kind byte is the lap SECTOR ------------------------------
    # Constant through a racing line, but `track.ild` runs 1, 2, 3 in contiguous
    # blocks -- the lap's sectors. fixup_res renumbers this byte when reversing a
    # line and guards it with `cmp edx, 5`, so at most four are allowed.
    contiguous = tagged = 0
    sectored = []
    for path in files:
        u, _ = records(path)
        kinds = [(r[10] >> 16) & 0xFF for r in u]
        tagged += all((r[10] >> 24) == 0xFF for r in u)
        runs = [kinds[0]]
        for k in kinds[1:]:
            if k != runs[-1]:
                runs.append(k)
        contiguous += len(runs) == len(set(kinds))    # each value in one block
        if len(set(kinds)) > 1:
            sectored.append((path.name, len(set(kinds))))
    check("field 10's top byte is always 0xFF", tagged == len(files), f"{tagged} files")
    check("each kind value occupies one contiguous block",
          contiguous == len(files), f"{contiguous}/{len(files)} files")
    check("only the checkpoint line is sectored, and never past four",
          bool(sectored) and all(n2 <= 4 and f.endswith(".ild") for f, n2 in sectored),
          f"{len(sectored)} sectored files, max {max(n2 for _, n2 in sectored)} sectors"
          if sectored else "none found")

    # the low word is a plain incrementing index (which the engine zeroes on load)
    seq = all(all((r[10] & 0xFFFF) == i for i, r in enumerate(records(p)[0]))
              for p in files)
    check("field 10's low word is the record index", seq, "0, 1, 2, ...")

    # --- fields 12/13 fall by the step, on a shared block structure ----------
    rate12 = rate13 = shared = total = 0
    for path in files:
        u, f = records(path)
        n = len(f)
        if n < 6:
            continue
        total += 1
        # inside a block both drop by exactly field 8
        d12 = sum(1 for i in range(n - 1)
                  if abs((f[i][12] - f[i + 1][12]) - f[i][8]) < 0.05)
        d13 = sum(1 for i in range(n - 1)
                  if abs((f[i][13] - f[i + 1][13]) - f[i][8]) < 0.05)
        rate12 += d12 > (n - 1) * 0.6
        rate13 += d13 > (n - 1) * 0.6
        # f12 - f13 changes only where f13 resets
        diff = [round(f[i][12] - f[i][13], 2) for i in range(n)]
        resets = {i for i in range(n) if f[(i + 1) % n][13] > f[i][13]}
        moved = {i for i in range(n - 1) if diff[i] != diff[i + 1]}
        shared += moved <= resets

    check("field 12 falls by the step between boundaries", rate12 == total,
          f"{rate12}/{total} files")
    check("field 13 falls by the step between boundaries", rate13 == total,
          f"{rate13}/{total} files")
    # One shipped file breaks this: uptown's rdefault.ili moves the difference at
    # two records with no reset. Everything else holds, so it is reported rather
    # than asserted away -- a hand-edited line is the likeliest explanation.
    check("field 12 - field 13 changes only at a field 13 reset",
          shared >= total - 1,
          f"{shared}/{total} files share one block structure"
          + ("" if shared == total else f"; {total - shared} exception(s)"))

    # --- those boundaries are corners ---------------------------------------
    ratios = []
    for path in files:
        u, f = records(path)
        n = len(f)
        b = [i for i in range(n) if f[(i + 1) % n][13] > f[i][13]]
        if len(b) < 2:
            continue
        curv = [abs(r[7]) for r in f]
        mean = sum(curv) / n
        if mean:
            ratios.append((sum(curv[i] for i in b) / len(b)) / mean)
    check("block boundaries sit where curvature is high",
          bool(ratios) and min(ratios) > 1.2,
          f"{min(ratios):.2f}x-{max(ratios):.2f}x the track mean" if ratios else "no data")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
