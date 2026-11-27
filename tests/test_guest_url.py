import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import guest_url as gu


def test_safe_direct_urls_canonicalise():
    assert gu.validate("https://Example.com/a/b.mp3?x=1#frag")[0] == "https://example.com/a/b.mp3?x=1"
    assert gu.validate("http://cdn.example.org:8080/v.mp4")[0] == "http://cdn.example.org:8080/v.mp4"


@pytest.mark.parametrize("bad", [
    "", "   ", "file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)",
    "http://user:pw@example.com/x", "http://localhost/x", "http://127.0.0.1/x",
    "http://169.254.169.254/latest", "http://10.0.0.5/x", "http://192.168.1.2/x",
    "http://[::1]/x", "http://2130706433/x", "http://0x7f.1/x", "http://printer.local/x",
    "http://example.com:22/x", "http://example.com/a b", "https://x" + "a" * 3000 + ".com",
    "http://metadata.google.internal/x", "http://example.com\\@evil/x"])
def test_hostile_urls_rejected(bad):
    assert gu.validate(bad)[0] is None


def test_rebinding_caught_at_playback():
    assert gu.revalidate_resolved("https://example.com/a.mp4", ["93.184.216.34"]) == (True, "")
    assert not gu.revalidate_resolved("https://example.com/a.mp4", ["127.0.0.1"])[0]
    assert not gu.revalidate_resolved("https://example.com/a.mp4", [])[0]
    assert not gu.revalidate_resolved("http://10.0.0.1/a", ["93.184.216.34"])[0]


def test_summary_hides_query_and_credentials():
    s = gu.summary("https://example.com/" + "p" * 80 + "?token=SECRET")
    assert "SECRET" not in s and s.startswith("example.com/") and s.endswith("…")
