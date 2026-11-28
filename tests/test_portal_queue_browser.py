"""Real-browser Up Next checks at phone width (#324). Opt in: SMOOTHCAST_BROWSER_SMOKE=1."""
from __future__ import annotations

import os
import threading
import time

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
            items.nth(99).wait_for()
            assert items.count() == 100
            page.locator("#queue [data-queue-more]").click()
            assert items.count() == 120
            assert page.locator("#queue [data-queue-more]").count() == 0
            assert "120 of 120" in page.locator("#queueFeedback").inner_text()
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


class _RealQueueRig(PortalRig):
    """Portal over the production queue mixin: real ids, revisions and 409 fencing."""

    def __init__(self, paths):
        from cast_portal_queue import PortalQueueMixin

        class Host(PortalQueueMixin):
            queue_durations: dict = {}
            now_playing = None
            session = None
            busy = False
            selected_index = None

            def _rebuild_queue(self):
                pass

        self.host_obj = host = Host()
        host.queue = list(paths)
        self.calls = []

        def dispatch(action, payload):
            self.calls.append((action, payload))
            if action == "status":
                rows = host._portal_queue_status()
                playing = bool(host.now_playing)
                return {"title": "Current film" if playing else "",
                        "state": "PLAYING" if playing else "STOPPED", "queue": rows,
                        "queue_total": len(host.queue), "queue_revision": host._portal_queue_revision}
            return host._portal_queue_action(action, payload)

        self.queue = []
        import threading
        import time
        self.server = portal._PortalHTTPServer(("127.0.0.1", 0), "1234", dispatch,
                                               uploads=None, clock=time.monotonic)
        self.server.pin_required = False
        # The desktop publishes a snapshot that SSE watches; mirror that seam.
        self.server.status_peek = lambda: (host._portal_queue_revision if hasattr(host, "_portal_queue_revision") else 0,
                                           {"queue": host._portal_queue_status(), "queue_total": len(host.queue),
                                            "queue_revision": getattr(host, "_portal_queue_revision", 0),
                                            "state": "STOPPED"})
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02},
                         daemon=True).start()


@pytest.mark.skipif(not OPT_IN, reason="explicit opt-in: installed Playwright Chromium")
def test_two_browsers_see_each_others_moves_and_stale_move_recovers():
    from playwright.sync_api import sync_playwright

    rig = _RealQueueRig([f"/private/song{i}.mp3" for i in range(5)])
    origin = f"http://{rig.host}"

    def titles(page):
        return page.evaluate("[...document.querySelectorAll('#queue .queue-item')].map(e=>e.querySelector('.queue-title,strong,span').textContent.trim())")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-background-networking"])
        pages = []
        errors = []
        for name in ("Ann", "Ben"):
            context = browser.new_context(viewport={"width": 390, "height": 800}, service_workers="block")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/", wait_until="domcontentloaded")
            page.locator("#name").fill(name)
            page.locator("#loginForm button").click()
            page.locator("#queue .queue-item").nth(4).wait_for()
            pages.append(page)
        ann, ben = pages
        try:
            before = titles(ben)
            started = time.monotonic()
            ann.locator("#queue .queue-item").nth(1).get_by_role("button", name="later in Up Next").first.click()
            ben.wait_for_function(
                "(previous) => JSON.stringify([...document.querySelectorAll('#queue .queue-item')].map(e=>e.querySelector('.queue-title,strong,span').textContent.trim())) !== JSON.stringify(previous)",
                arg=before, timeout=8000)
            after_ben = titles(ben)
            assert time.monotonic() - started < 1.0, "owner budget is 0.5s p95; 1s guards flakes"
            assert after_ben != before and after_ben == titles(ann), (before, after_ben, titles(ann))
            assert not errors, errors
        finally:
            browser.close()


