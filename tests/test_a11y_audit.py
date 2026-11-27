import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import a11y_audit as a


def n(role, name="", children=None, **kw): return {"role": role, "name": name, "children": children or [], **kw}


def test_row_label_announces_title_position_and_state():
    assert a.row_label("Film One", 3, 12, "playing") == "Film One, 3 of 12, playing"
    assert a.row_label("", 1, 1) == "Untitled, 1 of 1" and a.row_label("x", 5, 2, "next") == "x, 5 of 5, up next"
    assert a.row_label("x", 0, 0, "bogus") == "x, 1 of 1" and len(a.row_label("t" * 500, 1, 2)) < 140


def test_unnamed_interactive_widgets_fail_and_named_pass():
    ok = n("window", "SmoothCast", [n("push button", "Pause"), n("slider", "Seek", value_text="1:02 of 1:30:00"), n("label", "")])
    assert a.audit(ok) == []
    bad = n("window", "W", [n("push button", ""), n("toggle button", " "), n("panel", "", [n("check box", "")])])
    f = a.audit(bad)
    assert [x["problem"] for x in f] == ["unnamed interactive widget"] * 3 and len(f) == 3
    assert a.audit(n("push button", "", description="Open file")) == []


def test_range_widgets_need_value_text_and_glyph_buttons_flagged():
    f = a.audit(n("window", "W", [n("slider", "Volume"), n("push button", "⏵"), n("progress bar", "Loading")]))
    assert [(x["role"], x["problem"]) for x in f] == [("push button", "icon-only button name is a glyph, not a label"), ("slider", "range widget has no value text")]
    assert a.audit(n("push button", "⏵", description="Play")) == []


def test_paths_are_stable_and_big_trees_bounded():
    f = a.audit(n("window", "W", [n("panel", "Bar", [n("push button", "")])]))
    assert f[0]["path"] == "/window[W]/panel[Bar]/push button[-]"
    wide = n("window", "W", [n("label", "x") for _ in range(a.MAX_NODES + 5)])
    assert a.audit(wide)[-1]["problem"] == "tree too large to audit" and a.audit({}) == [] and a.audit(n("window", "W", ["junk", None])) == []


def test_text_scale_clipping_check():
    labels = {"Cast to receiver": 150.0, "Stop": 40.0, "Add a folder to your library": 260.0}
    assert a.scaled_fits(labels, 1.0, 320) == []
    assert a.scaled_fits(labels, 2.0, 320) == ["Add a folder to your library", "Cast to receiver"] and a.scaled_fits({}, 2.0, 360) == []
