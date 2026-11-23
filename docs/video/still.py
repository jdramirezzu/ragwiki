"""Save still frames of video.html at given times, to check the layout."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

lang, times = sys.argv[1], [float(t) for t in sys.argv[2:]]
url = (Path(__file__).parent / "video.html").resolve().as_uri() + f"?lang={lang}"
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(url)
    page.wait_for_timeout(800)
    for t in times:
        page.evaluate(f"render({t})")
        page.screenshot(path=f"still-{lang}-{t:05.1f}.png")
    browser.close()