@pytest.mark.skipif(not OPT_IN, reason="explicit opt-in: installed Playwright Chromium")
def test_three_browsers_announce_and_converge_on_move_while_playing():
    from playwright.sync_api import sync_playwright

    rig = _RealQueueRig([f"/private/song{i}.mp3" for i in range(5)])
    rig.host_obj.now_playing = "/private/current-film.mkv"
    entered, release = threading.Event(), threading.Event()
    original_action = rig.host_obj._portal_queue_action

    def delayed_move(action, payload):
        if action == "queue_move":
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test did not release the queue move")
        return original_action(action, payload)

    rig.host_obj._portal_queue_action = delayed_move
    origin = f"http://{rig.host}"

    def titles(page):
        return page.evaluate("[...document.querySelectorAll('#queue .queue-item')].map(e=>e.querySelector('.queue-title,strong,span').textContent.trim())")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-background-networking"])
        pages = []
        try:
            for name in ("Ann", "Ben", "Cal"):
                page = browser.new_page(viewport={"width": 390, "height": 800}, service_workers="block")
                page.goto(origin + "/", wait_until="domcontentloaded")
                page.locator("#name").fill(name)
                page.locator("#loginForm button").click()
                page.locator("#queue .queue-item").nth(4).wait_for()
                pages.append(page)
            ann, ben, cal = pages
            previous = titles(ben)
            moved_title = ann.locator("#queue .queue-item").nth(1).locator("strong").inner_text()
            started = time.monotonic()
            ann.locator("#queue .queue-item").nth(1).get_by_role(
                "button", name="later in Up Next").first.click()
            assert entered.wait(2), "the move request did not reach the room handler"
            feedback = ann.locator("#queueFeedback")
            assert feedback.get_attribute("role") == "status"
            assert feedback.get_attribute("aria-live") == "polite"
            assert f"Moving {moved_title} from position 2 of 5 to position 3" in feedback.text_content()
            assert "Waiting for the room to accept the move" in feedback.text_content()
            release.set()
            feedback.filter(
                has_text=f"{moved_title} moved to position 3 of 5").wait_for(timeout=5000)
            for page in (ben, cal):
                page.wait_for_function(
                    "(before) => JSON.stringify([...document.querySelectorAll('#queue .queue-item')].map(e=>e.querySelector('.queue-title,strong,span').textContent.trim())) !== JSON.stringify(before)",
                    arg=previous, timeout=5000,
                )
            assert time.monotonic() - started < 1.0
            assert titles(ann) == titles(ben) == titles(cal)
            assert rig.host_obj.now_playing == "/private/current-film.mkv"
            assert all(page.locator("#queueFeedback").get_attribute("role") == "status"
                       and page.locator("#queueFeedback").get_attribute("aria-live") == "polite"
                       for page in pages)
            assert "Position 3 of 5" in ann.locator("#queue .queue-item").nth(2).inner_text()
        finally:
            release.set()
            browser.close()


@pytest.mark.skipif(not OPT_IN, reason="explicit opt-in: installed Playwright Chromium")
def test_queue_over_the_status_cap_is_disclosed_not_silently_truncated():
    from playwright.sync_api import sync_playwright

    rig = _RealQueueRig([f"/p/s{i}.mp3" for i in range(130)])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-background-networking"])
        page = browser.new_page(viewport={"width": 390, "height": 800}, service_workers="block")
        try:
            page.goto(f"http://{rig.host}/", wait_until="domcontentloaded")
            page.locator("#name").fill("Ann")
            page.locator("#loginForm button").click()
            page.locator("#queue .queue-item").nth(99).wait_for()
            assert page.locator("#queueCount").text_content() == "100 of 130 shown"
        finally:
            browser.close()


@pytest.mark.skipif(not OPT_IN, reason="explicit opt-in: installed Playwright Chromium")
def test_stale_move_is_rejected_explained_and_the_list_catches_up():
    from playwright.sync_api import sync_playwright

    rig = _RealQueueRig([f"/private/song{i}.mp3" for i in range(4)])
    origin = f"http://{rig.host}"
    live = {"on": True}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-background-networking"])
        page = browser.new_page(viewport={"width": 390, "height": 800}, service_workers="block")

        def gate(route):  # freeze this client's view: no events, no status polls
            if live["on"] or "/api/action" in route.request.url or "/api/events" not in route.request.url \
                    and "/api/status" not in route.request.url:
                route.continue_()
            else:
                route.abort()

        page.route("**/*", gate)
        try:
            page.goto(origin + "/", wait_until="domcontentloaded")
            page.locator("#name").fill("Ben")
            page.locator("#loginForm button").click()
            page.locator("#queue .queue-item").nth(3).wait_for()
            live["on"] = False
            page.wait_for_timeout(500)
            host = rig.host_obj  # another participant reorders: Ben's revision is now stale
            host.queue.insert(0, host.queue.pop(3))
            host._portal_observe_queue()
            page.locator("#queue .queue-item").nth(1).get_by_role("button", name="later in Up Next").first.click()
            page.locator("#queueFeedback").filter(has_text="not applied").wait_for(timeout=5000)
            assert "Up Next changed" in page.locator("#queueFeedback").text_content()
            assert [p for a, p in rig.calls if a == "queue_move"], "client never sent the stale move"
            assert host.queue[0].endswith("song3.mp3") and host.queue[1].endswith("song0.mp3")  # not corrupted
            live["on"] = True
            page.wait_for_function(
                "() => document.querySelector('#queue .queue-item').textContent.includes('song3')", timeout=8000)
        finally:
            browser.close()


@pytest.mark.skipif(not OPT_IN, reason="explicit opt-in: installed Playwright Chromium")
def test_320px_with_200_percent_text_has_no_horizontal_scroll():
    from playwright.sync_api import sync_playwright

    rig = _RealQueueRig([f"/p/Some quite long song title number {i}.mp3" for i in range(6)])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-background-networking"])
        page = browser.new_page(viewport={"width": 320, "height": 640}, service_workers="block")
        try:
            page.goto(f"http://{rig.host}/", wait_until="domcontentloaded")
            page.locator("#name").fill("Ann")
            page.locator("#loginForm button").click()
            page.locator("#queue .queue-item").nth(5).wait_for()
            page.add_style_tag(content="html{font-size:200% !important}")
            page.wait_for_timeout(300)
            width, inner = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
            assert width <= inner, f"{width}px wide in {inner}px at 200% text"
        finally:
            browser.close()
