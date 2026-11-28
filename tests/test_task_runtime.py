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


def test_daemon_loop_is_named_counted_and_stopped_by_shutdown():
    rt = tr.Runtime()
    ticks = []

    def loop(scope):
        while not scope.cancelled:
            ticks.append(1)
            time.sleep(0.005)

    thread = rt.spawn_daemon("heartbeat", rt.scope(), loop)
    assert thread.name == "sc-daemon-heartbeat" and rt.daemon_count == 1
    time.sleep(0.05)
    assert rt.shutdown(budget=1.0) is True
    assert rt.daemon_count == 0 and ticks


def test_daemons_do_not_consume_pool_slots():
    rt = tr.Runtime(limits={"network": 1, "disk": 1, "cpu": 1, "media": 1})
    stop = threading.Event()
    for n in range(5):
        rt.spawn_daemon(f"d{n}", rt.scope(), lambda s: stop.wait(5))
    assert rt.daemon_count == 5
    done = threading.Event()
    rt.submit("network", rt.scope(), lambda s: 1, lambda r, e: done.set())
    assert done.wait(1.0)
    stop.set()
    rt.shutdown(0.5)


def test_hung_daemon_is_reported_by_shutdown_within_budget():
    rt = tr.Runtime()
    stop = threading.Event()
    rt.spawn_daemon("stuck", rt.scope(), lambda s: stop.wait(5))   # ignores cancellation
    began = time.monotonic()
    assert rt.shutdown(budget=0.2) is False
    assert time.monotonic() - began < 1.0
    stop.set()


def test_dying_daemon_is_recorded_and_cancel_is_not_an_error():
    rt = tr.Runtime()

    def boom(scope):
        raise ValueError("lost the socket")

    def polite(scope):
        raise tr.Cancelled()

    rt.spawn_daemon("boom", rt.scope(), boom).join(1)
    rt.spawn_daemon("polite", rt.scope(), polite).join(1)
    assert [(n, type(e).__name__) for n, e in rt.errors] == [("boom", "ValueError")]


def test_spawn_after_shutdown_or_cancel_is_refused():
    rt = tr.Runtime()
    cancelled = rt.scope()
    cancelled.cancel()
    assert rt.spawn_daemon("x", cancelled, lambda s: None) is None
    rt.shutdown(0.1)
    assert rt.spawn_daemon("y", rt.scope(), lambda s: None) is None


def test_scope_wait_wakes_at_once_on_cancel_and_times_out_otherwise():
    scope = tr.Scope()
    assert scope.wait(0.01) is False
    threading.Timer(0.02, scope.cancel).start()
    began = time.monotonic()
    assert scope.wait(5.0) is True and time.monotonic() - began < 1.0


def test_spawn_daemon_honours_an_explicit_thread_name():
    rt = tr.Runtime()
    thread = rt.spawn_daemon("loop", rt.scope(), lambda s: None, thread_name="smoothcast-mesh")
    assert thread.name == "smoothcast-mesh"
    thread.join(1)
