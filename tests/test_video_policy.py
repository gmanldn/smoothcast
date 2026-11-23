"""Automatic crop and deinterlace policies (issue #54).

Pure parsing/decision tests, fake-runner detection tests and filter-chain
assembly. Real-FFmpeg checks live in test_video_policy_ffmpeg.py.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import streamer
import video_policy as vp
from video_policy import Crop, Idet, Plan

LETTERBOX = Crop(640, 360, 0, 60)

CROP_LOG = ("[Parsed_cropdetect_0 @ 0x7f] x1:0 x2:639 y1:60 y2:419 w:640 h:360 x:0 y:60 pts:1 t:2.0 "
            "limit:24.000000 crop=640:360:0:60\n"
            "[Parsed_cropdetect_0 @ 0x7f] x1:0 x2:639 y1:60 y2:419 w:640 h:360 x:0 y:60 pts:2 t:2.1 "
            "limit:24.000000 crop=640:360:0:60\n")
IDET_LOG = ("[Parsed_idet_0 @ 0x55] Multi frame detection: TFF:     0 BFF:     0 Progressive:     0 Undetermined:     0\n"
            "[Parsed_idet_0 @ 0x7f] Multi frame detection: TFF:    51 BFF:     0 Progressive:     3 Undetermined:     2\n")


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch, tmp_path):
    vp._CACHE.clear()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    yield
    vp._CACHE.clear()


def runner_returning(text="", *, error=None, calls=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        if error is not None:
            raise error
        return SimpleNamespace(stderr=text, returncode=0)
    return run


# --- parsing --------------------------------------------------------------------

def test_parse_crops_reads_every_suggestion():
    assert vp.parse_crops(CROP_LOG) == [LETTERBOX, LETTERBOX]
    assert vp.parse_crops("no crop here") == [] and vp.parse_crops(None) == []


def test_parse_idet_takes_the_last_populated_summary():
    assert vp.parse_idet(IDET_LOG) == Idet(tff=51, bff=0, progressive=3, undetermined=2)
    assert vp.parse_idet("") == Idet() and vp.parse_idet("garbage") == Idet()
    only_undetermined = "Multi frame detection: TFF: 0 BFF: 0 Progressive: 0 Undetermined: 125"
    assert vp.parse_idet(only_undetermined) == Idet()


# --- crop decisions -----------------------------------------------------------------

def test_crop_is_chosen_only_when_samples_agree():
    assert vp.choose_crop([LETTERBOX] * 3, 640, 480) == LETTERBOX
    other = Crop(640, 352, 0, 64)
    assert vp.choose_crop([LETTERBOX, LETTERBOX, other], 640, 480) == LETTERBOX   # 2/3 agree
    assert vp.choose_crop([LETTERBOX, other, Crop(640, 340, 0, 70)], 640, 480) is None  # no majority
    assert vp.choose_crop([LETTERBOX] * 2, 640, 480) is None                        # too few samples


@pytest.mark.parametrize("crop", [
    Crop(641, 360, 0, 60),       # odd width
    Crop(640, 359, 0, 60),       # odd height
    Crop(8, 8, 0, 0),            # tiny
    Crop(640, 360, 10, 200),     # outside the frame
    Crop(640, 360, -2, 0),       # negative offset
    Crop(640, 476, 0, 2),        # removes < 2% of the picture: not worth a filter
    Crop(640, 160, 0, 160),      # keeps < 40%: probably a dark scene, never trust it
])
def test_unsafe_or_pointless_crops_are_rejected(crop):
    assert vp.choose_crop([crop] * 4, 640, 480) is None


def test_degenerate_frame_sizes_never_crop():
    assert vp.choose_crop([LETTERBOX] * 3, 0, 480) is None
    assert vp.choose_crop([LETTERBOX] * 3, 640, 0) is None
    assert vp.choose_crop([], 640, 480) is None


# --- deinterlace decisions -------------------------------------------------------------

@pytest.mark.parametrize("idet,expected", [
    (Idet(tff=100), True), (Idet(bff=100), True), (Idet(tff=70, bff=5, progressive=25), True),
    (Idet(progressive=100), False),                      # plainly progressive
    (Idet(tff=40, bff=37, progressive=24), False),       # mixed field order: noise, not interlacing
    (Idet(tff=20, progressive=5), False),                # too few frames to judge
    (Idet(tff=30, progressive=70), False),               # mostly progressive
    (Idet(), False),
])
def test_interlace_decision_needs_ratio_and_consistent_field_order(idet, expected):
    assert vp.is_interlaced(idet) is expected


def test_plan_orders_filters_and_reports_the_output_size():
    plan = Plan(deinterlace=True, crop=LETTERBOX)
    assert plan.filters() == [vp.DEINTERLACE_FILTER, "crop=640:360:0:60"]
    assert plan.output_size(640, 480) == (640, 360) and Plan().output_size(640, 480) == (640, 480)
    assert Plan().empty and Plan().filters() == [] and not plan.empty


# --- detection with a fake runner ---------------------------------------------------------

def test_detect_crop_samples_three_windows_on_the_chosen_video_stream():
    calls: list[list[str]] = []
    crop = vp.detect_crop("/m/film.mkv", 7200, 640, 480, video_stream=2,
                          runner=runner_returning(CROP_LOG, calls=calls))
    assert crop == LETTERBOX and len(calls) == 3
    for command in calls:
        assert command[:2] == ["ffmpeg", "-hide_banner"] and "0:2" in command
        assert "-an" in command and "-sn" in command and "cropdetect" in " ".join(command)
        assert command[command.index("-t") + 1] == str(vp.CROP_SAMPLE_SECONDS)
    starts = [float(c[c.index("-ss") + 1]) for c in calls]
    assert starts == sorted(starts) and 0 < starts[0] < starts[-1] < 7200


def test_detection_failures_mean_do_nothing_and_are_reported_as_failed():
    for error in (subprocess.TimeoutExpired("ffmpeg", 12), OSError("no ffmpeg"), ValueError("x")):
        health = vp.Health()
        assert vp.detect_crop("/m/f.mkv", 100, 640, 480, runner=runner_returning(error=error), health=health) is None
        assert health.failed
        health = vp.Health()
        assert vp.detect_interlaced("/m/f.mkv", 100, runner=runner_returning(error=error), health=health) is False
        assert health.failed
    health = vp.Health()
    assert vp.detect_interlaced("/m/f.mkv", 100, runner=runner_returning(IDET_LOG), health=health) is True
    assert not health.failed


def test_unknown_duration_still_probes_once_from_the_start():
    calls: list[list[str]] = []
    vp.detect_interlaced("/m/f.mkv", 0, runner=runner_returning(IDET_LOG, calls=calls))
    assert len(calls) == 1 and calls[0][calls[0].index("-ss") + 1] == "0.0"


# --- configuration and caching ---------------------------------------------------------------

def write_config(tmp_path, data):
    folder = tmp_path / "cfg" / "cast-control"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(data if isinstance(data, str) else json.dumps(data))


def test_flags_default_off_and_only_a_literal_true_enables(tmp_path):
    assert vp.load_flags() == (False, False)
    write_config(tmp_path, {"auto_crop": True, "auto_deinterlace": "yes"})
    assert vp.load_flags() == (True, False)
    write_config(tmp_path, {"auto_crop": 1, "auto_deinterlace": True})
    assert vp.load_flags() == (False, True)
    for junk in ("{bad", "[]", "5"):
        write_config(tmp_path, junk)
        assert vp.load_flags() == (False, False)


def test_make_plan_is_free_when_disabled(tmp_path):
    movie = tmp_path / "m.mkv"
    movie.write_bytes(b"x")
    calls: list[list[str]] = []
    plan = vp.make_plan(str(movie), 100, 640, 480, runner=runner_returning(CROP_LOG, calls=calls))
    assert plan is vp.EMPTY_PLAN and calls == []


def test_make_plan_uses_config_flags_and_caches_per_file(tmp_path):
    movie = tmp_path / "m.mkv"
    movie.write_bytes(b"x" * 10)
    write_config(tmp_path, {"auto_crop": True, "auto_deinterlace": True})
    calls: list[list[str]] = []
    run = runner_returning(CROP_LOG + IDET_LOG, calls=calls)
    first = vp.make_plan(str(movie), 7200, 640, 480, runner=run)
    assert first == Plan(deinterlace=True, crop=LETTERBOX)
    used = len(calls)
    assert used == 4                                  # 1 idet + 3 crop windows
    assert vp.make_plan(str(movie), 7200, 640, 480, runner=run) == first
    assert len(calls) == used                         # cached: seek restarts cost nothing
    movie.write_bytes(b"y" * 11)                      # the file changed: measure again
    vp.make_plan(str(movie), 7200, 640, 480, runner=run)
    assert len(calls) == used * 2


def test_explicit_flags_override_config_and_failures_are_not_cached(tmp_path):
    movie = tmp_path / "m.mkv"
    movie.write_bytes(b"x")
    write_config(tmp_path, {"auto_crop": True})
    calls: list[list[str]] = []
    boom = runner_returning(error=OSError("x"), calls=calls)
    assert vp.make_plan(str(movie), 100, 640, 480, crop=False, deinterlace=False, runner=boom).empty
    assert calls == []
    assert vp.make_plan(str(movie), 100, 640, 480, crop=True, deinterlace=False, runner=boom).empty
    first = len(calls)
    assert first > 0
    vp.make_plan(str(movie), 100, 640, 480, crop=True, deinterlace=False, runner=boom)
    assert len(calls) == first * 2                    # a failed pass is retried, not remembered


def test_missing_file_is_never_cached_and_never_raises():
    run = runner_returning(CROP_LOG)
    plan = vp.make_plan("/nonexistent/film.mkv", 100, 640, 480, crop=True, deinterlace=False, runner=run)
    assert plan.crop == LETTERBOX       # detection itself still works from the runner's output
    assert not vp._CACHE                # but a file we cannot stat is never cached


# --- filter-chain assembly in streamer ----------------------------------------------------------

def chain(**kwargs):
    return streamer.Session()._filter_args(False, None, kwargs.pop("software", True), 1.0, **kwargs)


def test_chain_without_a_plan_is_unchanged():
    assert chain(video_size=(1920, 1080)) == []
    assert chain(video_size=(1920, 1080), video_plan=Plan()) == []


def test_plan_filters_come_first_on_the_software_path():
    out = chain(video_size=(640, 480), video_plan=Plan(deinterlace=True, crop=LETTERBOX))
    assert out == ["-vf", f"{vp.DEINTERLACE_FILTER},crop=640:360:0:60"]


def test_hardware_encode_downloads_frames_for_the_software_filters():
    out = chain(software=False, video_size=(1280, 720), video_plan=Plan(crop=Crop(1280, 536, 0, 92)))
    assert out == ["-vf", "hwdownload,format=nv12,crop=1280:536:0:92,hwupload"]
    assert chain(software=False, video_size=(1280, 720), video_plan=Plan()) == []


def test_cropped_size_drives_the_scaling_decision():
    big = Plan(crop=Crop(3840, 1600, 0, 280))
    out = chain(video_size=(3840, 2160), video_plan=big)[1]
    assert out.startswith("crop=3840:1600:0:280,scale=w=1920:h=1080:force_original_aspect_ratio=decrease")
    small = chain(video_size=(1920, 1080), video_plan=Plan(crop=Crop(1920, 800, 0, 140)))[1]
    assert small == "crop=1920:800:0:140"                  # fits: no scale added


def test_plan_filters_precede_burned_in_subtitles(tmp_path):
    staged = tmp_path / "subs.srt"
    out = streamer.Session()._filter_args(True, staged, True, 1.0, video_size=(640, 480),
                                          video_plan=Plan(crop=LETTERBOX))[1]
    assert out.index("crop=") < out.index("subtitles=")


def test_start_transcode_and_dlna_plan_before_choosing_the_encoder():
    text = (ROOT / "src" / "streamer.py").read_text(encoding="utf-8")
    assert text.index("video_policy.make_plan(") < text.index("self.used_software_fallback = True")
    assert "video_plan=video_plan," in text
    assert "video_policy.make_plan(" in (ROOT / "src" / "dlna.py").read_text(encoding="utf-8")


def test_defaults_keep_both_policies_off():
    text = (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")
    assert '"auto_crop": False' in text and '"auto_deinterlace": False' in text
    assert '"video_policy"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


# --- preview and its plain-language description (Preferences > Check this film) -------------------

def test_describe_reports_crop_percentage_and_interlacing():
    both = vp.describe(vp.Detection(crop=LETTERBOX, interlaced=True), 640, 480)
    assert both == "Black bars: crop to 640×360 (removes 25% of the picture) · Interlaced: deinterlacing would apply"
    none = vp.describe(vp.Detection(), 640, 480)
    assert none == "No black bars found · Progressive: no deinterlacing needed"
    assert vp.describe(vp.Detection(crop=LETTERBOX), 0, 0).startswith("No black bars found")  # unknown size: never divide


def test_preview_runs_both_detectors_regardless_of_the_flags_and_never_caches(tmp_path):
    movie = tmp_path / "m.mkv"
    movie.write_bytes(b"x")
    calls: list[list[str]] = []
    run = runner_returning(CROP_LOG + IDET_LOG, calls=calls)
    found = vp.preview(str(movie), 7200, 640, 480, runner=run)    # flags are off (default config)
    assert found == vp.Detection(crop=LETTERBOX, interlaced=True)
    assert len(calls) == 4 and not vp._CACHE
    quiet = vp.preview(str(movie), 7200, 640, 480, runner=runner_returning(error=OSError("x")))
    assert quiet == vp.Detection()                                 # a failed pass means 'nothing found'


def test_preferences_expose_the_switches_and_the_film_check():
    # The film-check card lives in PicturePreferencesMixin (preferences_picture_ui).
    prefs = "\n".join((ROOT / "src" / name).read_text(encoding="utf-8")
                      for name in ("preferences_ui.py", "preferences_picture_ui.py"))
    assert '"auto_crop"' in prefs and '"auto_deinterlace"' in prefs
    assert "picture_check.PictureCheck(self.owner)" in prefs and "save_config(owner.cfg)" in prefs
    check = (ROOT / "src" / "picture_check.py").read_text(encoding="utf-8")
    assert "video_policy.preview(" in check and "domain=\"background\"" in check
    assert '"picture_check"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
