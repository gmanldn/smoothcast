import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import doctor


def test_python_ffmpeg_and_filters():
    assert doctor.python_version((3, 9, 1)).status == "fail"
    assert doctor.python_version((3, 12, 0)).status == "pass"
    assert doctor.ffmpeg(lambda t: None).status == "fail"
    assert doctor.ffmpeg(lambda t: "/x", lambda: {"subtitles"}).status == "warn"
    assert doctor.ffmpeg(lambda t: "/x", lambda: set(doctor.REQUIRED_FILTERS)).status == "pass"
    assert doctor.ffmpeg(lambda t: "/x").status == "warn"


def test_receiver_disk_tmp_listener_clock():
    def refuse(addr, timeout):
        raise ConnectionRefusedError
    assert doctor.receiver("tv", connect=refuse).status == "fail"
    ok = SimpleNamespace(close=lambda: None)
    assert doctor.receiver("tv", connect=lambda a, t: ok).status == "pass"
    assert doctor.disk_space("/", lambda p: SimpleNamespace(free=10)).status == "warn"
    assert doctor.disk_space("/", lambda p: SimpleNamespace(free=10 * 1024 ** 3)).status == "pass"
    def deny(p):
        raise OSError
    assert doctor.disk_space("/", deny).status == "fail"
    assert doctor.temp_writable().status == "pass"
    assert doctor.listener().status == "pass"
    assert doctor.clock(lambda: 5).status == "warn" and doctor.clock().status == "pass"


def test_run_survives_a_crashing_check_and_reports_json_and_exit_code():
    def boom():
        raise RuntimeError("x")
    results = doctor.run([doctor.clock, boom])
    assert results[1].status == "fail" and "RuntimeError" in results[1].detail
    data = json.loads(doctor.to_json(results))
    assert data["status"] == "fail" and len(data["checks"]) == 2
    assert doctor.exit_code(results) == 2 and doctor.exit_code(results[:1]) == 0


def test_vpn_route_warns_only_for_tunnel_interfaces():
    import doctor_vpn

    assert doctor_vpn.vpn_route("wg0").status == doctor_vpn.WARN
    assert "LAN" in doctor_vpn.vpn_route("tun0").fix
    assert doctor_vpn.vpn_route("eth0").status == doctor_vpn.PASS
    assert doctor_vpn.vpn_route(None).status == doctor_vpn.PASS
