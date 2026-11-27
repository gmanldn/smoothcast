import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import warm_registry as w


class H:
    def __init__(self): self.cancelled = 0
    def cancel(self): self.cancelled += 1


def mk(size=0, boom=False):
    s = {"handles": [], "gone": [], "dirs": set()}
    def start(k, d):
        if boom: raise RuntimeError("ffmpeg missing")
        h = H(); s["handles"].append(h); s["dirs"].add(d); return h
    def rm(d): s["gone"].append(d); s["dirs"].discard(d)
    return w.Registry(start, rm, lambda d: size), s


def test_trigger_rules():
    assert w.should_warm("k", 500, True) and w.should_warm("k", 59.9, False)
    assert not w.should_warm("k", 60, False) and not w.should_warm("k", 500, False)
    assert not w.should_warm(None, 5, True) and not w.should_warm("k", None, False) and not w.should_warm("k", -1, False)


def test_warm_job_cancels_on_queue_change_without_orphans():
    r, s = mk(); assert r.request("film-1") == "warming"
    r.on_queue_changed("film-2")
    assert s["handles"][0].cancelled == 1 and s["dirs"] == set() and r.state == "idle" and r.key is None
    assert r.log == ["start:film-1", "cancel:film-1:queue_changed"]
    r.request("film-2"); r.on_queue_changed("film-2"); assert s["handles"][1].cancelled == 0 and r.state == "warming"


def test_only_one_warm_job_ever_and_repeat_request_is_noop():
    r, s = mk(); r.request("a"); assert r.request("a") == "warming" and len(s["handles"]) == 1
    r.request("b"); assert s["handles"][0].cancelled == 1 and len(s["dirs"]) == 1 and r.key == "b"


def test_started_item_takes_warm_segments_skipping_probe_and_encode():
    r, s = mk(); r.request("film-1"); r.mark_done("film-1")
    t = r.take("film-1")
    assert t == {"dir": "warm/film_1", "skip_probe": True, "skip_initial_encode": True, "segments": 3} and r.state == "idle"
    assert s["gone"] == [] and s["handles"][0].cancelled == 0       # dir now belongs to the stream
    assert r.take("film-1") is None


def test_play_before_ready_cancels_and_plays_cold():
    r, s = mk(); r.request("x"); assert r.take("x") is None and s["dirs"] == set() and s["handles"][0].cancelled == 1
    assert r.take("other") is None


def test_over_budget_is_dropped_and_start_failure_is_skipped():
    r, s = mk(size=w.BUDGET_BYTES + 1); r.request("big"); r.mark_done("big")
    assert r.state == "idle" and s["dirs"] == set() and r.log[-1] == "cancel:big:budget"
    r2, s2 = mk(boom=True); assert r2.request("y") == "skipped" and r2.state == "idle" and s2["gone"] == ["warm/y"]


def test_empty_key_cancels_and_keys_are_sanitised_into_the_warm_root():
    r, s = mk(); r.request("../../etc/passwd"); assert ".." not in r.dir and r.dir.startswith("warm/") and "/" not in r.dir[5:]
    assert r.request(None) == "idle" and s["dirs"] == set()
    assert w.BUDGET_BYTES == 524288000 and w.HEAD_BYTES == 8388608
