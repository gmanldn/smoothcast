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
    texts = {l.peer: (l.healthy, l.text) for l in node_profile.profile(r).links}
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
    import portal_mesh_http
    import portal_mesh_panel
    html = portal_mesh_panel.panel_html()
    assert "/api/mesh/diagram.svg" in html and "/api/mesh/profiles" in html


def test_gtk_popover_describes_every_node_fact():
    import pytest
    gi = pytest.importorskip("gi")
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
