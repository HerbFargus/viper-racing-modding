"""
SFX0 -- .sfx car sound effects (engine loops, horn, shift, crash/UI cues, etc.).

Standard 0SER envelope (tag SFX0) wrapping a WAV-"fmt "-chunk-shaped 20-byte
sub-header, 2 bytes at a fixed offset that are "da" in most real files but not
reliably meaningful (see the header table below), the raw sample bytes, and a
fixed trailing pad. Reverse-engineered by round-tripping controlled synthetic WAV
files through a real community tool (mksfx.exe, plus its accompanying usage guide
describing the naming convention and audio requirements) and cross-checking the
result against real .sfx files -- every OTHER field decodes cleanly and
consistently across all of them.

HEADER (payload-relative offsets, 20 bytes, immediately after the envelope):

    0x00  int32  data_size          -- length of the real sample data in bytes,
                                        NOT including the trailing pad
    0x04  int16  format_tag         -- 1 = PCM, 2 = Microsoft ADPCM (same codes
                                        as the standard Windows WAVEFORMATEX
                                        wFormatTag field). Only PCM is solved so
                                        far -- see SfxInfo.is_pcm / to_wav_bytes.
    0x06  int16  channels           -- 1 (mono) in every real sample seen; the
                                        mksfx guide requires mono explicitly
    0x08  int32  sample_rate        -- 44100 for viper0/1/2.sfx (the RPM-sweep
                                        engine loops), 22050 for viperi.sfx (idle)
    0x0C  int32  byte_rate          -- matches sample_rate * block_align for PCM
    0x10  int16  block_align        -- 2 for 16-bit mono PCM (channels *
                                        bits_per_sample/8); mksfx -a (ADPCM)
                                        changes this to 4, block structure not
                                        yet decoded
    0x14  int16  bits_per_sample    -- 16 in every real sample seen (mksfx guide
                                        requires 16-bit explicitly)
    0x16  2 bytes "da"               -- "da" in every viper.car engine sample AND
                                        12 of race.res's 16 shared UI/gameplay
                                        .sfx files (horn, shift, road, splash,
                                        countdown, spotter-voice cues) -- but the
                                        remaining 4 (crash1/2/3.sfx, squeal.sfx)
                                        have \\x00\\x00 here instead, with every
                                        OTHER header field still fully valid and
                                        every sample still decoding correctly.
                                        Real, non-random pattern (4/4 impact-type
                                        sounds, 0/12 of everything else) rather
                                        than noise, but its actual meaning isn't
                                        understood -- parse() no longer enforces
                                        it, just skips these 2 bytes unread; only
                                        build() still writes literal "da" (its
                                        own output is self-consistent regardless
                                        of whether that's exactly right).

Then `data_size` bytes of raw sample data (PCM: signed 16-bit little-endian mono,
i.e. already exactly what a standard WAV "data" chunk would hold), then a FIXED
4096-byte trailing pad regardless of data_size -- confirmed identical (in size,
not content) across all 4 real viper.car samples (34842/34842/42212/27048-byte
payloads, each followed by exactly 4096 more bytes) and two synthetic tests (40
and 6000 bytes of real data). In at least one synthetic sample this pad was
confirmed to be uninitialized memory leaked by mksfx.exe itself (literal
environment-variable text, e.g. "USE_LOCAL_OAUTH=", turned up inside it) -- not
meaningful content, and not something build() tries to reproduce; it's zero-filled
instead, which is presumably indistinguishable to anything that actually reads
this format (nothing has been found that reads past data_size bytes of real audio).

mksfx.exe's -L ("looped") flag does NOT touch this header or data_size at all --
instead it duplicates the sample data once, writing two back-to-back copies into
the buffer before the pad begins. The reported data_size still describes only one
copy. This looks like a gapless-loop buffer-priming trick rather than a distinct
file format; build() does not attempt to reproduce it (write your source sample
already loop-ready -- see the mksfx guide's note on trimming to a zero-crossing --
and this module just stores it once, like the non-looped case).

NOT YET SOLVED: the ADPCM sample encoding itself (format_tag=2, block_align=4) --
every real .sfx in the retail data uses plain PCM, so this hasn't been forced yet.
(.ens, the per-car engine-sound crossfade parameter file this format's own module
docstring used to list as unexamined, is solved -- see ens.py.)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import envelope

TAG = b"0XFS"  # reversed "SFX0", same convention as every other format here
VERSION = 1
HEADER_SIZE = 20
MARKER = b"da"
TRAILING_PAD_SIZE = 4096

FORMAT_PCM = 1
FORMAT_ADPCM = 2


@dataclass
class SfxInfo:
    format_tag: int
    channels: int
    sample_rate: int
    byte_rate: int
    block_align: int
    bits_per_sample: int
    sample_data: bytes  # exactly data_size bytes, raw (PCM: signed 16-bit LE)

    @property
    def is_pcm(self) -> bool:
        return self.format_tag == FORMAT_PCM

    @property
    def duration_seconds(self) -> float:
        return len(self.sample_data) / self.byte_rate if self.byte_rate else 0.0


def parse(data: bytes) -> SfxInfo:
    """Parse a standalone .sfx file's bytes (0SER envelope included)."""
    env = envelope.parse(data)
    if env.tag != TAG:
        raise ValueError(f"not a .sfx file: tag {env.tag!r}, expected {TAG!r}")
    payload = env.payload
    data_size, format_tag, channels, sample_rate, byte_rate, block_align, bits = (
        struct.unpack_from("<ihhiihh", payload, 0)
    )
    # Not validated -- see the module docstring's header table: real files disagree
    # on what's here (usually "da", but not always), while every other field stays
    # self-consistent regardless, so treating this as a hard requirement would
    # reject real, correctly-decodable data (crash1/2/3.sfx, squeal.sfx).
    data_start = HEADER_SIZE + 2
    sample_data = payload[data_start:data_start + data_size]
    if len(sample_data) != data_size:
        raise ValueError(f"payload too short for declared data_size {data_size} (got {len(sample_data)} bytes)")
    return SfxInfo(
        format_tag=format_tag, channels=channels, sample_rate=sample_rate,
        byte_rate=byte_rate, block_align=block_align, bits_per_sample=bits,
        sample_data=sample_data,
    )


