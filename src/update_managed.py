"""Read-only view of a managed install's activation record (#579). GTK-free."""
from __future__ import annotations


def managed_facts(app_root) -> tuple[str | None, str | None, str | None]:
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
