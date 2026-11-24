"""#591: every web screen has a persistent Home control and shows the host version."""
from __future__ import annotations

from html.parser import HTMLParser
from http.client import HTTPConnection
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_screen_page
import version

PAGES = ["/", "/index.html", "/screen", "/nodes"]


class _Header(HTMLParser):
    """Records Home links and version badges, and whether each sits in a hidden view."""

    VOID = {"meta", "link", "input", "img", "br", "hr", "source", "path"}

    def __init__(self):
        super().__init__()
        self.stack: list[tuple[str, dict]] = []
        self.home: list[dict] = []
        self.versions: list[tuple[dict, str, bool]] = []
        self._in_version: dict | None = None
        self._text = ""

    def _hidden_ancestor(self) -> bool:
        return any("hidden" in attrs for _, attrs in self.stack)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "scVersion":
            self._in_version, self._text = attrs, ""
            self._version_hidden = self._hidden_ancestor() or "hidden" in attrs
        if tag == "a" and (attrs.get("class") or "").split()[:1] in (["home-btn"], ["home-link"]):
            self.home.append({**attrs, "_hidden": self._hidden_ancestor() or "hidden" in attrs,
                              "_in": [t for t, _ in self.stack]})
        if tag not in self.VOID:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if self._in_version is not None and tag == "span":
            self.versions.append((self._in_version, self._text, self._version_hidden))
            self._in_version = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_version is not None:
            self._text += data


@pytest.fixture(scope="module")
def server():
    srv = portal._PortalHTTPServer(("127.0.0.1", 0), "234567", lambda *_: {})
    srv.nodes_provider = lambda: [{"name": "Study", "url": "http://192.168.1.9:80/"}]
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _get(server, path: str) -> tuple[int, str]:
    port = server.server_address[1]
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Host": f"smoothcast.local:{port}"})
    reply = conn.getresponse()
    return reply.status, reply.read().decode("utf-8")


@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_a_visible_home_control_and_the_exact_host_version(server, path):
    status, text = _get(server, path)
    assert status == 200
    assert "__SC_VERSION__" not in text and "/*TOKENS*/" not in text
    page = _Header()
    page.feed(text)

    # Exactly one version badge, rendered by the server, never inside a hidden view.
    assert len(page.versions) == 1
    attrs, shown, hidden = page.versions[0]
    assert shown == version.label()
    assert attrs["aria-label"] == f"Host version {version.label()}"
    assert not hidden

    # Exactly one Home control, never inside a view that can be hidden, with a text label.
    homes = [h for h in page.home if "home" in (h.get("class") or "")]
    assert len(homes) == 1
    home = homes[0]
    assert not home["_hidden"]
    assert home["href"] in ("/", "#roomTop")
    assert "main" not in home["_in"]  # outside the scrolling content, so always reachable


def test_room_home_sits_in_the_sticky_app_bar_and_returns_focus_to_the_top():
    page = portal._page().decode("utf-8")
    bar = page[page.index('<header class="app-bar"'):page.index("</header>")]
    assert 'id="homeButton"' in bar and "<span>Home</span>" in bar
    assert 'id="scVersion"' in bar
    assert 'header.app-bar{position:sticky;top:0' in page
    assert '<p class="site-intro" id="roomTop" tabindex="-1">' in page  # focus target
    script = page[page.index("// #591"):]
    assert 'top.focus({preventScroll:true})' in script
    assert 'prefers-reduced-motion: reduce' in script
    # Section nav docks under the bar instead of under the viewport top.
    assert "#dashboard nav{top:calc(var(--bar-h) + 6px)" in page


def test_screen_home_returns_to_the_room_and_only_fades_during_untouched_playback():
    page = portal_screen_page.screen_page().decode("utf-8")
    body = page[page.index("<body>"):]
    first = body[:body.index('<div class="stage"')]
    assert 'id="homeLink" href="/"' in first  # before (outside) all four screen states
    assert 'id="scVersion"' in first
    wake = page[page.index("function wake()"):page.index("document.addEventListener(\"pointermove\"")]
    assert 'home.classList.remove("hide")' in wake
    assert '!video.paused&&!$("player").hidden' in wake  # never hidden on a slate or form
    assert ".home-link:focus-visible{opacity:1" in page  # keyboard always reveals it
