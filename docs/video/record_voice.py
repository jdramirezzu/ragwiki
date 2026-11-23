"""Record the narration from the terminal, one clip per scene, while you read the script.

Usage: python record_voice.py <es|en> <out-folder> [--from N]

For each clip it shows the line, counts down, records while a bar shows the time against the
scene's window, and lets you keep, replay or redo the take. Enter stops a take early.
Uses PipeWire (pw-record, pw-play) or ALSA (arecord, aplay), whichever is installed.
"""

import argparse
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

HERE = Path(__file__).parent
SECTIONS = {"es": "## Español", "en": "## English"}
WINDOWS = [4.5, 9.0, 4.2, 7.6, 9.6, 4.6, 5.6, 7.6, 4.6, 7.6, 9.6, 6.6, 7.2]
BOLD, DIM, YELLOW, GREEN, RED, RESET = (
    "\033[1m",
    "\033[2m",
    "\033[33m",
    "\033[32m",
    "\033[31m",
    "\033[0m",
)
MENU = " · ".join(
    f"{BOLD}{k}{RESET} {action}"
    for k, action in (("Enter", "keep"), ("p", "play"), ("r", "redo"), ("q", "quit"))
)


def script(lang: str) -> list[str]:
    text = (HERE / "narration.md").read_text(encoding="utf-8")
    section = text.split(SECTIONS[lang], 1)[1].split("\n## ", 1)[0]
    lines = re.findall(r"^\| s(\d\d) \| (.+?) \|$", section, flags=re.M)
    return [line for _, line in sorted(lines)]


def tools() -> tuple[list[str], list[str]]:
    if shutil.which("pw-record") and shutil.which("pw-play"):
        return ["pw-record", "--rate", "48000", "--channels", "1"], ["pw-play"]
    if shutil.which("arecord") and shutil.which("aplay"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", "48000", "-c", "1"], ["aplay", "-q"]
    raise SystemExit("Install PipeWire (pw-record) or ALSA utils (arecord) to record.")


def key(timeout: float | None = None) -> str | None:
    """One key press without Enter; None when the timeout passes."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if ready else None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


def screen(number: int, total: int, text: str, window: float, note: str = "") -> None:
    width = min(shutil.get_terminal_size().columns, 90)
    print("\033[2J\033[H", end="")
    print(f"{DIM}clip s{number:02d} of {total} · window {window:.1f} s{RESET}\n")
    for line in wrap(text, width - 4):
        print(f"  {BOLD}{line}{RESET}")
    print()
    if note:
        print(note)


def take(record: list[str], path: Path, window: float) -> float:
    for n in (3, 2, 1):
        print(f"\r  {YELLOW}{n}…{RESET}   ", end="", flush=True)
        time.sleep(0.7)
    process = subprocess.Popen([*record, str(path)], stderr=subprocess.DEVNULL)
    start = time.monotonic()
    limit = window + 2.0
    width = 40
    while True:
        elapsed = time.monotonic() - start
        filled = min(width, int(width * elapsed / window))
        color = GREEN if elapsed <= window else RED
        bar = "█" * filled + "·" * (width - filled)
        print(
            f"\r  {RED}● REC{RESET} {color}{bar}{RESET} {elapsed:4.1f} / {window:.1f} s  "
            f"{DIM}Enter = stop{RESET}  ",
            end="",
            flush=True,
        )
        pressed = key(0.1)
        if pressed in ("\n", "\r", " ") or elapsed >= limit:
            break
    process.terminate()
    process.wait()
    print()
    return time.monotonic() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lang", choices=SECTIONS)
    parser.add_argument("out", type=Path)
    parser.add_argument("--from", dest="first", type=int, default=1, help="start at clip N")
    args = parser.parse_args()

    lines = script(args.lang)
    record, play = tools()
    args.out.mkdir(parents=True, exist_ok=True)
    print("\033[2J\033[H")
    print(f"{BOLD}Narration · {args.lang}{RESET}  ({len(lines)} clips into {args.out})\n")
    print("Read each line calmly. Press a key when ready; Enter stops the take.")
    print(f"Then: {MENU}")
    print(f"\n{DIM}Tip: say one test clip and play it back to check the microphone level.{RESET}")
    print("\nPress any key to start…")
    key()

    number = args.first
    while number <= len(lines):
        text, window = lines[number - 1], WINDOWS[number - 1]
        path = args.out / f"s{number:02d}.wav"
        done = " (already recorded: Enter re-records, n next)" if path.exists() else ""
        screen(
            number, len(lines), text, window, f"{DIM}Press Enter to record{done}, q to quit{RESET}"
        )
        choice = key()
        if choice == "q":
            break
        if choice == "n" and path.exists():
            number += 1
            continue
        screen(number, len(lines), text, window)
        length = take(record, path, window)
        while True:
            verdict = (
                f"{GREEN}fits{RESET}"
                if length <= window
                else f"{RED}{length - window:.1f} s too long: say it a little faster{RESET}"
            )
            print(f"\n  {length:.1f} s · {verdict}")
            print(f"  {MENU}")
            choice = key()
            if choice == "p":
                subprocess.run([*play, str(path)], stderr=subprocess.DEVNULL)
                continue
            break
        if choice == "q":
            break
        if choice == "r":
            continue
        number += 1

    recorded = sorted(p.name for p in args.out.glob("s??.wav"))
    print(f"\n{len(recorded)} of {len(lines)} clips in {args.out}")
    if len(recorded) == len(lines):
        print(f"{GREEN}All clips recorded. Now run mix.py (see narration.md).{RESET}")
    os.system("stty sane")


if __name__ == "__main__":
    main()
