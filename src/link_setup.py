"""Off-thread owner setup for link isolation: install the launcher, attack-test it (#588).

Never enables a provider. GTK-free so Preferences can call it from a worker thread.
"""
from __future__ import annotations

import link_provision


def setup_and_qualify() -> tuple[bool, str]:
    """Install the wrapper, then attack-test it. Blocking: call off the GTK thread.

    Never enables a provider. ``ok`` means the launcher passed qualification; the
    message says plainly what failed otherwise.
    """
    ok, message = link_provision.install()
    if not ok:
        return False, message.capitalize() + "."
    import link_sandbox_probe
    launcher = link_provision.default_launcher()
    if not launcher:
        return False, "The launcher was written but is not usable."
    result = link_sandbox_probe.qualify(launcher)
    link_sandbox_probe.save(launcher, result)
    if result.verified:
        return True, "Isolation passed the attack test. YouTube links can now be enabled; BitTorrent still needs your own launcher."
    return False, "Isolation failed the attack test and stays off" + (": " + result.detail if result.detail else ".")


def start_setup(on_done) -> None:
    """Run ``setup_and_qualify`` on the bounded disk pool; ``on_done(ok, text)`` runs on a worker."""
    import task_runtime

    def finish(result, error) -> None:
        if error is not None:
            on_done(False, f"Setup failed: {type(error).__name__}.")
        else:
            on_done(*result)

    rt = task_runtime.shared()
    rt.submit("disk", rt.scope(), lambda _s: setup_and_qualify(), finish)
