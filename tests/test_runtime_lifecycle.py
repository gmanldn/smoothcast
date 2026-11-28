import threading

import task_runtime as tr


def test_scope_wait_is_clamped_to_remaining_deadline(monkeypatch):
    now = [10.0]
    scope = tr.Scope(deadline=0.25, clock=lambda: now[0])
    waits = []

    def wait(timeout):
        waits.append(timeout)
        now[0] += timeout
        return False

    monkeypatch.setattr(scope._cancel, 'wait', wait)
    assert scope.wait(5.0) is True
    assert waits == [0.25]
    assert scope.wait(5.0) is True
    assert waits == [0.25]


def test_delayed_dispatch_is_fenced_after_cancellation():
    dispatched, results = [], []
    rt = tr.Runtime(deliver=dispatched.append)
    try:
        scope = rt.scope()
        rt.submit('network', scope, lambda s: 42, lambda r, e: results.append(r)).result(2)
        assert len(dispatched) == 1
        scope.cancel()
        dispatched.pop()()
        assert results == []
    finally:
        rt.shutdown()


def test_cancelled_running_work_cannot_deliver_success():
    rt = tr.Runtime()
    entered, release = threading.Event(), threading.Event()
    results = []
    scope = rt.scope()

    def work(_scope):
        entered.set()
        release.wait(2)
        return 42

    try:
        future = rt.submit('network', scope, work, lambda r, e: results.append(r))
        assert entered.wait(1)
        scope.cancel()
        release.set()
        future.result(2)
        assert results == []
    finally:
        release.set()
        rt.shutdown()


def test_external_scope_is_cancelled_when_runtime_shuts_down():
    rt = tr.Runtime()
    scope = tr.Scope()
    dispatched = []
    rt._deliver = dispatched.append
    rt.submit('network', scope, lambda s: 42, lambda r, e: None).result(2)
    assert rt.shutdown()
    assert scope.cancelled
    assert rt.scope().cancelled
