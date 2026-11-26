"""Qualify an owner-configured link-acquisition launcher by attacking it (#588).

``CommandProvider`` cannot see an arbitrary launcher's OS policy, so it never
claims isolation. This module *tests* it: the launcher runs a tiny probe that
tries to (1) connect to an IPv4 loopback service, (2) connect to an IPv6
loopback service, (3) connect to a service bound on this computer's private LAN
address, (4) reach the cloud metadata address (169.254.169.254, link-local),
(5) read a canary file in the owner's home directory and (6) leave a detached
child process behind. The evidence is collected host-side (connection counts at
the listeners, the canary's content echoed back, whether the child outlived the
launcher), not trusted from the probe's own report. Only a launcher that denies
every reachable one of these is "verified".

It contacts no external host, downloads nothing and starts no media tool. The
canary is created and removed by this module. GTK-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time

CHECKS = ("probe_ran", "loopback_denied", "ipv6_denied", "private_lan_denied",
          "metadata_denied", "home_denied", "process_tree_terminated")
METADATA_ADDRESS = "169.254.169.254"
CACHE_SCHEMA = 2

_PROBE = r"""
import json, os, socket, subprocess, sys
spec = json.loads(sys.argv[1])
out = {"ran": True}
def reach(host, port):
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:
        return False
out["loopback"] = reach("127.0.0.1", spec["loopback"])
out["loopback6"] = reach("::1", spec["loopback6"]) if spec.get("loopback6") else None
out["lan"] = reach(spec["lan_ip"], spec["lan"]) if spec.get("lan_ip") else None
# Link-local/cloud metadata has no listener we can bind, so a successful
# connection here is itself the evidence; failing to connect passes.
out["metadata"] = reach(spec["metadata"], 80)
try:
    out["home"] = open(spec["canary"], "r").read(64)
except OSError:
    out["home"] = None
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)  # " + spec["tag"]],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
out["child"] = True
print("QUALIFY " + json.dumps(out), flush=True)
"""


@dataclass
class Qualification:
    verified: bool
    checks: dict[str, str] = field(default_factory=dict)
    detail: str = ""

    def as_dict(self) -> dict:
        return {"verified": self.verified, "checks": dict(self.checks), "detail": self.detail}


class _Listener:
    """Counts connection attempts: the host-side proof that egress was (not) denied."""

    def __init__(self, host: str, family: int = socket.AF_INET) -> None:
        self.sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            self.sock.bind((host, 0))
            self.sock.listen(4)
            self.sock.settimeout(0.2)
            self.port = self.sock.getsockname()[1]
            self.count = 0
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        except (OSError, RuntimeError):
            self.sock.close()
            raise

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.count += 1
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(1)
        self.sock.close()


def lan_address() -> str | None:
    """A private IPv4 address of this computer (no packet is sent), or None."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    parts = ip.split(".")
    private = (parts[0] == "10" or (parts[0] == "192" and parts[1] == "168")
               or (parts[0] == "172" and 16 <= int(parts[1]) <= 31))
    return ip if private else None


def _tagged(tag: str) -> list[int]:
    """Live host processes whose command line carries *tag*. Matching by tag, not by
    the PID the probe reports, keeps this correct inside PID namespaces."""
    found: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if tag.encode() not in (entry / "cmdline").read_bytes():
                continue
            if (entry / "stat").read_text().split(")")[-1].split()[0] == "Z":
                continue
        except (OSError, IndexError):
            continue
        found.append(int(entry.name))
    return found


def _complete_report(report: object, *, ipv6: bool, private: bool) -> bool:
    """Absence of a probe observation is not evidence of isolation."""
    if not isinstance(report, dict) or report.get("ran") is not True:
        return False
    if report.get("child") is not True or "home" not in report:
        return False
    if report["home"] is not None and not isinstance(report["home"], str):
        return False
    for key, enabled in (("loopback", True), ("metadata", True),
                         ("loopback6", ipv6), ("lan", private)):
        if key not in report:
            return False
        if enabled and type(report[key]) is not bool:
            return False
        if not enabled and report[key] is not None:
            return False
    return True


