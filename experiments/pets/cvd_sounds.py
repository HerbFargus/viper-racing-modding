"""Synthesised horns for the Cats vs Dogs cars, on kit.sound's source-filter voice.
  meow   "mi-aa-ow": pitch rises then falls, F1/F2 glide from an i to an a to a u (0.90 s loop)
  bark   "wuf": a rough, fast-falling pitch, hard attack, short decay, a subharmonic growl (0.50 s)

    python cvd_sounds.py      writes meow.wav and bark.wav (three loops each) to listen to
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.sound import RATE, silence, to_pcm, voice, wav_bytes  # noqa: E402

import numpy as np  # noqa: E402


def meow():
    call = voice(0.62,
                 f0=[(0, 520), (.25, 760), (.55, 700), (1, 430)],
                 f1=[(0, 320), (.2, 420), (.45, 950), (.75, 700), (1, 420)],
                 f2=[(0, 2300), (.2, 2200), (.45, 1600), (.75, 1100), (1, 850)],
                 f3=[(0, 3200), (1, 2800)],
                 amp=[(0, 0), (.06, .35), (.16, .8), (.5, 1), (.85, .6), (1, 0)],
                 jitter=0.01, breath=0.03, seed=4)
    return np.concatenate([call, silence(0.28)])


def bark():
    woof = voice(0.2, f0=[(0, 480), (.3, 400), (1, 230)], f1=[(0, 750), (.4, 650), (1, 420)],
                 f2=[(0, 1500), (.4, 1250), (1, 900)], f3=[(0, 2600), (1, 2400)],
                 amp=[(0, 0), (.04, 1), (.25, .85), (.6, .4), (1, 0)],
                 bw=(140, 180, 250), jitter=0.06, breath=0.12, seed=9)
    growl = voice(0.2, f0=[(0, 240), (.3, 200), (1, 115)], f1=[(0, 600), (1, 380)],
                  f2=[(0, 1200), (1, 800)], f3=[(0, 2400), (1, 2200)],
                  amp=[(0, 0), (.05, 1), (.5, .5), (1, 0)], jitter=0.08, breath=0.05, seed=11)
    call = woof + 0.35 * growl
    return np.concatenate([call / np.abs(call).max(), silence(0.3)])


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for name, fn in (("meow", meow), ("bark", bark)):
        pcm = to_pcm(fn())
        (here / f"{name}.wav").write_bytes(wav_bytes(pcm, loops=3))
        print(f"{name}: {len(pcm) / RATE:.2f} s loop -> {name}.wav (three loops)")
