"""A failed name-based status read retries once via a verified receiver address."""
import castctl

OK = {"player_state": "PLAYING"}


def _backend(monkeypatch, ads=()):
    backend = castctl.CattBackend()
    backend._advertisements = tuple(ads)
    monkeypatch.setattr(castctl, "_backend", backend)
    monkeypatch.setattr(castctl, "log_backend_failure", lambda *a, **k: None)
    castctl._info_failures.clear()
    return backend


def test_retries_once_through_the_verified_address(monkeypatch):
    backend = _backend(monkeypatch)
    calls = []

    def fake_info(device, timeout=8):
        calls.append(device)
        return OK if device == "192.0.2.9" else None

    monkeypatch.setattr(castctl, "_catt_info", fake_info)
    monkeypatch.setattr(backend, "refreshed_route", lambda name: "192.0.2.9")
    assert backend.info("TV") == OK
    assert calls == ["TV", "192.0.2.9"]


def test_no_verified_route_means_no_second_attempt(monkeypatch):
    backend = _backend(monkeypatch)
    calls = []
    monkeypatch.setattr(castctl, "_catt_info", lambda d, timeout=8: calls.append(d))
    monkeypatch.setattr(backend, "refreshed_route", lambda name: name)
    assert backend.info("TV") is None
    assert calls == ["TV"]


def test_success_never_rediscovers(monkeypatch):
    backend = _backend(monkeypatch)
    monkeypatch.setattr(castctl, "_catt_info", lambda d, timeout=8: OK)

    def boom(name):
        raise AssertionError("must not rediscover after success")

    monkeypatch.setattr(backend, "refreshed_route", boom)
    assert backend.info("TV") == OK


def test_rediscovery_is_throttled_and_survives_scan_failure(monkeypatch):
    backend = _backend(monkeypatch)
    scans = []

    def failing_scan(timeout):
        scans.append(timeout)
        raise OSError("no multicast")

    monkeypatch.setattr(castctl, "_passive_cast_scan", failing_scan)
    assert backend.refreshed_route("TV") == "TV"
    assert backend.refreshed_route("TV") == "TV"
    assert len(scans) == 1
