import threading
import time

import pytest

import task_runtime as tr


def test_result_is_delivered_through_the_dispatcher():
    got, dispatched = [], []
    rt = tr.Runtime(deliver=lambda fn: (dispatched.append(1), fn()))
    scope = rt.scope()
    rt.submit("network", scope, lambda s: 42, lambda r, e: got.append((r, e))).result(2)
    assert got == [(42, None)] and dispatched
    rt.shutdown()


def test_errors_reach_the_owner_not_the_void():
    got = []
    rt = tr.Runtime()
    rt.submit("disk", rt.scope(), lambda s: 1 / 0, lambda r, e: got.append(e)).result(2)
    assert isinstance(got[0], ZeroDivisionError)
    rt.shutdown()


def test_concurrency_is_bounded_per_class():
    rt = tr.Runtime(limits={"network": 2})
    live, peak, lock = [0], [0], threading.Lock()

    def work(_s):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
    scope = rt.scope()
    for f in [rt.submit("network", scope, work) for _ in range(8)]:
        f.result(5)
    assert peak[0] <= 2
    rt.shutdown()


def test_cancelled_scope_skips_pending_work_and_swallows_callbacks():
    got = []
    rt = tr.Runtime(limits={"cpu": 1})
    scope = rt.scope()
    gate = threading.Event()
    rt.submit("cpu", scope, lambda s: gate.wait(2))
    queued = rt.submit("cpu", scope, lambda s: "late", lambda r, e: got.append(r))
    scope.cancel()
    gate.set()
    queued.result(2)
    assert got == []
    rt.shutdown()


def test_deadline_cancels_cooperatively():
    now = [0.0]
    scope = tr.Scope(deadline=1.0, clock=lambda: now[0])
    scope.check()
    now[0] = 2.0
    with pytest.raises(tr.Cancelled):
        scope.check()


def test_shutdown_returns_within_budget_even_with_a_hung_task():
    rt = tr.Runtime()
    release = threading.Event()
    rt.submit("media", rt.scope(), lambda s: release.wait(5))
    began = time.monotonic()
    assert rt.shutdown(budget=0.2) is False
    assert time.monotonic() - began < 1.0
    release.set()
    assert rt.submit("media", rt.scope(), lambda s: 1) is None   # closed
