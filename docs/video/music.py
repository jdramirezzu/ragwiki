"""Generate the intro's background music from sine waves: calm, original and license-free.

Usage: python music.py <out.wav> [seconds]
"""

import sys
import wave

import numpy as np

RATE = 44_100
BPM = 84
BEAT = 60 / BPM
# A minor, F major, C major, G major: two bars each.
CHORDS = [
    (57, [57, 60, 64, 69]),
    (53, [53, 57, 60, 65]),
    (48, [52, 55, 60, 64]),
    (55, [55, 59, 62, 67]),
]


def hz(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def envelope(n: int, attack: float, release: float) -> np.ndarray:
    env = np.ones(n)
    a, r = int(attack * RATE), int(release * RATE)
    env[:a] = np.linspace(0, 1, a)
    env[n - r :] = np.linspace(1, 0, r)
    return env


def pad(note: int, length: float) -> np.ndarray:
    t = np.arange(int(length * RATE)) / RATE
    f = hz(note)
    tone = sum(np.sin(2 * np.pi * f * d * t) for d in (0.997, 1.0, 1.003)) / 3
    tone += 0.25 * np.sin(2 * np.pi * 2 * f * t) + 0.1 * np.sin(2 * np.pi * 3 * f * t)
    return tone * envelope(len(t), 1.6, 1.8)


def pluck(note: int, length: float = 1.2) -> np.ndarray:
    t = np.arange(int(length * RATE)) / RATE
    f = hz(note + 12)
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * np.exp(-t * 4.5)


def reverb(signal: np.ndarray) -> np.ndarray:
    out = signal.copy()
    for delay, gain in ((0.031, 0.35), (0.047, 0.3), (0.067, 0.25), (0.113, 0.2), (0.173, 0.15)):
        d = int(delay * RATE)
        echo = np.zeros_like(signal)
        echo[d:] = signal[:-d] * gain
        out += echo
    return out


def render(seconds: float) -> np.ndarray:
    total = int(seconds * RATE)
    left, right = np.zeros(total + RATE * 12), np.zeros(total + RATE * 12)
    bar = 4 * BEAT
    start, i = 0.0, 0
    while start < seconds:
        root, notes = CHORDS[i % len(CHORDS)]
        length = 2 * bar + 1.5
        s = int(start * RATE)
        for k, note in enumerate(notes):
            tone = pad(note, length) * 0.16
            pan = 0.35 + 0.1 * k
            left[s : s + len(tone)] += tone * (1 - pan)
            right[s : s + len(tone)] += tone * pan
        bass = pad(root - 12, length) * 0.22
        left[s : s + len(bass)] += bass
        right[s : s + len(bass)] += bass
        # A soft arpeggio on the eighth notes after the intro, for movement.
        if start >= 4.5:
            for step in range(16):
                at = int((start + step * BEAT / 2) * RATE)
                note = notes[(step * 3) % len(notes)]
                tone = pluck(note) * 0.07
                side = left if step % 2 else right
                side[at : at + len(tone)] += tone
        start += 2 * bar
        i += 1
    stereo = np.stack([reverb(left), reverb(right)], axis=1)[:total]
    fade_in, fade_out = int(1.5 * RATE), int(4 * RATE)
    stereo[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    stereo[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    return stereo / np.max(np.abs(stereo)) * 0.5


def main() -> None:
    out = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 94
    data = (render(seconds) * 32767).astype("<i2")
    with wave.open(out, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(data.tobytes())
    print("music", out)


if __name__ == "__main__":
    main()
