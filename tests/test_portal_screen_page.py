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
