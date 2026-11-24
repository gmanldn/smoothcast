"""The self-hosted screen page and dashboard panel stay valid and offline."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_screen_page
import portal_screens


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, flags=re.S)


def test_pages_are_self_contained_and_never_use_innerhtml():
    pages = {
        "screen": portal_screen_page.screen_page().decode(),
        "panel": portal_screen_page.panel_html(),
        "dashboard": portal._page().decode(),
    }
    for name, html in pages.items():
        assert not re.search(r"(?:src|href)=[\"']https?://", html), name
        assert "innerHTML" not in html and "document.write" not in html, name
        assert "eval(" not in html, name
    assert "__MIMES__" not in pages["screen"]


def test_dashboard_embeds_the_panel_once_before_the_scripts_it_hooks():
    html = portal._page().decode()
    assert html.count('id="screensPanel"') == 1
    assert "window.scRenderScreens&&window.scRenderScreens(s)" in html
    assert html.index("</main>") > html.index('id="screensPanel"')


def test_every_capability_the_page_probes_is_known_to_the_server():
    html = portal_screen_page.screen_page().decode()
    listed = re.search(r"const MIMES=(\[.*?\]);", html).group(1)
    mimes = set(re.findall(r'"([a-z]+/[a-z0-9.+-]+)"', listed))
    assert mimes == set(portal_screens.KNOWN_MIMES)


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
@pytest.mark.parametrize("name", ["screen", "panel"])
def test_page_scripts_parse(name, tmp_path):
    html = (portal_screen_page.screen_page().decode() if name == "screen"
            else portal_screen_page.panel_html())
    for index, script in enumerate(_scripts(html)):
        target = tmp_path / f"{name}{index}.js"
        target.write_text(script, encoding="utf-8")
        result = subprocess.run(["node", "--check", str(target)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr


def test_wake_lock_pip_and_dim_hint_contract():
    html = portal_screen_page.screen_page().decode()
    assert 'navigator.wakeLock.request("screen")' in html
    assert 'addEventListener("visibilitychange"' in html and "keepAwake()" in html
    assert 'id="pipButton"' in html and "document.pictureInPictureEnabled" in html
    assert "For an iPad on a stand, turn on Guided Access" in html


def test_idle_screen_shows_self_hosted_join_qr_and_safe_short_address():
    html = portal_screen_page.screen_page().decode()
    assert '<div class="stage" id="slate" hidden>' in html
    assert 'src="/join-qr.png"' in html
    assert 'id="joinAddress"' in html
    assert '$("joinAddress").textContent=location.host' in html
    assert "joinAddress\").innerHTML" not in html
    # Playing view and login remain independent from the idle QR slate.
    assert '<div id="player" hidden>' in html
    assert 'id="loginView" hidden' in html


def test_idle_join_code_is_a_corner_badge_when_queued_and_large_when_queue_empty():
    html = portal_screen_page.screen_page().decode()
    assert "#slate.corner .join-qr{position:fixed" in html
    assert "#slate.empty .join-qr img{width:min(320px" in html
    assert "function slateLayout(queueEmpty)" in html
    # False => something is queued (corner); true => nothing queued (large);
    # absent => keep the default centred layout.
    assert 'toggle("corner",queueEmpty===false)' in html
    assert 'toggle("empty",queueEmpty===true)' in html
    assert "slateLayout(d.queue_empty)" in html
