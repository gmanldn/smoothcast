import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import skip_segments as ss


@pytest.mark.parametrize("title,kind", [("Intro", "intro"), ("OPENING", "intro"), ("op", "intro"), ("Intro 2", "intro"),
                                        ("Recap", "recap"), ("Previously on", "recap"), ("Credits", "credits"),
                                        ("End Credits", "credits"), ("ED", "credits"), ("Générique", "intro"),
                                        ("Abspann", "credits"), ("Chapter 3", None), ("The Opening Scene", None), ("", None)])
def test_chapter_title_classification(title, kind):
    assert ss.classify(title) == kind


def test_from_chapters_builds_markers_and_skips_bad_rows():
    ms = ss.from_chapters([{"title": "Cold open", "start": 0, "end": 60}, {"title": "Intro", "start": 60, "end": 150},
                           {"title": "Credits", "start": 2400, "end": 2500}, {"title": "Intro", "start": "x", "end": 1}, {"title": "Intro", "start": 9, "end": 9}])
    assert [(m["kind"], m["start"], m["end"]) for m in ms] == [("intro", 60, 150), ("credits", 2400, 2500)]


def hashes(seed, n, intro=None, at=0):
    rnd = random.Random(seed)
    h = [rnd.randrange(10**9) for _ in range(n)]
    if intro:
        h[at:at + len(intro)] = intro
    return h


def test_audio_match_finds_shared_intro_with_different_cold_open_lengths():
    intro = [random.Random(7).randrange(10**9) for _ in range(90)]          # 90 hops x 1 s = 90 s theme
    a, b = hashes(1, 600, intro, 30), hashes(2, 600, intro, 55)
    seg = ss.common_segment(a, b, 1.0)
    assert seg and seg["kind"] == "intro" and seg["source"] == "audio-match"
    assert seg["start"] == 30 and seg["end"] == 120 and seg["start_b"] == 55


def test_short_or_absent_common_audio_gives_no_marker():
    short = [random.Random(9).randrange(10**9) for _ in range(10)]
    assert ss.common_segment(hashes(1, 300, short, 20), hashes(2, 300, short, 20), 1.0) is None
    assert ss.common_segment(hashes(1, 300), hashes(2, 300), 1.0) is None and ss.common_segment([], [], 1.0) is None


def test_button_label_target_and_credits_next_episode():
    ms = [{"kind": "intro", "start": 60, "end": 150, "source": "chapter"}, {"kind": "credits", "start": 2400, "end": 2500, "source": "chapter"}]
    assert ss.button(ms, 30) is None and ss.button(ms, 70) == {"label": "Skip intro", "kind": "intro", "target": 150, "next_episode": False}
    assert ss.button(ms, 149.5) is None                                   # last second: no pointless button
    c = ss.button(ms, 2410, duration=2500); assert c["label"] == "Skip credits" and c["next_episode"] and c["target"] == 2500


def test_auto_skip_is_opt_in_never_first_episode_and_once():
    b = {"kind": "intro", "target": 150}
    assert not ss.auto_skip(b, False, 5, 2, set()) and not ss.auto_skip(b, True, 1, 2, set())
    assert not ss.auto_skip(b, True, 5, 0.5, set()) and ss.auto_skip(b, True, 5, 1.0, set())
    assert not ss.auto_skip(b, True, 5, 2, {("intro", 150)}) and not ss.auto_skip(None, True, 5, 2, set())


def test_merge_precedence_manual_over_chapter_over_audio():
    a = [{"kind": "intro", "start": 30, "end": 120, "source": "audio-match"}]
    c = [{"kind": "intro", "start": 60, "end": 150, "source": "chapter"}]
    m = [{"kind": "intro", "start": 61, "end": 151, "source": "manual"}]
    assert ss.merge(c, a)[0]["source"] == "chapter" and ss.merge(c, a, m)[0]["source"] == "manual" and ss.merge([], a)[0]["source"] == "audio-match"
