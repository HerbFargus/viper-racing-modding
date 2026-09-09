"""Check the native track-format writers against real tracks.

The goal these serve is building a track without the original MKWORLD toolchain.
Each format gets the same treatment: write it natively, then compare against
every example we hold -- the 8 stock tracks, any community tracks in the Data
folder, and anything freshly compiled by the original tools.

Run:  python scripts/check_track_formats.py [Data-folder] [compiled-out-folder]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, bsp, envelope, sol  # noqa: E402

DEFAULT_DATA = Path.home() / "Desktop" / "claude-code" / "game-files" / "Viper Racing" / "Data"
SKIP = ("TEST", "BACKUP", "LEFTOVER", "pristine")

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def tracks(data: Path):
    """Every track archive worth comparing against, stock or community."""
    for p in sorted(list(data.glob("*.trk")) + list(data.glob("*.tra"))):
        if any(k in p.name for k in SKIP):
            continue
        try:
            yield p, {e.name.lower(): e for e in archive.read(p)}
        except Exception:
            continue


def check_bsp(data: Path, compiled: Path | None) -> None:
    print("track.bsp -- fixed world-bounds record")
    seen = 0
    for p, members in tracks(data):
        e = members.get("track.bsp")
        if e is None:
            continue
        seen += 1
        payload = bsp.parse(e.payload)
        diffs = bsp.differences(payload)
        if diffs:
            check(f"{p.name} matches the canonical record", False, f"offsets {diffs[:8]}")
            return
    check(f"canonical record matches all {seen} tracks on disk", seen > 0, f"{seen} archives")

    # A freshly compiled .bsp is the stronger test: it is what MKWORLD writes
    # today, not what shipped in 1998.
    if compiled and (compiled / "track.bsp").exists():
        payload = bsp.parse((compiled / "track.bsp").read_bytes())
        raw = bsp.differences(payload, ignore_noise=False)
        check("matches a freshly compiled track (ignoring padding + 1-ULP drift)",
              not bsp.differences(payload), f"{len(raw)} raw byte diffs, all noise")
    else:
        print("  SKIP  no compiled track.bsp given -- pass its folder as argv[2]")

    check("build() emits a complete file", len(bsp.build()) == bsp.SIZE + 20,
          f"{len(bsp.build())} bytes")
    check("build() round-trips through parse()", bsp.parse(bsp.build()) == bsp.PAYLOAD)


def check_sol(data: Path, compiled: Path | None) -> None:
    print()
    print("track.sol -- collision solids")
    seen = exact = 0
    empties = []
    for p, members in tracks(data):
        e = members.get("track.sol")
        if e is None:
            continue
        seen += 1
        parsed = sol.parse(e.payload)
        if envelope.parse(sol.build(parsed)).payload == e.payload:
            exact += 1
        else:
            check(f"{p.name} round-trips byte-exact", False)
            return
        if parsed.is_empty:
            empties.append(p.stem)
    check(f"all {seen} .sol files round-trip byte-exact", seen and exact == seen,
          f"{exact}/{seen}")

    # An empty .sol is a shipped configuration, not a degenerate case -- several
    # community tracks carry one -- so synthesising it is worth getting right.
    check("empty() is what the compiler writes for a wall-less scene",
          len(empties) > 0, f"tracks shipping an empty .sol: {', '.join(empties) or 'none'}")

    if compiled and (compiled / "track.sol").exists():
        raw = (compiled / "track.sol").read_bytes()
        parsed = sol.parse(raw)
        check("a freshly compiled .sol round-trips",
              sol.build(parsed) == raw,
              f"{len(parsed.primitives)} primitives, {len(parsed.tail):,}-byte tail")
        if parsed.is_empty:
            check("empty() reproduces the compiler byte-for-byte", sol.empty() == raw)

    # Refusing to invent a spatial index is deliberate; keep it that way.
    populated = sol.Sol(primitives=[sol.Primitive(bytes(sol.RECORD_SIZE))], index=[0], tail=b"")
    try:
        sol.build(populated)
        check("build() refuses to invent a tail for a populated .sol", False, "it did not raise")
    except sol.SolError:
        check("build() refuses to invent a tail for a populated .sol", True)


if __name__ == "__main__":
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    compiled = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    check_bsp(data, compiled)
    check_sol(data, compiled)
    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        print("failed: " + ", ".join(failures))
        sys.exit(1)
