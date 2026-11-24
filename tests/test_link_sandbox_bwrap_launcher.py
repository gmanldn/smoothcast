"""The reference bubblewrap launcher: real isolation, filtered egress, qualifies (#588)."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import link_sandbox_probe as probe
import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "link_sandbox_bwrap.py"
pytestmark = pytest.mark.skipif(not shutil.which("bwrap") or sys.platform != "linux",
                                reason="needs bubblewrap on Linux")

TOOL = r"""
import json, os, socket, sys
out = {"proxy": os.environ.get("HTTPS_PROXY")}
def attempt(host, port):
    try:
        socket.create_connection((host, port), timeout=2).close(); return True
    except OSError:
        return False
out["direct_loopback"] = attempt("127.0.0.1", 22)
out["direct_public"] = attempt("8.8.8.8", 443)
def connect(target):
    try:
        s = socket.create_connection(("127.0.0.1", 3128), timeout=3)
        s.sendall(("CONNECT %s HTTP/1.1\r\nHost: x\r\n\r\n" % target).encode())
        return s.recv(64).split(b"\r\n")[0].decode()
    except OSError as exc:
        return "error:" + type(exc).__name__
out["via_proxy_loopback"] = connect("127.0.0.1:443")
out["via_proxy_metadata"] = connect("169.254.169.254:80")
out["via_proxy_private"] = connect("192.168.0.1:443")
out["via_proxy_ipv6"] = connect("[::1]:443")
out["via_proxy_bad_port"] = connect("example.com:22")
open("result.json", "w").write(json.dumps(out))
open(os.path.expanduser("~/leak"), "w").write("x") if False else None
"""


def run_launcher(tmp_path, tool=TOOL):
    done = subprocess.run([sys.executable, str(LAUNCHER), sys.executable, "-c", tool], cwd=tmp_path,
                          capture_output=True, text=True, timeout=60)
    return done


def available(tmp_path):
    done = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--unshare-net", "true"],
                          capture_output=True, timeout=20)
    if done.returncode:
        pytest.skip("bubblewrap cannot create namespaces here")


def test_tool_has_no_direct_network_and_only_a_filtering_proxy(tmp_path):
    available(tmp_path)
    done = run_launcher(tmp_path)
    assert done.returncode == 0, done.stderr
    got = json.loads((tmp_path / "result.json").read_text())
    assert got["proxy"] == "http://127.0.0.1:3128"
    assert got["direct_loopback"] is False and got["direct_public"] is False
    for key in ("via_proxy_loopback", "via_proxy_metadata", "via_proxy_private", "via_proxy_ipv6"):
        assert "403" in got[key], (key, got[key])
    assert "403" in got["via_proxy_bad_port"]  # port 22 never allowed


def test_home_is_empty_and_only_staging_is_writable(tmp_path):
    available(tmp_path)
    canary = Path.home() / ".smoothcast-bwrap-canary"
    canary.write_text("secret")
    try:
        tool = (r"import os, json; r = {}; "
                r"r['home'] = os.path.exists(os.path.expanduser('~/.smoothcast-bwrap-canary')); "
                r"r['etc'] = os.access('/etc/hostname', os.W_OK) or os.access('/usr', os.W_OK); "
                r"open('r.json','w').write(json.dumps(r))")
        assert run_launcher(tmp_path, tool).returncode == 0
        got = json.loads((tmp_path / "r.json").read_text())
        assert got == {"home": False, "etc": False}
    finally:
        canary.unlink(missing_ok=True)


def test_torrent_engine_is_refused_and_relative_paths_too(tmp_path):
    done = subprocess.run([sys.executable, str(LAUNCHER), "/usr/bin/aria2c", "--version"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert done.returncode == 2 and "BitTorrent" in done.stderr
    done = subprocess.run([sys.executable, str(LAUNCHER), "relative-tool"], cwd=tmp_path,
                          capture_output=True, text=True, timeout=20)
    assert done.returncode == 2


def test_the_reference_launcher_passes_the_qualification_attack_test(tmp_path):
    available(tmp_path)
    wrapper = tmp_path / "launch"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{LAUNCHER}" "$@"\n')
    wrapper.chmod(0o755)
    result = probe.qualify(str(wrapper))
    assert result.checks["probe_ran"] == "pass", result.detail
    assert result.checks["loopback_denied"] == "pass"
    assert result.checks["home_denied"] == "pass"
    assert result.checks["process_tree_terminated"] == "pass"
    assert result.checks["private_lan_denied"] in {"pass", "skipped"}


def test_no_residual_proxy_socket_or_processes_after_a_run(tmp_path):
    available(tmp_path)
    import glob
    before = set(glob.glob("/tmp/smoothcast-egress-*"))
    assert run_launcher(tmp_path, "pass").returncode == 0
    assert set(glob.glob("/tmp/smoothcast-egress-*")) == before
