"""Swap the horn for Streets of SimCity's missile launch.

    python missilesound.py <sosc.iso> <cars_dir> [SOUND_NAME]

SoSC keeps its effects as plain WAVs in /SOUND on the disc, under names that say
what they are -- so unlike the wheels and the dash, nothing here has to be
identified by eye. The rocket set is:

    MISSILE.WAV   18,860 bytes  the launch      <- default
    RCKTFLY.WAV   38,956 bytes  the flight loop
    RCKEXPL.WAV   97,226 bytes  the detonation
    MISLLPU.WAV   17,580 bytes  the pickup

All four are 8-bit mono 22,050 Hz. A .sfx wants 16-bit mono, which mksfx.exe
required too, so the depth conversion below is not a liberty -- an 8-bit WAV was
never a valid input to the original tool either.

It is installed per-car as horn.sfx rather than into race.res. That much is
settled: the shared sounds are documented as defaults a car's own copy beats, and
horn.sfx is named as one of them. (ball.mod, which missile.py writes the same
way, is the unsettled one -- see that file.)
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vrmod import archive, sfx                                   # noqa: E402

SECTOR = 2048
DEFAULT = "MISSILE.WAV"
TARGET = "horn.sfx"


def iso_files(iso: Path) -> dict:
    """{/PATH/NAME.EXT: (lba, size)} for every file on an ISO9660 disc."""
    fh = iso.open("rb")

    def sector(n):
        fh.seek(n * SECTOR)
        return fh.read(SECTOR)

    pvd = sector(16)
    if pvd[1:6] != b"CD001":
        raise SystemExit(f"{iso.name} is not an ISO9660 image")
    root = pvd[156:156 + 34]

    out = {}

    def walk(lba, length, path="", depth=0):
        if depth > 8:
            return
        fh.seek(lba * SECTOR)
        data = fh.read(length)
        o = 0
        while o < len(data):
            ln = data[o]
            if ln == 0:                      # padding to the end of the sector
                o = (o // SECTOR + 1) * SECTOR
                if o >= len(data):
                    break
                continue
            rec = data[o:o + ln]
            ext = struct.unpack_from("<I", rec, 2)[0]
            size = struct.unpack_from("<I", rec, 10)[0]
            is_dir = rec[25] & 2
            name = rec[33:33 + rec[32]].decode("latin-1")
            if name not in ("\x00", "\x01"):     # "." and ".."
                full = f"{path}/{name.split(';')[0]}"
                if is_dir:
                    walk(ext, size, full, depth + 1)
                else:
                    out[full.upper()] = (ext, size)
            o += ln

    walk(struct.unpack_from("<I", root, 2)[0],
         struct.unpack_from("<I", root, 10)[0])
    out["__fh__"] = fh
    return out


def read_file(files: dict, name: str) -> bytes:
    hits = [k for k in files if k.endswith("/" + name.upper())]
    if not hits:
        raise SystemExit(f"{name} is not on the disc")
    lba, size = files[hits[0]]
    fh = files["__fh__"]
    fh.seek(lba * SECTOR)
    return fh.read(size)


def to_16bit_mono(wav: bytes):
    """8-bit unsigned PCM -> 16-bit signed, which is what a .sfx carries."""
    if wav[0:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise SystemExit("not a RIFF/WAVE file")
    fmt = data = None
    pos = 12
    while pos + 8 <= len(wav):
        cid = wav[pos:pos + 4]
        size = struct.unpack_from("<I", wav, pos + 4)[0]
        chunk = wav[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = chunk
        elif cid == b"data":
            data = chunk
        pos += 8 + size + (size % 2)
    tag, ch, rate, _br, _ba, bits = struct.unpack_from("<hhiihh", fmt, 0)
    if tag != 1:
        raise SystemExit(f"format {tag} is not PCM")
    if ch != 1:
        raise SystemExit(f"{ch} channels -- expected mono")
    if bits == 16:
        samples = data
    elif bits == 8:
        # 8-bit WAV is UNSIGNED and centred on 128; 16-bit is signed and centred
        # on 0. Subtract the bias before scaling or the whole clip arrives with a
        # large DC offset, which plays as a click and clips the loud half.
        samples = b"".join(struct.pack("<h", (b - 128) * 256) for b in data)
    else:
        raise SystemExit(f"{bits}-bit is neither 8 nor 16")
    return sfx.SfxInfo(format_tag=1, channels=1, sample_rate=rate,
                       byte_rate=rate * 2, block_align=2, bits_per_sample=16,
                       sample_data=samples), bits, rate, len(samples) // 2


def main(argv):
    if len(argv) not in (2, 3):
        raise SystemExit(__doc__.strip().splitlines()[2])
    iso, cars = Path(argv[0]), Path(argv[1])
    want = argv[2] if len(argv) > 2 else DEFAULT
    files = iso_files(iso)
    wav = read_file(files, want)
    info, bits, rate, n = to_16bit_mono(wav)
    raw = sfx.build(info)
    print(f"  {want}: {len(wav):,} bytes, {bits}-bit {rate} Hz mono, "
          f"{n:,} samples ({n / rate:.2f}s) -> {len(raw):,} byte .sfx")
    for car in sorted(cars.glob("*.car")):
        entries = archive.upsert_entry(archive.read(car), TARGET, raw)
        archive.write(entries, car)
        print(f"  {car.stem:10s} {TARGET} replaced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
