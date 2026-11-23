"""#413: the desktop Find window's row model and its wiring."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import find_results as fr

ROOT = Path(__file__).resolve().parents[1]
LOCAL = {"origin": "local", "online": True}
STUDY = {"origin": "s", "origin_name": "Study PC", "online": True}
DAD = {"origin": "d", "origin_name": "Dad's laptop", "online": False}


def film(key, title, copies, **kw):
    return {"id": key, "title": title, "copies": copies, **kw}


def test_where_describes_availability():
    assert fr.where([LOCAL]) == "On this computer"
    assert fr.where([STUDY, LOCAL]) == "On Study PC - also on this computer"
    assert fr.where([DAD]) == "Dad's laptop is offline"
    assert fr.where([DAD, STUDY]) == "On Study PC"
    assert fr.where([]) == ""


def test_flatten_orders_groups_and_marks_what_can_be_added():
    data = {"groups": [
        {"type": "films", "items": [film("qh:1", "Alien", [LOCAL], year=1979),
                                    film("qh:2", "Offline Film", [DAD])]},
        {"type": "shows", "items": [{"name": "Bluey", "count": 2, "episodes": [
            film("qh:3", "S01E01", [STUDY]), film("qh:4", "S01E02", [STUDY])]}]},
        {"type": "artists", "items": [{"id": "ar:abba", "name": "ABBA", "count": 12}]},
        {"type": "songs", "items": [film("qh:5", "Fernando", [STUDY], artist="ABBA", album="Greatest")]}]}
    rows = fr.flatten(data)
    assert [r.title for r in rows] == ["Alien", "Offline Film", "Bluey: S01E01", "Bluey: S01E02",
                                       "ABBA", "Fernando"]
    assert [r.can_add for r in rows] == [True, False, True, True, False, True]
    assert rows[0].subtitle == "1979 - On this computer"
    assert rows[1].subtitle == "Dad's laptop is offline"
    assert rows[4].key == "" and rows[4].subtitle == "12 songs"          # headers are not queueable
    assert rows[5].subtitle == "ABBA - Greatest - On Study PC"


def test_available_only_hides_unplayable_results_but_keeps_headers():
    data = {"groups": [{"type": "films", "items": [film("qh:1", "On", [LOCAL]), film("qh:2", "Off", [DAD])]},
                       {"type": "artists", "items": [{"name": "ABBA", "count": 1}]}]}
    assert [r.title for r in fr.flatten(data, available_only=True)] == ["On", "ABBA"]


def test_missing_fields_never_raise():
    rows = fr.flatten({"groups": [{"type": "films", "items": [{}, {"id": "qh:9"}]}, {"type": "x"}, {}]})
    assert [(r.title, r.key, r.can_add) for r in rows] == [("Untitled", "", False), ("Untitled", "qh:9", False)]
    assert fr.flatten({}) == []


def test_find_window_is_wired_into_actions_menu_and_main_window():
    control = (ROOT / "src/cast_control.py").read_text(encoding="utf-8")
    assert 'simple("find-house", lambda *a: self._window().action_find_house())' in control
    assert "FindMixin" in control.split("class MainWindow(")[1].split(")")[0]
    assert '"Find in the house…", "app.find-house"' in (ROOT / "src/cast_ui.py").read_text(encoding="utf-8")
    ui = (ROOT / "src/find_ui.py").read_text(encoding="utf-8")
    assert "markup_escape_text(item.title)" in ui and "markup_escape_text(item.subtitle)" in ui
    assert "valid=lambda: self.get_visible()" in ui                      # stale results never render
    assert "ticket == self._ticket" in ui
    assert 'self.owner._portal_queue_action("queue_add_key"' in ui       # same path as the web remote
