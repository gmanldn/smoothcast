import socket

import doctor
import doctor_ssdp


class FakeSock:
    def __init__(self, replies=0, send_error=None):
        self.replies, self.send_error, self.sent = replies, send_error, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def setsockopt(self, *a):
        pass

    def settimeout(self, t):
        pass

    def sendto(self, data, addr):
        if self.send_error:
            raise self.send_error
        self.sent.append(addr)

    def recvfrom(self, n):
        if self.replies:
            self.replies -= 1
            return b"HTTP/1.1 200 OK", ("192.168.1.9", 1900)
        raise socket.timeout


def run(sock):
    return doctor_ssdp.ssdp(lambda *a: sock, wait=1.0, clock=_clock())


def _clock():
    t = [0.0]

    def now():
        t[0] += 0.1
        return t[0]
    return now


def test_reply_passes_and_probe_goes_to_the_group():
    s = FakeSock(replies=2)
    r = run(s)
    assert r.status == doctor.PASS and "2" in r.detail
    assert s.sent == [doctor_ssdp.GROUP]


def test_silence_warns_with_a_fix():
    r = run(FakeSock())
    assert r.status == doctor.WARN and r.fix


def test_send_failure_warns_never_crashes():
    r = run(FakeSock(send_error=OSError("net unreachable")))
    assert r.status == doctor.WARN and "OSError" in r.detail
