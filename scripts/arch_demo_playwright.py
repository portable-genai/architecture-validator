"""Presenter-controlled Playwright walkthrough of the live C3 intake-gate demo.

Drives a headed browser through the policy-as-code intake gate served by
``scripts/arch_demo_server.py``. It is **paced by the presenter**: before each step it
prints what is about to happen and waits for you to press Enter, then performs the action
(click "Next ▶") and highlights the panel to look at. You stay in control of timing.

Usage (two terminals)::

    # terminal 1 — the live demo server
    PYTHONPATH=src:tests python scripts/arch_demo_server.py

    # terminal 2 — the guided walkthrough (a real Chrome window opens)
    pip install playwright && playwright install chromium     # one-time
    python scripts/arch_demo_playwright.py

Point it at the live Next.js console instead by setting ``DEMO_URL=http://localhost:3000``
(the manual click-through there is the same two submissions; the spotlight selectors fall
back gracefully if a panel is not found).

Environment overrides:
    DEMO_URL    server base URL (default http://127.0.0.1:8092)
    HEADLESS=1  run headless (used for the self-test; no window)
    DEMO_AUTO=1 don't wait for Enter — advance automatically (self-test / recording)
    SLOWMO_MS   per-action slow-motion in ms (default 250 headed, 0 headless)
    CHROME_PATH explicit Chromium/Chrome binary (else Playwright's own)
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:8092")
HEADLESS = os.environ.get("HEADLESS") == "1"
AUTO = os.environ.get("DEMO_AUTO") == "1"
SLOWMO = int(os.environ.get("SLOWMO_MS", "0" if HEADLESS else "250"))
CHROME_PATH = os.environ.get("CHROME_PATH") or None

# (narration shown in the terminal, whether this step clicks "Next", panel to spotlight)
STEPS = [
    (
        "The intake gate is ready. Two synthetic project submissions are queued: a "
        "customer-facing onboarding bot and a grounded internal policy assistant. Nothing "
        "has been validated yet.",
        False,
        None,
    ),
    (
        "Submission 1 — the onboarding bot: it processes customer PII, fine-tunes on past "
        "chats, and is declared in us-central1 with almost no controls. Watch the gate "
        "BLOCK it: eight principle FAILs (P-01, P-02, P-03, P-05, P-06, P-08, P-09, P-12), "
        "the maker-checker review flag is raised, and one non-functional requirement is "
        "injected per unmet principle.",
        True,
        ".verdict",
    ),
    (
        "Submission 2 — the grounded policy assistant: Singapore region, no PII, RAG over "
        "governed docs, eval gate, maker-checker, CMEK, VPC-SC, an exit plan. Every "
        "principle is satisfied, so it CLEARS intake and the injected-requirements panel "
        "goes green: nothing to add.",
        True,
        ".verdict",
    ),
]


def _pause(prompt: str) -> None:
    if AUTO:
        time.sleep(1.2)
        return
    try:
        input(prompt)
    except EOFError:  # non-interactive stdin
        time.sleep(1.0)


def _spotlight(page, selector: str | None) -> None:
    if not selector:
        return
    with contextlib.suppress(Exception):  # cosmetic only
        page.eval_on_selector_all(
            selector,
            "els => els.forEach((e,i)=>{ if(i<6){ e.style.transition='box-shadow .3s';"
            " e.style.boxShadow='0 0 0 3px #3a60f0'; setTimeout(()=>e.style.boxShadow='',1600);} })",
        )


def _reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(BASE + "/state", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        # The live Next.js console has no /state route; fall back to the root.
        try:
            with urllib.request.urlopen(BASE + "/", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            return False


def main() -> int:
    if not _reachable():
        print(f"Cannot reach the demo server at {BASE}.")
        print("Start it first:  PYTHONPATH=src:tests python scripts/arch_demo_server.py")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, executable_path=CHROME_PATH)
        page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()

        print("\n=== C3 intake-gate live demo — press Enter to advance each step ===\n")
        with contextlib.suppress(Exception):
            page.goto(BASE + "/restart", wait_until="load")  # reset the demo server (no-op on UI)
        page.goto(BASE + "/", wait_until="load")

        for i, (say, click, spotlight) in enumerate(STEPS):
            print(f"[{i + 1}/{len(STEPS)}] {say}")
            _pause("        ⏎  press Enter to run this step… ")
            if click:
                btn = page.locator(".democtl button.next")
                if btn.count() and btn.is_enabled():
                    btn.click()
                    page.wait_for_load_state("load")
            page.wait_for_timeout(200)
            _spotlight(page, spotlight)
            page.wait_for_timeout(700)
            print()

        print("Demo complete. The browser stays open for questions.")
        _pause("        ⏎  press Enter to close the browser… ")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
