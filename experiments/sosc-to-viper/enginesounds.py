"""Give each converted car its own engine note, from the Streets of SimCity disc.

SoSC ships 27 engine samples in `SOUND/ENGINES`, and they are NOT all the same
sound -- every one is distinct by content, and they fall into six families whose
names say what they are:

    396*     Chevrolet big-block          CAM*     Camaro
    CBRA* / COBRA*   Shelby Cobra V8      GHIA*    VW Karmann Ghia flat-four
    MUST*    Mustang V8                   VWBUSMID VW bus

Which car uses which is NOT on the disc in any extractable form -- the only
occurrences of those filenames outside the ISO's own directory table are inside
the executable. So the assignment below is a judgement, and it is a comfortable
one, because the families line up with the real cars these models are:

    airhawk   1969 Camaro        -> CAM     the actual car
    strtrat   VW Beetle          -> GHIA    the Karmann Ghia is a Beetle underneath
    j57       Ford GT40          -> MUST    Ford V8, same family as the GT40's 289
    azzaroni  Ferrari 250 GT     -> COBRA   no V12 on the disc; the throatiest V8
    police    Oldsmobile Cutlass -> 396     GM big-block
    hmxvan    GMC C-Series       -> VWBUS   the only commercial engine there is
    hunter    (no road-car twin) -> CBRA

FORMAT. The two games disagree twice over. SoSC's samples are 8-bit STEREO at
22,050 Hz; Viper's `.sfx` importer requires 16-bit MONO, which is not this
toolkit being fussy -- it is what `mksfx.exe` itself demanded of its input, and
`sfx.from_wav_bytes` enforces it rather than silently resampling something that
was never a valid input. So the conversion is done here, explicitly: average the
two channels, and lift unsigned 8-bit (centre 128) to signed 16-bit.

BANDS. A Viper car carries `<prefix>i.sfx` for idle plus `0`, `1` and sometimes
`2` for load, all short loops the engine pitch-shifts. SoSC's names map onto
that readably: the long, low `OFF`/`END`/`LOW` samples are the idle, `MID` is
the working loop, `HI`/`REV` the upper band. Where a family is missing a band
its nearest sibling is reused -- VWBUS has exactly one sample, so the van runs
the whole range off it, which is what a one-sample family can give you.
"""
from __future__ import annotations

import io
import struct
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from vrmod import archive, envelope, sfx  # noqa: E402

# car prefix -> which sample plays for idle, and for each load band.
# "2" is optional; a car that has no <prefix>2.sfx simply skips it.
#
# No band may be a STRT sample. Those are STARTER MOTORS, not engine notes: the
# Hunter (one of the two cars whose donor has a <prefix>2.sfx slot) looped
# CBRASTRT under its engine in every race, and it read in-game as a constant
# scraping sound. The band plays the upper working loop instead.
FLEET = {
    "airhawk":  dict(i="CAMOFF",   b0="CAMMID",   b1="CAMMID",    b2="CAMMID"),
    "strtrat":  dict(i="GHIAOFF",  b0="GHIAMID",  b1="GHIAMID2",  b2="GHIAMID2"),
    "j57":      dict(i="MUSTEND",  b0="MUSTMID",  b1="MUSTMD1",   b2="MUSTMD1"),
    "azzaroni": dict(i="COBRALOW", b0="COBRAMID", b1="COBRAHI",   b2="COBRAMD2"),
    "police":   dict(i="396END",   b0="396MID",   b1="396MID",    b2="396MID"),
    "hmxvan":   dict(i="VWBUSMID", b0="VWBUSMID", b1="VWBUSMID",  b2="VWBUSMID"),
    "hunter":   dict(i="CBRAOFF",  b0="CBRAREV",  b1="CBRAREV",   b2="CBRAREV"),
}


