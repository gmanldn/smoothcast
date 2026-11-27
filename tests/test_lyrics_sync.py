import random
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import lyrics_sync as ly

LRC = """[ar: Band]
[ti:Song]
[00:12.00]First line
[00:17.50]Second <00:17.50>Se<00:18.00>cond <00:18.50>word
[00:05.00][01:30.00]Chorus
garbage line
[bad:xx]
[99:99.99]Late
"""


def test_parse_sorted_repeated_stamps_metadata_and_malformed_skipped():
    p = ly.parse(LRC)
    assert p["synced"] and p["meta"]["ar"] == "Band"
    assert [(l["t"], l["text"]) for l in p["lines"]] == [(5.0, "Chorus"), (12.0, "First line"), (17.5, "Second Second word"),
                                                         (90.0, "Chorus"), (6039.99, "Late")]      # prefix text kept; garbage/[bad:xx] dropped


def test_enhanced_word_timing():
    p = ly.parse("[00:17.50]<00:17.50>Se<00:18.00>cond <00:18.50>word")
    assert p["lines"][0]["text"] == "Second word"
    assert [(w["t"], w["text"]) for w in p["lines"][0]["words"]] == [(17.5, "Se"), (18.0, "cond "), (18.5, "word")]
    assert ly.current(p, 18.1) == {"line": 0, "word": 1} and ly.current(p, 18.6)["word"] == 2


def test_current_line_before_first_between_and_after_last_with_offset():
    p = ly.parse("[00:10.00]a\n[00:20.00]b")
    assert ly.current(p, 5) == {"line": None, "word": None}
    assert ly.current(p, 10)["line"] == 0 and ly.current(p, 19.9)["line"] == 0 and ly.current(p, 20)["line"] == 1 and ly.current(p, 999)["line"] == 1
    assert ly.current(p, 18, offset=2.0)["line"] == 1 and ly.current(p, 18, offset=99)["line"] == 1   # offset clamped to +-5
    assert ly.current(p, 14, offset=-5)["line"] is None


def test_unsynced_text_is_static_and_empty_is_safe():
    p = ly.parse("Just words\nmore words")
    assert not p["synced"] and [l["text"] for l in p["lines"]] == ["Just words", "more words"] and ly.current(p, 3) == {"line": None, "word": None}
    assert ly.parse("") == {"synced": False, "lines": [], "meta": {}} and ly.parse(None)["lines"] == []


def test_offset_tag_and_long_line_and_line_cap():
    assert ly.parse("[offset:+500]\n[00:10.00]x")["lines"][0]["t"] == 10.5
    assert len(ly.parse("[00:01.00]" + "a" * 5000)["lines"][0]["text"]) == ly.MAX_LINE_CHARS
    assert len(ly.parse("\n".join(f"[00:{i % 60:02d}.00]l{i}" for i in range(9000)))["lines"]) <= ly.MAX_LINES


def test_fuzz_never_raises_and_stays_sorted():
    rnd = random.Random(3); alphabet = string.printable + "[]<>:.éあ"
    for _ in range(300):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randrange(0, 200)))
        p = ly.parse(s)
        if p["synced"]:
            t = [l["t"] for l in p["lines"]]; assert t == sorted(t)
        ly.current(p, rnd.uniform(-5, 500), rnd.uniform(-20, 20))


def test_sidecar_language_preference_and_offsets_persist(tmp_path):
    names = ["Song.lrc", "Song.fr.lrc", "Other.lrc"]
    assert ly.pick_sidecar(names, "Song", "fr") == "Song.fr.lrc" and ly.pick_sidecar(names, "Song", "en") == "Song.lrc"
    assert ly.pick_sidecar(["Song.de.lrc"], "Song", "en") == "Song.de.lrc" and ly.pick_sidecar(["x.lrc"], "Song") is None
    o = ly.Offsets(tmp_path / "o.json"); assert o.set("qh:1", 2.5) == 2.5 and o.set("qh:2", 99) == 5.0
    assert ly.Offsets(tmp_path / "o.json").get("qh:1") == 2.5 and ly.Offsets(tmp_path / "o.json").get("qh:2") == 5.0
    o.set("qh:1", 0); assert ly.Offsets(tmp_path / "o.json").get("qh:1") == 0.0
