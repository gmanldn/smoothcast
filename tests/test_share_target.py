import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pwa_manifest
import share_target as st


def test_manifest_gets_valid_share_target_schema():
    m = json.loads(st.manifest_with_share(pwa_manifest.manifest()))
    assert st.valid_share_target(m["share_target"]) and m["share_target"]["action"] == "/share" and m["name"] and m["start_url"] == "/"
    bad = dict(m["share_target"], method="GET"); assert not st.valid_share_target(bad)
    assert not st.valid_share_target({}) and not st.valid_share_target({"action": "/s", "method": "POST", "enctype": "multipart/form-data", "params": {}})


def test_guard_rejects_cross_origin_unauthenticated_offlan_and_wrong_method():
    ok = dict(method="POST", origin="http://house.local:8080", host="house.local:8080", authenticated=True)
    assert st.guard(**ok) == (200, "")
    assert st.guard(**{**ok, "origin": "http://evil.example"})[0] == 403 and st.guard(**{**ok, "origin": None})[0] == 403
    assert st.guard(**{**ok, "authenticated": False})[0] == 401 and st.guard(**{**ok, "method": "GET"})[0] == 405
    assert st.guard(**ok, content_type="application/json")[0] == 415
    assert st.guard(**ok, on_lan=False) == (403, "Connect to the house Wi-Fi to share.")
    assert st.guard(**{**ok, "origin": "http://house.local:8080.evil.com"})[0] == 403


def test_classify_files_urls_and_messages():
    r = st.classify([{"name": "a.mp4", "type": "video/mp4", "size": 5}, {"name": "x.pdf", "type": "application/pdf"}, {"name": "p.jpg", "type": "image/jpeg"}])
    assert [i["kind"] for i in r["items"]] == ["video", "image"] and "isn't a video" in r["messages"][0]
    u = st.classify([], text="look https://video.example.com/watch?v=1.", title="T")
    assert u["items"] == [{"kind": "url", "url": u["items"][0]["url"], "title": "T"}] and u["items"][0]["url"].startswith("https://video.example.com")
    bad = st.classify([], url="http://192.168.1.1/admin"); assert bad["items"] == [] and bad["messages"]
    assert st.classify([])["messages"] == ["Nothing to share was found."]
    assert len(st.classify([{"name": f"{i}.mp3", "type": "audio/mpeg"} for i in range(30)])["items"]) == st.MAX_FILES


def test_pending_share_survives_login_once_and_expires():
    t = [0.0]; p = st.Pending(clock=lambda: t[0]); tok = p.stash({"items": [1]})
    t[0] = 60; assert p.resume(tok) == {"items": [1]} and p.resume(tok) is None
    tok2 = p.stash({"x": 1}); t[0] = 60 + st.PENDING_TTL_S + 1; assert p.resume(tok2) is None and p.resume("nope") is None
    for i in range(80): p.stash({"i": i})
    assert len(p.d) <= st.MAX_PENDING
