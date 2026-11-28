import power_port as pp
import sleep_inhibit


class Proc:
    def __init__(self):
        self.terminated = 0

    def terminate(self):
        self.terminated += 1


def test_systemd_and_caffeinate_spawn_then_terminate_exactly_once():
    procs, argv = [], []

    def spawn(a):
        argv.append(a)
        procs.append(Proc())
        return procs[-1]
    for backend, head in ((pp.SystemdInhibit(spawn), "systemd-inhibit"), (pp.Caffeinate(spawn), "caffeinate")):
        token = backend.acquire("handover")
        assert argv[-1][0] == head
        backend.release(token)
        assert procs[-1].terminated == 1


def test_missing_helper_means_nothing_held_not_a_crash():
    def spawn(_):
        raise FileNotFoundError("no systemd-inhibit")
    b = pp.SystemdInhibit(spawn)
    token = b.acquire("x")
    assert token is None
    b.release(token)


def test_windows_sets_then_clears_execution_state():
    calls = []
    b = pp.WindowsExecutionState(lambda f: calls.append(f) or 1)
    token = b.acquire("x")
    b.release(token)
    assert calls == [pp.ES_CONTINUOUS | pp.ES_SYSTEM_REQUIRED, pp.ES_CONTINUOUS]
    assert pp.WindowsExecutionState(lambda f: 0).acquire("x") is None


def test_release_never_raises_even_if_terminate_fails():
    class Bad:
        def terminate(self):
            raise OSError("gone")
    pp.Caffeinate(lambda a: Bad()).release(Bad())


def test_choose_by_platform_and_falls_back_to_noop():
    spawn, state = (lambda a: Proc()), (lambda f: 1)
    assert isinstance(pp.choose("linux", spawn=spawn), pp.SystemdInhibit)
    assert isinstance(pp.choose("darwin", spawn=spawn), pp.Caffeinate)
    assert isinstance(pp.choose("win32", set_state=state), pp.WindowsExecutionState)
    assert isinstance(pp.choose("linux"), sleep_inhibit.NoopBackend)


def test_works_inside_the_bounded_inhibitor_and_the_fake_satisfies_the_contract():
    fake = pp.Fake()
    with sleep_inhibit.Inhibitor(backend=fake) as inhibitor:
        assert fake.held
    assert len(fake.released) == 1
