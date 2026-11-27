"""A failed name-based status read retries once via a verified receiver address."""
import castctl

OK = {"player_state": "PLAYING"}


class NoMirror:
    def info(self, host, timeout):
        return None

    def close(self):
        pass


def _backend(monkeypatch, ads=()):
    backend = castctl.CattBackend()
    backend._advertisements = tuple(ads)
    backend._mirror = NoMirror()
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


def test_failed_catt_read_falls_back_to_the_direct_status_mirror(monkeypatch):
    backend = _backend(monkeypatch)
    seen = []

    class Mirror(NoMirror):
        def info(self, host, timeout):
            seen.append(host)
            return OK

    backend._mirror = Mirror()
    monkeypatch.setattr(castctl, "_catt_info", lambda d, timeout=8: None)
    monkeypatch.setattr(backend, "refreshed_route", lambda name: "192.168.1.20")
    assert backend.info("TV") == OK
    assert seen == ["192.168.1.20"]


def test_mirror_never_used_without_a_verified_private_address(monkeypatch):
    backend = _backend(monkeypatch)

    class Mirror(NoMirror):
        def info(self, host, timeout):
            raise AssertionError("unverified name must not reach the mirror")

    backend._mirror = Mirror()
    monkeypatch.setattr(castctl, "_catt_info", lambda d, timeout=8: None)
    monkeypatch.setattr(backend, "refreshed_route", lambda name: name)
    assert backend.info("TV") is None


class LiveMirror(NoMirror):
    def __init__(self, live=True):
        self.live = live
        self.forgotten = []

    def connected(self, host):
        return self.live

    def info(self, host, timeout):
        return OK if self.live else None

    def forget(self, host):
        self.forgotten.append(host)


def test_proven_direct_connection_answers_before_spawning_catt(monkeypatch):
    backend = _backend(monkeypatch)
    backend._mirror = LiveMirror()
    backend._mirror_routes["TV"] = "192.168.1.20"
    monkeypatch.setattr(castctl, "_catt_info",
                        lambda d, timeout=8: (_ for _ in ()).throw(AssertionError("no catt")))
    assert backend.info("TV") == OK


def test_dropped_direct_connection_falls_back_to_catt_and_is_forgotten(monkeypatch):
    backend = _backend(monkeypatch)
    mirror = backend._mirror = LiveMirror(live=False)
    backend._mirror_routes["TV"] = "192.168.1.20"
    monkeypatch.setattr(castctl, "_catt_info", lambda d, timeout=8: OK)
    assert backend.info("TV") == OK
    assert "TV" not in backend._mirror_routes
    assert mirror.forgotten == ["192.168.1.20"]


def test_successful_fallback_remembers_the_direct_route(monkeypatch):
    backend = _backend(monkeypatch)
    backend._mirror = LiveMirror()
    monkeypatch.setattr(castctl, "_catt_info", lambda d, timeout=8: None)
    monkeypatch.setattr(backend, "refreshed_route", lambda name: "192.168.1.20")
    assert backend.info("TV") == OK
    assert backend._mirror_routes == {"TV": "192.168.1.20"}
