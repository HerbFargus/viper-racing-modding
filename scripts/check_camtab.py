"""Checks for `camera.tab` — a track's broadcast cameras.

Structural claims run against the SHIPPED files; the reader and writer are checked
for self-consistency and run anywhere.

    python scripts/check_camtab.py path/to/Data

WHAT THESE GUARD. The record geometry is derivable two ways — the header stores the
record size, and it also falls out of `(len - 76) / count` — and an early version of
this work read it from the wrong header offset, got zero, and silently reported every
camera in a track as sitting at the position of camera 0. So the two derivations are
checked against each other on every shipped file. The 32-slot runtime ceiling is
checked because the loader does not check it.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import archive, camtab, envelope, ili  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def shipped(data: Path):
    out = []
    for p in sorted(data.glob("*.trk")):
        try:
            by = {e.name.lower(): e for e in archive.read(p)}
        except Exception:                                        # noqa: BLE001
            continue
        if "camera.tab" in by:
            e = by["camera.tab"]
            out.append((p.stem, envelope.build(e.tag, e.version, e.payload), by))
    return out


def main() -> int:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    samples = shipped(data) if data and data.is_dir() else []

    print("camera.tab -- the shipped files")
    if not samples:
        print("  no Data folder given -- pass one to check the shipped files")
    else:
        bad = [n for n, raw, _ in samples
               if camtab.build_raw(camtab.parse_raw(raw)) != envelope.parse(raw).payload]
        check("every shipped camera.tab rebuilds byte-identically", not bad,
              f"{len(samples)} tracks" if not bad else str(bad))

        # The record size is stored AND derivable. An early version of this work
        # read it from the wrong offset and got 0, which made every record alias
        # to record 0 -- and the size check was the thing that would have caught it.
        mismatch = []
        for n, raw, _ in samples:
            pay = envelope.parse(raw).payload
            count = struct.unpack_from("<i", pay, 0)[0]
            stored = struct.unpack_from("<i", pay, camtab.SIZE_AT)[0]
            derived = (len(pay) - camtab.HEADER_SIZE) // count
            if stored != derived or stored != camtab.RECORD_SIZE:
                mismatch.append((n, stored, derived))
        check("the stored record size agrees with the derived one", not mismatch,
              f"{camtab.RECORD_SIZE} bytes everywhere" if not mismatch else str(mismatch))

        cams = {n: camtab.parse(raw) for n, raw, _ in samples}
        kinds = {}
        for v in cams.values():
            for c in v:
                kinds[c.type] = kinds.get(c.type, 0) + 1
        check("every camera type is one the engine accepts",
              set(kinds) <= set(camtab.TYPES),
              ", ".join(f"{k} x{v}" for k, v in sorted(kinds.items())))

        over = [(n, len(v)) for n, v in cams.items() if len(v) > camtab.MAX_CAMERAS]
        check(f"no shipped track exceeds the {camtab.MAX_CAMERAS}-slot runtime array",
              not over, f"most is {max(len(v) for v in cams.values())}"
              if not over else str(over))

        slot0 = [n for n, v in cams.items() if v and v[0].type != "fixed"]
        check("slot 0 is always fixed -- selection scans from index 1, so it never "
              "comes up automatically", not slot0,
              f"{len(cams)} tracks" if not slot0 else str(slot0))

        # The aim: every fixed camera should point at the track it was placed for.
        misses = []
        for n, raw, by in samples:
            if "default.ili" not in by:
                continue
            e = by["default.ili"]
            line = [(q.x, q.z) for q in
                    ili.parse(envelope.build(e.tag, e.version, e.payload))]
            for c in camtab.parse(raw):
                if c.type != "fixed":
                    continue
                fx, _fy, fz = c.forward
                mag = math.hypot(fx, fz) or 1.0
                fx, fz = fx / mag, fz / mag
                best = min((abs((tx - c.x) * fz - (tz - c.z) * fx)
                            for tx, tz in line
                            if (tx - c.x) * fx + (tz - c.z) * fz > 0), default=1e9)
                misses.append(best)
        if misses:
            worst = max(misses)
            check("every fixed camera aims at its own racing line", worst < 30.0,
                  f"median {sorted(misses)[len(misses)//2]:.1f} m, worst {worst:.1f} m, "
                  f"{len(misses)} cameras")

    print("\ncamera.tab -- reading and writing")
    cams = [camtab.Camera("fixed", 100.0, 8.0, -200.0, 0.0, 90.0, 0.0),
            camtab.Camera("pan_zoom", -50.0, 4.5, 30.0, 0.8, 5.0, 0.0)]
    raw = camtab.build(cams)
    back = camtab.parse(raw)
    check("values survive a build/parse round-trip",
          [(c.type, c.x, c.y, c.z, c.a1, c.a2, c.a3) for c in back]
          == [(c.type, c.x, c.y, c.z, c.a1, c.a2, c.a3) for c in cams],
          f"{len(cams)} cameras")
    check("the payload is header + n x record",
          len(raw) == camtab.HEADER_SIZE + len(cams) * camtab.RECORD_SIZE,
          f"{len(raw)} bytes")
    check("text round-trips too",
          [c.type for c in camtab.parse_text(camtab.to_text(cams))] == [c.type for c in cams])

    try:
        camtab.build([camtab.Camera("fixed", 0, 0, 0)] * (camtab.MAX_CAMERAS + 1))
        check("more than 32 cameras is refused", False, "accepted an overrun")
    except camtab.CamTabError:
        check("more than 32 cameras is refused", True,
              "the loader would overrun TVCamera[32]")
    try:
        camtab.build([camtab.Camera("orbit", 0, 0, 0)])
        check("an unknown camera type is refused", False, "accepted it")
    except camtab.CamTabError:
        check("an unknown camera type is refused", True, "the engine LogPanics on this")

    print("\ncamera.tab -- aiming")
    # forward = (sin yaw, 0, cos yaw): 0 looks +Z, 90 looks +X.
    for yaw, want in ((0.0, (0.0, 1.0)), (90.0, (1.0, 0.0)),
                      (180.0, (0.0, -1.0)), (-90.0, (-1.0, 0.0))):
        fx, _fy, fz = camtab.forward(0.0, yaw, 0.0)
        check(f"yaw {yaw:>6.0f} looks toward ({want[0]:+.0f}, {want[1]:+.0f})",
              abs(fx - want[0]) < 1e-6 and abs(fz - want[1]) < 1e-6,
              f"({fx:+.3f}, {fz:+.3f})")
    check("a zero rotation is the identity, looking +Z",
          camtab.forward(0, 0, 0) == (0.0, 0.0, 1.0),
          "the VectorLength < 0.0001 path in update_camera")

    # aim() must actually point at what it is given, including height.
    eye = (-100.0, 12.0, 40.0)
    worst = 0.0
    for tgt in ((200.0, 0.0, 40.0), (-100.0, 0.0, 500.0), (-400.0, 30.0, -60.0),
                (0.0, -20.0, 0.0), (-100.0, 80.0, 41.0)):
        f = camtab.forward(*camtab.aim(eye, tgt))
        d = [t - e for t, e in zip(tgt, eye)]
        n = math.sqrt(sum(c * c for c in d))
        d = [c / n for c in d]
        worst = max(worst, math.degrees(math.acos(
            max(-1.0, min(1.0, sum(a * b for a, b in zip(f, d)))))))
    check("aim() points at its target in three dimensions, height included",
          worst < 0.2, f"worst error {worst:.3f} deg over 5 targets")

    # Real readings off the engine's own HUD (page 6) from the free-roam camera,
    # holding a heading near +90 while pitching. Measurements, not constructions:
    # a change to rotation() or forward() that broke these would be wrong.
    print("\ncamera.tab -- against readings taken from the game")
    for tri, heading, pitch in (((0.0, 90.0, 0.0), 90.0, 0.0),
                                ((33.0, 86.0, -33.0), 90.6, -42.1),
                                ((-37.0, 87.0, 37.0), 93.4, 47.1)):
        fx, fy, fz = camtab.forward(*tri)
        h = math.degrees(math.atan2(fx, fz))
        p = math.degrees(math.asin(max(-1.0, min(1.0, fy))))
        check(f"{str(tri):>21} decodes to heading {heading:+.1f}, pitch {pitch:+.1f}",
              abs(h - heading) < 0.5 and abs(p - pitch) < 0.5,
              f"got heading {h:+.1f}, pitch {p:+.1f}")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
