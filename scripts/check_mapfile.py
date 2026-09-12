"""Check crash-log symbolisation against real binaries.

The interesting case is the v1.0 `race.exe`: it is a Release Candidate that
shipped with its own linker map appended past the last section, which is exactly
where the crash handler looks. So its symbols are real names rather than the
`sub_<va>` placeholders inference produces, and a dump it wrote can be read back
in full.

Run:  python scripts/check_mapfile.py [Data-folder]
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import mapfile  # noqa: E402

DEFAULT_DATA = (Path.home() / "Desktop" / "claude-code" / "game-files"
                / "installs" / "v1.0-RC")

# A real dump, written by the game. The first frame is labelled `my_handler` by
# the handler itself, which gives an independent check on the map's alignment:
# resolving it must land on that function at byte 0.
REAL_DUMP = """NON-DEBUG
( 00415680 , none , my_handler )
( 00416049 , EXCEPTION_ACCESS_VIOLATION , ? )
( 00411407, call-stack , ? )
( 004112C4, call-stack , ? )
( 00470F68, call-stack , ? )
( 00401542, call-stack , ? )
( 0040147B, call-stack , ? )
( 00412380, call-stack , ? )
"""

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> None:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    try:
        eng = mapfile.engine(data)
    except mapfile.MapError as e:
        print(f"  {e}")
        sys.exit(1)
    print(f"source: {data}  (engine: {eng.name})\n")

    syms, src = mapfile.symbols(data)
    has_real_map = src == "embedded map"
    check("an engine binary is found, live one first", eng.name in mapfile.ENGINE_NAMES,
          eng.name)
    check("symbols are available", len(syms) > 100, f"{len(syms):,} from {src}")

    frames = mapfile.resolve_trace(REAL_DUMP, data)
    check("every frame in the dump is parsed", len(frames) == 8, str(len(frames)))
    check("the exception kind is carried through",
          any(k == "EXCEPTION_ACCESS_VIOLATION" for _, k, _, _ in frames))

    if has_real_map:
        # The handler named frame 0 itself; the map must agree, at byte 0.
        addr, _, name, off = frames[0]
        check("frame 0 resolves to the handler the dump names",
              mapfile.pretty(name) == "my_handler", mapfile.pretty(name))
        check("and lands on its FIRST byte, which checks the map's alignment",
              off == 0, f"+0x{off:x}")
        # The documented deliberate fault: abend()+0x9 raises so the handler runs.
        _, _, n1, o1 = frames[1]
        check("frame 1 is abend()+0x9, the deliberate fault",
              mapfile.pretty(n1) == "abend" and o1 == 0x9,
              f"{mapfile.pretty(n1)}+0x{o1:x}")
        names = [mapfile.pretty(n) for _, _, n, _ in frames]
        check("the call chain reads bottom-up as WinMain -> AppMain -> app_begin",
              names[-1].startswith("_WinMain") and names[-2] == "AppMain"
              and names[-3] == "app_begin", " <- ".join(names[-3:]))
        check("every offset is small, so each address really is inside its function",
              all(o < 0x4000 for _, _, _, o in frames),
              f"max +0x{max(o for _, _, _, o in frames):x}")
        check("no frame is left unresolved", all(n != "?" for _, _, n, _ in frames))

    check("pretty() undecorates an MSVC name",
          mapfile.pretty("?my_handler@@YGJPAU_EXCEPTION_POINTERS@@@Z") == "my_handler")
    check("pretty() passes undecorated names through untouched",
          mapfile.pretty("_WinMain@16") == "_WinMain@16"
          and mapfile.pretty("sub_00401000") == "sub_00401000")

    # A binary with no appended map must fall back rather than fail.
    tmp = Path(tempfile.mkdtemp(prefix="check_mapfile_"))
    try:
        bare = tmp / "race.bin"
        blob = eng.read_bytes()
        lay = mapfile._layout(blob)
        bare.write_bytes(blob[:lay.image_end])          # truncate the map away
        s2, src2 = mapfile.symbols(tmp)
        check("a binary with no map falls back to inference",
              src2 == "inferred from call targets", src2)
        check("the fallback still names something", len(s2) > 100, f"{len(s2):,}")
        check("read_map() reports nothing for it", mapfile.read_map(bare.read_bytes()) == {})
        if has_real_map:
            check("...and the real map has far more symbols than inference",
                  len(syms) > len(s2) * 2, f"{len(syms):,} vs {len(s2):,}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        for f in failures:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
