"""#454: the web remote shows a DEMO badge only on a genuine isolated demo host."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_mode
import portal

TOKEN = "ab" * 32


@pytest.fixture
def demo_env(tmp_path, monkeypatch):
    (tmp_path / demo_mode.MARKER).write_text(TOKEN, encoding="ascii")
    monkeypatch.setenv(demo_mode.ENV, "1")
    monkeypatch.setenv(demo_mode.TOKEN_ENV, TOKEN)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def test_no_badge_and_no_placeholder_on_a_normal_host(monkeypatch):
    monkeypatch.delenv(demo_mode.ENV, raising=False)
    page = portal._page().decode()
    assert "sc-demo" not in page and "SC_DEMO" not in page and ">DEMO<" not in page


def test_badge_appears_on_the_room_page_of_a_verified_demo_host(demo_env):
    page = portal._page().decode()
    assert page.count('class="sc-demo"') == 1 and ">DEMO</span>" in page
    assert "<!--SC_DEMO-->" not in page


def test_a_forged_environment_without_the_private_marker_gets_no_badge(tmp_path, monkeypatch):
    monkeypatch.setenv(demo_mode.ENV, "1")
    monkeypatch.setenv(demo_mode.TOKEN_ENV, TOKEN)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))  # no marker file written
    assert "sc-demo" not in portal._page().decode()


def test_badge_text_is_static_markup_with_no_user_controlled_content(demo_env):
    badge = portal._demo_badge()
    assert badge.startswith("<span") and badge.endswith("</span>")
    assert "<script" not in badge and "{" not in badge


def test_both_page_templates_carry_the_marker_once_each():
    assert portal._HTML.count("<!--SC_DEMO-->") == 1
    assert portal._NODES_HTML.count("<!--SC_DEMO-->") == 1
