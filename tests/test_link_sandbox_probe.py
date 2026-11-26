"""The qualifier must catch an unsafe launcher and pass a real isolating one (#588)."""
from __future__ import annotations

from pathlib import Path
import shutil
import stat
import time
import sys

import link_sandbox_probe as probe
import pytest


def script(tmp_path, body, name="launcher"):
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_pass_through_launcher_is_rejected_with_the_failing_checks_named(tmp_path):
    result = probe.qualify(script(tmp_path, 'exec "$@"'))
    assert result.verified is False and result.checks["probe_ran"] == "pass"
    assert result.checks["loopback_denied"] == "FAIL"
    assert result.checks["home_denied"] == "FAIL"
    assert result.checks["process_tree_terminated"] == "FAIL"
    assert result.detail.startswith("NOT isolated:")


def test_launcher_that_never_runs_the_probe_is_not_verified(tmp_path):
    result = probe.qualify(script(tmp_path, "exit 0"))
    assert result.verified is False and set(result.checks.values()) == {"not_run"}
    assert "did not run" in result.detail


@pytest.mark.parametrize("launcher", ["", "relative/launcher", "/does/not/exist"])
def test_missing_or_relative_launcher_is_never_run(launcher):
    result = probe.qualify(launcher)
    assert result.verified is False and set(result.checks.values()) == {"not_run"}


def test_canary_is_removed_even_when_the_probe_leaks_it(tmp_path):
    probe.qualify(script(tmp_path, 'exec "$@"'))
    assert not list(Path.home().glob(".smoothcast-qualify-*"))


def test_leaked_child_process_is_cleaned_up_after_detection(tmp_path):
    result = probe.qualify(script(tmp_path, 'exec "$@"'))
    assert result.checks["process_tree_terminated"] == "FAIL"
    time.sleep(0.1)
    # nothing the probe spawned survives the qualifier
    left = [p for p in Path("/proc").iterdir() if p.name.isdigit()
            and b"time.sleep(60)  # smoothcast-qualify-" in _cmdline(p)
            and b"python" in _cmdline(p).split(b"\0")[0]]
    assert not left


def _cmdline(path):
    try:
        return (path / "cmdline").read_bytes()
    except OSError:
        return b""


@pytest.mark.skipif(not shutil.which("bwrap") or sys.platform != "linux", reason="needs bubblewrap")
def test_real_bubblewrap_launcher_with_no_network_and_a_blank_home_verifies(tmp_path):
    home = str(Path.home())
    launcher = script(tmp_path, f'exec bwrap --ro-bind / / --tmpfs "{home}" --tmpfs /tmp '
                                f'--dev /dev --proc /proc --unshare-net --unshare-pid '
                                f'--die-with-parent "$@"')
    result = probe.qualify(launcher)
    if result.checks.get("probe_ran") != "pass":
        pytest.skip("bubblewrap cannot create namespaces here: " + result.detail)
    assert result.checks["loopback_denied"] == "pass"
    assert result.checks["private_lan_denied"] in {"pass", "skipped"}
    assert result.checks["home_denied"] == "pass"
    assert result.checks["process_tree_terminated"] == "pass"
    assert result.verified is (result.checks["private_lan_denied"] == "pass")


def test_qualification_is_cached_only_for_the_exact_launcher_file(tmp_path):
    launcher = script(tmp_path, 'exec "$@"')
    good = probe.Qualification(True, {n: "pass" for n in probe.CHECKS}, "isolation verified")
    assert probe.save(launcher, good) and probe.is_verified(launcher)
    Path(launcher).write_text("#!/bin/sh\n# edited\nexec \"$@\"\n")  # changed file: trust is void
    assert not probe.is_verified(launcher)
    bad = probe.Qualification(False, {}, "NOT isolated")
    probe.save(launcher, bad)
    assert not probe.is_verified(launcher)
    assert not probe.is_verified("") and not probe.is_verified("/does/not/exist")


