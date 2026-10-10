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
