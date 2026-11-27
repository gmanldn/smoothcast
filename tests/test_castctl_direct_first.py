"""A verified receiver address answers over the kept direct connection before
catt is spawned: catt start-up alone can exceed the whole status budget (#686)."""
import castctl

OK = {"player_state": "PLAYING"}


class Mirror:
    def __init__(self, result=OK):
        self.result = result
        self.calls = []

    def info(self, host, timeout):
        self.calls.append((host, timeout))
        return self.result

    def connected(self, host):
        return True

    def forget(self, host):
        pass

    def close(self):
        pass


def _backend(monkeypatch, mirror):
    backend = castctl.CattBackend()
    backend._mirror = mirror
    monkeypatch.setattr(castctl, "log_backend_failure", lambda *a, **k: None)
    castctl._info_failures.clear()
    return backend


def _no_catt(device, timeout=8):
    raise AssertionError("catt must not be spawned when the direct read works")


def test_ip_target_reads_directly_without_catt(monkeypatch):
    mirror = Mirror()
    backend = _backend(monkeypatch, mirror)
    monkeypatch.setattr(castctl, "_catt_info", _no_catt)
    assert backend.info("192.168.0.160", timeout=8) == OK
    host, budget = mirror.calls[0]
    assert host == "192.168.0.160" and budget <= 4.0
    assert backend._mirror_routes == {"192.168.0.160": "192.168.0.160"}


def test_verified_name_reads_directly_and_caches_the_identity_check(monkeypatch):
    mirror = Mirror()
    backend = _backend(monkeypatch, mirror)
    checks = []
    monkeypatch.setattr(backend, "receiver_route",
                        lambda name: checks.append(name) or "192.168.0.160")
    monkeypatch.setattr(castctl, "_catt_info", _no_catt)
    assert backend.info("Living Room TV") == OK
    backend._mirror_routes.clear()  # force the pre-catt path again
    assert backend.info("Living Room TV") == OK
    assert checks == ["Living Room TV"]


def test_failed_direct_read_still_falls_back_to_catt(monkeypatch):
    backend = _backend(monkeypatch, Mirror(result=None))
    calls = []
    monkeypatch.setattr(castctl, "_catt_info",
                        lambda d, timeout=8: calls.append((d, timeout)) or OK)
    assert backend.info("192.168.0.160", timeout=8) == OK
    assert calls and calls[0][1] >= 3.5  # catt keeps the rest of the budget


def test_unverified_name_never_reaches_the_direct_connection(monkeypatch):
    mirror = Mirror()
    backend = _backend(monkeypatch, mirror)
    monkeypatch.setattr(backend, "receiver_route", lambda name: name)
    monkeypatch.setattr(backend, "refreshed_route", lambda name: name)
    monkeypatch.setattr(castctl, "_catt_info", lambda d, timeout=8: OK)
    assert backend.info("TV") == OK
    assert mirror.calls == []
