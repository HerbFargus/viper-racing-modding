"""Checks for the string table and the AI driver renamer.

Runs against a synthetic .lng, so it needs no game files. Point it at a real
install as an optional argument to additionally exercise the shipped file.

    python scripts/check_ainames.py [path/to/Data]

WHAT THESE ARE GUARDING. english.lng is not a text file: it is an index of
(key offset, value offset) pairs over a blob of packed strings, and the only
reason a name can be longer than the one it replaces is that lng.py appends the
new string and repoints the offset instead of overwriting in place. That means
a bug here does not look like a crash -- it looks like the wrong string, or a
menu elsewhere in the game reading garbage, noticed weeks later. So every
write is checked by reading the whole table back and asserting that exactly the
intended entries moved and nothing else did.
"""
from __future__ import annotations

import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import ainames, lng  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def synthetic(pairs: list[tuple[str, str]]) -> bytes:
    """Build a string table in the shipped layout, so the checks exercise the
    real parser rather than a convenient stand-in."""
    header = bytearray(lng.TABLE_AT)
    header[0:4] = lng.MAGIC
    header[4:8] = lng.KIND
    struct.pack_into("<I", header, lng.COUNT_AT, len(pairs))
    table = bytearray(len(pairs) * lng.ENTRY)
    blob = bytearray()
    base = lng.TABLE_AT + len(table)
    seen: dict[bytes, int] = {}

    def intern(s: str) -> int:
        b = s.encode("latin-1")
        if b not in seen:
            seen[b] = base + len(blob)
            blob.extend(b + b"\0")
        return seen[b]

    for i, (k, v) in enumerate(pairs):
        struct.pack_into("<II", table, i * lng.ENTRY,
                         intern(k) - lng.OFFSET_BIAS, intern(v) - lng.OFFSET_BIAS)
    return bytes(header) + bytes(table) + bytes(blob)