# A load band is a short loop the engine pitch-shifts with RPM; an idle sample
# can be long. The shipped cars are unambiguous about the difference -- their
# 0/1/2 bands run 0.25-0.48s while their idles run 0.61-2.55s -- and SoSC's
# samples are all recordings, up to 2.29s. Handing the engine a 2.3-second loop
# to pitch-shift gives you a tape of a car, not a car.
MAX_BAND_SECONDS = 0.55


def to_viper_wav(data: bytes, max_seconds: float | None = None) -> bytes:
    """8-bit stereo 22 kHz -> 16-bit mono, the only input .sfx accepts.

    `max_seconds` trims from the MIDDLE, not the start: the front of these
    samples is the recording settling and the tail often fades, so the centre is
    the steadiest stretch and the one that loops without a seam.
    """
    src = wave.open(io.BytesIO(data))
    frames = src.readframes(src.getnframes())
    ch, width, rate = src.getnchannels(), src.getsampwidth(), src.getframerate()

    if width == 1:
        # unsigned 8-bit, silence at 128
        samples = [(b - 128) * 256 for b in frames]
    elif width == 2:
        samples = list(struct.unpack(f"<{len(frames)//2}h", frames))
    else:
        raise SystemExit(f"unsupported sample width {width}")

    if ch == 2:
        samples = [(samples[i] + samples[i + 1]) // 2
                   for i in range(0, len(samples) - 1, 2)]
    elif ch != 1:
        raise SystemExit(f"unsupported channel count {ch}")

    if max_seconds is not None:
        keep = int(rate * max_seconds)
        if len(samples) > keep:
            start = (len(samples) - keep) // 2
            samples = samples[start:start + keep]

    buf = io.BytesIO()
    out = wave.open(buf, "wb")
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(rate)
    out.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    out.close()
    return buf.getvalue()


def apply_to_car(car: Path, prefix: str, engines: Path, plan: dict) -> list[str]:
    """Swap in the engine samples this car is assigned. Returns what changed."""
    entries = archive.read(car)
    have = {e.name.lower() for e in entries}
    wanted = {f"{prefix}i.sfx": plan["i"], f"{prefix}0.sfx": plan["b0"],
              f"{prefix}1.sfx": plan["b1"], f"{prefix}2.sfx": plan["b2"]}

    changed, out = [], []
    for e in entries:
        key = e.name.lower()
        source = wanted.get(key)
        # Only members the car ALREADY has are replaced. Adding a <prefix>2.sfx
        # to a car whose tables never mention one is a different change, and a
        # sound the game does not ask for is dead weight in the archive.
        if source is None:
            out.append(e)
            continue
        # idle keeps its full length; the load bands are trimmed to a loop
        limit = None if key.endswith("i.sfx") else MAX_BAND_SECONDS
        wav = to_viper_wav((engines / f"{source}.WAV").read_bytes(), limit)
        raw = sfx.build(sfx.from_wav_bytes(wav))
        out.append(archive.ArchiveEntry(name=e.name, tag=e.tag,
                                        version=e.version, payload=raw[20:]))
        changed.append(f"{e.name} <- {source}.WAV")
    archive.write(out, car)
    missing = [k for k in wanted if k not in have]
    return changed, missing


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("enginesounds.py <engines_dir> <fleet_dir_or_car>")
    engines, target = Path(sys.argv[1]), Path(sys.argv[2])
    cars = sorted(target.rglob("*.car")) if target.is_dir() else [target]
    for car in cars:
        plan = FLEET.get(car.stem)
        if not plan:
            print(f"  {car.stem:10s} no engine assigned, left alone")
            continue
        changed, missing = apply_to_car(car, car.stem, engines, plan)
        family = plan["b0"].rstrip("0123456789")
        print(f"  {car.stem:10s} {len(changed)} sample(s) from {family}*")
        for line in changed:
            print(f"      {line}")
        if missing:
            print(f"      (no {', '.join(sorted(missing))} in this car -- skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
