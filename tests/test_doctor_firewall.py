import doctor
import doctor_firewall as fw


def fake(table):
    return lambda cmd: table.get(cmd[0], (127, ""))


def test_ufw_inactive_passes():
    assert fw.firewall(fake({"ufw": (0, "Status: inactive")}), "linux").status == doctor.PASS


def test_ufw_active_warns_with_a_fix():
    r = fw.firewall(fake({"ufw": (0, "Status: active")}), "linux")
    assert r.status == doctor.WARN and "ufw allow" in r.fix


def test_firewalld_running_warns_and_stopped_passes():
    assert fw.firewall(fake({"firewall-cmd": (0, "running\n")}), "linux").status == doctor.WARN
    assert fw.firewall(fake({"firewall-cmd": (0, "not running\n")}), "linux").status == doctor.PASS


def test_unknown_state_is_warn_not_pass_or_fail():
    assert fw.firewall(fake({}), "linux").status == doctor.WARN


def test_other_platforms_are_warn_with_manual_guidance():
    r = fw.firewall(fake({}), "win32")
    assert r.status == doctor.WARN and "win32" in r.detail


def test_doctor_main_runs_the_firewall_check(monkeypatch, capsys):
    import json
    import doctor
    import doctor_firewall
    monkeypatch.setattr(doctor_firewall, "firewall",
                        lambda: doctor.Result("firewall", doctor.PASS, "stub"))
    doctor.main(["--json"])
    names = [c["name"] for c in json.loads(capsys.readouterr().out)["checks"]]
    assert "firewall" in names
