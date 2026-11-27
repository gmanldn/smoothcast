"""Firewall heuristic for ``doctor`` (#211 slice). Read-only; never changes rules.

Linux: ufw / firewalld state via injected command runner. Other platforms report
WARN with what to check by hand. A failed or unprivileged probe is WARN, not FAIL:
we can't know, and must not claim a firewall is fine or broken when unverified.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Callable

from doctor import PASS, WARN, Result

PORT_HINT = "the SmoothCast portal and HLS ports (shown in Preferences)"


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def firewall(run: Callable[[list[str]], tuple[int, str]] = _run, platform: str = sys.platform) -> Result:
    name = "firewall"
    if not platform.startswith("linux"):
        return Result(name, WARN, f"cannot inspect the firewall on {platform}",
                      f"Allow SmoothCast through the OS firewall for {PORT_HINT}.")
    code, out = run(["ufw", "status"])
    if code == 0 and "inactive" in out.lower():
        return Result(name, PASS, "ufw is inactive")
    if code == 0 and "active" in out.lower():
        return Result(name, WARN, "ufw is active and may block TVs from reaching SmoothCast",
                      f"Review: sudo ufw allow from 192.168.0.0/16 to any port <port> (for {PORT_HINT}).")
    code, out = run(["firewall-cmd", "--state"])
    if code == 0 and out.strip() == "running":
        return Result(name, WARN, "firewalld is running and may block TVs from reaching SmoothCast",
                      f"Review firewall-cmd --add-port for {PORT_HINT}.")
    if code == 0:
        return Result(name, PASS, "firewalld is not running")
    return Result(name, WARN, "could not determine firewall state (no ufw/firewalld info or no permission)",
                  "Run: sudo ufw status   or   sudo firewall-cmd --state")
