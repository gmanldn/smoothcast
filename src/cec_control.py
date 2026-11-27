"""HDMI-CEC wake/input wrapper (#384). Never required; invisible when ``cec-client`` is absent.

Only allow-listed commands reach the subprocess (no shell, stdin carries one CEC command, hard 3 s timeout).
Callers run it off the GTK thread; ``wake_for_cast`` is idempotent and logs a TV that ignores CEC once.
"""
from __future__ import annotations

import re
import shutil
import subprocess

TIMEOUT_S = 3.0
ALLOWED = {"on": re.compile(r"on (?:[0-9]|1[0-5])"), "standby": re.compile(r"standby (?:[0-9]|1[0-5])"),
           "as": re.compile(r"as"), "pow": re.compile(r"pow (?:[0-9]|1[0-5])")}
_POWER = re.compile(r"power status:\s*(on|standby|in transition[a-z ]*|unknown)", re.I)


def allowed(command: str) -> bool:
    return isinstance(command, str) and any(p.fullmatch(command) for p in ALLOWED.values())


def available(which=shutil.which) -> bool:
    return which("cec-client") is not None


def doctor_line(node: str, ok: bool) -> str:
    return f"HDMI-CEC: available on {node}" if ok else "HDMI-CEC: not available"


def send(command: str, exe: str = "cec-client", run=subprocess.run) -> dict:
    """-> {ok, out, reason}. Rejects anything not allow-listed before spawning."""
    if not allowed(command):
        return {"ok": False, "out": "", "reason": "not_allowed"}
    try:
        p = run([exe, "-s", "-d", "1"], input=command + "\n", capture_output=True, text=True, timeout=TIMEOUT_S, shell=False, check=False)
    except FileNotFoundError:
        return {"ok": False, "out": "", "reason": "absent"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "", "reason": "timeout"}
    except OSError:
        return {"ok": False, "out": "", "reason": "error"}
    out = (p.stdout or "")[:4000]
    if p.returncode != 0 or "can't open" in out.lower() or "failed" in out.lower() and "adapter" in out.lower():
        return {"ok": False, "out": out, "reason": "busy"}
    return {"ok": True, "out": out, "reason": ""}


def power_status(out: str) -> str:
    m = _POWER.search(out or "")
    return m.group(1).lower().split()[0] if m else "unknown"


class Waker:
    """Wake the TV once per cast; remember a TV that ignores CEC so the log isn't spammed."""

    def __init__(self, send_fn=send, log=None) -> None:
        self.send, self.log, self.ignored = send_fn, log or (lambda m: None), set()

    def wake_for_cast(self, room: str, tv_state: str, has_cec_node: bool, address: int = 0) -> dict:
        if not has_cec_node:
            return {"acted": False, "why": "no_cec_node"}
        if tv_state == "on":
            return {"acted": False, "why": "already_on"}      # Cast launch handles inputs on awake TVs
        if room in self.ignored:
            return {"acted": False, "why": "ignored"}
        r1 = self.send(f"on {address}")
        r2 = self.send("as") if r1["ok"] else r1
        if not (r1["ok"] and r2["ok"]):
            if r1["reason"] in ("absent", "busy", "timeout"):
                return {"acted": False, "why": r1["reason"]}  # transient/absent: no user-facing error
            return {"acted": False, "why": r1["reason"]}
        st = power_status(r1["out"])
        if st in ("standby",):
            self.ignored.add(room)
            self.log(f"CEC: TV in {room} ignored the wake request")   # logged once, never shown to the user
            return {"acted": True, "why": "ignored_by_tv"}
        return {"acted": True, "why": "woken"}
