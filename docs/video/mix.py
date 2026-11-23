"""Add the music and, when recorded, the narration to the intro video.

Usage:
  python mix.py --video in.mp4 --out out.mp4 [--voice folder-with-s01..s13] [--music music.wav]

Each clip `sNN` starts at its scene (see narration.md). The music is lowered while the voice
speaks. Clips longer than their window are reported, not cut.
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
# Start and window of each clip, in seconds; they follow the scenes in video.html.
CLIPS = [
    (0.3, 4.5),
    (5.3, 9.0),
    (14.7, 4.2),
    (19.3, 7.6),
    (27.3, 9.6),
    (37.3, 4.6),
    (42.3, 5.6),
    (48.3, 7.6),
    (56.3, 4.6),
    (61.3, 7.6),
    (69.3, 9.6),
    (79.3, 6.6),
    (86.3, 7.2),
]
# Laptop microphones pick up a low rumble that eats headroom: cut it, reduce the hiss and
# even out the voice before the levels are matched.
VOICE_CLEANUP = (
    "highpass=f=100:poles=2,highpass=f=100:poles=2,afftdn=nf=-30,"
    "acompressor=threshold=-20dB:ratio=3:attack=5:release=120"
)
AUDIO = (".wav", ".m4a", ".mp3", ".ogg", ".flac", ".aac", ".webm", ".opus")


def duration(path: Path) -> float:
    probe = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe)
    if not match:
        raise SystemExit(f"Cannot read {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def find_clips(folder: Path) -> list[tuple[int, Path]]:
    found = []
    for number in range(1, len(CLIPS) + 1):
        matches = [p for p in folder.glob(f"s{number:02d}.*") if p.suffix.lower() in AUDIO]
        if matches:
            found.append((number, matches[0]))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--voice", type=Path, help="folder with s01..s13 audio clips")
    parser.add_argument("--music", type=Path, help="music file; generated when missing")
    parser.add_argument("--music-volume", type=float, default=0.55)
    parser.add_argument("--declip", action="store_true", help="repair clipped takes first")
    args = parser.parse_args()

    total = duration(args.video)
    tmp = Path(tempfile.mkdtemp(prefix="ragwiki-mix-"))
    music = args.music
    if music is None:
        music = tmp / "music.wav"
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("music.py")), str(music), str(total)],
            check=True,
        )

    inputs = ["-i", str(args.video), "-i", str(music)]
    filters = [f"[1:a]aresample=48000,volume={args.music_volume}[music]"]
    clips = find_clips(args.voice) if args.voice else []
    if args.voice and not clips:
        raise SystemExit(f"No clips named s01..s13 in {args.voice}")

    for number, path in clips:
        start, window = CLIPS[number - 1]
        length = duration(path)
        if length > window:
            print(f"warning: s{number:02d} lasts {length:.1f} s, its window is {window:.1f} s")

    if clips:
        labels = []
        for index, (number, path) in enumerate(clips, start=2):
            start = int(CLIPS[number - 1][0] * 1000)
            inputs += ["-i", str(path)]
            repair = "adeclip," if args.declip else ""
            filters.append(
                f"[{index}:a]{repair}aresample=48000,aformat=channel_layouts=stereo,"
                f"{VOICE_CLEANUP},adelay={start}|{start},apad=whole_dur={total}[v{number}]"
            )
            labels.append(f"[v{number}]")
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,asplit=2[voice][key]"
        )
        filters.append(
            "[music][key]sidechaincompress=threshold=0.02:ratio=10:attack=30:release=600[ducked]"
        )
        filters.append("[ducked][voice]amix=inputs=2:normalize=0,alimiter=limit=0.95[aout]")
    else:
        filters.append("[music]alimiter=limit=0.95[aout]")

    command = [FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters)]
    command += ["-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    command += ["-t", f"{total:.3f}", "-movflags", "+faststart", str(args.out)]
    subprocess.run(command, check=True)
    print(f"done {args.out} ({len(clips)} voice clips)")


if __name__ == "__main__":
    main()
