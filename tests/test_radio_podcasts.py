import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import radio_podcasts as rp

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Show</title>
<item><title>Old</title><guid>g1</guid><pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate><enclosure url="https://cdn.example.com/1.mp3" type="audio/mpeg"/><itunes:duration>1:02:03</itunes:duration></item>
<item><title>New</title><guid>g2</guid><pubDate>Mon, 01 Jan 2025 10:00:00 GMT</pubDate><enclosure url="https://cdn.example.com/2.mp3" type="audio/mpeg"/></item>
<item><title>No audio</title><enclosure url="https://cdn.example.com/x.pdf" type="application/pdf"/></item></channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title><entry><title>E</title><id>i1</id><link rel="enclosure" href="https://x.example.com/e.m4a" type="audio/mp4"/></entry></feed>"""


def test_parses_rss_and_atom_newest_first_and_skips_non_audio():
    f, _ = rp.parse_feed(RSS)
    assert f["title"] == "Show" and [e["guid"] for e in f["episodes"]] == ["g2", "g1"] and f["episodes"][1]["duration"] == 3723.0
    a, _ = rp.parse_feed(ATOM); assert a["episodes"][0]["url"].endswith("e.m4a")


def test_rejects_entity_expansion_doctype_oversize_and_deep_nesting_and_junk():
    bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><channel><title>&b;</title></channel></rss>'
    assert rp.parse_feed(bomb)[0] is None and "blocks" in rp.parse_feed(bomb)[1]
    assert rp.parse_feed(b"<!doctype html><rss/>")[0] is None
    assert rp.parse_feed(b"<rss>" + b" " * (rp.MAX_BYTES + 1))[1] == "That feed is too large."
    deep = b"<rss>" + b"<a>" * 40 + b"</a>" * 40 + b"</rss>"
    assert rp.parse_feed(deep)[1] == "That feed is too deeply nested."
    for junk in (b"not xml", b"<html><body/></html>", b"", None):
        assert rp.parse_feed(junk)[0] is None


def test_episode_cap_and_feed_cap():
    items = b"".join(b'<item><guid>%d</guid><enclosure url="https://c.example.com/%d.mp3" type="audio/mpeg"/></item>' % (i, i) for i in range(700))
    f, _ = rp.parse_feed(b"<rss><channel><title>T</title>" + items + b"</channel></rss>")
    assert len(f["episodes"]) == rp.MAX_EPISODES
    s = rp.Subscriptions()
    for i in range(rp.MAX_FEEDS):
        assert s.add_feed(f"https://feeds.example.com/{i}.xml")[0]
    assert s.add_feed("https://feeds.example.com/extra.xml")[0] is None


def test_url_safety_reused_for_stations_and_feeds():
    s = rp.Subscriptions()
    for bad in ("http://192.168.1.5/stream", "ftp://x.example.com/s", "https://user:pw@radio.example.com/s", "javascript:alert(1)", "http://localhost/s"):
        assert not s.add_station("x", bad)[0] and s.add_feed(bad)[0] is None
    assert s.add_station("Jazz FM", "https://stream.example.com/jazz.mp3")[0] and len(s.stations) == 1


def test_conditional_get_304_keeps_data_and_etag_roundtrip():
    s = rp.Subscriptions(); u, _ = s.add_feed("https://feeds.example.com/a.xml")
    assert s.conditional_headers(u) == {} and s.due(0) == [u]
    assert s.handle_response(u, 200, {"ETag": '"v1"', "Last-Modified": "Tue, 02 Jan 2025 00:00:00 GMT"}, RSS, 100)[0]
    assert s.conditional_headers(u) == {"If-None-Match": '"v1"', "If-Modified-Since": "Tue, 02 Jan 2025 00:00:00 GMT"}
    assert s.due(100 + rp.REFRESH_S - 1) == [] and s.due(100 + rp.REFRESH_S) == [u]
    assert s.handle_response(u, 304, {}, b"", 7300)[0] and len(s.feeds[u]["episodes"]) == 2 and s.feeds[u]["checked"] == 7300
    assert not s.handle_response(u, 500, {}, b"", 9000)[0] and len(s.feeds[u]["episodes"]) == 2
    assert not s.handle_response(u, 200, {}, b"<!DOCTYPE x><rss/>", 9000)[0] and len(s.feeds[u]["episodes"]) == 2


def test_new_badge_and_per_resident_progress():
    s = rp.Subscriptions(); u, _ = s.add_feed("https://feeds.example.com/a.xml"); s.handle_response(u, 200, {}, RSS, 1)
    assert s.new_count(u) == 2 and s.total_new() == 2
    s.mark_seen(u); assert s.total_new() == 0
    s.set_progress("sam", "g1", 600); s.set_progress("mum", "g1", 30); s.set_progress("", "g1", 5)
    assert s.get_progress("sam", "g1") == 600 and s.get_progress("mum", "g1") == 30 and s.get_progress(None, "g1") == 0.0
