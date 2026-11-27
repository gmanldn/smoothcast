import subprocess

import castctl


def _run_with(monkeypatch, result=None, exc=None):
    logged = []
    monkeypatch.setattr(castctl, "log_backend_failure", lambda m, **k: logged.append(m))
    castctl._info_failures.clear()

    def fake(args, timeout=10):
        if exc:
            raise exc
        return result

    monkeypatch.setattr(castctl, "_run", fake)
    return logged


def test_timeout_reason_recorded_and_logged_once(monkeypatch):
    logged = _run_with(monkeypatch, exc=subprocess.TimeoutExpired("catt", 8))
    assert castctl._catt_info("TV") is None
    assert castctl._catt_info("TV") is None
    assert "timed out" in castctl.last_info_failure("TV")
    assert len(logged) == 1


def test_nonzero_exit_includes_stderr(monkeypatch):
    r = subprocess.CompletedProcess([], 1, "", "Error: Device not found")
    _run_with(monkeypatch, result=r)
    assert castctl._catt_info("TV") is None
    assert "Device not found" in castctl.last_info_failure("TV")


def test_success_clears_reason(monkeypatch):
    _run_with(monkeypatch, exc=OSError("boom"))
    castctl._catt_info("TV")
    assert castctl.last_info_failure("TV")
    monkeypatch.setattr(castctl, "_run", lambda a, timeout=10: subprocess.CompletedProcess([], 0, '{"player_state":"IDLE"}', ""))
    assert castctl._catt_info("TV")
    assert castctl.last_info_failure("TV") == ""


def test_receiver_offline_error_carries_reason(monkeypatch):
    import streamer
    castctl._info_failures.clear()
    castctl._info_failures["TV"] = "status helper timed out after 8s"
    monkeypatch.setattr(castctl, "info", lambda d, timeout=8: None)
    s = streamer.Session.__new__(streamer.Session)
    s.caster = None
    try:
        s._await_receiver("TV", lambda i: False, timeout=0.3, interval=0.05)
    except streamer.StreamPreparationError as exc:
        assert "timed out" in str(getattr(exc, "detail", "")) + str(exc)
    else:
        raise AssertionError("expected failure")
