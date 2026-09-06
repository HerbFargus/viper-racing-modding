"""
ESFX -- .ens, one per car, engine-sound crossfade parameters (e.g. vipere.ens).

Confirmed structurally by cross-car comparison, not a real tool's own text-dump
output (unlike cf.py/cockpit_tab.py -- no such tool has surfaced for this format):
a FIXED-SIZE 228-byte payload (0SER envelope, tag ESFX) = int32 recordCount + a
fixed 8-slot array of 7-float32 records (28 bytes each; 4 + 8*28 = 228 bytes
exactly), of which only the first `recordCount` slots hold real data. The rest is
uninitialized memory left over from whatever tool originally wrote the file --
same kind of artifact already confirmed independently in .sfx's own trailing pad
(see sfx.py). Confirmed here two ways: the math is exact for both a recordCount=3
car (real data ends at byte 88, matching) and a recordCount=2 car (ends at byte
60, matching), and the "padding" bytes are genuinely different between two
different cars' .ens files while the real leading records are stable -- exactly
what uninitialized memory vs. real data should look like.

recordCount matches, record-for-record in order, the number of non-idle .sfx
files a car actually has (<prefix>0/1/2.sfx) -- confirmed directly against real
data: every Mario-Kart-character-conversion car plus stock viper.car has
recordCount=3 and all three <prefix>0/1/2.sfx files; exotic/plane/sedan/sports
(the same 4 cars already confirmed elsewhere in this project to have no cockpit
and no owned suspension overrides -- likely AI-only/spectator vehicles) have
recordCount=2 and are specifically missing <prefix>2.sfx.

Each 7-float record's individual field meanings are INFERRED from context and
cross-car comparison, not independently confirmed against any real tool's own
labels:

    [0]     "base RPM" (guess) -- possibly the RPM at which this sample's
            natural/recorded pitch is correct (a pitch-shift reference point).
            Identical between the 0.sfx and 1.sfx records on every car checked,
            consistent with the mksfx guide's description of 0.sfx and 1.sfx
            often being paired/similar recordings ("you need samples of both 0
            and 1 at 3000 RPM").
    [1],[2] two small (0-2 range) scalars -- plausibly a volume or pitch-scale
            pair; not confirmed.
    [3],[4] an ascending RPM pair (e.g. 542/1200, 3400/4250) -- plausibly this
            layer's own crossfade RPM range, consistent with the mksfx guide's
            per-file RPM coverage description. Varies per record/car.
    [5]     an RPM value close to (but not exactly) a car's redline (e.g. 6100).
    [6]     10000.0 in literally every record on every car checked, including
            cars whose [3]/[4]/[5] differ -- looks like an engine-wide constant
            rather than real per-car data, not something worth exposing as
            "editable" until proven otherwise.

No build() yet -- read-only until the field semantics are on firmer ground;
writing plausible-looking values back without knowing what they really control
risks silently breaking a car's engine sound rather than tuning it.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import envelope

TAG = b"XFSE"  # reversed "ESFX", same convention as every other format here
RECORD_FIELDS = 7
RECORD_SIZE = RECORD_FIELDS * 4  # 28 bytes
MAX_RECORDS = 8  # (228 - 4) // 28 -- see module docstring
PAYLOAD_SIZE = 4 + MAX_RECORDS * RECORD_SIZE  # 228, always, regardless of recordCount


@dataclass
class EnsInfo:
    records: list[tuple[float, float, float, float, float, float, float]]


def parse(data: bytes) -> EnsInfo:
    """Parse a standalone .ens file's bytes (0SER envelope included)."""
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .ens file: tag {env.tag!r}, expected {TAG!r}")
    payload = env.payload
    count = struct.unpack_from("<i", payload, 0)[0]
    if count < 0 or count > MAX_RECORDS:
        raise ValueError(f"recordCount {count} outside the expected 0..{MAX_RECORDS} range")
    records = [
        struct.unpack_from(f"<{RECORD_FIELDS}f", payload, 4 + i * RECORD_SIZE)
        for i in range(count)
    ]
    return EnsInfo(records=records)


def parse_file(path: str | Path) -> EnsInfo:
    return parse(Path(path).read_bytes())
