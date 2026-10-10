"""A rolling-boulder horn: a seamless 2 s loop of rumble, thuds, grind and gravel, generated.

The horn is a short loop the game repeats while the horn is held (stock horn.sfx is
0.44 s), and a car carrying its own horn.sfx overrides the shared one in race.res
(confirmed in game). Everything here is periodic over the loop -- noise is shaped in
the frequency domain of the whole loop, and every event wraps around its end -- so
the loop point never clicks.

    python make_rumble.py <car> [<car> ...]     (keeps <car>.rumble-backup beside Backups/)
"""
import io
import shutil
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
from vrmod import archive, envelope, sfx  # noqa: E402

RATE, SECONDS = 22050, 2.0
N = int(RATE * SECONDS)


def band_noise(lo, hi, rng, tilt=0.0):
    """Periodic noise with energy only between lo and hi Hz (tilt < 0 leans low)."""
    spec = rng.normal(size=N // 2 + 1) + 1j * rng.normal(size=N // 2 + 1)
    f = np.fft.rfftfreq(N, 1 / RATE)
    gain = ((f >= lo) & (f <= hi)).astype(float)
    gain *= np.where(f > 0, (np.maximum(f, 1.0) / max(lo, 1.0)) ** tilt, 0.0)
    x = np.fft.irfft(spec * gain, N)
    return x / (np.abs(x).max() + 1e-12)


def wrap_add(dst, src, at):
    idx = (np.arange(len(src)) + at) % N
    np.add.at(dst, idx, src)


def rumble(seed=1981):
    rng = np.random.default_rng(seed)
    t = np.arange(N) / RATE
    # the body: deep rumble, swelling slowly (periods that divide the loop)
    body = band_noise(30, 220, rng, tilt=-0.8)
    body *= 0.75 + 0.25 * np.sin(2 * np.pi * t / SECONDS) * np.sin(2 * np.pi * 3 * t / SECONDS + 1.0)
    # the thuds: the stone rolling over its flat faces, irregular, ~3.5 a second
    thuds = np.zeros(N)
    k = np.arange(int(0.35 * RATE)) / RATE
    at = 0.0
    while at < SECONDS - 1e-6:
        f0 = rng.uniform(38, 60)
        ph = 2 * np.pi * f0 * k * (1 - 0.35 * k)
        # a fundamental plus the overtones a small speaker can actually play
        hit = (np.sin(ph) + 0.55 * np.sin(2 * ph + 0.4) + 0.35 * np.sin(3.1 * ph)) * np.exp(-k / rng.uniform(0.06, 0.11))
        wrap_add(thuds, hit * rng.uniform(0.55, 1.0), int(at * RATE))
        at += rng.uniform(0.22, 0.36)
    # the grind: stone on stone, mid band, gated by the thuds' rhythm
    gate = (np.abs(thuds) > 0.15).astype(float)
    gate = np.convolve(np.concatenate([gate[-400:], gate]), np.ones(400) / 400, "valid")[:N]   # smooth the gate, not the grind
    grind = band_noise(160, 900, rng) * (0.45 + 0.55 * gate / (gate.max() + 1e-12))
    # gravel: sparse crunches, bright and short
    gravel = np.zeros(N)
    for _ in range(int(SECONDS * 22)):
        n = int(rng.uniform(0.004, 0.012) * RATE)
        crunch = rng.normal(size=n) * np.exp(-np.arange(n) / (n / 4))
        wrap_add(gravel, crunch * rng.uniform(0.2, 1.0), int(rng.uniform(0, N)))
    gravel = np.fft.irfft(np.fft.rfft(gravel) * ((np.fft.rfftfreq(N, 1 / RATE) > 900) &
                                                 (np.fft.rfftfreq(N, 1 / RATE) < 4200)), N)
    gravel /= np.abs(gravel).max() + 1e-12
    mix = 0.7 * body + 0.9 * thuds / (np.abs(thuds).max() + 1e-12) + 0.55 * grind + 0.28 * gravel
    mix = np.tanh(1.4 * mix / np.abs(mix).max())               # a little saturation, like a big mass
    return (mix / np.abs(mix).max() * 0.9 * 32767).astype("<i2")


def as_sfx(samples):
    info = sfx.SfxInfo(format_tag=1, channels=1, sample_rate=RATE, byte_rate=RATE * 2, block_align=2,
                       bits_per_sample=16, sample_data=samples.tobytes())
    return sfx.build(info)


def as_wav(samples):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(np.tile(samples, 3).tobytes())            # three loops, to hear the seam
    return buf.getvalue()


def install(car_path, blob):
    car_path = Path(car_path)
    backup = car_path.parent / "Backups" / (car_path.name + ".rumble-backup")
    if not backup.exists():
        shutil.copy2(car_path, backup)
    data = car_path.read_bytes()
    layout = archive.read_layout(data)
    entries = archive.read_bytes(data)
    env = envelope.parse(blob)
    for e in entries:
        if e.name.lower() == "horn.sfx":
            e.tag, e.version, e.payload = env.tag, env.version, env.payload
            break
    else:
        entries.append(archive.ArchiveEntry(name="horn.sfx", tag=env.tag, version=env.version, payload=env.payload))
    car_path.write_bytes(archive.to_bytes(entries, partitioned=layout.partitioned))
    back = {e.name.lower(): e for e in archive.read(car_path)}
    info = sfx.parse(envelope.build(back["horn.sfx"].tag, back["horn.sfx"].version, back["horn.sfx"].payload))
    return len(info.sample_data) / (info.sample_rate * 2), backup


if __name__ == "__main__":
    s = rumble()
    here = Path(__file__).resolve().parent
    (here / "boulder_rumble.wav").write_bytes(as_wav(s))
    blob = as_sfx(s)
    print(f"rumble: {len(s) / RATE:.1f} s loop at {RATE} Hz; seam step {abs(int(s[0]) - int(s[-1]))} "
          f"(of 32767); preview boulder_rumble.wav (three loops)")
    for car in sys.argv[1:]:
        secs, backup = install(car, blob)
        print(f"{Path(car).name}: horn.sfx is now the rumble ({secs:.1f} s); original kept as {backup.name}")
