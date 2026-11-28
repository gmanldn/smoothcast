"""#465: shutdown is ordered, bounded, logged, and leaves nothing behind."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import entry_name
import fingerprint
import library_folders as lf
import library_index_v2 as li
import mesh_library
import replica_store as rs
import shutdown_plan as sp
from test_room_conformance import RoomHarness


# --- the plan --------------------------------------------------------------
def test_steps_run_in_order_once_and_are_reported():
    order, plan = [], sp.ShutdownPlan()
    assert plan.run("a", lambda: order.append("a")) and plan.run("b", lambda: order.append("b"))
    assert plan.run("a", lambda: order.append("again")) is True          # idempotent per name
    report = plan.report()
    assert order == ["a", "b"] and [s["name"] for s in report["steps"]] == ["a", "b"]
    assert report["within_budget"] is True and report["overruns"] == []


def test_a_hung_threaded_step_is_abandoned_logged_by_name_and_does_not_block_the_exit():
    release, logs = threading.Event(), []
    plan = sp.ShutdownPlan(log=logs.append)
    started = time.monotonic()
    assert plan.run("portal_socket", lambda: release.wait(5), deadline=0.1, threaded=True) is False
    assert time.monotonic() - started < 1.0                              # the hang was not waited out
    assert any("portal_socket" in line and "abandoned" in line for line in logs)
    assert plan.report()["overruns"] == ["portal_socket"]
    release.set()


def test_slow_inline_steps_are_logged_with_their_name_and_failures_never_propagate():
    now, logs = [0.0], []
    plan = sp.ShutdownPlan(clock=lambda: now[0], log=logs.append)
    plan.run("save_settings", lambda: now.__setitem__(0, now[0] + 0.4), deadline=0.25)
    assert plan.run("boom", lambda: 1 / 0) is False                       # error swallowed, reported
    assert any("save_settings" in line and "400 ms" in line for line in logs)
    assert any("boom" in line and "ZeroDivisionError" in line for line in logs)
    now[0] += 0.7
    assert plan.report()["within_budget"] is False and plan.report()["total_ms"] == 1100.0


# --- the ledger ------------------------------------------------------------
def test_ledger_counts_clean_and_unclean_previous_exits(tmp_path):
    ledger = sp.ShutdownLedger(tmp_path / "shutdown.json")
    assert ledger.begin() == "none"                                       # first ever start
    assert ledger.begin() == "unclean"                                    # it never reported ending
    ledger.end({"total_ms": 312.5, "overruns": ["portal"]})
    assert ledger.begin() == "clean"
    summary = ledger.summary()
    assert summary["clean_exits"] == 1 and summary["unclean_exits"] == 1
    assert summary["last_shutdown_ms"] == 312.5 and summary["last_overruns"] == ["portal"]
    assert not list(tmp_path.glob("*.tmp"))


def test_ledger_survives_corruption_and_unwritable_locations(tmp_path):
    path = tmp_path / "shutdown.json"
    path.write_text("{not json")
    ledger = sp.ShutdownLedger(path)
    assert ledger.begin() == "none" and ledger.summary()["unclean_exits"] == 0
    blocked = sp.ShutdownLedger(tmp_path / "file" / "x.json")
    (tmp_path / "file").write_text("a file, not a directory")
    assert blocked.begin() == "none"                                      # never raises


# --- a headless app core, quit, nothing left behind -----------------------
class FakeZeroconf:
    registered: list = []

    def __init__(self, ip):
        pass

    def register_service(self, info):
        FakeZeroconf.registered.append(info.server)

    def unregister_service(self, info):
        FakeZeroconf.registered.remove(info.server)

    def close(self):
        pass


def listening(pid: int) -> list:
    proc = psutil.Process(pid)
    conns = proc.net_connections(kind="inet") if hasattr(proc, "net_connections") else proc.connections("inet")
    return [c for c in conns if c.status == psutil.CONN_LISTEN]


def test_headless_core_quits_inside_the_budget_and_leaves_nothing_behind(tmp_path, monkeypatch):
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))                # any stray temp file shows up here
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    FakeZeroconf.registered = []
    baseline_threads = {t.name for t in threading.enumerate()}

    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "Film (1999).mkv").write_bytes(b"x" * 5000)
    indexer = li.LibraryIndexer(tmp_path / "idx.sqlite3", probe=lambda p: {})
    indexer.set_folders([lf.LibraryFolder("f_1", str(lib), "Films", "video", True)])
    indexer.start()
    mesh = mesh_library.MeshLibrary(indexer, store=rs.ReplicaStore(tmp_path / "r.sqlite3"))
    mesh.start()
    mesh.search_service.search("film")                                    # spins up the fan-out pool
    fingerprint.KEYS.get(lib / "Film (1999).mkv")                         # and the content-key hasher
    entry = entry_name.EntryName("192.168.1.5", 8080, zeroconf_factory=FakeZeroconf,
                                 info_factory=lambda *a, **k: type("I", (), {"server": k["server"]})())
    entry.apply(True)
    portal = RoomHarness(count=1)                                         # a real listening socket
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])   # an owned stream
    assert listening(os.getpid()) and psutil.Process().children() and FakeZeroconf.registered

    plan = sp.ShutdownPlan()
    plan.run("receiver_stream", lambda: (child.terminate(), child.wait(2)))
    plan.run("portal", portal.close)
    plan.run("mdns", entry.close)
    plan.run("house_services", lambda: (mesh.stop(), indexer.stop(0.3), fingerprint.KEYS.close()),
             threaded=True)
    report = plan.report()

    assert report["within_budget"] and report["total_ms"] < 1000, report
    assert psutil.Process().children() == [], "orphan child process"
    assert listening(os.getpid()) == [], "listening socket left open"
    assert FakeZeroconf.registered == [] and entry.name is None, "mDNS record left registered"
    assert list(scratch.iterdir()) == [], "stray temp files"
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        leftovers = {t.name for t in threading.enumerate() if t.is_alive()} - baseline_threads
        leftovers = {n for n in leftovers if n.startswith(("library-indexer", "replica-manager",
                                                            "fanout", "content-key"))}
        if not leftovers:
            break
        time.sleep(0.05)
    assert not leftovers, f"service threads still running: {sorted(leftovers)}"


def test_lifecycle_close_uses_named_steps_and_records_a_clean_exit():
    text = (Path(__file__).resolve().parents[1] / "src" / "cast_lifecycle.py").read_text(encoding="utf-8")
    body = text.split("def _on_close", 1)[1].split("def _finish_delayed_close", 1)[0]
    steps = [line.split('"')[1] for line in body.splitlines() if "plan.run(" in line]
    assert steps == ["ui_timers", "metrics", "background_work", "join_slate", "sc_core", "portal",
                     "house_services", "receiver_watch", "media", "settings"]
    assert body.index('plan.run("sc_core"') < body.index('plan.run("portal"')
    assert body.index('plan.run("portal"') < body.index('plan.run("house_services"')
    assert body.rstrip().endswith("return False") and "w._finish_shutdown()" in body
    host = (Path(__file__).resolve().parents[1] / "src" / "cast_portal_host.py").read_text(encoding="utf-8")
    assert "ShutdownLedger().end(report)" in host
    control = (Path(__file__).resolve().parents[1] / "src" / "cast_control.py").read_text(encoding="utf-8")
    assert "shutdown_plan.begin_ledger()" in control
