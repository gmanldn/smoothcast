"""Offline fact gathering for the Preferences update row (#579, #582). GTK-free."""
from __future__ import annotations

from update_status import UpdateFacts


def facts_for_preferences(cfg: dict, *, root, playing: bool = False) -> UpdateFacts:
    """Offline facts for the Preferences row: no network, Git, import or file writes.

    A check or staging result is not known here, so the phase stays ``idle``;
    the row therefore never claims an update is available, staged or running.
    """
    import version
    from update_managed import managed_facts
    active, previous, journal_state = managed_facts(root)
    return UpdateFacts(
        running_version=version.__version__,
        running_commit=version.read_checkout_revision(root),
        active_commit=active, previous_commit=previous, journal_state=journal_state,
        channel=str(cfg.get("update_channel", "develop")),
        checks_enabled=cfg.get("check_release_updates") is True,
        require_signature=cfg.get("release_check_verify") is not False,
        playing=bool(playing))


NOT_FOUND = ("No newer release was found on this channel, or this install cannot be "
             "checked from here (installed builds update through their installer).")


def check_now(cfg: dict, root) -> str:
    """Explicit user-requested read-only check; blocking, so call off the GTK thread.

    The click is the consent, so ``enabled`` does not depend on the startup
    preference. Never changes files; an unchecked/ineligible install is said so
    rather than reported as up to date.
    """
    import dataclasses
    import update_control
    import update_status
    channel = cfg.get("update_channel")
    channel = channel if channel in update_control.UPDATE_CHANNELS else "develop"
    verify = cfg.get("release_check_verify") is not False
    try:
        found = update_control.find_candidate(root, enabled=True, verify=verify, channel=channel)
    except Exception:
        return "The update check failed. Check your network connection and try again."
    if found is None:
        return NOT_FOUND
    candidate, release, signed = found
    # An unsigned candidate is reported as untrusted, never as available.
    facts = dataclasses.replace(
        facts_for_preferences(cfg, root=root), channel=channel, checks_enabled=True,
        candidate=candidate, candidate_signed=signed)
    status = update_status.describe(facts)
    return f"{status.headline}. {status.detail} Version {release}. No files were changed."


def start_check(cfg: dict, root, on_done) -> None:
    """Run ``check_now`` on a daemon thread; ``on_done(text)`` is called from it."""
    import threading
    threading.Thread(target=lambda: on_done(check_now(cfg, root)),
                     daemon=True, name="update-check").start()
