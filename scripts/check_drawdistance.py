"""Checks for the draw-distance setting.

Runs against synthetic options files in a temp directory, so it needs no game
files. Point it at a real Data folder as an optional argument to additionally
report what that install is set to.

    python scripts/check_drawdistance.py [path/to/Data]

The point of most of these is that this writes into a file the user's install
depends on. The community view extender rewrote **line 92 by number**; on a file
whose layout differs that lands on whatever else is there. So the checks below
care less about the arithmetic than about what the write leaves behind.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import drawdistance as dd  # noqa: E402

CRLF = "\r\n"
PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def fake_install(root: Path, body: str, *, name: str = "options.cfg") -> tuple[Path, Path]:
    """A Data folder whose sibling Config holds `body` verbatim."""
    data = root / "Data"
    data.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "Config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    f = cfg_dir / name
    f.write_bytes(body.encode("latin-1"))
    return data, f


def options(value: str = "0.500000", *, eol: str = "\r\n", pad: str = "",
            before: int = 90, after: int = 48) -> str:
    """Something shaped like the real file: the key buried in a long list."""
    lines = [f"setting_{i:03d} {i}" for i in range(before)]
    lines.append(f"{dd.KEY} {value}{pad}")
    lines += [f"detail_level 0.500000"]
    lines += [f"other_{i:03d} {i}" for i in range(after)]
    return eol.join(lines) + eol


def raised(fn) -> str | None:
    try:
        fn()
    except dd.SettingError as e:
        return str(e)
    return None


def main() -> int:
    print("draw distance -- the transform")

    # The values traced out of race.bin: fmul 1700, fadd 300.
    check("the shipped 0.5 is 1,150 units",
          dd.effective(dd.DEFAULT_VALUE) == 1150.0, "0.5 * 1700 + 300")
    check("the in-game slider at full is 2,000 units",
          dd.effective(dd.SLIDER_MAX) == 2000.0, "1.0 * 1700 + 300")
    check("the view extender's 100 is 170,300 units",
          dd.effective(dd.INFINITY_VALUE) == 170300.0, "85x the slider")
    check("value_for inverts effective",
          abs(dd.effective(dd.value_for(5000.0)) - 5000.0) < 1e-6, "5,000 units")

    # BASE is added after the multiply, so anything under it is unreachable --
    # better to say so than to write a negative value into the file.
    msg = raised(lambda: dd.value_for(dd.BASE - 1))
    check("refuses a distance under the 300-unit floor", msg is not None, msg or "no error")

    print("\ndraw distance -- reading and writing")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        data, f = fake_install(tmp / "a", options())
        before = f.read_bytes()
        v, found = dd.read(data)
        check("reads the stored value", v == 0.5 and found == f, f"{v} from {found.name}")

        dd.write(data, dd.INFINITY_VALUE)
        after = f.read_bytes()

        # THE check. A whole-file rewrite here is silent -- it looks fine in a
        # text diff and still corrupts an install whose file this is.
        bl, al = before.split(b"\n"), after.split(b"\n")
        changed = [i for i, (x, y) in enumerate(zip(bl, al)) if x != y]
        check("writing changes exactly one line",
              len(changed) == 1 and len(bl) == len(al),
              f"line {changed[0] + 1} of {len(bl)}" if len(changed) == 1
              else f"{len(changed)} lines changed")
        check("and it is the draw_distance line",
              changed == [90] and al[90] == b"draw_distance 100.000000\r",
              al[changed[0]].decode("latin-1", "replace") if changed else "none")

        # read_text translates CRLF to LF; writing that back rewrites the file.
        check("CRLF line endings survive the write",
              after.count(b"\r\n") == before.count(b"\r\n")
              and b"\n" not in after.replace(b"\r\n", b""),
              f"{after.count(chr(13).encode() + chr(10).encode())} CRLF, no bare LF")

        dd.write(data, dd.DEFAULT_VALUE)
        check("a round trip is byte-for-byte the original",
              f.read_bytes() == before, f"{len(before)} bytes")

        # The community tool hardcoded line 92. Nothing here may depend on
        # where the key sits.
        moved, mf = fake_install(tmp / "b", options(before=3, after=200))
        dd.write(moved, dd.SLIDER_MAX)
        v, _ = dd.read(moved)
        lines = mf.read_bytes().split(CRLF.encode())
        check("finds the key by name, not by line number",
              v == 1.0 and lines[3].startswith(b"draw_distance"),
              "key on line 4, still the line rewritten")
        # Line 92 is 1-based, so index 91 -- whatever happens to live there.
        untouched = options(before=3, after=200).split(CRLF)[91].encode("latin-1")
        check("the line the old tool would have hit is untouched",
              lines[91] == untouched, lines[91].decode("latin-1"))

        # An install that has never run the game, or a hand-edited file.
        bare, _ = fake_install(tmp / "c", "detail_level 0.500000\r\n")
        check("says so when there is no draw_distance line",
              raised(lambda: dd.read(bare)) is not None
              and raised(lambda: dd.write(bare, 1.0)) is not None, "both raise")

        empty = tmp / "d" / "Data"
        empty.mkdir(parents=True)
        check("says so when there is no options file at all",
              raised(lambda: dd.read(empty)) is not None, "raises")

        # value*1700+300 with value <= 0 is still a number, and the game would
        # take it; it is never what anyone meant.
        ok, _ = fake_install(tmp / "e", options())
        check("refuses a non-positive value",
              raised(lambda: dd.write(ok, 0.0)) is not None
              and raised(lambda: dd.write(ok, -1.0)) is not None, "both raise")

        # Trailing blanks after the number are part of the line, not the value.
        padded, pf = fake_install(tmp / "f", options(pad="  \t"))
        v, _ = dd.read(padded)
        dd.write(padded, dd.SLIDER_MAX)
        line = pf.read_bytes().split(CRLF.encode())[90]
        check("trailing whitespace is neither eaten nor parsed",
              v == 0.5 and line == b"draw_distance 1.000000  \t",
              repr(line.decode("latin-1")))

        # An LF-only file must not gain CRs either -- preservation both ways.
        lf, lff = fake_install(tmp / "g", options(eol="\n"))
        dd.write(lf, dd.SLIDER_MAX)
        check("an LF-only file stays LF-only",
              b"\r" not in lff.read_bytes(), "no CR introduced")

        # options.def is the fallback when the game has never written a .cfg.
        deff, _ = fake_install(tmp / "h", options(), name="options.def")
        v, found = dd.read(deff)
        check("falls back to options.def", v == 0.5 and found.name == "options.def",
              found.name)

    if len(sys.argv) > 1:
        live = Path(sys.argv[1])
        print(f"\nagainst {live}")
        try:
            v, f = dd.read(live)
            print(f"  {f.name}: {dd.KEY} {v:g} -> {dd.effective(v):,.0f} units")
        except dd.SettingError as e:
            print(f"  {e}")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
