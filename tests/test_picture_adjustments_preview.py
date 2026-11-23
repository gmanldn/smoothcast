"""Headless picture preview matches the encoder's validated colour filters (#112)."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import picture_adjustments
import screenshot


@pytest.mark.parametrize(("config", "expected"), [
    ({}, "scale=640:360:force_original_aspect_ratio=decrease"),
    ({"picture_hue": -45}, "hue=h=-45,scale=640:360:force_original_aspect_ratio=decrease"),
    ({"picture_brightness": 0.2, "picture_contrast": 1.25,
      "picture_saturation": 0.8, "picture_hue": 30},
     "eq=brightness=0.2:contrast=1.25:saturation=0.8,hue=h=30,"
     "scale=640:360:force_original_aspect_ratio=decrease"),
    ({"picture_hue": "1; rm -rf /"}, "scale=640:360:force_original_aspect_ratio=decrease"),
])
def test_preview_filter_matches_cast_filter_before_scaling(tmp_path, monkeypatch,
                                                            config, expected):
    media = tmp_path / "film.mp4"
    media.write_bytes(b"fake bytes, FFmpeg call mocked")
    calls = []
    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b"\xff\xd8JPEG", stderr=b"")
    monkeypatch.setattr(screenshot.subprocess, "run", fake_run)
    out = screenshot.preview_frame(media, 2.5, picture_config=config)
    assert out.startswith(b"\xff\xd8")
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[cmd.index("-vf") + 1] == expected
    assert cmd.count("-vf") == 1
    assert cmd[cmd.index("-map") + 1] == "0:0"
    assert "shell" not in cmd
    if picture_adjustments.active(config):
        assert cmd[cmd.index("-vf") + 1].startswith(",".join(picture_adjustments.filters(config)))


def test_concurrent_picture_pref_change_invalidates_stale_decodes_without_cast():
    tree = ast.parse((ROOT / "src/preferences_picture_ui.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "PicturePreferencesMixin")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
              and n.name == "_refresh_picture_preview")
    ns = {}
    exec(compile("class Preview:\n" + textwrap.indent(ast.unparse(fn), "    "),
                 "<isolated-colour-refresh>", "exec"), ns)
    calls = []
    owner = SimpleNamespace(_preview_path="/tmp/film.mp4", _preview_position=5.5,
                            _preview_generation=17, session=None, external=False,
                            _queue_preview=lambda position: calls.append(position))
    obj = ns["Preview"]()
    obj.owner = owner
    obj._refresh_picture_preview()
    assert owner._preview_generation == 18 and calls == [5.5]
    owner.session = object()
    obj._refresh_picture_preview()
    assert owner._preview_generation == 18 and calls == [5.5]
    owner.session = None
    owner.external = True
    obj._refresh_picture_preview()
    assert owner._preview_generation == 18 and calls == [5.5]
    owner.external = False
    owner._preview_path = None
    obj._refresh_picture_preview()
    assert owner._preview_generation == 18 and calls == [5.5]


def test_preference_changes_and_reset_both_trigger_new_local_preview():
    src = (ROOT / "src/preferences_picture_ui.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "PicturePreferencesMixin")
    methods = {n.name: ast.unparse(n) for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert "self._refresh_picture_preview()" in methods["_picture_changed"]
    assert "self._refresh_picture_preview()" in methods["_reset_picture"]
    # Asynchronous work uses an immutable snapshot; frames cannot blend settings.
    av = (ROOT / "src/cast_av.py").read_text(encoding="utf-8")
    assert 'aspect_options["picture_config"] = dict(self.cfg)' in av
    assert "picture_config: dict | None = None" in (ROOT / "src/screenshot.py").read_text()
