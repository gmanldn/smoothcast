"""#463: the startup import gate and the deferrals it protects."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
import import_budget as ib

LOG = """import time: self [us] | cumulative | imported package
import time:       100 |        100 |       json
import time:      9000 |      45000 |       zeroconf
import time:       500 |      46000 |     peer_discovery
import time:       300 |      50000 |   cast_portal
import time:       200 |      52000 | cast_control
"""


def rows():
    return ib.parse(LOG)


def test_parse_reads_depth_and_cumulative_time():
    parsed = rows()
    assert parsed[-1] == (200, 52000, 0, "cast_control")
    assert [r[2] for r in parsed] == [3, 3, 2, 1, 0]


def test_a_denylisted_import_is_reported_with_who_imported_it():
    report = ib.evaluate(rows())
    assert report["import_ms"] == 52.0 and report["modules"] == 5
    (problem,) = report["problems"]
    assert "zeroconf is imported at startup (zeroconf <- peer_discovery <- cast_portal <- cast_control)" \
        in problem


def test_clean_log_passes_and_budgets_are_enforced():
    clean = ib.parse(LOG.replace("zeroconf", "json_extra"))
    assert ib.evaluate(clean)["problems"] == []
    assert any("modules imported" in p for p in ib.evaluate(clean, max_modules=3)["problems"])
    assert any("took" in p for p in ib.evaluate(clean, max_ms=10)["problems"])
    assert ib.evaluate(clean, max_ms=10, slack=10)["problems"] == []          # slack scales the time budget


def test_missing_entry_module_is_a_problem_not_a_crash():
    assert any("was not imported" in p for p in ib.evaluate(ib.parse("garbage\n"))["problems"])


def test_submodules_of_a_denylisted_package_count():
    log = LOG.replace("zeroconf", "zeroconf._utils.net")
    assert any("zeroconf is imported" in p for p in ib.evaluate(ib.parse(log))["problems"])


def test_deferred_modules_are_lazy_in_source():
    """Cheap static guard that works without GTK: nobody re-adds the eager imports."""
    forbidden = {
        "peer_discovery.py": "from zeroconf import",
        "lan_interfaces.py": "\nimport psutil\n",
        "cast_portal_host.py": "\nimport mesh_library\n",
        "library_replication.py": "\nimport library_index_v2\n",
    }
    for name, needle in forbidden.items():
        text = (ROOT / "src" / name).read_text(encoding="utf-8")
        top = text.split("\nclass ", 1)[0].split("\ndef ", 1)[0]
        assert needle not in top, f"{name} imports {needle.strip()} at module level"


def test_peer_discovery_still_works_with_lazy_zeroconf(monkeypatch):
    import peer_discovery
    assert peer_discovery.Zeroconf is None                       # nothing resolved at import
    calls = []

    class Zc:
        def __init__(self, **kw): calls.append("zc")
        def register_service(self, info): calls.append("reg")
        def close(self): pass

    class Info:
        def __init__(self, *a, **k): pass

    class Browser:
        def __init__(self, *a, **k): calls.append("browse")

    monkeypatch.setattr(peer_discovery, "Zeroconf", Zc)
    monkeypatch.setattr(peer_discovery, "ServiceInfo", Info)
    monkeypatch.setattr(peer_discovery, "ServiceBrowser", Browser)
    peer_discovery.PeerDirectory("192.168.1.5", "study", 8080)
    assert calls == ["zc", "reg", "browse"]


def test_real_gui_entry_import_meets_the_budget():
    pytest.importorskip("gi")
    try:
        report = ib.evaluate(ib.parse(ib.measure()), slack=3.0)   # generous: this is a unit-test box
    except (RuntimeError, subprocess.SubprocessError) as exc:
        pytest.skip(f"GUI entry module cannot be imported here: {exc}")
    assert report["problems"] == [], report


def test_startup_timeline_marks_are_first_write_wins_ordered_and_budgeted():
    import time
    import startup_timeline as st
    st.reset()
    assert st.snapshot() == {"marks_ms": {}, "budget_ms": 800.0, "within_budget": None}
    st.mark("activate")
    time.sleep(0.01)
    st.mark("window_built")
    first = st.snapshot()["marks_ms"]["activate"]
    st.mark("activate")                                   # a second activation does not move it
    assert st.snapshot()["marks_ms"]["activate"] == first
    st.mark_idle()
    snap = st.snapshot()
    assert list(snap["marks_ms"]) == ["activate", "window_built", "interactive"]
    assert snap["marks_ms"]["window_built"] > first and snap["within_budget"] is True
    st.reset()


def test_diagnostics_report_the_startup_timeline_without_private_data():
    import diagnostics
    import startup_timeline as st
    st.reset()
    st.mark("interactive")
    payload = diagnostics.collect(home="/home/sam")
    assert payload["startup"]["budget_ms"] == 800.0 and "interactive" in payload["startup"]["marks_ms"]
    assert all(isinstance(v, float) for v in payload["startup"]["marks_ms"].values())
    st.reset()


def test_gui_entry_records_the_timeline_marks_on_activation():
    text = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    assert text.index("import startup_timeline") < text.index("import gi")        # its clock starts first
    for needle in ('mark("activate")', 'mark("window_built")', 'mark("presented")',
                   "GLib.idle_add(startup_timeline.mark_idle)"):
        assert needle in text
