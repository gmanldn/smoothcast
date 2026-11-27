"""Offline fact gathering for the Preferences update row (#579, #582). GTK-free."""
from __future__ import annotations

from update_status import UpdateFacts


def facts_for_preferences(cfg: dict, *, root, playing: bool = False) -> UpdateFacts:
    """Offline facts for the Preferences row: no network, Git, import or file writes.

    A check or staging result is not known here, so the phase stays ``idle``;
    the row therefore never claims an update is available, staged or running.
    """
    import version
    from settings import UpdateSettings
    from update_managed import managed_facts
    prefs = UpdateSettings.from_config(cfg)
    active, previous, journal_state = managed_facts(root)
    return UpdateFacts(
        running_version=version.__version__,
        running_commit=version.read_checkout_revision(root),
        active_commit=active, previous_commit=previous, journal_state=journal_state,
        channel=prefs.channel, checks_enabled=prefs.check_releases,
        require_signature=prefs.verify_release,
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
    from settings import UpdateSettings
    prefs = UpdateSettings.from_config(cfg)
    channel, verify = prefs.channel, prefs.verify_release
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
    """Run ``check_now`` on the bounded network pool; ``on_done(text)`` is called from a worker."""
    import task_runtime
    rt = task_runtime.shared()
    rt.submit("network", rt.scope(deadline=60.0), lambda _s: check_now(cfg, root),
              lambda result, error: on_done(result if error is None else f"Update check failed: {error}"))
