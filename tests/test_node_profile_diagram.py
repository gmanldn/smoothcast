import xml.etree.ElementTree as ET

import mesh_diagram
import mesh_model as mm
import node_profile


def rec(node_id="a" * 32, name="Lounge PC", **kw):
    return mm.NodeRecord(node_id=node_id, boot_id="b" * 32, name=name, version="2.2.10", **kw)


def test_profile_keeps_every_attachment():
    r = rec(capabilities=("relay", "weird-cap"), addresses=("192.168.1.5",), mesh_port=7001, room_port=8080,
            targets=(mm.TargetObservation("t1", "cast", "Living Room TV"),),
            clients=(mm.ClientSummary("c1", "controller", name="Sam"),),
            sources=(mm.SourceSummary("video", 3, ("mp4",)),),
            edges=(mm.EdgeObservation("node", "z" * 32, 10, 12),))
    p = node_profile.profile(r, local_id=r.node_id)
    assert p.role == "This device" and p.ports == "mesh 7001, room 8080"
    assert "Relays media for other nodes" in p.capabilities and "Weird cap" in p.capabilities
    assert p.targets == ("Living Room TV (cast, ready)",) and p.clients == ("Sam (controller)",)
    assert p.sources == ("3 video files · mp4",) and p.links[0].text == "12 ms" and p.links[0].healthy


def test_failing_and_never_reached_links_say_why():
    r = rec(edges=(mm.EdgeObservation("node", "y" * 32, None, None, "timeout"),
                   mm.EdgeObservation("target", "t", None)))
    texts = {link.peer: (link.healthy, link.text) for link in node_profile.profile(r).links}
    assert texts["y" * 32] == (False, "failing: timeout") and texts["t"] == (False, "never reached")


def test_diagram_is_valid_escaped_svg_with_text_state():
    a = rec("a" * 32, "<b>Lounge</b>", edges=(mm.EdgeObservation("node", "c" * 32, 5, 9),))
    b = rec("c" * 32, "Office", targets=tuple(mm.TargetObservation(f"t{i}", "dlna", f"T{i}") for i in range(9)))
    svg = mesh_diagram.render([node_profile.profile(a, local_id=a.node_id), node_profile.profile(b)])
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and "<b>" not in svg and "&lt;b&gt;Lounge" in svg
    assert "9 ms" in svg and "+3 more" in svg and "script" not in svg


def test_empty_and_single_node():
    assert "No devices found yet" in mesh_diagram.render([])
    ET.fromstring(mesh_diagram.render([node_profile.profile(rec())]))


def test_redact_strips_private_fields():
    r = rec(addresses=("192.168.1.5",), clients=(mm.ClientSummary("c1", "controller", name="Sam"),),
            edges=(mm.EdgeObservation("node", "z" * 32, 1, 1),), sources=(mm.SourceSummary("video", 1),))
    p = node_profile.profile(node_profile.redact(r))
    assert p.addresses == () and p.links == () and p.sources == () and "Sam" not in " ".join(p.clients)
    assert node_profile.as_dict(p)["links"] == []


def test_panel_references_diagram_routes():
    import portal_mesh_panel
    html = portal_mesh_panel.panel_html()
    assert "/api/mesh/diagram.svg" in html and "/api/mesh/profiles" in html


def test_gtk_popover_describes_every_node_fact():
    import pytest
    pytest.importorskip("gi")
    mesh_ui = pytest.importorskip("mesh_ui")
    r = rec(addresses=("192.168.1.5",), mesh_port=7001, targets=(mm.TargetObservation("t1", "cast", "TV"),),
            edges=(mm.EdgeObservation("node", "z" * 32, 1, 7),))
    text = mesh_ui.NetworkPopover.describe(node_profile.profile(r))
    assert "192.168.1.5" in text and "TV (cast, ready)" in text and "7 ms" in text and "mesh 7001" in text


def test_diagram_keeps_asymmetric_observations_in_both_orders():
    a = rec("a" * 32, "Lounge", edges=(mm.EdgeObservation("node", "b" * 32, 5, 9),))
    b = rec("b" * 32, "Office", edges=(mm.EdgeObservation("node", "a" * 32, None, None, "timeout"),))
    for records in ([a, b], [b, a]):
        root = ET.fromstring(mesh_diagram.render([node_profile.profile(r) for r in records]))
        lines = root.findall("{*}line")
        assert len(lines) == 1 and lines[0].get("stroke-dasharray") == "6 4"
        assert lines[0].get("stroke") == mesh_diagram.COLOURS["bad"]
        labels = {el.text for el in root.findall("{*}text")}
        assert {"Lounge → Office: 9 ms", "Office → Lounge: failing: timeout"} <= labels


