"""Synthesised sounds: a source-filter voice for horns (a meow, a bark, a moo...).

A harmonic pulse train whose pitch follows a contour, shaped by three moving formants (vowel
resonances), with a little breath noise. Contours are lists of (time 0..1, value) points.
Horns loop while held, so a horn is one call plus enough silence to breathe, and both ends of
the loop sit at zero (no click at the seam). Write a WAV with a few loops to listen to; the
car build takes the single-loop WAV (16-bit mono, what sfx.from_wav_bytes requires).
"""
from __future__ import annotations

import io
import wave

import numpy as np

RATE = 22050


def contour(points, n):
    t, v = zip(*points)
    return np.interp(np.linspace(0, 1, n), t, v)


def voice(dur, f0, f1, f2, f3, amp, *, bw=(90, 120, 180), jitter=0.0, breath=0.02, seed=1):
    n = int(RATE * dur)
    rng = np.random.default_rng(seed)
    pitch = contour(f0, n)
    if jitter:
        wob = np.cumsum(rng.normal(0, 1, n))
        wob = (wob - np.linspace(wob[0], wob[-1], n)) / (np.abs(wob).max() + 1e-9)
        pitch = pitch * (1 + jitter * wob)
    phase = 2 * np.pi * np.cumsum(pitch) / RATE
    F = [contour(p, n) for p in (f1, f2, f3)]
    out = np.zeros(n)
    for k in range(1, int(5000 / max(pitch.min(), 60)) + 1):
        fk = k * pitch
        gain = sum(1.0 / (1.0 + ((fk - Fi) / b) ** 2) for Fi, b in zip(F, bw))
        out += gain * (fk < RATE / 2 - 500) / k ** 0.6 * np.sin(k * phase)
    noise = np.convolve(rng.normal(0, 1, n), np.ones(6) / 6, mode="same")
    return (out / (np.abs(out).max() + 1e-9) + breath * noise) * contour(amp, n)


def silence(seconds):
    return np.zeros(int(RATE * seconds))


def to_pcm(x, peak=0.85):
    x = x / (np.abs(x).max() + 1e-9) * peak
    x[0] = x[-1] = 0.0
    return (x * 32767).astype("<i2")


def wav_bytes(pcm, loops=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(np.tile(pcm, loops).tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------- engines
# Moved from experiments/pets/recovered/circuit/engine_sfx.py (the jeeps' engines).
# A car carries <prefix>i.sfx (idle) and <prefix>0/1/2.sfx (load layers); the game pitch-shifts
# each layer by rpm / base_rpm, base_rpm being the layer's first .ens field (2559 for layers 0
# and 1, 1283 for layer 2 on every car sampled). So each loop sounds like the engine AT its base
# rpm: firing frequency = rpm / 60 x pulses per rev (2 inline four, 3 six, 4 V8, 5 V10). Every
# loop holds a whole number of pulses, so the seam never clicks; cylinders differ slightly and
# consistently, which is what makes it an engine rather than a buzzer.

def _band(n, lo, hi, rng):
    spec = rng.normal(size=n // 2 + 1) + 1j * rng.normal(size=n // 2 + 1)
    f = np.fft.rfftfreq(n, 1 / RATE)
    x = np.fft.irfft(spec * ((f >= lo) & (f <= hi)), n)
    return x / (np.abs(x).max() + 1e-12)


def engine_loop(rpm, pulses_per_rev, seconds, *, cylinders, bright=0.0, lumpy=0.0, seed=1):
    rng = np.random.default_rng(seed)
    n = int(round(seconds * RATE))
    f_fire = rpm / 60.0 * pulses_per_rev
    pulses = max(1, int(round(seconds * f_fire)))
    period = n / pulses
    f_fire = RATE / period
    gains = 1.0 + (rng.uniform(-0.12, 0.12, cylinders) * (1 + 2 * lumpy))
    shifts = rng.uniform(-0.05, 0.05, cylinders) * lumpy * period
    k = np.arange(int(period * 3)) / RATE
    tau = 0.9 / f_fire
    out = np.zeros(n)
    for p in range(pulses):
        c = p % cylinders
        f1, f2 = f_fire * rng.uniform(1.9, 2.3), f_fire * rng.uniform(3.6, 4.4)
        thump = (np.sin(2 * np.pi * f1 * k) + 0.55 * np.sin(2 * np.pi * f2 * k + 1.1)) * np.exp(-k / tau)
        burst = rng.normal(size=len(k)) * np.exp(-k / (0.25 * tau)) * (0.25 + 0.35 * bright)
        start = int(round(p * period + shifts[c])) % n
        np.add.at(out, (np.arange(len(k)) + start) % n, (thump + burst) * gains[c])
    t = np.arange(n) / RATE
    mod = 0.6 + 0.4 * np.cos(2 * np.pi * f_fire * t)
    out += _band(n, 700, 2600, rng) * mod * (0.10 + 0.25 * bright)
    out += _band(n, 2600, 6000, rng) * mod * 0.12 * bright
    out += 0.25 * np.sin(2 * np.pi * (f_fire / 2) * t)
    out = np.tanh(1.3 * out / (np.abs(out).max() + 1e-12))
    out = out * (6100 / 32767) / (np.sqrt((out ** 2).mean()) + 1e-12)     # the stock van's loudness
    return (np.clip(out, -1, 1) * 32767).astype("<i2")


def engine_set(pulses_per_rev, cylinders, idle_rpm=850, seed=11):
    """{suffix: 16-bit samples} for the i, 0, 1, 2 loops at 22,050 Hz."""
    return {
        "i": engine_loop(idle_rpm, pulses_per_rev, 0.99, cylinders=cylinders, lumpy=1.0, seed=seed),
        "0": engine_loop(2559, pulses_per_rev, 0.55, cylinders=cylinders, bright=0.3, lumpy=0.4, seed=seed + 1),
        "1": engine_loop(2559, pulses_per_rev, 0.55, cylinders=cylinders, bright=0.4, lumpy=0.4, seed=seed + 2),
        "2": engine_loop(1283, pulses_per_rev, 0.55, cylinders=cylinders, bright=1.0, lumpy=0.2, seed=seed + 3),
    }
