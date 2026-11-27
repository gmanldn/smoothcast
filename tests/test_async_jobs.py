"""P1 #194: bounded headless concurrency and main-context callback contracts."""
from __future__ import annotations

from queue import Empty, Queue
import sys
import threading

import pytest

from async_jobs import UserFacingError, WorkDomains


def fixture(limits=None):
    callbacks = Queue()
    errors = []
    pool = WorkDomains(
        lambda callback: callbacks.put(callback),
        on_error=lambda message, **kwargs: errors.append(message),
        limits=limits or {"media": (1, 1), "status": (1, 2),
                          "transport": (1, 2)},
    )
    return pool, callbacks, errors


def deliver(callbacks, *, timeout=3.0):
    callback = callbacks.get(timeout=timeout)
    assert callback() is False  # one-shot GLib idle
    callbacks.task_done()


def test_media_conversion_cannot_starve_device_status_or_transport():
    pool, callbacks, _ = fixture()
    media_started, release_media = threading.Event(), threading.Event()
    status_done, transport_done = threading.Event(), threading.Event()
    try:
        assert pool.submit(
            lambda: (media_started.set(), release_media.wait(3)),
            domain="media",
        )
        assert media_started.wait(2), "media worker never started"
        assert pool.submit(lambda: status_done.set(), domain="status")
        assert pool.submit(lambda: transport_done.set(), domain="transport")
        assert status_done.wait(2), "status was stuck behind media preparation"
        assert transport_done.wait(2), "transport was stuck behind media preparation"
        assert not release_media.is_set()
    finally:
        release_media.set()
        pool.shutdown()


def test_queue_capacity_is_bounded_and_rejected_task_gets_failure_callback():
    pool, callbacks, errors = fixture()
    running, release = threading.Event(), threading.Event()
    seen = []
    try:
        assert pool.submit(
            lambda: (running.set(), release.wait(3)), domain="media",
        )
        assert running.wait(2)
        assert pool.submit(lambda: seen.append("queued"), domain="media")
        assert pool.submit(
            lambda: seen.append("overflow"), domain="media",
            failed=lambda message: seen.append(message),
        ) is False
        deliver(callbacks)
        assert seen == ["Media work queue is busy; retry shortly"]
        assert len(pool._workers["media"]) == 1
        assert errors and "queue is busy" in errors[0]
    finally:
        release.set()
        pool.shutdown()


def test_callbacks_are_dispatched_not_called_on_workers():
    """INV-007: Blocking I/O callbacks must be delivered on the main context."""
    pool, callbacks, _ = fixture()
    submitted_from = threading.get_ident()
    seen = []
    try:
        def work():
            seen.append(("work", threading.get_ident()))
            return "done"
        assert pool.submit(
            work, done=lambda result: seen.append(("callback", threading.get_ident(), result)),
            domain="status",
        )
        deliver(callbacks)
        assert seen[0][0] == "work" and seen[0][1] != submitted_from
        assert seen[1] == ("callback", submitted_from, "done")
    finally:
        pool.shutdown()


def test_stale_owner_validation_occurs_on_main_context_and_drops_reply():
    pool, callbacks, _ = fixture()
    selected = {"generation": 1}
    seen = []
    try:
        assert pool.submit(
            lambda: 42,
            domain="transport",
            done=seen.append,
            valid=lambda: selected["generation"] == 1,
        )
        callback = callbacks.get(timeout=3)
        selected["generation"] = 2
        assert callback() is False
        assert seen == []
        callbacks.task_done()
    finally:
        pool.shutdown()


def test_failure_is_reported_without_exposing_the_exception():
    callbacks = Queue()
    details = []
    pool = WorkDomains(
        callbacks.put,
        on_error=lambda _message, *, exc_info: details.append(sys.exc_info()[1] if exc_info else None),
    )
    seen = []
    try:
        def fail():
            raise OSError("Could not open /private/media/film.mkv")
        assert pool.submit(fail, failed=seen.append, domain="transport")
        deliver(callbacks)
        assert seen == ["Check that the receiver is connected, then try again."]
        assert len(details) == 1 and "/private/media/film.mkv" in str(details[0])
        assert pool.submit(lambda: "recovered", done=seen.append, domain="transport")
        deliver(callbacks)
        assert seen[-1] == "recovered"
    finally:
        pool.shutdown()


