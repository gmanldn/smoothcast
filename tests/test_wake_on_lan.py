import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pytest
import wake_on_lan as w

MAC = "AA:bb:CC:01:02:03"


def test_magic_packet_bytes_exact():
    p = w.magic_packet(MAC)
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:] == bytes([0xaa, 0xbb, 0xcc, 1, 2, 3]) * 16
    assert w.magic_packet("aa-bb-cc-01-02-03") == p
    for bad in ("", "aa:bb", "zz:bb:cc:01:02:03", None, "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        with pytest.raises(ValueError): w.magic_packet(bad)


def test_send_uses_udp9_broadcast_and_closes_socket():
    class S:
        def __init__(self): self.sent, self.closed, self.opt = None, 0, None
        def setsockopt(self, *a): self.opt = a
        def sendto(self, b, addr): self.sent = (b, addr)
        def close(self): self.closed += 1
    s = S(); assert w.send(MAC, "192.168.1.255", lambda: s) and s.sent == (w.magic_packet(MAC), ("192.168.1.255", 9)) and s.closed == 1 and s.opt[-1] == 1
    assert not w.send(MAC, "999.1.1.1", lambda: S()) and not w.send("bad", "10.0.0.255", lambda: S())
    class Boom(S):
        def sendto(self, *a): raise OSError
    b = Boom(); assert not w.send(MAC, "10.0.0.255", lambda: b) and b.closed == 1


def test_wake_flow_times_out_cleanly_with_fake_clock():
    t = [0.0]; k = w.Wake(lambda: t[0]); sent = []
    r = k.start("Bedroom PC", {"mac": MAC, "broadcast": "10.0.0.255"}, ["n1", "n2"], lambda s, m, b: sent.append(s) or True)
    assert r == {"state": "waking", "sent": 2, "message": "Waking Bedroom PC… 0 s"} and sent == ["n1", "n2"]
    t[0] = 12; assert k.poll("Bedroom PC", MAC, False) == {"state": "waking", "message": "Waking Bedroom PC… 12 s"}
    t[0] = 60; assert k.poll("Bedroom PC", MAC, False) == {"state": "timeout", "message": "Bedroom PC is asleep and can't be woken remotely."}
    assert k.poll("Bedroom PC", MAC, False) == {"state": "idle"}


def test_node_reappearing_ends_wake_and_duplicate_requests_are_deduped():
    t = [0.0]; k = w.Wake(lambda: t[0]); sent = []
    f = lambda s, m, b: sent.append(s) or True
    k.start("B", {"mac": MAC, "broadcast": "10.0.0.255"}, ["n1"], f); t[0] = 3
    assert k.start("B", {"mac": MAC, "broadcast": "10.0.0.255"}, ["n1"], f)["sent"] == 0 and sent == ["n1"]
    t[0] = 14; assert k.start("B", {"mac": MAC, "broadcast": "10.0.0.255"}, ["n1"], f)["sent"] == 1
    assert k.poll("B", MAC, True) == {"state": "up", "message": "B is awake."} and k.poll("B", MAC, True)["state"] == "idle"


def test_unavailable_when_no_wol_or_no_sender_or_all_sends_fail():
    k = w.Wake(lambda: 0.0); msg = "Bedroom PC is asleep and can't be woken remotely."
    assert k.start("Bedroom PC", None, ["n"], None) == {"state": "unavailable", "message": msg}
    assert k.start("Bedroom PC", {"mac": "bad", "broadcast": "10.0.0.255"}, ["n"], None)["state"] == "unavailable"
    assert k.start("Bedroom PC", {"mac": MAC, "broadcast": "10.0.0.255"}, [], None)["state"] == "unavailable"
    def bad(*a): raise RuntimeError
    assert k.start("Bedroom PC", {"mac": MAC, "broadcast": "10.0.0.255"}, ["n"], bad)["state"] == "unavailable" and k.started == {}


def test_node_record_only_when_opted_in_and_mac_from_sysfs(tmp_path):
    assert w.SETTING == "Let other computers wake this one"
    assert w.node_record_field(False, MAC, "10.0.0.255") is None and w.node_record_field(True, "x", "10.0.0.255") is None
    assert w.node_record_field(True, MAC, "10.0.0.255") == {"mac": "aa:bb:cc:01:02:03", "broadcast": "10.0.0.255"}
    (tmp_path / "eth0").mkdir(); (tmp_path / "eth0" / "address").write_text("AA:BB:CC:01:02:03\n")
    assert w.read_linux_mac("eth0", str(tmp_path)) == "aa:bb:cc:01:02:03" and w.read_linux_mac("../x", str(tmp_path)) is None and w.read_linux_mac("nope", str(tmp_path)) is None
