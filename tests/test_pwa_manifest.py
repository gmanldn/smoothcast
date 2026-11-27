import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pwa_manifest as pw


def test_manifest_is_standalone_and_start_url_carries_no_secrets():
    m = json.loads(pw.manifest(start_url="/?token=SECRET"))
    assert m["display"] == "standalone" and m["start_url"] == "/" and "SECRET" not in json.dumps(m)
    assert json.loads(pw.manifest(start_url="//evil.com"))["start_url"] == "/"
    assert json.loads(pw.manifest(start_url="/room"))["start_url"] == "/room"


def test_only_exact_shell_assets_are_cacheable():
    assert all(pw.cacheable(p) for p in pw.SHELL_ASSETS)
    for p in ("/api/status", "/pair", "/queue", "/media/a.mp4", "/history", "/static/app.js?x=1", "/events", "/other"):
        assert not pw.cacheable(p), p
    assert not pw.cacheable("/static/app.js", "POST")


def test_install_offer_requires_secure_https_lan_and_explains_otherwise():
    assert pw.install_offer(True, True, True)["offer"]
    http = pw.install_offer(False, True, False)
    assert not http["offer"] and "HTTPS" in http["message"]
    assert not pw.install_offer(True, False, True)["offer"]


def test_service_worker_excludes_api_and_uses_allowlist_only():
    js = pw.service_worker()
    assert "/static/app.js" in js and "/api/" not in js and "u.search" in js and "caches.delete" in js
