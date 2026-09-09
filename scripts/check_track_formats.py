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

from vrmod import archive, bsp  # noqa: E402

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


if __name__ == "__main__":
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    compiled = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    check_bsp(data, compiled)
    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        print("failed: " + ", ".join(failures))
        sys.exit(1)
