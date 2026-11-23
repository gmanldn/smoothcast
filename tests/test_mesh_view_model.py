"""Network view model: states, reasons, stable updates, announcements (#403)."""
from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_model as mm
import mesh_view_model as vm
from mesh_state import MeshView

ME, A, B = "1" * 32, "a" * 32, "b" * 32


def rec(node, name, **kw):
    return mm.NodeRecord(node_id=node, boot_id="c" * 32, name=name, version="1.2.0", **kw)


def tv(i, state="ready", **kw):
    return mm.TargetObservation(f"tv-{i}", "cast", f"TV {i}", state=state, model="Chromecast", **kw)


def view(*records):
    return MeshView(1, ME, tuple(sorted(records, key=lambda r: r.node_id)))


def test_nodes_clients_and_targets_with_badges_and_summary():
    v = view(rec(ME, "Lounge PC", targets=(tv(1),), clients=(mm.ClientSummary("c1", "screen", ("playing",), 0, "Kitchen"),)),
             rec(A, "Study", targets=(tv(1), tv(2, "unreachable")),
                 edges=(mm.EdgeObservation("target", "tv-2", None, None, "timeout"),)))
    model = vm.build_model(v, primary_id=A)
    nodes = {r.title: r for r in model.nodes}
    assert nodes["Lounge PC"].badges == ("This device",) and nodes["Lounge PC"].state == "self"
    assert nodes["Study"].badges == ("Primary",) and nodes["Study"].state_text == "Online"
    assert model.nodes[0].title == "Lounge PC"                      # this device first
    (client,) = model.clients
    assert client.title == "Kitchen" and client.badges == ("Screen", "Playing") and "Lounge PC" in client.subtitle
    t = {r.title: r for r in model.targets}
    assert t["TV 1"].state == "ready" and t["TV 1"].detail == ""
    assert "Lounge PC" in t["TV 1"].seen_by and "Study" in t["TV 1"].seen_by
    assert t["TV 2"].state == "unreachable" and "reach" in t["TV 2"].detail.lower()
    assert model.summary == "2 devices · 1 connected client · 1 of 2 targets ready"
    assert model.empty_hint == ""


def test_every_non_ready_state_has_text_and_a_reason():
    v = view(rec(ME, "Me", targets=(tv(1, "busy", owner=A), tv(2, "stale", age_ms=90_000),
                                    tv(3, "unreachable"))), rec(A, "Study"))
    rows = {r.title: r for r in vm.build_model(v).targets}
    assert rows["TV 1"].detail == "In use from Study."
    assert rows["TV 2"].detail == "Not seen for 1 min."
    assert rows["TV 3"].detail
    for row in rows.values():
        assert row.state_text and row.state_text != row.state or row.state == "ready"
        assert row.state_text in vm.STATE_TEXT.values()


def test_cached_peers_appear_as_last_seen_and_never_duplicate_live_ones():
    v = view(rec(ME, "Me"), rec(A, "Study"))
    model = vm.build_model(v, cached_peers=[(A, "Study", 5), (B, "Attic Pi", 7200)])
    attic = [r for r in model.nodes if r.title == "Attic Pi"][0]
    assert attic.state == "cached" and attic.badges == ("Cached",) and attic.subtitle == "2 h ago"
    assert len([r for r in model.nodes if r.title == "Study"]) == 1
    assert model.nodes[-1] is attic                                    # cached last
    assert "2 devices" in model.summary                                # cached not counted


def test_empty_state_is_honest_about_blocked_multicast():
    model = vm.build_model(view(rec(ME, "Me")))
    assert model.empty_hint == "Searching for other SmoothCast devices…"
    hint = "Multicast looks blocked - add a host by address."
    assert vm.build_model(view(rec(ME, "Me")), multicast_hint=hint).empty_hint == hint
    assert vm.build_model(view(rec(ME, "Me"), rec(A, "B"))).empty_hint == ""


