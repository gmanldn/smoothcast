import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import drain as d
import sleep_inhibit as si


class Backend:
    def __init__(self): self.acq = self.rel = 0
    def acquire(self, why): self.acq += 1; return "tok"
    def release(self, tok): self.rel += 1


def rig(start=True, ready=True, switch=True, boom=False):
    ev, t = [], [0.0]
    def mk(name, ret=None):
        def f(*a):
            ev.append(name)
            if boom and name == "start": raise RuntimeError("x")
            return ret
        return f
    act = {"start": mk("start", start), "ready": mk("ready", ready), "switch": mk("switch", switch), "stop_local": mk("stop_local"),
           "save_resume": mk("save_resume"), "notify": lambda m: ev.append("notify:" + m), "announce": mk("announce")}
    b = Backend(); inh = si.Inhibitor(b, lambda: t[0])
    return act, ev, b, inh, t


NODES = [{"id": "n1", "awake": True, "encode": True, "has_file": True}]
S = {"key": "k", "position": 3733}


def test_never_stops_local_before_target_confirmed_and_switched():
    act, ev, b, inh, t = rig(); r = d.drain(S, NODES, act, inh, lambda: t[0])
    assert r["outcome"] == "handed_over" and r["target"] == "n1"
    assert ev.index("stop_local") > ev.index("switch") > ev.index("ready") > ev.index("start")
    for kw in ({"start": False}, {"ready": False}, {"switch": False}, {"boom": True}):
        act, ev, b, inh, t = rig(**kw); r = d.drain(S, NODES, act, inh, lambda: t[0])
        assert r["outcome"] == "stopped" and "stop_local" in ev
        assert ev.index("stop_local") > ev.index("save_resume") and ("switch" not in ev or kw == {"switch": False})


def test_inhibitor_released_on_every_path_even_on_exception():
    for kw in ({}, {"start": False}, {"boom": True}):
        act, ev, b, inh, t = rig(**kw); d.drain(S, NODES, act, inh, lambda: t[0]); assert b.acq == 1 and b.rel == 1 and not inh.held
    act, ev, b, inh, t = rig(); act["announce"] = lambda m: (_ for _ in ()).throw(RuntimeError()); d.drain(S, NODES, act, inh, lambda: t[0]); assert b.rel == 1
    b2 = Backend()
    try:
        with si.Inhibitor(b2) as i: raise ValueError
    except ValueError: pass
    assert b2.rel == 1; i.release(); assert b2.rel == 1               # idempotent
    class Bad(Backend):
        def acquire(self, w): raise OSError
    assert si.Inhibitor(Bad()).acquire() is False


def test_inhibitor_never_holds_longer_than_15s():
    t = [0.0]; i = si.Inhibitor(Backend(), lambda: t[0], max_hold=999); i.acquire()
    assert i.max_hold == 15.0 and not i.expired() and i.remaining() == 15.0
    t[0] = 15.0; assert i.expired() and i.remaining() == 0.0
    assert si.Inhibitor(si.NoopBackend()).acquire() is True


def test_no_target_saves_resume_and_notifies_exact_message():
    act, ev, b, inh, t = rig(); r = d.drain(S, [{"id": "z", "awake": False, "encode": True, "has_file": True}], act, inh, lambda: t[0], "Lounge PC")
    assert r == {"outcome": "stopped", "steps": ["no_target"]}
    assert ev == ["announce", "save_resume", "notify:Lounge PC is going to sleep; playback stopped at 1:02:13.", "stop_local"]


def test_falls_to_next_target_when_first_fails_and_deadline_stops_trying():
    nodes = NODES + [{"id": "n2", "awake": True, "encode": True, "proxy_ok": True}]
    calls = []
    act, ev, b, inh, t = rig(); act["start"] = lambda tg, p: (calls.append(tg["id"]), tg["id"] == "n2")[1]
    assert d.drain(S, nodes, act, inh, lambda: t[0])["target"] == "n2" and calls == ["n1", "n2"]
    act, ev, b, inh, t = rig(); orig = act["announce"]; act["announce"] = lambda m: (orig(m), t.__setitem__(0, 16.0))[0]
    r = d.drain(S, NODES, act, inh, lambda: t[0]); assert r["outcome"] == "stopped" and r["steps"] == ["deadline", "no_target"] and "start" not in ev


def test_pick_target_rules_message_and_format():
    n = [{"id": "a", "awake": True, "encode": True, "proxy_ok": True, "load": 0.1}, {"id": "b", "awake": True, "encode": True, "has_file": True, "load": 0.9},
         {"id": "c", "awake": True, "encode": False, "has_file": True}, {"id": "e", "awake": True, "encode": True}]
    assert d.pick_target(n, "k")["id"] == "b" and d.pick_target(n[2:], "k") is None and d.pick_target([], "k") is None
    assert d.leaving(15) == {"type": "node.leaving", "in_seconds": 15} and d.leaving(999)["in_seconds"] == 60
    assert d.fmt_time(3733) == "1:02:13" and d.fmt_time(None) == "0:00:00" and d.fmt_time(-5) == "0:00:00"
