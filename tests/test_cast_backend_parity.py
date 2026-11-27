"""Every castctl control helper works on the pychromecast backend as it does on catt (#202)."""
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "tests")

import castctl
from test_pychromecast_backend import FakeCast, discovered_backend

HELPERS = {
    "play": lambda d: castctl.play(d),
    "pause": lambda d: castctl.pause(d),
    "play_toggle": lambda d: castctl.play_toggle(d),
    "stop": lambda d: castctl.stop(d),
    "seek": lambda d: castctl.seek(d, 59.9),
    "volume": lambda d: castctl.volume(d, 42),
    "mute": lambda d: castctl.set_muted(d, True),
    "unmute": lambda d: castctl.set_muted(d, False),
    "subs_off": lambda d: castctl.subs_off(d),
}


def test_every_helper_verb_is_accepted_by_pychromecast(monkeypatch):
    backend, _browser = discovered_backend([FakeCast()])
    backend.scan(timeout=0)
    monkeypatch.setattr(castctl, "_backend", backend)
    results = {name: run("Living Room") for name, run in HELPERS.items()}
    assert {n: r for n, r in results.items() if r != (True, "")} == {}
    backend.close()


def test_pychromecast_rejects_unknown_verbs_without_raising(monkeypatch):
    backend, _browser = discovered_backend([FakeCast()])
    backend.scan(timeout=0)
    ok, message = backend.command("Living Room", "definitely_not_a_verb")
    assert ok is False and message
    backend.close()
