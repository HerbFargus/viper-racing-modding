"""Engine sound loops, synthesised -- no recorded engine anywhere in them.

A Viper car carries <prefix>i.sfx (idle) and <prefix>0/1/2.sfx (load layers). The
game pitch-shifts each load layer by rpm / base_rpm, where base_rpm is the layer's
first .ens field (2559 for layers 0 and 1, 1283 for the high layer 2 on every car
sampled). So each loop here is built to sound like the engine AT its base rpm: the
firing frequency is base_rpm / 60 x pulses-per-rev (2 for an inline four, 3 for a
six, 5 for a V10).

Each loop is periodic by construction -- a whole number of firing pulses placed at
exact fractions of the loop, every noise band shaped over the whole loop -- so the
seam never clicks. A pulse is an exhaust thump (two damped low resonances) plus a
short noise burst; cylinders differ slightly and consistently (a fixed per-cylinder
gain and timing pattern), which is what makes a loop sound like an engine rather
than a buzzer.
"""
import numpy as np

import make_rumble as mr                           # its band_noise / wrap_add helpers


def _band(n, lo, hi, rate, rng):
    spec = rng.normal(size=n // 2 + 1) + 1j * rng.normal(size=n // 2 + 1)
    f = np.fft.rfftfreq(n, 1 / rate)
    x = np.fft.irfft(spec * ((f >= lo) & (f <= hi)), n)
    return x / (np.abs(x).max() + 1e-12)


def loop(rpm, pulses_per_rev, seconds, rate, *, cylinders, bright=0.0, lumpy=0.0, seed=1):
    rng = np.random.default_rng(seed)
    n = int(round(seconds * rate))
    f_fire = rpm / 60.0 * pulses_per_rev
    pulses = max(1, int(round(seconds * f_fire)))
    period = n / pulses                                    # exact: the loop holds whole pulses
    f_fire = rate / period
    gains = 1.0 + (rng.uniform(-0.12, 0.12, cylinders) * (1 + 2 * lumpy))
    shifts = rng.uniform(-0.05, 0.05, cylinders) * lumpy * period
    k = np.arange(int(period * 3)) / rate
    tau = 0.9 / f_fire
    out = np.zeros(n)
    for p in range(pulses):
        c = p % cylinders
        f1, f2 = f_fire * rng.uniform(1.9, 2.3), f_fire * rng.uniform(3.6, 4.4)
        thump = (np.sin(2 * np.pi * f1 * k) + 0.55 * np.sin(2 * np.pi * f2 * k + 1.1)) * np.exp(-k / tau)
        burst = rng.normal(size=len(k)) * np.exp(-k / (0.25 * tau)) * (0.25 + 0.35 * bright)
        start = int(round(p * period + shifts[c])) % n
        idx = (np.arange(len(k)) + start) % n
        np.add.at(out, idx, (thump + burst) * gains[c])
    t = np.arange(n) / rate
    mod = 0.6 + 0.4 * np.cos(2 * np.pi * f_fire * t)       # intake and valvetrain, pulsing with the firing
    out += _band(n, 700, 2600, rate, rng) * mod * (0.10 + 0.25 * bright)
    out += _band(n, 2600, 6000, rate, rng) * mod * 0.12 * bright
    out += 0.25 * np.sin(2 * np.pi * (f_fire / 2) * t)     # the crank's half-order, felt more than heard
    out = np.tanh(1.3 * out / (np.abs(out).max() + 1e-12))
    rms = np.sqrt((out ** 2).mean())
    out = out * (6100 / 32767) / (rms + 1e-12)             # the donor van's loudness
    return (np.clip(out, -1, 1) * 32767).astype("<i2")


def engine_set(pulses_per_rev, cylinders, idle_rpm=850, seed=11):
    """{suffix: samples} for i, 0, 1, 2 -- all 22,050 Hz, like the van's."""
    rate = 22050
    return rate, {
        "i": loop(idle_rpm, pulses_per_rev, 0.99, rate, cylinders=cylinders, lumpy=1.0, seed=seed),
        "0": loop(2559, pulses_per_rev, 0.55, rate, cylinders=cylinders, bright=0.3, lumpy=0.4, seed=seed + 1),
        "1": loop(2559, pulses_per_rev, 0.55, rate, cylinders=cylinders, bright=0.4, lumpy=0.4, seed=seed + 2),
        "2": loop(1283, pulses_per_rev, 0.55, rate, cylinders=cylinders, bright=1.0, lumpy=0.2, seed=seed + 3),
    }
