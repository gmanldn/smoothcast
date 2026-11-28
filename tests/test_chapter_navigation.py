"""Issue #39: chapter source-time mapping and safe GTK-free navigation."""
from __future__ import annotations
import ast
from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import streamer


def chapter(start, end, title=''):
    return {"start": start, "end": end, "time_base": "1/1000", "tags": {"title": title}}


def test_chapter_fractional_source_times_and_titles():
    results = streamer.parse_chapters([chapter(1001, 2503, " Intro "), chapter(2503, 7450, "")], 8)
    assert [(x.start, x.end, x.title) for x in results] == [
        (1.001, 2.503, "Intro"), (2.503, 7.45, "Chapter 2"),
    ]


def test_chapters_reject_bad_overlap_and_out_of_range():
    data = [None, chapter(-1, 1000), chapter(1000, 1000),
            chapter(0, 2000, "First"), chapter(1200, 2200, "Overlapping edition"),
            chapter(2000, 3000, "Second"), chapter(20000, 21000)]
    results = streamer.parse_chapters(data, 3)
    assert [(x.start, x.end) for x in results] == [(0.0, 2.0), (2.0, 3.0)]
    assert streamer.parse_chapters({'invalid': data}) == ()
    assert streamer.parse_chapters([{"start_time": "NaN", "end_time": "1"}]) == ()
    assert len(streamer.parse_chapters([chapter(i*1000, (i+1)*1000) for i in range(300)])) == 128


def test_probe_binds_chapters_to_same_media():
    info = streamer.MediaInfo(Path("film.mkv"))
    streamer._read_probe(info, {"format": {"duration": "5"}, "streams": [
        {"codec_type": "video", "index": 0, "codec_name": "h264", "width": 100, "height": 60}
    ], "chapters": [chapter(1500, 2300, "Scene")]})
    assert info.chapters == (streamer.Chapter(1.5, 2.3, "Scene"),)


def test_chapter_jump_cannot_seek_other_film_or_foreign_stream():
    text = (ROOT / "src" / "bookmark_ui.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BookmarkUiMixin")
    methods = {n.name: ast.get_source_segment(text, n) for n in owner.body
               if isinstance(n, ast.FunctionDef)}
    source = "class W:\n" + "\n".join(textwrap.indent(textwrap.dedent(methods[n]), "    ")
                                          for n in ("_chapter_media", "_jump_to_chapter"))
    scope = {}
    exec(compile(source, "<chapter>", "exec"), scope)
    w = scope["W"]()
    info = streamer.MediaInfo(Path("/film.mkv"))
    info.chapters = (streamer.Chapter(2.5, 3.5, "Scene"),)
    w.media, w.session, w.external = info, None, False
    w._preview_path, w.seek_to, w.toast = "/film.mkv", Mock(), Mock()
    w._jump_to_chapter(0)
    w.seek_to.assert_called_once_with(2.5, feedback_label="Chapter: Scene")
    w._preview_path = "/different.mkv"
    w._jump_to_chapter(0)
    assert w.seek_to.call_count == 1
    w.session = SimpleNamespace(state=SimpleNamespace(file="/film.mkv"))
    w._jump_to_chapter(0)
    assert w.seek_to.call_count == 2
    w.external = True
    w._jump_to_chapter(0)
    assert w.seek_to.call_count == 2


def test_chapter_action_is_parameterised_and_menu_refreshes():
    control = (ROOT / "src" / "cast_control.py").read_text()
    menu = (ROOT / "src" / "cast_ui.py").read_text()
    from gui_source import legacy_self
    queue = legacy_self((ROOT / "src" / "cast_queue.py").read_text())
    probe = (ROOT / "src" / "streamer.py").read_text()
    assert '"chapter-jump", GLib.VariantType.new("i")' in control
    assert 'append_submenu("Chapters", self._build_chapters_menu())' in menu
    assert "self.menu_button.set_menu_model(self._build_menu())" in queue
    assert '"-show_chapters"' in probe