def qualify(launcher: str, *, lan_ip: str | None = "auto", timeout: float = 30.0,
            python: str | None = None) -> Qualification:
    """Run the probe through *launcher* (``launcher EXECUTABLE ARGV...``)."""
    path = Path(launcher) if launcher else None
    if path is None or not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        return Qualification(False, {name: "not_run" for name in CHECKS}, "launcher missing or not executable")
    python = python or sys.executable
    loop = loop6 = private = None
    canary = None
    tag = "smoothcast-qualify-" + secrets.token_hex(6)
    secret = secrets.token_hex(16)
    started = False
    try:
        lan = lan_address() if lan_ip == "auto" else lan_ip
        loop = _Listener("127.0.0.1")
        try:
            loop6 = _Listener("::1", socket.AF_INET6)
        except OSError:
            loop6 = None  # no host IPv6 loopback: nothing to reach, count as denied
        private = _Listener(lan) if lan else None
        candidate = Path.home() / f".smoothcast-qualify-{secrets.token_hex(6)}"
        # Reserve a fresh owner-only file; never overwrite a pre-existing path.
        fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        canary = candidate
        with os.fdopen(fd, "w") as handle:
            handle.write(secret)
        spec = {"loopback": loop.port, "loopback6": loop6.port if loop6 else 0,
                "lan": private.port if private else 0, "metadata": METADATA_ADDRESS,
                "lan_ip": lan, "canary": str(canary), "tag": tag}
        with tempfile.TemporaryDirectory(prefix="smoothcast-qualify-") as staging:
            try:
                started = True
                done = subprocess.run([str(path), python, "-c", _PROBE, json.dumps(spec)],
                                      cwd=staging, stdin=subprocess.DEVNULL, capture_output=True,
                                      text=True, timeout=timeout, env={"PATH": os.environ.get("PATH", "")})
            except subprocess.TimeoutExpired:
                return Qualification(False, {n: "not_run" for n in CHECKS}, "probe timed out")
            except OSError as exc:
                return Qualification(False, {n: "not_run" for n in CHECKS}, f"launcher failed to start: {exc}")
        report = None
        for line in done.stdout.splitlines():
            if line.startswith("QUALIFY "):
                try:
                    report = json.loads(line[8:])
                except ValueError:
                    report = None
        if done.returncode != 0 or not _complete_report(
                report, ipv6=loop6 is not None, private=private is not None):
            return Qualification(False, {n: "not_run" for n in CHECKS},
                                 f"launcher did not run the probe successfully (exit {done.returncode}); "
                                 "complete qualification evidence required")
        time.sleep(0.4)  # let a well-behaved launcher finish tearing the tree down
        checks = {"probe_ran": "pass"}
        checks["loopback_denied"] = "pass" if loop.count == 0 and not report.get("loopback") else "FAIL"
        # No host IPv6 loopback means no IPv6 service to reach: treat as denied.
        checks["ipv6_denied"] = ("pass" if loop6 is None
                                 else "pass" if loop6.count == 0 and not report.get("loopback6") else "FAIL")
        if private is None:
            checks["private_lan_denied"] = "skipped"
        else:
            checks["private_lan_denied"] = "pass" if private.count == 0 and not report.get("lan") else "FAIL"
        # The cloud metadata address (link-local) has no listener we can bind, so
        # reaching it at all is the evidence; failing to connect passes.
        checks["metadata_denied"] = "FAIL" if report.get("metadata") else "pass"
        checks["home_denied"] = "FAIL" if report.get("home") == secret[:64] else "pass"
        # Without a host process inventory, absence of a detected descendant
        # is not evidence that the descendant was terminated.
        checks["process_tree_terminated"] = (
            "FAIL" if _tagged(tag) else "pass" if Path("/proc").is_dir() else "skipped"
        )
        verified = all(value == "pass" for value in checks.values())
        failed = [name for name, value in checks.items() if value == "FAIL"]
        detail = ("isolation verified" if verified else
                  "NOT isolated: " + ", ".join(failed) if failed else
                  "not fully verified: " + ", ".join(n for n, v in checks.items() if v != "pass"))
        return Qualification(verified, checks, detail)
    except (OSError, RuntimeError):
        return Qualification(False, {n: "not_run" for n in CHECKS},
                             "Could not prepare or inspect local isolation checks.")
    finally:
        try:
            for pid in _tagged(tag) if started else ():
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        except OSError:
            pass
        for listener in (loop, loop6, private):
            if listener is not None:
                try:
                    listener.close()
                except (OSError, RuntimeError):
                    pass
        if canary is not None:
            try:
                canary.unlink()
            except OSError:
                pass


# -- cached result, tied to the exact launcher file ---------------------------------------
def cache_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "cast-control" / "link-qualification.json"


def _identity(launcher: str) -> dict | None:
    # A same-size edit with a preserved mtime must invalidate qualification.
    # Bound the read; a launcher should never require hashing a huge file.
    try:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(launcher, flags), "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 16 << 20:
                return None
            payload = handle.read((16 << 20) + 1)
            after = os.fstat(handle.fileno())
        current = Path(launcher).stat()
        if (len(payload) != before.st_size or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns)):
            return None
    except OSError:
        return None
    return {"path": str(launcher), "size": before.st_size, "mtime_ns": before.st_mtime_ns,
            "sha256": hashlib.sha256(payload).hexdigest()}


def save(launcher: str, result: Qualification) -> bool:
    """Remember a result only for this exact launcher file and content digest."""
    identity = _identity(launcher)
    if identity is None:
        return False
    target = cache_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps({"schema": CACHE_SCHEMA, "launcher": identity, **result.as_dict()},
                                  sort_keys=True))
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def is_verified(launcher: str) -> bool:
    """True only if the saved qualification passed for the *current* launcher file."""
    identity = _identity(launcher) if launcher else None
    if identity is None:
        return False
    try:
        data = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return False
    return (isinstance(data, dict) and data.get("schema") == CACHE_SCHEMA
            and data.get("verified") is True
            and data.get("launcher") == identity
            and isinstance(data.get("checks"), dict)
            and all(data["checks"].get(name) == "pass" for name in CHECKS))
