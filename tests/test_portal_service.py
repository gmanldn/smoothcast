import portal_service
import supervisor


class FakePortal:
    def __init__(self, alive=True):
        self.thread = type("T", (), {"is_alive": lambda s: alive})()
        self.stopped = 0

    def stop(self):
        self.stopped += 1


def test_start_health_stop_lifecycle_under_the_supervisor():
    made = []
    svc = portal_service.PortalService(lambda: made.append(FakePortal()) or made[-1])
    sup = supervisor.Supervisor()
    sup.add("portal", svc)
    assert sup.start("portal") == "running" and svc.healthy()
    sup.stop_all()
    assert made[0].stopped == 1 and not svc.healthy()


def test_dead_server_thread_is_unhealthy():
    svc = portal_service.PortalService(lambda: FakePortal(alive=False))
    svc.start()
    assert not svc.healthy()


def test_start_failure_is_contained_by_the_supervisor():
    def boom():
        raise OSError("bind failed")
    sup = supervisor.Supervisor()
    sup.add("portal", portal_service.PortalService(boom))
    assert sup.start("portal") == "failed"
