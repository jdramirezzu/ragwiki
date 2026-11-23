"""Capture screenshots of the running ragwiki lab for the intro video.

Usage: python shots.py <out-dir> <phase>
  phase "before": Files and Build tabs before the WikiLLM is built.
  phase "after":  Build, Ask (comparisons, single answers, citation drawer) and Results.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/"
out, phase = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)

    def open_tab(tab: str) -> None:
        page.goto(f"{URL}#{tab}")
        if tab == "build":
            page.wait_for_function(
                "document.querySelector('#ragStatus').textContent.length > 0", timeout=90000
            )
        page.wait_for_timeout(1500)
        page.evaluate("scrollTo(0, 0)")
        page.wait_for_timeout(300)

    def shot(name: str, tab: str, full: bool = False) -> None:
        open_tab(tab)
        page.screenshot(path=str(out / f"{name}.png"), full_page=full)

    if phase == "before":
        shot("01-files", "sources")
        shot("02-build-before", "build")
    else:
        shot("03-build-ready", "build")
        page.evaluate("document.querySelector('.diff').scrollIntoView({block: 'start'})")
        page.evaluate("scrollBy(0, -90)")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "03b-build-differ.png"))

        open_tab("ask")
        page.screenshot(path=str(out / "04-ask.png"))
        cards = page.locator("#answers .cmp")
        cross = cards.filter(has_text="Across these papers").first
        cross.scroll_into_view_if_needed()
        cross.screenshot(path=str(out / "04c-ask-cross.png"))
        fact = cards.filter(has_text="WiCER stand").first
        fact.scroll_into_view_if_needed()
        fact.screenshot(path=str(out / "04d-ask-fact.png"))
        page.evaluate("scrollBy(0, -160)")
        fact.locator(".arm.wiki .cite").first.click()
        page.wait_for_timeout(900)
        page.screenshot(path=str(out / "05-citation.png"))
        page.keyboard.press("Escape")

        for mode in ("rag", "wiki"):
            open_tab("ask")
            page.locator(f'.seg.mode button[data-mode="{mode}"]').click()
            page.wait_for_timeout(1200)
            page.screenshot(path=str(out / f"06-ask-{mode}.png"))

        shot("07-results", "results")
    browser.close()
print("ok")