def parse_file(path: str | Path) -> SfxInfo:
    return parse(Path(path).read_bytes())


def build(info: SfxInfo) -> bytes:
    """Serialize an SfxInfo back into standalone .sfx bytes (0SER envelope
    included). Pads with zeros out to TRAILING_PAD_SIZE rather than reproducing
    whatever mksfx.exe happened to leave in that region (uninitialized memory in
    every sample checked, see the module docstring) -- and does not reproduce the
    -L flag's double-copy trick; write an already loop-ready sample instead.
    """
    header = struct.pack(
        "<ihhiihh", len(info.sample_data), info.format_tag, info.channels,
        info.sample_rate, info.byte_rate, info.block_align, info.bits_per_sample,
    )
    payload = header + MARKER + info.sample_data + bytes(TRAILING_PAD_SIZE)
    return envelope.build(TAG, VERSION, payload)


def to_wav_bytes(info: SfxInfo) -> bytes:
    """Build a standard, playable WAV file from the decoded sample data.

    PCM only for now -- .sfx's ADPCM variant (format_tag=2) isn't solved yet (see
    the module docstring), so this raises rather than emitting a WAV whose fmt
    chunk claims ADPCM but doesn't have the extra cbSize/samplesPerBlock fields
    (and fact chunk) a real ADPCM WAV needs to actually be decodable.
    """
    if info.format_tag != FORMAT_PCM:
        raise ValueError(
            f"can't build a WAV for format_tag={info.format_tag} yet -- only PCM "
            f"({FORMAT_PCM}) is understood so far; ADPCM ({FORMAT_ADPCM}) still "
            "needs its block structure reverse-engineered"
        )
    fmt_chunk = struct.pack(
        "<hhiihh", info.format_tag, info.channels, info.sample_rate,
        info.byte_rate, info.block_align, info.bits_per_sample,
    )
    data_chunk = info.sample_data
    if len(data_chunk) % 2:
        data_chunk += b"\x00"  # RIFF chunks are word-aligned
    body = (
        b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt_chunk)) + fmt_chunk
        + b"data" + struct.pack("<I", len(info.sample_data)) + data_chunk
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def sfx_to_wav(sfx_path: str | Path, wav_path: str | Path) -> None:
    info = parse_file(sfx_path)
    Path(wav_path).write_bytes(to_wav_bytes(info))


def from_wav_bytes(data: bytes) -> SfxInfo:
    """Parse a standard RIFF/WAVE file's bytes into an SfxInfo, ready for build()
    -- the reverse of to_wav_bytes(). Used by the Sound drawer's WAV import (see
    cli.py's _apply_commit): a modder's replacement audio arrives as a real WAV
    file, gets parsed here, then build() re-wraps it in the real .sfx envelope/
    header. Requires 16-bit mono PCM -- not a new restriction this adds, that's
    what mksfx.exe itself requires of its input (see the module docstring's
    mksfx-guide reference), just enforced here too rather than silently
    resampling/downmixing something that wouldn't have been a valid mksfx input
    either.
    """
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    fmt_chunk: bytes | None = None
    data_chunk: bytes | None = None
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        chunk_data = data[pos + 8:pos + 8 + chunk_size]
        if chunk_id == b"fmt ":
            fmt_chunk = chunk_data
        elif chunk_id == b"data":
            data_chunk = chunk_data
        pos += 8 + chunk_size + (chunk_size % 2)  # RIFF chunks are word-aligned
    if fmt_chunk is None or data_chunk is None:
        raise ValueError("WAV file is missing a 'fmt ' or 'data' chunk")
    format_tag, channels, sample_rate, byte_rate, block_align, bits_per_sample = (
        struct.unpack_from("<hhiihh", fmt_chunk, 0)
    )
    if format_tag != FORMAT_PCM:
        raise ValueError(
            f"WAV file is format_tag={format_tag}, not PCM ({FORMAT_PCM}) -- "
            "only plain 16-bit PCM WAV files can be converted to .sfx"
        )
    if channels != 1:
        raise ValueError(f"WAV file has {channels} channel(s) -- .sfx requires mono (1 channel)")
    if bits_per_sample != 16:
        raise ValueError(f"WAV file is {bits_per_sample}-bit -- .sfx requires 16-bit samples")
    return SfxInfo(
        format_tag=format_tag, channels=channels, sample_rate=sample_rate,
        byte_rate=byte_rate, block_align=block_align, bits_per_sample=bits_per_sample,
        sample_data=data_chunk,
    )


def wav_to_sfx(wav_path: str | Path, sfx_path: str | Path) -> None:
    info = from_wav_bytes(Path(wav_path).read_bytes())
    Path(sfx_path).write_bytes(build(info))
