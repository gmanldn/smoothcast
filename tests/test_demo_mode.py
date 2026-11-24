"""Demo mode is capability-gated and fails closed off loopback (#454/#523)."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import demo_mode  # noqa: E402
import demo_runtime  # noqa: E402


def fake_run(command, **kwargs):
    Path(command[-1]).write_bytes(b"x")
    return subprocess.CompletedProcess(command, 0)


def test_env_flag_alone_does_not_activate(tmp_path):
    assert not demo_mode.active({"SMOOTHCAST_DEMO": "1"})
    assert not demo_mode.active({"SMOOTHCAST_DEMO": "1", "SMOOTHCAST_DEMO_TOKEN": "a" * 64,
                                 "XDG_RUNTIME_DIR": str(tmp_path)})


def test_token_must_match_marker_and_not_be_symlink(tmp_path):
    with demo_runtime.demo_runtime(tmp_path, run=fake_run) as demo:
        env = demo.environment()
        assert demo_mode.active(env)
        assert not demo_mode.active({**env, "SMOOTHCAST_DEMO_TOKEN": "b" * 64})
        assert not demo_mode.active({**env, "SMOOTHCAST_DEMO": "0"})
        marker = demo.session.runtime_dir / demo_mode.MARKER
        real = demo.session.runtime_dir / "real"
        marker.rename(real)
        marker.symlink_to(real)
        assert not demo_mode.active(env)


@pytest.mark.parametrize("host,ok", [("127.0.0.1", True), ("localhost", True), ("::1", True),
                                      ("192.168.1.5", False), ("8.8.8.8", False),
                                      ("239.255.255.250", False), ("tv.local", False), (None, False)])
def test_loopback_classification(host, ok):
    assert demo_mode.is_loopback_host(host) is ok


GUARD_SCRIPT = textwrap.dedent("""
    import socket, sys
    sys.path.insert(0, {src!r})
    import demo_mode
    assert demo_mode.install_network_guard()
    def refused(call):
        try:
            call()
        except demo_mode.DemoModeError:
            return True
        return False
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    assert refused(lambda: s.sendto(b"x", ("239.255.255.250", 1900)))
    assert refused(lambda: s.bind(("0.0.0.0", 0)))
    assert refused(lambda: s.bind(("", 0)))
    t = socket.socket()
    assert refused(lambda: t.connect(("192.168.1.10", 8009)))
    assert refused(lambda: t.connect_ex(("8.8.8.8", 53)))
    assert refused(lambda: socket.create_connection(("192.168.1.10", 80), timeout=0.2))
    assert refused(lambda: socket.getaddrinfo("example.com", 80))
    s.bind(("127.0.0.1", 0))  # loopback still works
    print("GUARD-OK")
""")


def test_network_guard_refuses_everything_but_loopback_in_a_subprocess(tmp_path):
    with demo_runtime.demo_runtime(tmp_path, run=fake_run) as demo:
        env = {**os.environ, **demo.environment()}
        done = subprocess.run([sys.executable, "-I", "-c", GUARD_SCRIPT.format(src=str(ROOT / "src"))],
                              env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0 and "GUARD-OK" in done.stdout, done.stderr


def test_guard_is_a_noop_when_inactive():
    done = subprocess.run([sys.executable, "-I", "-c",
                           f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); import demo_mode;"
                           "print(demo_mode.install_network_guard())"],
                          env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=30)
    assert done.stdout.strip() == "False"


def test_demo_castctl_and_dlna_only_reach_the_loopback_receiver(tmp_path):
    """End to end in a child process: castctl picks the demo backend, dlna finds nothing."""
    pytest.importorskip("pychromecast")
    script = textwrap.dedent(f"""
        import sys
        sys.path[:0] = [{str(ROOT / 'src')!r}, {str(ROOT)!r}]
        import castctl, dlna, demo_runtime
        assert type(castctl._backend).__name__ == "PyChromecastBackend"
        assert dlna.discover() == []
        devices = castctl.scan(timeout=0)
        print([d.name for d in devices])
        castctl._backend.close()
    """)
    with demo_runtime.demo_runtime(tmp_path, run=fake_run) as demo:
        # HOME is the throwaway profile, so user site-packages must be passed explicitly.
        env = {**os.environ, **demo.environment(),
               "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
        done = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                              text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert demo_runtime.DEMO_DEVICE_NAME in done.stdout


DISCOVERY_MODULES = ("castctl", "dlna")


@pytest.mark.parametrize("module", DISCOVERY_MODULES)
def test_every_discovery_entry_point_consults_demo_mode(module):
    tree = ast.parse((ROOT / "src" / f"{module}.py").read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "demo_mode" in names, f"{module} discovery is not demo-gated"


def test_desktop_header_shows_demo_badge_only_under_the_demo_gate():
    source = (ROOT / "src" / "panel_ui.py").read_text()
    tree = ast.parse(source)
    gated = [n for n in ast.walk(tree) if isinstance(n, ast.If)
             and "demo_mode.active()" in ast.get_source_segment(source, n.test)
             and '"DEMO"' in ast.get_source_segment(source, n)]
    assert gated, "the DEMO badge must sit behind demo_mode.active()"