def test_guest_style_models_hide_client_names():
    v = view(rec(ME, "Me", clients=(mm.ClientSummary("c1", "controller", (), 0, "Secret Sam"),)))
    row = vm.build_model(v, show_client_names=False).clients[0]
    assert row.title == "Remote" and "Secret" not in repr(row)


@pytest.mark.parametrize("ms,text", [(0, "just now"), (4999, "just now"), (5000, "5 s ago"),
                                     (59_000, "59 s ago"), (60_000, "1 min ago"),
                                     (3_600_000, "1 h ago"), (86_400_000 * 3, "3 d ago"),
                                     (-5, "just now")])
def test_relative_age(ms, text):
    assert vm.relative_age(ms) == text


def test_diff_is_minimal_and_order_is_stable_under_churn():
    base = [rec(ME, "Me"), rec(A, "Study"), rec(B, "Laptop")]
    first = vm.build_model(view(*base))
    same = vm.build_model(view(*base))
    assert vm.diff_rows(first.all_rows(), same.all_rows()).empty
    changed = vm.build_model(view(rec(ME, "Me", targets=(tv(1),)), base[1], base[2]))
    d = vm.diff_rows(first.all_rows(), changed.all_rows())
    assert [r.key for r in d.added] == ["target:tv-1"] and [r.title for r in d.changed] == ["Me"]
    gone = vm.build_model(view(base[0], base[2]))
    d2 = vm.diff_rows(first.all_rows(), gone.all_rows())
    assert d2.removed == (f"node:{A}",) and not d2.added and not d2.changed


def test_update_cost_stays_bounded_on_a_64_node_fixture():
    records = [rec(f"{i:032x}", f"Node {i}", targets=tuple(tv(i * 3 + j) for j in range(3)))
               for i in range(1, 64)] + [rec(ME, "Me")]
    v = view(*records)
    started = time.perf_counter()
    for _ in range(10):
        model = vm.build_model(v, primary_id=records[0].node_id)
        vm.diff_rows(model.all_rows(), model.all_rows())
    assert (time.perf_counter() - started) / 10 < 0.05
    assert len(model.nodes) == 64 and len(model.targets) == 189


def test_announcements_are_short_and_ignore_cached_entries():
    a = vm.build_model(view(rec(ME, "Me")))
    b = vm.build_model(view(rec(ME, "Me"), rec(A, "Study", targets=(tv(1),))))
    assert vm.announcement(None, b) == ""
    assert "Study joined" in vm.announcement(a, b)
    assert "Study left" in vm.announcement(b, a)
    assert vm.announcement(a, a) == ""
    many = vm.build_model(view(rec(ME, "Me"), *[rec(f"{i:032x}", f"N{i}") for i in range(1, 6)]))
    assert vm.announcement(a, many) == "5 devices joined"
    cached = vm.build_model(view(rec(ME, "Me")), cached_peers=[(A, "Ghost", 5)])
    assert vm.announcement(a, cached) == ""


def test_draining_nodes_are_labelled():
    row = vm.build_model(view(rec(ME, "Me"), rec(A, "Study", status="draining"))).nodes[1]
    assert "Leaving" in row.badges


# -- browser panel -------------------------------------------------------------

def test_browser_panel_is_self_contained_parses_and_is_in_the_dashboard():
    import re
    import shutil
    import subprocess
    import portal
    import portal_mesh_panel
    html = portal_mesh_panel.panel_html()
    assert not re.search(r"(?:src|href)=[\"']https?://", html)
    assert "innerHTML" not in html and "eval(" not in html
    page = portal._page().decode()
    assert page.count('id="meshPanel"') == 1 and "/api/mesh/events" in page
    if shutil.which("node"):
        script = re.findall(r"<script>(.*?)</script>", html, flags=re.S)[0]
        out = Path(__file__).with_name("_mesh_panel_check.js")
        out.write_text(script)
        try:
            result = subprocess.run(["node", "--check", str(out)], capture_output=True,
                                    text=True, timeout=30)
        finally:
            out.unlink(missing_ok=True)
        assert result.returncode == 0, result.stderr
