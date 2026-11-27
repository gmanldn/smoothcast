import threading
import time

import supervisor as sv


class Fake:
    def __init__(self, healthy=True, start_error=None, hang=False):
        self.ok, self.start_error, self.hang = healthy, start_error, hang
        self.starts = self.stops = 0
        self.release = threading.Event()

    def start(self):
        self.starts += 1
        if self.start_error:
            raise self.start_error

    def healthy(self):
        return self.ok

    def stop(self):
        self.stops += 1
        if self.hang:
            self.release.wait(5)


def test_start_and_clean_stop():
    s = sv.Supervisor()
    s.add("portal", Fake())
    assert s.start("portal") == sv.RUNNING
    assert s.stop("portal") == sv.STOPPED


def test_hung_stop_is_abandoned_within_the_hard_deadline():
    fake = Fake(hang=True)
    s = sv.Supervisor()
    s.add("portal", fake, hard=0.2)
    s.start("portal")
    began = time.monotonic()
    assert s.stop("portal") == sv.STUCK
    assert time.monotonic() - began < 1.0
    fake.release.set()


def test_unhealthy_service_restarts_after_backoff():
    now = [0.0]
    fake = Fake(healthy=False)
    s = sv.Supervisor(clock=lambda: now[0])
    s.add("mesh", fake)
    s.start("mesh")
    assert s.tick()["mesh"] == sv.FAILED
    assert fake.starts == 1
    s.tick()
    assert fake.starts == 1            # backoff not elapsed
    now[0] = 5.0
    s.tick()
    assert fake.starts == 2            # restarted


def test_start_failure_is_contained_and_restarts_are_capped():
    now = [0.0]
    fake = Fake(start_error=OSError("port busy"))
    s = sv.Supervisor(clock=lambda: now[0])
    s.add("portal", fake, max_restarts=2)
    assert s.start("portal") == sv.FAILED
    for t in (10, 100, 1000, 10000):
        now[0] = t
        s.tick()
    assert fake.starts == 3            # first start + 2 restarts, then it stops trying
