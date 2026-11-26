"""Update status wording and safe actions without GTK or network (#582)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import update_facts as uf
import update_status as us

A, B, C = "a" * 40, "b" * 40, "c" * 40
BASE = us.UpdateFacts(running_version="1.2.52", running_commit=A, channel="develop", checks_enabled=True)


def d(**changes):
    return us.describe(replace(BASE, **changes))


def test_running_line_names_version_short_commit_and_channel():
    s = d()
    assert s.running_line == "SmoothCast 1.2.52 (aaaaaaa) on develop"
    assert s.channel_line == "Channel: develop (default)"
    assert d(channel="main").channel_line == "Channel: main (released builds only)"
    assert "not recognised" in d(channel="weird").channel_line
    assert d(channel="weird").running_line.endswith("on develop")


def test_commit_text_is_sanitised_never_echoing_junk():
    assert us.short("A" * 40) == "aaaaaaa"
    for junk in (None, "", "zz", "../../etc/passwd", "abc", "g" * 40):
        assert us.short(junk) == "unknown"
    assert "unknown" in d(running_commit="<script>").running_line
    assert "<script>" not in d(running_commit="<script>").running_line


def test_checks_off_offers_to_enable_and_never_claims_an_update():
    s = d(checks_enabled=False, candidate=B, phase="staged", active_commit=A, staged_commit=B)
    assert s.state == "off" and s.actions == ("enable_checks",)


@pytest.mark.parametrize("phase,state", [("downloaded", "downloaded"), ("verified", "verified")])
def test_fetched_files_are_never_presented_as_running(phase, state):
    s = d(candidate=B, candidate_signed=True, phase=phase)
    assert s.state == state and not s.running_new_version
    assert "not" in s.detail.lower()
    assert "restart_now" not in s.actions


def test_signature_policy_blocks_unsigned_or_unchecked_candidates():
    unsigned = d(candidate=B, candidate_signed=False, phase="staged", active_commit=A, staged_commit=B)
    assert unsigned.state == "untrusted" and "restart_now" not in unsigned.actions
    pending = d(candidate=B, candidate_signed=None, phase="downloaded")
    assert pending.state == "verifying"
    relaxed = d(candidate=B, candidate_signed=False, phase="staged", active_commit=A, staged_commit=B, require_signature=False)
    assert relaxed.state == "untrusted" and "restart_now" not in relaxed.actions


def test_staged_update_waits_for_playback_and_never_restarts_itself():
    ready = d(candidate=B, candidate_signed=True, phase="staged", active_commit=A, staged_commit=B)
    assert ready.state == "ready" and ready.actions == ("restart_now", "restart_when_idle")
    busy = d(candidate=B, candidate_signed=True, phase="staged", active_commit=A, staged_commit=B, playing=True)
    assert busy.state == "awaiting_idle" and busy.actions == ("restart_when_idle",)
    assert "will not restart during playback" in busy.detail


def test_activation_journal_states_have_honest_wording():
    assert d(journal_state="planned").state == "preparing"
    assert d(journal_state="probed").actions == ("cancel",)
    switched = d(journal_state="switched")
    assert switched.state == "confirming" and switched.actions == ()
    rolled = d(journal_state="rolled_back", active_commit=A, previous_commit=C)
    assert rolled.state == "rolled_back" and "aaaaaaa is running again" in rolled.detail
    assert "ccccccc" not in rolled.detail
    assert d(journal_state="aborted").state == "aborted"


def test_updated_only_when_running_commit_is_the_acknowledged_generation():
    ok = d(running_commit=B, active_commit=B, previous_commit=A, journal_state="acked")
    assert ok.state == "running_new" and ok.running_new_version and "rollback" in ok.actions
    # activation reference moved but the app still runs the old commit: not "Updated"
    stale = d(running_commit=A, active_commit=B, previous_commit=A, journal_state="acked")
    assert stale.state != "running_new"
    # acknowledged but previous == running (nothing changed): not "Updated"
    same = d(running_commit=B, active_commit=B, previous_commit=B, journal_state="acked")
    assert same.state != "running_new"


@pytest.mark.parametrize("fault", sorted(us.FAULTS))
def test_every_fault_is_civil_actionable_and_free_of_internals(fault):
    s = d(fault=fault)
    assert s.state == "fault" and s.detail == us.FAULTS[fault]
    for banned in ("Traceback", "Exception", "Something went wrong", "errno", "/home/"):
        assert banned not in s.detail
    assert len(s.headline) <= 90 and len(s.detail) <= 240
    assert "check_now" in s.actions
    assert ("retry" in s.actions) == (fault != "bad_signature")


def test_unknown_fault_code_is_ignored_not_echoed():
    s = d(fault="<b>boom</b>")
    assert s.state != "fault" and "boom" not in s.detail


def test_available_update_is_not_installed_and_current_is_calm():
    s = d(candidate=B, candidate_signed=True, phase="idle")
    assert s.state == "available" and "Nothing is installed yet" in s.detail
    assert d(candidate=A, candidate_signed=True).state == "current"
    assert d().state == "unchecked"


def test_checking_is_cancellable_and_does_not_touch_playback():
    s = d(phase="checking")
    assert s.state == "checking" and s.actions == ("cancel",) and "does not interrupt playback" in s.detail


def test_copy_follows_the_ux_contract_for_every_reachable_state():
    states = [d(), d(checks_enabled=False), d(phase="checking"), d(phase="downloaded", candidate=B, candidate_signed=True),
              d(phase="verified", candidate=B, candidate_signed=True),
              d(phase="staged", candidate=B, candidate_signed=True, active_commit=A, staged_commit=B),
              d(phase="staged", candidate=B, candidate_signed=True, active_commit=A, staged_commit=B, playing=True),
              d(journal_state="planned"), d(journal_state="switched"),
              d(journal_state="rolled_back", previous_commit=C), d(journal_state="aborted"),
              d(candidate=B, candidate_signed=False, phase="staged", active_commit=A, staged_commit=B)]
    for s in states:
        assert len(s.headline) <= 90 and len(s.detail) <= 240, s.state
        assert not s.headline.endswith("."), s.headline
        assert "Something went wrong" not in s.detail and "!" not in s.headline + s.detail
        assert s.accessible_label.startswith(s.headline)


def test_exact_commit_identity_not_display_prefix_controls_update_detection():
    collision = "a" * 7 + "b" * 33
    assert us.short(collision) == us.short(A)
    assert d(candidate=collision, candidate_signed=True).state == "available"
    assert d(candidate=A.upper(), candidate_signed=True).state == "current"
    assert d(candidate=A[:7]).state == "unchecked"
    assert d(running_commit=A[:7], candidate=A).state == "unchecked"


def test_verified_download_never_offers_restart_even_if_reference_moved():
    status = d(candidate=B, candidate_signed=True, phase="verified", active_commit=B)
    assert status.state == "verified" and "restart_now" not in status.actions


@pytest.mark.parametrize("changes", [
    {"staged_commit": None},
    {"staged_commit": C},
    {"candidate": B[:7]},
    {"running_commit": A[:7]},
    {"staged_commit": B[:7]},
    {"active_commit": A[:7]},
])
def test_staged_build_needs_exact_matching_identities(changes):
    facts = replace(BASE, candidate=B, candidate_signed=True, phase="staged",
                    active_commit=A, staged_commit=B)
    status = us.describe(replace(facts, **changes))
    assert status.state == "unconfirmed" and status.actions == ("check_now",)


def test_staging_never_requires_switching_active_reference():
    status = d(candidate=B, candidate_signed=True, phase="staged",
               active_commit=A, staged_commit=B)
    assert status.state == "ready"
    mismatch = d(candidate=B, candidate_signed=True, phase="staged",
                 active_commit=B, staged_commit=B)
    assert mismatch.state == "activation_mismatch"
    assert "restart_now" not in mismatch.actions


def test_rollback_does_not_claim_a_build_is_running_without_confirmation():
    status = d(journal_state="rolled_back", active_commit=B, previous_commit=C)
    assert status.state == "rolled_back"
    assert "not confirmed" in status.detail and "is running again" not in status.detail
    status = d(journal_state="rolled_back")
    assert "not confirmed" in status.detail


def test_sha256_commit_ids_are_supported_but_abbreviations_are_not():
    running, candidate = "a" * 64, "b" * 64
    assert d(running_commit=running, candidate=running).state == "current"
    assert d(running_commit=running, candidate=candidate).state == "available"
    assert d(running_commit=running, candidate=candidate[:40]).state == "available"
    assert d(running_commit=running, candidate=candidate[:12]).state == "unchecked"


@pytest.mark.parametrize("terminal", ["acked", "rolled_back", "aborted"])
def test_old_terminal_journal_does_not_hide_new_staging_or_check(terminal):
    facts = dict(journal_state=terminal, active_commit=A, previous_commit=C)
    assert d(phase="checking", **facts).state == "checking"
    ready = d(candidate=B, candidate_signed=True, phase="staged", staged_commit=B, **facts)
    assert ready.state == "ready" and "restart_now" in ready.actions

@pytest.mark.parametrize("changes", [
    {"phase": "unknown"}, {"journal_state": "unknown"},
    {"journal_state": "acked", "active_commit": None},
    {"journal_state": "acked", "active_commit": "a" * 7},
    {"journal_state": "acked", "running_commit": 123},
])
def test_inconsistent_update_state_never_claims_current_or_offers_restart(changes):
    facts = dict(candidate=A, candidate_signed=True, active_commit=A)
    facts.update(changes)
    status = d(**facts)
    assert status.state == "unconfirmed"
    assert status.actions == ("check_now",)
    assert not status.running_new_version


def test_updated_build_does_not_offer_rollback_during_playback():
    facts = dict(running_commit=B, active_commit=B, previous_commit=A, journal_state="acked")
    assert "rollback" in d(**facts).actions
    playing = d(playing=True, **facts)
    assert playing.running_new_version and playing.actions == ("check_now",)
    assert "unavailable during playback" in playing.detail



def test_preferences_facts_are_offline_and_never_claim_a_phase(tmp_path):
    facts = uf.facts_for_preferences({"update_channel": "main", "check_release_updates": True}, root=tmp_path)
    assert facts.channel == "main" and facts.checks_enabled and facts.phase == "idle"
    assert facts.running_commit is None and facts.require_signature is True
    status = us.describe(facts)
    assert "main" in status.running_line and not status.running_new_version
    assert facts.playing is False


def test_managed_install_facts_show_staged_reference_and_corrupt_records_fail_quiet(tmp_path):
    old, new = "a" * 40, "b" * 40
    install = tmp_path / "inst"
    app = install / "releases" / old
    app.mkdir(parents=True)
    (install / "active.json").write_text(
        '{"current": "%s", "previous": "%s", "seq": 2}' % (new, old))
    facts = uf.facts_for_preferences({"check_release_updates": True}, root=app)
    assert (facts.active_commit, facts.previous_commit) == (new, old)
    (install / "active.json").write_text("{not json")
    facts = uf.facts_for_preferences({}, root=app)
    assert facts.active_commit is None and facts.journal_state is None
    assert uf.facts_for_preferences({}, root=tmp_path).active_commit is None  # checkout: not managed


def test_check_now_reports_notice_or_honest_not_found(tmp_path, monkeypatch):
    import update_control as uc
    seen = {}
    def fake(root, **kw):
        seen.update(kw)
        return seen.get("notice")
    monkeypatch.setattr(uc, "check_release", fake)
    assert uf.check_now({"update_channel": "bogus"}, tmp_path) == uf.NOT_FOUND
    assert seen["enabled"] is True and seen["channel"] == "develop" and seen["verify"] is True
    monkeypatch.setattr(uc, "check_release", lambda *a, **k: "SmoothCast v9 is available")
    assert uf.check_now({}, tmp_path).startswith("SmoothCast v9")
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(uc, "check_release", boom)
    assert "failed" in uf.check_now({}, tmp_path)
