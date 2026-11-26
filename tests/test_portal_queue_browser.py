"""Real-browser Up Next checks at phone width (#324). Opt in: SMOOTHCAST_BROWSER_SMOKE=1."""
from __future__ import annotations

import os

import pytest

import portal
from test_portal import PortalRig

OPT_IN = os.environ.get("SMOOTHCAST_BROWSER_SMOKE") == "1"


def test_phone_header_lets_the_version_shrink():
    page = portal._page().decode()
    assert ".brand h1{display:none}.sc-version{flex:0 1 auto;min-width:0;overflow-wrap:anywhere" in page


@pytest.mark.skipif(not OPT_IN, reason="explicit opt-in: installed Playwright Chromium")
def test_queue_320px_no_overflow_named_buttons_and_keyboard_move():
    from playwright.sync_api import sync_playwright

    queue = [{"id": f"q{i}", "title": f"Track {i} " + "long name " * (4 if i % 7 == 0 else 0),
              "name": f"t{i}.mp3"} for i in range(120)]
    rig = PortalRig(queue=queue)
    rig.server.pin_required = False
    origin = f"http://{rig.host}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-background-networking"])
        context = browser.new_context(viewport={"width": 320, "height": 640}, service_workers="block")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda route: route.continue_()
                   if route.request.url.startswith(origin + "/") else route.abort())
        try:
            page.goto(origin + "/", wait_until="domcontentloaded")
            page.locator("#name").fill("Phone")
            page.locator("#loginForm button").click()
            items = page.locator("#queue .queue-item")
            items.nth(119).wait_for()
            assert items.count() == 120
            width, inner = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
            assert width <= inner, f"page is {width}px wide in a {inner}px viewport"
            unnamed = page.evaluate("""[...document.querySelectorAll('#queue button')].filter(
                b => !(b.getAttribute('aria-label') || b.textContent).trim()).length""")
            assert unnamed == 0
            items.nth(2).get_by_role("button", name="earlier in Up Next").first.focus()
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)
            moves = [payload for action, payload in rig.calls if action == "queue_move"]
            assert moves and moves[0]["id"] == "q2" and moves[0]["position"] == 1
            assert not errors, errors
        finally:
            context.close()
            browser.close()
