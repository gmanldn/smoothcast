"""Demo runtime: loopback-only receiver, isolated profile, no real device (#454)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import demo_runtime  # noqa: E402


def fake_run(command, **kwargs):
    Path(command[-1]).write_bytes(b"x")
    return subprocess.CompletedProcess(command, 0)


def test_runtime_points_profile_at_loopback_receiver_and_cleans_up(tmp_path):
    with demo_runtime.demo_runtime(tmp_path, run=fake_run) as demo:
        assert demo.host == "127.0.0.1" and demo.port > 0
        cfg = json.loads(demo.session.config_file.read_text())
        assert cfg["device"] == demo_runtime.DEMO_DEVICE_NAME
        assert cfg["cast_targets"] == [{"name": demo_runtime.DEMO_DEVICE_NAME,
                                        "host": "127.0.0.1", "port": demo.port}]
        assert cfg["library_folders"] == [str(demo.session.media_dir)]
        assert cfg["check_release_updates"] is False and cfg["keep_streaming"] is False
        env = demo.environment()
        assert env[demo_runtime.DEMO_ENV] == "1"
        assert all(Path(v).is_relative_to(demo.session.root)
                   for k, v in env.items()
                   if k not in (demo_runtime.DEMO_ENV, "SMOOTHCAST_DEMO_TOKEN"))
        assert {p.suffix for p in demo.media} >= {".mp4", ".mkv", ".srt", ".mp3"}
        assert all(p.is_relative_to(demo.session.media_dir) for p in demo.media)
        root = demo.session.root
        import socket
        socket.create_connection((demo.host, demo.port), timeout=2).close()
    assert not root.exists()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", demo.port), timeout=0.5)


def test_receiver_is_never_advertised_and_non_loopback_is_refused(tmp_path):
    seen = {}

    class Spy:
        def __init__(self, host, port, advertise):
            seen.update(host=host, advertise=advertise)
            self.host, self.port = host, 4242
            self.stopped = False

        def start(self):
            return self

        def stop(self):
            seen["stopped"] = True

    with demo_runtime.demo_runtime(tmp_path, run=fake_run, receiver_factory=Spy):
        pass
    assert seen == {"host": "127.0.0.1", "advertise": False, "stopped": True}

    class Bad(Spy):
        def __init__(self, host, port, advertise):
            super().__init__(host, port, advertise)
            self.host = "0.0.0.0"

    with pytest.raises(RuntimeError, match="loopback"):
        with demo_runtime.demo_runtime(tmp_path, run=fake_run, receiver_factory=Bad):
            pass
    assert seen["stopped"] is True


def test_media_failure_tears_down_profile(tmp_path):
    def boom(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    with pytest.raises(subprocess.CalledProcessError):
        with demo_runtime.demo_runtime(tmp_path, run=boom):
            pass
    assert list(tmp_path.iterdir()) == []
