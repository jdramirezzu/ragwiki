"""Render video.html frame by frame with Chrome and encode an MP4 with ffmpeg.

Usage: python record.py <lang> <out.mp4> [fps]
"""

import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

lang, out = sys.argv[1], sys.argv[2]
fps = int(sys.argv[3]) if len(sys.argv) > 3 else 30
page_url = (Path(__file__).parent / "video.html").resolve().as_uri() + f"?lang={lang}"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(page_url)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    duration = page.evaluate("window.DURATION")
    frames = int(duration * fps)
    ffmpeg = subprocess.Popen(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "image2pipe",
            "-framerate",
            str(fps),
            "-c:v",
            "mjpeg",
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
            out,
        ],
        stdin=subprocess.PIPE,
    )
    for frame in range(frames):
        page.evaluate(f"render({frame / fps})")
        ffmpeg.stdin.write(page.screenshot(type="jpeg", quality=92))
        if frame % (fps * 10) == 0:
            print(f"{frame / fps:.0f}s / {duration:.0f}s", flush=True)
    ffmpeg.stdin.close()
    ffmpeg.wait()
    browser.close()
print("done", out)
