"""Accessible-name ratchet (#449 slice 1): every interactive GTK widget needs a name.

Static analysis (no GTK import). A new unlabelled widget fails; so does a stale
baseline entry for a widget that has since been labelled or removed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit_accessible", ROOT / "scripts/ci/audit_accessible.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def _src(tmp_path, body):
    (tmp_path / "w.py").write_text("from gi.repository import Gtk\n" + textwrap.dedent(body), encoding="utf-8")
    return audit.audit(tmp_path)


def test_detects_unlabelled_and_accepts_every_labelling_route(tmp_path):
    records = _src(tmp_path, """
        def build(self):
            bare = Gtk.Button()
            bare.set_child(None)
            named = Gtk.Button()
            named.set_tooltip_text("Play")
            prop = Gtk.Switch()
            prop.update_property([Gtk.AccessibleProperty.LABEL], ["Auto"])
            inline = Gtk.Button(label="Apply")
            via_new = Gtk.Button.new_with_label("Go")
            self.scale = Gtk.Scale()
            Gtk.Entry()
    """)
    todo = audit.unlabelled(records)
    targets = sorted(t.split("::")[2] for t in todo)
    assert [x for x in targets if not x.startswith("<anonymous@")] == ["bare", "self.scale"]
    assert sum(x.startswith("<anonymous@") for x in targets) == 1


def test_ignores_non_gtk_modules_and_non_interactive_widgets(tmp_path):
    (tmp_path / "plain.py").write_text("class Button: pass\nb = Button()\n", encoding="utf-8")
    (tmp_path / "w.py").write_text("from gi.repository import Gtk\ndef f():\n    x = Gtk.Label(label='a')\n", encoding="utf-8")
    assert audit.audit(tmp_path) == []


def test_repository_has_no_new_unlabelled_widgets_and_a_current_baseline():
    baseline = set(json.loads(audit.BASELINE.read_text(encoding="utf-8"))["unlabelled"])
    current = set(audit.unlabelled(audit.audit()))
    assert current - baseline == set(), (
        f"new unlabelled widgets; add update_property([Gtk.AccessibleProperty.LABEL], [...]): {sorted(current - baseline)}")
    assert baseline - current == set(), (
        f"fixed or removed; delete from docs/a11y-baseline.json: {sorted(baseline - current)}")
