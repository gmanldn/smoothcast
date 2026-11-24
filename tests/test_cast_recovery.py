"""#13: failed cast launch/seek/transfer keeps position and offers clear recovery."""
from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cast_recovery as cr
from cast_recovery import FailureContext, plan_recovery
import errors


def kinds(plan):
    return [o.kind for o in plan.options]


def test_generic_launch_failure_offers_retry_then_encoding_then_targets():
    plan = plan_recovery(FailureContext("Living Room", position=754.2, duration=3600,
                                        targets=("Kitchen", "Den")))
    assert kinds(plan) == ["retry", "alternate_encoding", "alternate_target", "alternate_target"]
    assert plan.primary.kind == "retry" and plan.position == 754.2
    assert all(o.position == 754.2 for o in plan.options)
    assert "12:34" in plan.headline and "saved" in plan.headline
    enc = plan.options[1]
    assert (enc.device, enc.mode) == ("Living Room", "remux")
    assert "while starting" in enc.reason and "converting" in enc.reason and "remux" not in enc.reason
    assert [o.device for o in plan.options[2:]] == ["Kitchen", "Den"]
    assert all(o.reason and o.label for o in plan.options)


@pytest.mark.parametrize("stage,phrase", [("seek", "while seeking"), ("launch", "while starting"),
                                          ("transfer", "during playback")])
def test_reason_names_the_stage(stage, phrase):
    plan = plan_recovery(FailureContext("TV", stage=stage, targets=("Den",)))
    assert phrase in plan.options[1].reason and phrase in plan.options[-1].reason


def test_encoding_ladder_advances_and_ends_at_transcode():
    first = plan_recovery(FailureContext("TV", mode="direct"))
    assert [(o.kind, o.mode) for o in first.options if o.kind != "retry"] == [("alternate_encoding", "remux")]
    again = plan_recovery(FailureContext("TV", mode="remux", tried=(("TV", "direct"),)))
    assert [o.mode for o in again.options if o.kind == "alternate_encoding"] == ["transcode"]
    last = plan_recovery(FailureContext("TV", mode="transcode"))
    assert "alternate_encoding" not in kinds(last)
    unknown = plan_recovery(FailureContext("TV", mode="dlna"))
    assert "alternate_encoding" not in kinds(unknown)


def test_a_pair_that_failed_twice_is_never_offered_again():
    ctx = FailureContext("TV", mode="direct", tried=(("TV", "direct"), ("TV", "remux"), ("TV", "remux")),
                         targets=("Den",))
    plan = plan_recovery(ctx)
    assert "retry" not in kinds(plan)  # TV/direct has now failed twice
    assert not [o for o in plan.options if o.kind == "alternate_encoding" and o.mode == "remux"]
    assert [o.device for o in plan.options if o.kind == "alternate_target"] == ["Den"]
    blocked = plan_recovery(FailureContext("TV", mode="direct", targets=("Den",),
                                           tried=(("Den", "direct"), ("Den", "direct"))))
    assert "alternate_target" not in kinds(blocked)


@pytest.mark.parametrize("code,expected", [
    ("cast.receiver_offline", ["retry", "alternate_target"]),
    ("cast.no_supported_format", ["alternate_target"]),
    ("cast.settings_unsupported", ["alternate_target"]),
    ("cast.command_in_progress", ["retry"]),
    ("ffmpeg.decoder_timeout", ["retry", "alternate_encoding"]),
    ("ffmpeg.decoder_failed", []),
    ("media.unavailable", []),
])
def test_catalogued_failures_only_offer_options_that_can_help(code, expected):
    plan = plan_recovery(FailureContext("TV", error_code=code, targets=("Den",)))
    assert dict.fromkeys(kinds(plan)).keys() == dict.fromkeys(expected).keys()
    assert plan.steps == errors.CATALOGUE[code].steps
    assert errors.CATALOGUE[code].message in plan.headline


def test_non_retryable_catalogue_entry_never_offers_retry_even_if_allowed():
    assert not errors.CATALOGUE["cast.no_supported_format"].retryable
    assert "retry" not in kinds(plan_recovery(FailureContext("TV", error_code="cast.no_supported_format")))


def test_unknown_code_is_treated_as_unexpected_with_everything_offered():
    plan = plan_recovery(FailureContext("TV", error_code="made.up_code", targets=("Den",)))
    assert plan.steps == errors.FALLBACK.steps
    assert kinds(plan) == ["retry", "alternate_encoding", "alternate_target"]


