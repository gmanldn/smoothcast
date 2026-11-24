"""GTK-free demo runtime: private profile + generated media + loopback fake receiver (#454/#523).

Composes :mod:`demo_session` (isolated HOME/XDG profile), ``scripts/demo_media``
(ffmpeg-generated samples, no binaries in the repo) and ``fakecast``'s
in-process receiver. It never imports GTK, never performs network discovery
and never sends a command to a real device: the only receiver is bound to
127.0.0.1 and is not advertised on the LAN.

The ``--demo`` launcher is still disabled; it may only be enabled once the
application's real discovery paths honour :data:`DEMO_ENV` (see #523).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import secrets
from typing import Callable, Iterator

from demo_session import DemoSession, isolated_demo_profile

DEMO_ENV = "SMOOTHCAST_DEMO"
DEMO_DEVICE_NAME = "SmoothCast Demo TV"
_ROOT = Path(__file__).resolve().parents[1]


def load_media_generator():
    """Load scripts/demo_media.py (a script, not an importable package)."""
    spec = importlib.util.spec_from_file_location("demo_media", _ROOT / "scripts" / "demo_media.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("demo media generator is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class DemoRuntime:
    session: DemoSession
    host: str
    port: int
    media: tuple[Path, ...]
    token: str = ""

    def environment(self) -> dict[str, str]:
        """Profile environment plus the marker and capability token demo_mode checks."""
        return {**self.session.environment(), DEMO_ENV: "1", "SMOOTHCAST_DEMO_TOKEN": self.token}


def _register_target(session: DemoSession, host: str, port: int) -> None:
    """Point the disposable profile at the fake receiver and its media folder."""
    path = session.config_file
    config = json.loads(path.read_text(encoding="utf-8"))
    config["device"] = DEMO_DEVICE_NAME
    config["cast_targets"] = [{"name": DEMO_DEVICE_NAME, "host": host, "port": port}]
    config["library_folders"] = [str(session.media_dir)]
    path.write_text(json.dumps(config, sort_keys=True) + "\n", encoding="utf-8")


@contextmanager
def demo_runtime(parent: Path | None = None, *, run: Callable[..., object] | None = None,
                 receiver_factory=None) -> Iterator[DemoRuntime]:
    """Prepare everything a demo needs; tear it all down, including on errors."""
    with isolated_demo_profile(parent) as session:
        generator = load_media_generator()
        media = generator.make_demo_media(session.media_dir, *( [run] if run else [] ))
        if receiver_factory is None:
            from fakecast.receiver import FakeCastReceiver
            receiver_factory = FakeCastReceiver
        receiver = receiver_factory("127.0.0.1", 0, advertise=False)
        receiver.start()
        try:
            if receiver.host != "127.0.0.1":
                raise RuntimeError("demo receiver must be loopback-only")
            _register_target(session, receiver.host, receiver.port)
            token = secrets.token_hex(32)
            fd = os.open(session.runtime_dir / ".smoothcast-demo-token",
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as marker:
                marker.write(token)
            yield DemoRuntime(session, receiver.host, receiver.port, tuple(media), token)
        finally:
            receiver.stop()
