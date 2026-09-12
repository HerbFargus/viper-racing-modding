"""Synthesizes a rough placeholder "quack" -- a short, buzzy, descending-pitch
tone. Not a sampled real quack; just distinct enough from horn.sfx's real sound
to prove a WAV import->commit round-trip actually replaced the audio, played
back through vrmod's own wav2sfx/from_wav_bytes path."""
import math
import struct
import wave

SAMPLE_RATE = 22050  # matches real horn.sfx's own sample rate
DURATION = 0.35
N = int(SAMPLE_RATE * DURATION)

samples = []
for i in range(N):
    t = i / SAMPLE_RATE
    progress = i / N
    # Pitch drops from ~620Hz to ~280Hz over the duration -- the classic quack
    # downward "wah" shape -- with a second harmonic mixed in for a buzzier,
    # less pure-tone timbre than a plain sine.
    freq = 620 - 340 * progress
    phase = 2 * math.pi * freq * t
    val = 0.6 * math.sin(phase) + 0.3 * math.sin(2 * phase) + 0.1 * math.sin(3.3 * phase)
    # Quick attack, slower decay envelope so it doesn't click at the start/end.
    envelope = min(1.0, i / (SAMPLE_RATE * 0.01)) * (1.0 - progress) ** 0.6
    sample = max(-1.0, min(1.0, val * envelope))
    samples.append(int(sample * 32767))

with wave.open("quack.wav", "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SAMPLE_RATE)
    w.writeframes(struct.pack(f"<{len(samples)}h", *samples))

print(f"wrote quack.wav: {N} samples, {DURATION}s at {SAMPLE_RATE} Hz mono 16-bit")
