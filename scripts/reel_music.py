"""Synthesize the reel's soundtrack: a small lo-fi house loop locked to the edit's beat grid.

Everything is generated with numpy, so there's no licensing to worry about. Swap in your own
track with `edit_reel.py --music song.wav` instead (set BPM in the style to match it).

Run:  python scripts/reel_music.py out.wav [bpm] [seconds]
"""
import sys
import wave

import numpy as np

SR = 44100
RNG = np.random.default_rng(7)

# Am9 - Fmaj7 - Cmaj7 - G6, as MIDI notes
CHORDS = [[57, 60, 64, 67, 71], [53, 57, 60, 64, 69], [48, 55, 59, 64, 67], [55, 59, 62, 64, 71]]
ROOTS = [45, 41, 48, 43]


def hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def lowpass(x, cutoff):
    """One-pole lowpass; cutoff may be an array (per-sample sweep)."""
    a = np.exp(-2 * np.pi * np.broadcast_to(cutoff, x.shape) / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):  # fine for the few short buffers this runs on
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def lp_fast(x, cutoff):
    """Fixed-cutoff lowpass via FFT (brick-ish with a soft knee)."""
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(np.fft.rfft(x) / np.sqrt(1 + (f / cutoff) ** 4), len(x))


def hp_fast(x, cutoff):
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(np.fft.rfft(x) * (1 - 1 / np.sqrt(1 + (f / cutoff) ** 4)), len(x))


def reverb(x, seconds=2.2, mix=0.3):
    n = int(seconds * SR)
    ir = RNG.standard_normal(n) * np.exp(-np.linspace(0, 7, n))
    ir = lp_fast(ir, 5000)
    ir /= np.sqrt(np.sum(ir ** 2))
    size = len(x) + n
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:len(x)]
    return x * (1 - mix) + wet * mix


def env(n, a, d):
    t = np.arange(n) / SR
    return np.minimum(t / max(a, 1e-4), 1) * np.exp(-t / d)


def place(buf, sample, t, gain=1.0):
    i = int(t * SR)
    if i >= len(buf):
        return
    s = sample[: len(buf) - i]
    buf[i:i + len(s)] += gain * s


def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7) * 1.0


def clap():
    n = int(0.25 * SR)
    noise = hp_fast(RNG.standard_normal(n), 900)
    e = sum(env(n, 0.001, 0.012) * (np.arange(n) >= int(k * SR)) for k in (0, 0.008, 0.017))
    e = np.roll(e, 0) + 0.5 * env(n, 0.001, 0.08)
    return lp_fast(noise, 6000) * e * 0.35


def hat(open_=False):
    n = int((0.18 if open_ else 0.05) * SR)
    return hp_fast(RNG.standard_normal(n), 7000) * env(n, 0.0005, 0.06 if open_ else 0.012) * 0.22


def saw(f, n, detune=(0.0,)):
    t = np.arange(n) / SR
    return sum(2 * ((t * f * (1 + d)) % 1) - 1 for d in detune) / len(detune)


def pad_chord(notes, n):
    x = sum(saw(hz(m), n, (-0.004, 0.0, 0.0045)) for m in notes) / len(notes)
    return x


def pluck(note, n):
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * hz(note) * t) + 0.35 * np.sin(2 * np.pi * hz(note) * 2 * t + 0.4))
    return x * env(n, 0.002, 0.11)


def bass_note(note, n):
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * hz(note) * t) + 0.25 * np.sin(2 * np.pi * hz(note) * 2 * t)
    return x * np.minimum(t / 0.005, 1) * np.minimum((n / SR - t) / 0.03, 1)


def riser(dur):
    n = int(dur * SR)
    noise = RNG.standard_normal(n)
    sweep = np.geomspace(300, 9000, n)
    return lowpass(noise, sweep) * np.linspace(0, 1, n) ** 2 * 0.3