def test_diagram_retains_two_healthy_directional_timings():
    a = rec("a" * 32, "Lounge", edges=(mm.EdgeObservation("node", "b" * 32, 5, 9),))
    b = rec("b" * 32, "Office", edges=(mm.EdgeObservation("node", "a" * 32, 5, 14),))
    root = ET.fromstring(mesh_diagram.render([node_profile.profile(a), node_profile.profile(b)]))
    lines = root.findall("{*}line")
    assert len(lines) == 1 and lines[0].get("stroke-dasharray") is None
    labels = {el.text for el in root.findall("{*}text")}
    assert {"Lounge → Office: 9 ms", "Office → Lounge: 14 ms"} <= labels


def test_diagram_has_explicit_light_canvas_for_dark_text():
    for profiles in ([], [node_profile.profile(rec())]):
        root = ET.fromstring(mesh_diagram.render(profiles))
        canvas = root.find("{*}rect")
        assert canvas is not None and canvas.get("fill") == mesh_diagram.BACKGROUND
        assert canvas.get("width") == str(mesh_diagram.W)


def test_gtk_profiles_render_only_visible_changed_snapshots():
    # Exercise the actual methods without importing GTK or constructing a window.
    import ast
    from pathlib import Path
    from types import SimpleNamespace

    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/mesh_ui.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NetworkPopover")
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in {"show_profiles", "_render_profiles"}]
    ns = {}
    exec(compile(ast.Module(body=methods, type_ignores=[]), "<mesh profiles>", "exec"), ns)
    visibility = {"mapped": False, "expanded": False}
    calls = []
    owner = SimpleNamespace(
        _pending_profiles=(), _rendered_profiles=None,
        _profile_expander=SimpleNamespace(
            get_mapped=lambda: visibility["mapped"],
            get_expanded=lambda: visibility["expanded"]),
        _paint_profiles=calls.append,
    )
    owner._render_profiles = lambda *args: ns["_render_profiles"](owner, *args)
    def show(profiles):
        ns["show_profiles"](owner, profiles)
    show(["old"])
    show(["latest"])
    assert calls == []
    visibility["mapped"] = True
    show(["latest"])
    assert calls == []
    visibility["expanded"] = True
    owner._render_profiles()
    show(["latest"])
    assert calls == [("latest",)]
    visibility["mapped"] = False
    show(["new"])
    assert len(calls) == 1
    visibility["mapped"] = True
    owner._render_profiles()
    assert calls == [("latest",), ("new",)]


def test_uptime_text_is_plain_and_never_wrong():
    t = node_profile.uptime_text
    assert t(1000, 1000 + 30) == "under a minute"
    assert t(1000, 1000 + 5 * 60) == "5 min"
    assert t(1000, 1000 + 3 * 3600 + 12 * 60) == "3 h 12 min"
    assert t(1000, 1000 + 2 * 86400 + 5 * 3600) == "2 d 5 h"
    assert t(0, 5000) == "" and t(1000, None) == "" and t(1000, 500) == "" and t("x", 5000) == ""


def test_profile_omits_uptime_for_a_nonfinite_clock():
    record = rec(boot_epoch=10_000)
    for now in (float("nan"), float("inf"), float("-inf")):
        profile = node_profile.profile(record, now=now)
        assert not profile.uptime
        assert " · up " not in profile.headline


def test_profile_shows_uptime_only_when_the_clock_is_given():
    r = rec(boot_epoch=10_000)
    assert node_profile.profile(r).uptime == "" and "up " not in node_profile.profile(r).headline
    p = node_profile.profile(r, now=10_000 + 7200)
    assert p.uptime == "2 h 0 min" and p.headline.endswith("up 2 h 0 min")
    assert node_profile.as_dict(p)["uptime"] == "2 h 0 min"


def test_profile_exposes_reported_platform_and_gtk_description():
    r = rec(platform="Linux")
    p = node_profile.profile(r)
    assert p.platform == "Linux"
    assert node_profile.as_dict(p)["platform"] == "Linux"
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/mesh_ui.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NetworkPopover")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "describe")
    ns = {"node_profile": node_profile}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<mesh describe>", "exec"), ns)
    assert "Platform: Linux" in ns["describe"](p)
