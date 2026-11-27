import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import a11y_prefs as ap

EN = {"index": 1, "language": "eng"}
FR = {"index": 2, "language": "fra"}
ENAD = {"index": 3, "language": "eng", "title": "English (Audio Description)"}
MISFLAG = {"index": 4, "language": "eng", "title": "Commentary AD", "ad": True}
SUBEN = {"index": 10, "language": "eng"}
SUBHI = {"index": 11, "language": "eng", "hearing_impaired": True}
SUBFORCED = {"index": 12, "language": "eng", "forced": True}


def test_clean_enforces_schema_and_defaults():
    assert ap.clean(None) == ap.DEFAULT
    c = ap.clean({"captions": "always", "caption_size": "huge", "ad_track": "yes", "dialogue_boost": 9, "large_text": True, "x": 1})
    assert c["captions"] == "always" and c["caption_size"] == "medium" and c["ad_track"] is False and c["dialogue_boost"] == 0 and c["large_text"] is True and "x" not in c
    assert ap.clean({"dialogue_boost": True})["dialogue_boost"] == 0 and ap.clean({"dialogue_boost": 3})["dialogue_boost"] == 3


def test_audio_selection_across_layouts_ad_never_default():
    base = ap.clean({})
    assert ap.choose([ENAD, EN], [], base, ["en"])["audio"] == 1                       # AD is not picked unless asked
    assert ap.choose([FR, EN], [], base, ["en"])["audio"] == 1 and ap.choose([FR], [], base, ["en"])["audio"] == 2
    assert ap.choose([ENAD], [], base, ["en"])["audio"] == 3 and ap.choose([], [], base, ["en"])["audio"] is None
    want_ad = ap.clean({"ad_track": True})
    assert ap.choose([EN, ENAD], [], want_ad, ["en"])["audio"] == 3 and ap.choose([FR, EN], [], want_ad, ["en"])["audio"] == 1


def test_captions_modes_prefer_hearing_impaired_and_skip_forced():
    always, auto, off = (ap.clean({"captions": m}) for m in ("always", "auto", "off"))
    assert ap.choose([EN], [SUBEN, SUBHI], always, ["en"])["subtitle"] == 11
    assert ap.choose([EN], [SUBFORCED, SUBEN], always, ["en"])["subtitle"] == 10
    assert ap.choose([EN], [SUBEN], auto, ["en"])["subtitle"] is None and ap.choose([FR], [SUBEN], auto, ["en"])["subtitle"] == 10
    assert ap.choose([EN], [SUBEN], off, ["en"])["subtitle"] is None


def test_no_captions_toast_once_per_film():
    seen = set(); always = ap.clean({"captions": "always"})
    assert ap.choose([EN], [], always, ["en"], "k1", toasted=seen)["toast"] == "No captions for this film."
    assert ap.choose([EN], [], always, ["en"], "k1", toasted=seen)["toast"] is None and ap.choose([EN], [], always, ["en"], "k2", toasted=seen)["toast"]


def test_misflagged_ad_override_remembered_per_content_key():
    want_ad = ap.clean({"ad_track": True}); ov = {"film": 1}
    assert ap.choose([EN, MISFLAG], [], want_ad, ["en"])["audio"] == 4                 # flag trusted by default
    assert ap.choose([EN, MISFLAG], [], want_ad, ["en"], "film", ov)["audio"] == 1     # user chose track 1 as the AD
    assert ap.choose([EN, MISFLAG], [], ap.clean({}), ["en"], "other", ov)["audio"] == 1


def test_add_my_captions_keeps_audio_and_starter_prefs_apply():
    cur = {"audio": 2, "subtitle": None}
    r = ap.add_my_captions(cur, [SUBFORCED, SUBEN], ["en"]); assert r["audio"] == 2 and r["subtitle"] == 10 and r["toast"] is None
    assert ap.add_my_captions(cur, [], ["en"])["toast"] == "No captions for this film."
    assert ap.prefs_for({"a11y": {"captions": "always"}})["captions"] == "always" and ap.prefs_for(None) == ap.DEFAULT


def test_dialogue_filter_levels():
    assert ap.dialogue_filter(0) == "" and ap.dialogue_filter(9) == "" and ap.dialogue_filter(True) == ""
    assert all("acompressor" in ap.dialogue_filter(b) for b in (1, 2, 3)) and ap.dialogue_filter(1) != ap.dialogue_filter(3)


def test_static_audit_flags_real_problems_and_passes_clean_page():
    assert ap.audit_html('<button aria-label="Play"><svg/></button><button>Pause</button><label for=v>Volume</label><input id=v type=range><img alt="" src=x>') == []
    bad = ap.audit_html('<button><svg/></button><input name=q><img src=x><style>a{transition:1s}</style>')
    assert {"button without accessible name", "input 'q' without label", "img without alt", "animation without prefers-reduced-motion guard"} <= set(bad)
    assert ap.audit_html("<style>.tap{min-height:30px}</style>") == ["touch target below 44px"] and ap.audit_html("<style>.tap{min-height:44px}</style>") == []
    assert ap.audit_html("<style>a{transition:1s}@media (prefers-reduced-motion:reduce){a{transition:none}}</style>") == []
