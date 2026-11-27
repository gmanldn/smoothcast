import pytest

import power_backends as P
import sleep_inhibit


class Proc:
    def __init__(self, argv):
        self.argv, self.stopped = argv, 0

    def terminate(self):
        self.stopped += 1


def make(kind):
    procs = []

    def spawn(argv):
        procs.append(Proc(argv))
        return procs[-1]

    if kind == "fake":
        return P.Fake(), lambda: None
    if kind == "logind":
        return P.Logind(spawn, lambda n: "/usr/bin/" + n), lambda: procs[0].stopped
    if kind == "mac":
        return P.MacCaffeinate(spawn, lambda n: "/usr/bin/" + n), lambda: procs[0].stopped
    calls = []
    return P.Windows(lambda flags: calls.append(flags) or 1), lambda: calls[-1] == P.ES_CONTINUOUS


@pytest.mark.parametrize("kind", ["fake", "logind", "mac", "windows"])
def test_contract_acquire_then_release_exactly_once_through_the_inhibitor(kind):
    backend, released = make(kind)
    inh = sleep_inhibit.Inhibitor(backend)
    assert inh.acquire("handover") and inh.held
    inh.release()
    inh.release()
    assert not inh.held
    if kind != "fake":
        assert released()
    else:
        assert backend.active == 0


@pytest.mark.parametrize("backend", [P.Logind(lambda a: Proc(a), lambda n: None), P.MacCaffeinate(lambda a: Proc(a), lambda n: None),
                                      P.Windows(lambda f: 0), P.Fake(fail=True)])
def test_contract_failed_acquire_raises_and_inhibitor_proceeds_unprotected(backend):
    with pytest.raises(OSError):
        backend.acquire("x")
    inh = sleep_inhibit.Inhibitor(backend)
    assert inh.acquire() is False and not inh.held


def test_release_never_raises_even_on_a_dead_process_or_none():
    class Dead:
        def terminate(self):
            raise ProcessLookupError

    P.Logind(None, None).release(Dead())
    P.MacCaffeinate(None, None).release(None)
    P.Windows(lambda f: (_ for _ in ()).throw(OSError("gone"))).release(True)


def test_logind_argv_is_a_bounded_delay_lock_with_the_reason():
    seen = []
    P.Logind(lambda a: seen.append(a) or Proc(a), lambda n: "/bin/" + n).acquire("handover")
    assert seen[0][:2] == ["/bin/systemd-inhibit", "--what=sleep:shutdown"]
    assert "--why=handover" in seen[0] and "--mode=delay" in seen[0]


def test_platform_selection():
    kw = dict(spawn=None, which=None, set_state=None)
    assert isinstance(P.for_platform("linux", **kw), P.Logind)
    assert isinstance(P.for_platform("darwin", **kw), P.MacCaffeinate)
    assert isinstance(P.for_platform("win32", **kw), P.Windows)
    assert P.for_platform("freebsd14", **kw) is None
