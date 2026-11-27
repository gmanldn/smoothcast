"""A status read, rediscovery and retry included, never outlasts the caller's timeout."""
import castctl

OK = {"player_state": "PLAYING"}


class NoMirror:
    def info(self, host, timeout):
        return None

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now


def _setup(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(castctl.time, "monotonic", clock.monotonic)
    backend = castctl.CattBackend()
    backend._mirror = NoMirror()
    monkeypatch.setattr(castctl, "_backend", backend)
    monkeypatch.setattr(castctl, "log_backend_failure", lambda *a, **k: None)
    threads = []

    class FakeThread:
        def __init__(self, target, args=(), **_kwargs):
            threads.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr(castctl.threading, "Thread", FakeThread)
    castctl._info_failures.clear()
    return clock, backend, threads


def test_timed_out_name_read_defers_rediscovery_to_the_background(monkeypatch):
    clock, backend, threads = _setup(monkeypatch)
    budgets = []

    def slow_info(device, timeout=8):
        budgets.append((device, timeout))
        clock.now += timeout  # the helper used the whole budget
        return None

    monkeypatch.setattr(castctl, "_catt_info", slow_info)
    monkeypatch.setattr(backend, "refreshed_route",
                        lambda name: (_ for _ in ()).throw(AssertionError("no inline scan")))
    start = clock.now
    assert backend.info("TV", timeout=8) is None
    assert clock.now - start <= 8
    assert budgets == [("TV", 8)]
    assert [args for _target, args in threads] == [("TV",)]


def test_background_refresh_respects_the_rediscovery_throttle(monkeypatch):
    clock, backend, threads = _setup(monkeypatch)

    def slow_info(device, timeout=8):
        clock.now += timeout
        return None

    monkeypatch.setattr(castctl, "_catt_info", slow_info)
    backend._last_refresh["TV"] = clock.now
    assert backend.info("TV", timeout=8) is None
    assert threads == []


def test_retry_gets_only_the_remaining_budget(monkeypatch):
    clock, backend, threads = _setup(monkeypatch)
    budgets = []

    def info(device, timeout=8):
        budgets.append((device, timeout))
        clock.now += 0.5
        return OK if device == "192.0.2.9" else None

    def refresh(name):
        clock.now += 4.0  # scan plus identity check
        return "192.0.2.9"

    monkeypatch.setattr(castctl, "_catt_info", info)
    monkeypatch.setattr(backend, "refreshed_route", refresh)
    start = clock.now
    assert backend.info("TV", timeout=8) == OK
    assert budgets[0] == ("TV", 8)
    assert budgets[1][0] == "192.0.2.9"
    assert abs(budgets[1][1] - 3.5) < 1e-9
    assert clock.now - start <= 8
    assert threads == []


def test_no_retry_when_rediscovery_leaves_under_a_second(monkeypatch):
    clock, backend, _threads = _setup(monkeypatch)
    calls = []

    def info(device, timeout=8):
        calls.append(device)
        clock.now += 0.5
        return None

    def refresh(name):
        clock.now += 7.0
        return "192.0.2.9"

    monkeypatch.setattr(castctl, "_catt_info", info)
    monkeypatch.setattr(backend, "refreshed_route", refresh)
    assert backend.info("TV", timeout=8) is None
    assert calls == ["TV"]
