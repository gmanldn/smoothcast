"""Read-only view of a managed install's activation record (#579). GTK-free."""
from __future__ import annotations


def managed_facts(app_root) -> tuple[str | None, str | None, str | None]:
    """(active, previous, journal state) of a managed install, else all None.

    Only an app running from ``<install>/releases/<commit>`` is managed; a
    checkout or any unreadable/corrupt record yields nothing rather than a guess.
    """
    from pathlib import Path
    app = Path(app_root)
    if app.parent.name != "releases":
        return None, None, None
    install = app.parent.parent
    setup = Path(__file__).resolve().parent.parent / "setup"
    try:
        ma = _load_setup_module(setup, "managed_activation", "managed_generations")
        ref = ma.read_active(install)
        journal = ma._load_journal(install)
        return ref["current"], ref["previous"], journal["state"] if journal else None
    except Exception:
        return None, None, None


def _load_setup_module(setup, name: str, *deps: str):
    """Load ``setup/<name>.py`` (and its sibling ``deps``) by path, without touching sys.path."""
    import importlib.util
    import sys
    for mod in (*deps, name):
        if mod in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(mod, setup / f"{mod}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(mod, None)
            raise
    return sys.modules[name]