@pytest.mark.parametrize("wrapped", [False, True])
def test_expected_failure_preserves_only_reviewed_copy(wrapped):
    pool, callbacks, _errors = fixture()
    shown = "The selected subtitle track is unavailable. Choose another track."
    seen = []
    try:
        def fail():
            problem = UserFacingError(shown, detail="/private/media/film.mkv")
            if wrapped:
                raise RuntimeError("Raw wrapper output") from problem
            raise problem

        assert pool.submit(fail, failed=seen.append, domain="media")
        deliver(callbacks)
        assert seen == [shown]
    finally:
        pool.shutdown()


def test_shutdown_discards_pending_jobs_and_already_scheduled_callbacks():
    pool, callbacks, _ = fixture()
    started, release = threading.Event(), threading.Event()
    ran = []
    try:
        assert pool.submit(
            lambda: (started.set(), release.wait(3)), done=lambda _: ran.append("active"),
            domain="media",
        )
        assert started.wait(2)
        assert pool.submit(lambda: ran.append("pending"), domain="media")
        pool.shutdown()
        release.set()
        assert pool.submit(lambda: ran.append("late"), domain="media") is False
        pool._workers["media"][0].join(timeout=2)
        assert not pool._workers["media"][0].is_alive()
        while True:
            try:
                callback = callbacks.get_nowait()
            except Empty:
                break
            assert callback() is False
            callbacks.task_done()
        assert not ran
    finally:
        release.set()
        pool.shutdown()


def test_invalid_domains_and_limits_fail_early():
    with pytest.raises(ValueError, match="workers"):
        WorkDomains(lambda cb: cb(), limits={"media": (2, 1)})
    pool, callbacks, _ = fixture()
    try:
        with pytest.raises(ValueError, match="Unknown Async"):
            pool.submit(lambda: None, domain="unknown")
    finally:
        pool.shutdown()


def test_work_domains_are_inherited_by_real_gui_adapter_without_importing_gtk():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    widget_source = (root / "src" / "cast_widgets.py").read_text("utf-8")
    queue_source = "".join((root / "src" / name).read_text("utf-8")
                           for name in ("cast_queue.py", "cast_discovery.py"))
    session_source = (root / "src" / "cast_session.py").read_text("utf-8")
    assert "async_jobs.WorkDomains(" in widget_source
    assert "GLib.idle_add, on_error=error_log.log" in widget_source
    for domain in ("discovery", "status", "media"):
        assert f'domain="{domain}"' in queue_source
    for domain in ("transport", "status", "media", "cast_start"):
        assert f'domain="{domain}"' in session_source



def test_cast_start_does_not_wait_behind_saturated_media_workers():
    from async_jobs import DEFAULT_LIMITS

    pool = WorkDomains(lambda callback: callback())
    release = threading.Event()
    started = [threading.Event() for _ in range(DEFAULT_LIMITS["media"][0])]
    cast_started = threading.Event()
    try:
        for event in started:
            assert pool.submit(lambda e=event: (e.set(), release.wait(5)),
                               domain="media")
        assert all(event.wait(2) for event in started)
        for _ in range(DEFAULT_LIMITS["media"][1]):
            assert pool.submit(lambda: release.wait(5), domain="media")
        assert pool.submit(cast_started.set, domain="cast_start")
        assert cast_started.wait(2), "Play Now queued behind background media"
        assert not release.is_set()
    finally:
        release.set()
        pool.shutdown()


def test_thread_inventory_reports_live_threads_and_drops_finished_threads():
    from async_jobs import thread_inventory
    started, release = threading.Event(), threading.Event()

    def work():
        started.set()
        release.wait(3)

    thread = threading.Thread(target=work, name="sc-inventory-test", daemon=True)
    thread.start()
    try:
        assert started.wait(2)
        rows = thread_inventory()
        assert any("sc-inventory-test" in row and "daemon" in row and "alive" in row
                   for row in rows)
        assert any(" · main · alive" in row for row in rows)
    finally:
        release.set()
        thread.join(timeout=3)
    assert not any("sc-inventory-test" in row for row in thread_inventory())
