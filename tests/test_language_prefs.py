"""Persistent audio/subtitle language preferences (issue #38). No GTK, no ffmpeg."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import config_control
import language_prefs as lp
import streamer
from streamer import AudioTrack, MediaInfo, SubtitleTrack


def audio(index, language, *, default=False, title="", codec="aac"):
    return AudioTrack(index=index, codec=codec, language=language, title=title, default=default)


def sub(index, language, *, forced=False, default=False, codec="subrip"):
    return SubtitleTrack(index=index, codec=codec, language=language, forced=forced, default=default)


def write_config(monkeypatch, tmp_path, data):
    folder = tmp_path / "cast-control"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps(data) if not isinstance(data, str) else data)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


# --- normalisation ------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("en", "eng"), ("eng", "eng"), ("English", "eng"), ("EN-us", "eng"), ("en_GB", "eng"),
    ("fre", "fra"), ("fr", "fra"), ("ger", "deu"), ("de", "deu"), ("pt-BR", "por"),
    ("chi", "zho"), ("cmn", "zho"), ("ja", "jpn"), ("dut", "nld"), ("tlh", "tlh"),
])
def test_normalize_maps_codes_names_and_regions(raw, expected):
    assert lp.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", "und", "UND", "mul", "zxx", "mis", " ", None, 5, [], "x" * 300])
def test_undetermined_and_junk_never_match(raw):
    assert lp.normalize(raw) == ""


@pytest.mark.parametrize("path,expected", [
    ("/tv/Some.Show.S01E02.1080p.WEB.mkv", "some show"),
    ("Some Show - S10E11 - Title.mkv", "some show"),
    ("Show_Name_1x05.avi", "show name"),
    ("The.Show.s02e03.mkv", "the show"),
    ("Movie.2019.1080p.mkv", None),
    ("S01E02.mkv", None),
    ("", None), (None, None),
])
def test_series_key_from_file_names(path, expected):
    assert lp.series_key(path) == expected


# --- cleaning and config ----------------------------------------------------------

def test_clean_languages_dedupes_caps_and_drops_junk():
    assert lp.clean_languages(["en", "English", "ja", "und", 5, None, "fr"]) == ["eng", "jpn", "fra"]
    assert lp.clean_languages([f"l{i}" for i in range(50)]) == [f"l{i}" for i in range(lp.MAX_LANGUAGES)]
    for bad in (None, "en", {"a": 1}, 7):
        assert lp.clean_languages(bad) == []


def test_clean_overrides_is_bounded_and_strict():
    good = {"Some Show": {"audio": ["fr"], "subtitles": ["en"]}, "  ": {"audio": ["en"]},
            "empty": {"audio": []}, "bad": "x", 5: {"audio": ["en"]}}
    assert lp.clean_overrides(good) == {"some show": {"audio": ["fra"], "subtitles": ["eng"]}}
    many = {f"s{i}": {"audio": ["en"]} for i in range(500)}
    assert len(lp.clean_overrides(many)) == lp.MAX_OVERRIDES
    assert lp.clean_overrides(None) == {} and lp.clean_overrides([1]) == {}


def test_series_override_replaces_only_the_lists_it_sets():
    cfg = {"preferred_audio_languages": ["ja"], "preferred_subtitle_languages": ["en"],
           "language_overrides": {"some show": {"audio": ["fr"]}}}
    base = lp.prefs_from_config(cfg)
    assert (base.audio, base.subtitles) == (("jpn",), ("eng",))
    series = lp.prefs_from_config(cfg, "some show")
    assert (series.audio, series.subtitles) == (("fra",), ("eng",))
    assert lp.prefs_from_config(cfg, "other show") == base
    assert not lp.prefs_from_config({}).enabled and not lp.prefs_from_config("junk").enabled


def test_load_reads_the_config_file_and_never_raises(monkeypatch, tmp_path):
    write_config(monkeypatch, tmp_path, {"preferred_audio_languages": ["ja"],
                                          "language_overrides": {"some show": {"audio": ["fr"]}}})
    assert lp.load("/m/Film.mkv").audio == ("jpn",)
    assert lp.load("/m/Some.Show.S01E01.mkv").audio == ("fra",)
    write_config(monkeypatch, tmp_path, "{not json")
    assert lp.load("/m/Film.mkv") == lp.LanguagePrefs()
    write_config(monkeypatch, tmp_path, "[]")
    assert lp.load("/m/Film.mkv") == lp.LanguagePrefs()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing"))
    assert lp.load() == lp.LanguagePrefs()


def test_config_loader_validates_the_new_keys():
    defaults = {"preferred_audio_languages": [], "preferred_subtitle_languages": [], "language_overrides": {}}
    out = config_control.sanitise_config({
        "preferred_audio_languages": ["English", "ja", 5, "und"],
        "preferred_subtitle_languages": "en",
        "language_overrides": {"Show": {"audio": ["fr"]}, "x": 3},
    }, defaults)
    assert out == {"preferred_audio_languages": ["eng", "jpn"], "preferred_subtitle_languages": [],
                   "language_overrides": {"show": {"audio": ["fra"]}}}
    assert config_control.sanitise_config({"language_overrides": [1]}, defaults)["language_overrides"] == {}


# --- audio policy -------------------------------------------------------------------

def test_audio_follows_preference_order_then_falls_back():
    tracks = [audio(0, "eng", default=True), audio(1, "jpn"), audio(2, "fra")]
    assert lp.choose_audio(tracks, lp.LanguagePrefs(audio=("jpn", "eng"))).index == 1
    assert lp.choose_audio(tracks, lp.LanguagePrefs(audio=("deu", "fra"))).index == 2
    assert lp.choose_audio(tracks, lp.LanguagePrefs(audio=("deu",))) is None
    assert lp.choose_audio(tracks, lp.LanguagePrefs()) is None
    assert lp.choose_audio([], lp.LanguagePrefs(audio=("eng",))) is None


def test_audio_prefers_the_main_track_over_commentary_and_ties_go_to_default():
    tracks = [audio(0, "eng", title="Director's Commentary", default=True),
              audio(1, "eng", title="Audio Description"), audio(2, "eng"), audio(3, "eng", default=True)]
    assert lp.choose_audio(tracks, lp.LanguagePrefs(audio=("eng",))).index == 3
    only_commentary = [audio(0, "eng", title="Commentary"), audio(1, "jpn")]
    assert lp.choose_audio(only_commentary, lp.LanguagePrefs(audio=("eng",))).index == 0


def test_undetermined_audio_never_matches_a_preference():
    assert lp.choose_audio([audio(0, ""), audio(1, "und")], lp.LanguagePrefs(audio=("eng",))) is None


# --- subtitle policy: forced vs full ------------------------------------------------

SUBS = [sub(0, "eng"), sub(1, "eng", forced=True), sub(2, "fra"), sub(3, "jpn", forced=True)]
EN = lp.LanguagePrefs(subtitles=("eng",))


def test_understood_audio_gets_only_forced_captions_or_nothing():
    d = lp.choose_subtitle(SUBS, EN, audio(0, "eng"))
    assert d.decided and d.track.index == 1                       # forced English
    d = lp.choose_subtitle([sub(0, "eng"), sub(2, "fra")], EN, audio(0, "eng"))
    assert d.decided and d.track is None                          # no forced track: no subtitles


def test_foreign_audio_gets_the_full_track_in_the_preferred_language():
    d = lp.choose_subtitle(SUBS, EN, audio(0, "jpn"))
    assert d.decided and d.track.index == 0
    d = lp.choose_subtitle(SUBS, lp.LanguagePrefs(subtitles=("deu", "fra")), audio(0, "jpn"))
    assert d.track.index == 2                                      # second preference


def test_forced_only_is_the_last_resort_for_foreign_audio():
    d = lp.choose_subtitle([sub(1, "eng", forced=True), sub(2, "fra")], EN, audio(0, "jpn"))
    assert d.decided and d.track.index == 1


def test_no_matching_language_or_no_prefs_leaves_the_decision_undecided():
    assert not lp.choose_subtitle(SUBS, lp.LanguagePrefs(subtitles=("deu",)), audio(0, "jpn")).decided
    assert not lp.choose_subtitle(SUBS, lp.LanguagePrefs(), audio(0, "eng")).decided
    assert not lp.choose_subtitle([], EN, audio(0, "jpn")).decided
    assert lp.choose_subtitle(SUBS, EN, None).track.index == 0     # unknown audio: full English


def test_default_flag_breaks_ties_between_equal_candidates():
    d = lp.choose_subtitle([sub(0, "eng"), sub(5, "eng", default=True)], EN, audio(0, "jpn"))
    assert d.track.index == 5


# --- integration with streamer --------------------------------------------------------

def media(tmp_path, name="Film.mkv", audios=None, subs=None):
    return MediaInfo(path=tmp_path / name, audio_streams=audios or [], subtitle_tracks=subs or [])


def test_streamer_defaults_are_unchanged_without_preferences(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "none"))
    m = media(tmp_path, audios=[audio(0, "jpn"), audio(1, "eng", default=True)],
              subs=[sub(0, "fra"), sub(1, "eng"), sub(2, "deu", forced=True)])
    assert streamer.preferred_audio_track(m).index == 1            # the file's default
    assert streamer.preferred_embedded_subtitle(m).index == 2      # forced first, as before


def test_streamer_honours_preferences_only_in_auto_mode(monkeypatch, tmp_path):
    write_config(monkeypatch, tmp_path, {"preferred_audio_languages": ["ja"],
                                          "preferred_subtitle_languages": ["en"]})
    m = media(tmp_path, audios=[audio(0, "eng", default=True), audio(1, "jpn")],
              subs=[sub(0, "eng"), sub(1, "eng", forced=True)])
    assert streamer.preferred_audio_track(m).index == 1            # Japanese audio
    assert streamer.preferred_audio_track(m, 0).index == 0         # explicit choice wins
    assert streamer.preferred_embedded_subtitle(m).index == 0      # foreign audio: full English
    assert streamer.preferred_embedded_subtitle(m, 1).index == 1   # explicit choice wins


def test_streamer_understood_audio_uses_forced_or_no_subtitles(monkeypatch, tmp_path):
    write_config(monkeypatch, tmp_path, {"preferred_audio_languages": ["en"],
                                          "preferred_subtitle_languages": ["en"]})
    both = media(tmp_path, audios=[audio(0, "eng")], subs=[sub(0, "eng"), sub(1, "eng", forced=True)])
    assert streamer.preferred_embedded_subtitle(both).index == 1
    full_only = media(tmp_path, audios=[audio(0, "eng")], subs=[sub(0, "eng")])
    assert streamer.preferred_embedded_subtitle(full_only) is None


def test_streamer_series_override_applies_per_series(monkeypatch, tmp_path):
    write_config(monkeypatch, tmp_path, {"preferred_audio_languages": ["en"],
                                          "language_overrides": {"some show": {"audio": ["ja"]}}})
    tracks = [audio(0, "eng", default=True), audio(1, "jpn")]
    assert streamer.preferred_audio_track(media(tmp_path, "Some.Show.S01E01.mkv", tracks)).index == 1
    assert streamer.preferred_audio_track(media(tmp_path, "Other.Show.S01E01.mkv", tracks)).index == 0
    assert streamer.preferred_audio_track(media(tmp_path, "Some Show (2019).mkv", tracks)).index == 0


def test_image_subtitle_tracks_are_still_never_selected(monkeypatch, tmp_path):
    write_config(monkeypatch, tmp_path, {"preferred_subtitle_languages": ["en"]})
    m = media(tmp_path, audios=[audio(0, "jpn")], subs=[sub(0, "eng", codec="hdmv_pgs_subtitle")])
    assert streamer.preferred_embedded_subtitle(m) is None


def test_module_is_installed_and_mypy_gated():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"language_prefs"' in text and "src/language_prefs.py" in text