def impact():
    n = int(2.5 * SR)
    t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(30 + 60 * np.exp(-t * 8)) / SR) * np.exp(-t * 2.2)
    return boom * 0.9 + lp_fast(RNG.standard_normal(n), 1500) * np.exp(-t * 5) * 0.25


def render(bpm=120.0, total=45.0, drop=4.0, montage=(24.0, 32.0), outro=40.0):
    beat = 60.0 / bpm
    bar = 4 * beat
    n = int(total * SR)
    drums = np.zeros(n)
    music = np.zeros(n)
    fx = np.zeros(n)
    side = np.ones(n)  # sidechain gain from the kick
    k, c = kick(), clap()

    # pads: one chord per bar, filter opens after the drop
    t = 0.0
    i = 0
    while t < total:
        m = int(bar * SR)
        x = pad_chord(CHORDS[i % 4], m) * 0.55
        cutoff = 700 if t < drop else (2200 if not (montage[0] <= t < montage[1]) else 3200)
        if t >= outro:
            cutoff = 900
        x = lp_fast(x, cutoff) * np.minimum(np.arange(m) / (0.08 * SR), 1)
        place(music, x, t)
        i += 1
        t += bar

    # drums + bass from the drop to the outro
    t, step = drop, 0
    while t < outro - 1e-6:
        b = step % 16  # 16th position in the bar
        if b % 4 == 0:
            place(drums, k, t)
            j = int(t * SR)
            dip = int(0.32 * SR)
            side[j:j + dip] = np.minimum(side[j:j + dip], 0.35 + 0.65 * np.linspace(0, 1, len(side[j:j + dip])) ** 0.6)
        if b in (4, 12):
            place(drums, c, t)
        if b % 4 == 2:
            place(drums, hat(open_=(b == 14)), t)
        elif b % 2 == 1 and montage[0] <= t < montage[1]:
            place(drums, hat(), t, 0.5)
        chord_i = int(t / bar) % 4
        if b in (0, 3, 6, 10, 11):
            dur = beat * (0.7 if b != 6 else 1.2)
            place(music, bass_note(ROOTS[chord_i] - 12 + (12 if b == 11 else 0), int(dur * SR)) * 0.5, t)
        if montage[0] <= t < montage[1] or (t >= drop + 4 * bar and t < outro and b % 2 == 0):
            notes = CHORDS[chord_i]
            arp = [notes[(step * 3 + q) % len(notes)] + 12 for q in range(1)]
            place(music, pluck(arp[0], int(0.3 * SR)), t, 0.22 if montage[0] <= t < montage[1] else 0.1)
        step += 1
        t = drop + step * beat / 4

    # fx: risers into the drop and the montage, impact at the outro
    for at, dur in ((drop, 2.0), (montage[0], 2.0), (outro, 2.0)):
        place(fx, riser(dur), at - dur)
    place(fx, impact(), outro, 0.8)
    place(fx, impact(), drop, 0.5)

    # vinyl crackle under everything
    crackle = (RNG.random(n) > 0.9993) * RNG.standard_normal(n) * 0.25 + RNG.standard_normal(n) * 0.004
    music = reverb(music * side, 2.4, 0.28)
    mix = music + drums * 0.9 + reverb(fx, 1.8, 0.35) + lp_fast(crackle, 4000)
    # fade out over the last 2s
    fade = np.clip((total - np.arange(n) / SR) / 2.0, 0, 1)
    mix *= fade
    mix = np.tanh(mix * 1.4) / np.tanh(1.4)  # soft clip / glue
    mix /= np.max(np.abs(mix)) * 1.12
    stereo = np.stack([mix, np.roll(mix, int(0.0006 * SR)) * 0.98 + mix * 0.02], axis=1)
    return stereo


def write_wav(path, stereo):
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "reel_music.wav"
    bpm = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    total = float(sys.argv[3]) if len(sys.argv) > 3 else 45.0
    write_wav(out, render(bpm, total))
    print("saved", out)
