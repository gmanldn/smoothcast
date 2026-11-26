"""Offline fact gathering for the Preferences update row (#579, #582). GTK-free."""
from __future__ import annotations

from update_status import UpdateFacts


def facts_for_preferences(cfg: dict, *, root, playing: bool = False) -> UpdateFacts:
    """Offline facts for the Preferences row: no network, Git, import or file writes.

    A check or staging result is not known here, so the phase stays ``idle``;
    the row therefore never claims an update is available, staged or running.
    """
    import version
    active, previous, journal_state = _managed_facts(root)
    return UpdateFacts(
        running_version=version.__version__,
        running_commit=version.read_checkout_revision(root),
        active_commit=active, previous_commit=previous, journal_state=journal_state,
        channel=str(cfg.get("update_channel", "develop")),
        checks_enabled=cfg.get("check_release_updates") is True,
        require_signature=cfg.get("release_check_verify") is not False,
        playing=bool(playing))


def _managed_facts(app_root) -> tuple[str | None, str | None, str | None]:
    """(active, previous, journal state) of a managed install, else all None.

    Only an app running from ``<install>/releases/<commit>`` is managed; a
    checkout or any unreadable/corrupt record yields nothing rather than a guess.
    """
    from pathlib import Path
    import sys
    app = Path(app_root)
    if app.parent.name != "releases":
        return None, None, None
    install = app.parent.parent
    setup = str(Path(__file__).resolve().parent.parent / "setup")
    try:
        if setup not in sys.path:
            sys.path.append(setup)
        import managed_activation as ma
        ref = ma.read_active(install)
        journal = ma._load_journal(install)
        return ref["current"], ref["previous"], journal["state"] if journal else None
    except Exception:
        return None, None, None


NOT_FOUND = ("No newer release was found on this channel, or this install cannot be "
             "checked from here (installed builds update through their installer).")


def check_now(cfg: dict, root) -> str:
    """Explicit user-requested read-only check; blocking, so call off the GTK thread.

    The click is the consent, so ``enabled`` does not depend on the startup
    preference. Never changes files; an unchecked/ineligible install is said so
    rather than reported as up to date.
    """
    import update_control
    channel = cfg.get("update_channel")
    try:
        notice = update_control.check_release(
            root, enabled=True, verify=cfg.get("release_check_verify") is not False,
            channel=channel if channel in update_control.UPDATE_CHANNELS else "develop")
    except Exception:
        return "The update check failed. Check your network connection and try again."
    return notice or NOT_FOUND
