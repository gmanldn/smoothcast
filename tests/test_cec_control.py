import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cec_control as cec


def fake(tmp_path, body, name="cec-client"):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n"); p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_allow_list_rejects_everything_else_before_spawning():
    calls = []
    run = lambda *a, **k: calls.append(a)
    for bad in ("on 0; rm -rf /", "tx 10:36", "on 16", "on -1", "q", "", "on 0\nstandby 0", "as 1", None, 5):
        assert cec.send(bad, run=run) == {"ok": False, "out": "", "reason": "not_allowed"}
    assert calls == []
    for good in ("on 0", "standby 15", "as", "pow 0"):
        assert cec.allowed(good)


def test_real_subprocess_with_fake_cec_client(tmp_path):
    exe = fake(tmp_path, 'read cmd; echo "got:$cmd"; echo "power status: on"')
    r = cec.send("on 0", exe=exe); assert r["ok"] and "got:on 0" in r["out"] and cec.power_status(r["out"]) == "on"
    assert cec.send("on 0", exe=str(tmp_path / "missing"))["reason"] == "absent"
    assert cec.send("on 0", exe=fake(tmp_path, "exit 1", "busy"))["reason"] == "busy"
    assert cec.send("on 0", exe=fake(tmp_path, "echo \"can't open CEC adapter\"; exit 0", "noadapter"))["reason"] == "busy"


def test_timeout_is_bounded_and_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(cec, "TIMEOUT_S", 0.3)
    import time; t = time.time()
    assert cec.send("pow 0", exe=fake(tmp_path, "sleep 5", "slow"))["reason"] == "timeout" and time.time() - t < 3


def test_capability_detection_and_doctor_line():
    assert cec.available(which=lambda n: "/usr/bin/cec-client") and not cec.available(which=lambda n: None)
    assert cec.doctor_line("Lounge PC", True) == "HDMI-CEC: available on Lounge PC" and cec.doctor_line("X", False) == "HDMI-CEC: not available"
    assert cec.power_status("power status: standby") == "standby" and cec.power_status("junk") == "unknown"


def test_waker_flow_ignored_tv_logged_once_and_invisible_when_no_node():
    sent, logs = [], []
    ok = lambda out: (lambda c: sent.append(c) or {"ok": True, "out": out, "reason": ""})
    w = cec.Waker(ok("power status: on"), logs.append)
    assert w.wake_for_cast("Lounge", "standby", False) == {"acted": False, "why": "no_cec_node"} and sent == []
    assert w.wake_for_cast("Lounge", "on", True)["why"] == "already_on" and sent == []
    assert w.wake_for_cast("Lounge", "standby", True) == {"acted": True, "why": "woken"} and sent == ["on 0", "as"]
    sent.clear(); w2 = cec.Waker(ok("power status: standby"), logs.append)
    assert w2.wake_for_cast("Den", "standby", True)["why"] == "ignored_by_tv"
    assert w2.wake_for_cast("Den", "standby", True)["why"] == "ignored" and len(logs) == 1 and sent == ["on 0", "as"]
    w3 = cec.Waker(lambda c: {"ok": False, "out": "", "reason": "busy"}); assert w3.wake_for_cast("A", "off", True) == {"acted": False, "why": "busy"}