def test_provider_reports_verification_and_requires_it(tmp_path, monkeypatch):
    import link_acquisition as links
    launcher = script(tmp_path, 'exec "$@"')
    monkeypatch.setenv("SMOOTHCAST_LINK_SANDBOX", launcher)
    monkeypatch.setattr(links.shutil, "which", lambda name, **k: "/usr/bin/" + name)
    monkeypatch.setattr(links.media_tools, "find_media_tool", lambda name: "/usr/bin/ffprobe")
    provider = links.CommandProvider(("youtube",))
    assert provider.readiness()["youtube"]["isolation_verified"] is False
    assert provider.capabilities()["youtube"] is False  # launcher configured: isolation required
    assert any("qualified isolation" in item for item in provider.readiness()["youtube"]["missing"])
    probe.save(launcher, probe.Qualification(True, {n: "pass" for n in probe.CHECKS}, ""))
    assert provider.readiness()["youtube"]["isolation_verified"] is True
    assert provider.capabilities()["youtube"] is True


def test_link_check_qualify_prints_checks_and_fails_for_an_unsafe_launcher(tmp_path, monkeypatch, capsys):
    import json
    import link_acquisition as links
    monkeypatch.setenv("SMOOTHCAST_LINK_SANDBOX", script(tmp_path, 'exec "$@"'))
    code = links.diagnostics_main(["--tools-only", "--qualify"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1 and report["isolation_verified"] is False
    assert report["isolation_checks"]["loopback_denied"] == "FAIL"
    assert report["isolation_detail"].startswith("NOT isolated")

def test_same_size_and_mtime_launcher_edit_invalidates_qualification(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(probe, "cache_path", lambda: tmp_path / "verdict.json")
    launcher = Path(script(tmp_path, "exit 0"))
    good = probe.Qualification(True, {n: "pass" for n in probe.CHECKS}, "")
    assert probe.save(str(launcher), good)
    before = launcher.stat()
    launcher.write_text(launcher.read_text().replace("exit 0", "exit 1"))
    os.utime(launcher, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert launcher.stat().st_size == before.st_size
    assert not probe.is_verified(str(launcher))


def test_incomplete_cached_evidence_cannot_enable_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "cache_path", lambda: tmp_path / "verdict.json")
    launcher = script(tmp_path, "exit 0")
    checks = {n: "pass" for n in probe.CHECKS if n != "process_tree_terminated"}
    assert probe.save(launcher, probe.Qualification(True, checks, ""))
    assert not probe.is_verified(launcher)



@pytest.mark.parametrize("missing", ["ran", "loopback", "loopback6", "lan",
                                      "metadata", "home", "child"])
def test_incomplete_probe_evidence_is_rejected(missing):
    report = dict(ran=True, loopback=False, loopback6=False, lan=False,
                  metadata=False, home=None, child=True)
    assert probe._complete_report(report, ipv6=True, private=True)
    del report[missing]
    assert not probe._complete_report(report, ipv6=True, private=True)


@pytest.mark.parametrize("key,value", [("loopback", 0), ("metadata", "false"),
                                      ("child", False), ("home", []), ("lan", None)])
def test_malformed_probe_evidence_is_rejected(key, value):
    report = dict(ran=True, loopback=False, loopback6=False, lan=False,
                  metadata=False, home=None, child=True)
    report[key] = value
    assert not probe._complete_report(report, ipv6=True, private=True)


def test_incomplete_launcher_report_never_qualifies(tmp_path):
    launcher = script(tmp_path, """printf '%s\\n' 'QUALIFY {"ran":true}'""")
    result = probe.qualify(launcher, lan_ip=None)
    assert not result.verified and set(result.checks.values()) == {"not_run"}


def test_nonzero_launcher_exit_never_qualifies(tmp_path):
    launcher = script(tmp_path, """printf '%s\\n' 'QUALIFY {"ran":true,"loopback":false,"loopback6":null,"lan":null,"metadata":false,"home":null,"child":true}'
exit 1""")
    result = probe.qualify(launcher, lan_ip=None)
    assert not result.verified and set(result.checks.values()) == {"not_run"}


def test_old_cache_schema_requires_requalification(tmp_path, monkeypatch):
    import json
    target = tmp_path / "verdict.json"
    monkeypatch.setattr(probe, "cache_path", lambda: target)
    launcher = script(tmp_path, "exit 0")
    good = probe.Qualification(True, {n: "pass" for n in probe.CHECKS}, "")
    assert probe.save(launcher, good) and probe.is_verified(launcher)
    data = json.loads(target.read_text())
    del data["schema"]
    target.write_text(json.dumps(data))
    assert not probe.is_verified(launcher)