def stock_lng() -> list[tuple[str, str]]:
    pairs = [("ProductName:ViperRacing", "Viper Racing")]
    for tier, names in ainames.STOCK.items():
        for slot, name in enumerate(names):
            pairs.append((ainames.KEY.format(tier=tier, slot=slot), name))
    pairs.append(("Tracks:Bemidji:Name", "Bemidji"))
    return pairs


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="check_ainames_"))
    try:
        pairs = stock_lng()
        f = tmp / "english.lng"
        f.write_bytes(synthetic(pairs))

        # --- the parser ----------------------------------------------------
        t = lng.read(f)
        check("a synthetic table parses", len(t.entries) == len(pairs),
              f"{len(t.entries)} entries")
        check("keys and values round-trip", t.entries == pairs)

        for name, mangle in (
            ("a bad magic is rejected", lambda b: b"XXXX" + b[4:]),
            ("a count past the end is rejected",
             lambda b: b[:lng.COUNT_AT] + struct.pack("<I", 99999)
             + b[lng.COUNT_AT + 4:]),
        ):
            bad = tmp / "bad.lng"
            bad.write_bytes(mangle(f.read_bytes()))
            try:
                lng.read(bad)
                check(name, False, "parsed something it should not have")
            except lng.LngError:
                check(name, True)

        # An offset landing mid-string is the failure that would corrupt a
        # write, so it has to be caught at read time rather than trusted.
        blob = bytearray(f.read_bytes())
        ko, vo = struct.unpack_from("<II", blob, lng.TABLE_AT)
        struct.pack_into("<I", blob, lng.TABLE_AT, ko + 2)
        bad = tmp / "mid.lng"
        bad.write_bytes(bytes(blob))
        try:
            lng.read(bad)
            check("an offset into the middle of a string is rejected", False)
        except lng.LngError:
            check("an offset into the middle of a string is rejected", True)

        # --- the write ------------------------------------------------------
        long_name = "Bartholomew Featherstonehaugh"
        before = f.read_bytes()
        n = lng.set_values(f, {"AIDriverName:Easy:Driver1": long_name})
        after = lng.read(f)
        check("a name LONGER than the one it replaces is written", n == 1,
              f"{len(long_name)} chars over 'Berg'")
        check("...and reads back exactly",
              after.value("AIDriverName:Easy:Driver1") == long_name)
        check("...by growing the file, not overwriting a neighbour",
              f.stat().st_size == len(before) + len(long_name) + 1,
              f"{len(before):,} -> {f.stat().st_size:,}")
        moved = [i for i, (a, b) in enumerate(zip(t.entries, after.entries))
                 if a != b]
        want = [i for i, (k, _) in enumerate(pairs)
                if k == "AIDriverName:Easy:Driver1"]
        check("...and exactly one entry changed, the intended one",
              moved == want, f"changed {moved}, expected {want}")
        check("...with the original string still in the file",
              b"Berg\0" in f.read_bytes(),
              "which is what makes a revert exact")

        lng.set_values(f, {"AIDriverName:Easy:Driver1": "Berg"})
        check("reverting restores the table exactly",
              lng.read(f).entries == pairs)

        n = lng.set_values(f, {"AIDriverName:Easy:Driver1": "Berg"})
        check("rewriting an unchanged value is a no-op", n == 0,
              "so re-applying does not grow the file forever")

        try:
            lng.set_values(f, {"NoSuchKey:At:All": "x"})
            check("an unknown key is an error, not a silent no-op", False)
        except lng.LngError:
            check("an unknown key is an error, not a silent no-op", True)

        # --- the feature ----------------------------------------------------
        check("a fresh file reads as stock", ainames.is_stock(tmp))
        check("...and every slot reads as unset", ainames.current(tmp)
              == [None] * 7, "the tiers disagree, so there is no one name")

        changed = ainames.apply(tmp, ["Seamus", "Herb", "", None, "Ada"])
        # 3 filled slots: 7 tiers hold that slot, Career5 only holds slot 0.
        check("apply writes across every tier", changed == 3 * 7 + 1,
              f"{changed} entries")
        got = ainames.read_all(tmp)
        check("...the same name in Easy and in Hard",
              got["Easy"][0] == "Seamus" and got["Hard"][0] == "Seamus")
        check("...Career5 takes only the first name",
              got["Career5"] == ["Seamus"])
        check("...an empty slot keeps MGI's name",
              got["Easy"][2] == "Hall" and got["Easy"][3] == "Hecker",
              "half-filling the form is not a request to blank the rest")
        check("...and current() reports what was set",
              ainames.current(tmp)[:2] == ["Seamus", "Herb"]
              and ainames.current(tmp)[2] is None)
        check("a renamed roster is not stock", not ainames.is_stock(tmp))

        over = ainames.too_long(["Seamus", "Bartholomew Featherstonehaugh"])
        check("too_long flags a name past MGI's longest", over == [(1, over[0][1])]
              if over else False, f"SOFT_MAX={ainames.SOFT_MAX}")
        check("...and is advisory only -- apply still wrote it",
              ainames.apply(tmp, ["Bartholomew Featherstonehaugh"]) > 0,
              "the file has no limit; the screen might")

        ainames.reset(tmp)
        check("reset puts MGI's names back", ainames.is_stock(tmp))
        check("...and leaves the other keys alone",
              lng.read(f).value("Tracks:Bemidji:Name") == "Bemidji",
              "english.lng also holds the track names the switcher writes")

        saved = lng.compact(f)
        check("compact reclaims the appended strings", saved > 0,
              f"{saved} bytes")
        check("...without changing what the table says",
              lng.read(f).entries == pairs)

        # --- optional: the shipped file -------------------------------------
        if len(sys.argv) > 1:
            data = Path(sys.argv[1])
            real = ainames.lang_file(data)
            if not real.is_file():
                print(f"  --    no english.lng under {data}, skipping")
            else:
                print(f"\nagainst {real}")
                work = tmp / "real"
                work.mkdir()
                shutil.copy2(real, work / "english.lng")
                t = lng.read(work / "english.lng")
                check("the shipped table parses", len(t.entries) > 0,
                      f"{len(t.entries)} entries")
                check("...and the index ends where the strings begin",
                      lng.TABLE_AT + t.count * lng.ENTRY
                      == min(o for o in [
                          (struct.unpack_from("<I", t.raw,
                                              lng.TABLE_AT + i * lng.ENTRY)[0]
                           + lng.OFFSET_BIAS) for i in range(t.count)]),
                      "the check that count and layout agree")
                check("it ships the stock roster", ainames.is_stock(work))
                ainames.apply(work, ["Seamus"] * 7)
                check("...renames cleanly", ainames.current(work)[0] == "Seamus")
                ainames.reset(work)
                check("...and resets back to stock", ainames.is_stock(work))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