@pytest.mark.parametrize("position,duration,expected", [
    (None, None, 0.0), (-5, None, 0.0), (float("nan"), 100, 0.0), (float("inf"), 100, 0.0),
    ("12", 100, 0.0), (True, 100, 0.0), (50, 100, 50.0), (500, 100, 100.0), (500, None, 500.0),
    (500, float("nan"), 500.0), (500, -1, 500.0), (0, 100, 0.0),
])
def test_position_is_always_safe(position, duration, expected):
    assert cr.safe_position(position, duration) == expected
    plan = plan_recovery(FailureContext("TV", position=position, duration=duration))
    assert plan.position == expected and math.isfinite(plan.position)


@pytest.mark.parametrize("seconds,text", [(0, "0:00"), (59.9, "0:59"), (60, "1:00"), (3599, "59:59"),
                                          (3600, "1:00:00"), (7384, "2:03:04"), (-3, "0:00")])
def test_format_position(seconds, text):
    assert cr.format_position(seconds) == text


def test_targets_are_sanitised_deduplicated_and_bounded():
    targets = ("TV", "Den\x07‮", "Den", "", "  ", 42, "A" * 200, "B", "C", "D", "E")
    plan = plan_recovery(FailureContext("TV", targets=targets))
    names = [o.device for o in plan.options if o.kind == "alternate_target"]
    assert names == ["Den", "A" * 64, "B"]  # failed device and junk skipped, capped at 3
    assert len(plan.options) <= 1 + 1 + cr.MAX_TARGET_OPTIONS
    assert all("\x07" not in o.label and "‮" not in o.label for o in plan.options)


def test_hostile_tried_history_is_bounded():
    tried = tuple((f"d{i}", "direct") for i in range(10_000))
    assert plan_recovery(FailureContext("TV", tried=tried)).options  # no blow-up, still answers


def test_plan_is_pure_and_deterministic():
    ctx = FailureContext("TV", position=5, targets=("Den",))
    assert plan_recovery(ctx) == plan_recovery(ctx)
    with pytest.raises(Exception):
        ctx.device = "other"  # frozen


@pytest.mark.parametrize("message,code", [
    ("Receiver is offline", "cast.receiver_offline"),
    ("Chromecast not reachable at 192.168.1.5", "cast.receiver_offline"),
    ("Connection refused", "cast.receiver_offline"),
    ("Unsupported media type", "cast.no_supported_format"),
    ("probe timed out", "ffmpeg.decoder_timeout"),
    ("something odd", None), ("", None), (None, None),
])
def test_legacy_free_text_is_classified_conservatively(message, code):
    assert cr.classify_message(message) == code


# -- live-window observation (#13) -------------------------------------------
from types import SimpleNamespace  # noqa: E402


def _window(**over):
    base = dict(_device=lambda: "Living Room", tracker=SimpleNamespace(value=lambda: 90.0),
                session=SimpleNamespace(mode="direct"),
                devices=[SimpleNamespace(name="Living Room"), SimpleNamespace(name="Kitchen")],
                device_info={"duration": 3600})
    base.update(over)
    return SimpleNamespace(**base)


def test_plan_for_window_reads_position_mode_and_other_receivers():
    plan = cr.plan_for_window(_window(), "Receiver is offline")
    assert plan.position == 90.0
    assert [o.kind for o in plan.options] == ["retry", "alternate_target"]  # offline: no re-encode
    assert plan.options[1].device == "Kitchen"
    assert cr.summary_line(plan) == "Recovery: place 1:30 saved; options: retry, alternate_target"
    assert "Kitchen" not in cr.summary_line(plan)  # console line carries no receiver names


def test_plan_for_window_without_a_session_is_a_launch_failure():
    plan = cr.plan_for_window(_window(session=None), "boom")
    assert "while starting" in plan.options[1].reason


@pytest.mark.parametrize("broken", [
    dict(_device=lambda: ""), dict(_device=lambda: (_ for _ in ()).throw(RuntimeError("x"))),
    dict(tracker=SimpleNamespace(value=lambda: 1 / 0)), dict(devices=5), dict(device_info=object()),
])
def test_plan_for_window_never_raises(broken):
    result = cr.plan_for_window(_window(**broken), "failure")
    assert result is None or isinstance(result, cr.RecoveryPlan)


def test_plan_for_window_survives_a_bare_object():
    assert cr.plan_for_window(object(), None) is None
    assert cr.plan_for_window(None, None) is None


def test_cast_failed_observes_before_the_tracker_is_cleared():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gui_source import main_window_methods

    body = main_window_methods()["_cast_failed"]
    observe = body.index("cast_recovery.plan_for_window(self, message)")
    assert observe < body.index("self.tracker.clear()") and observe < body.index("self._stop_monitor()")
    assert "cast_recovery.summary_line(self._recovery_plan)" in body
    assert body.count("toast(") == 1  # observation only: still exactly the original toast
