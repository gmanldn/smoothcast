#!/usr/bin/env python3
"""On-demand, read-only diagnostic for agent sandbox network failures."""
from __future__ import annotations

import os
import subprocess
import sys

HOSTS = ("github.com", "api.github.com", "pypi.org")


def git_failure(code: int, stderr: str, *, missing_ref: bool = True) -> str:
    if code == 0:
        return "ok"
    if code == 124:
        return "timeout"
    if code == 127:
        return "unavailable"
    if code == 2 and missing_ref:
        return "missing-ref"
    message = stderr.lower()
    if any(x in message for x in ("could not resolve", "temporary failure in name resolution", "name or service not known")):
        return "dns"
    if any(x in message for x in ("ssl certificate", "tls", "certificate verification", "host key verification")):
        return "tls-or-host-key"
    if any(x in message for x in ("authentication failed", "permission denied", "could not read username", "403", "401")):
        return "authentication-or-access"
    if "repository not found" in message or "not a git repository" in message:
        return "repository-or-access"
    if any(x in message for x in ("failed to connect", "connection refused", "connection timed out", "network is unreachable")):
        return "transport"
    return "other-git-failure"


REMOTE_OPERATIONS = frozenset({"fetch", "push", "ls-remote"})


def remote_command(args: list[str], *, cwd, timeout: int = 120) -> subprocess.CompletedProcess:
    """Bound native Git transport without allowing interactive prompts.

    A timeout on push is an unknown remote outcome, not proof of failure.
    Return a normal result for the caller's existing receipt reconciliation.
    """
    if not args or args[0] not in REMOTE_OPERATIONS:
        raise ValueError("remote Git operation required")
    command = ["git", *args]
    try:
        return subprocess.run(
            command, cwd=cwd, timeout=timeout, check=False,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            errors="replace",
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", "transport timeout")
    except OSError:
        return subprocess.CompletedProcess(command, 127, "", "native Git unavailable")


def failure_guidance(operation: str, result: subprocess.CompletedProcess) -> str:
    """Return only allowlisted operation/category text; never expose stderr."""
    if operation not in REMOTE_OPERATIONS or not result.returncode:
        raise ValueError("failed remote Git operation required")
    category = git_failure(result.returncode, result.stderr or "",
                           missing_ref=operation == "ls-remote")
    return (f"Native Git {operation} failed ({category}). "
            "Run python3 scripts/agent_network.py once; preserve the worktree "
            "and pending shipment receipt. Do not bypass ship safeguards.")


def probe(args: list[str], timeout: int, *, git: bool = False) -> str:
    try:
        result = subprocess.run(
            args, timeout=timeout, check=False, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors="replace",
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError:
        return "unavailable"
    if git:
        return git_failure(result.returncode, result.stderr)
    return "ok" if result.returncode == 0 else "dns-failed"


def main() -> int:
    for host in HOSTS:
        status = probe([sys.executable, "-c",
                        "import socket,sys; socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)",
                        host], 5)
        print(f"DNS {host}: {status}", flush=True)
    status = probe(["git", "ls-remote", "--exit-code", "origin", "refs/heads/develop"], 15, git=True)
    print(f"Native Git develop: {status}")
    print("GitHub connector: not tested by this terminal; check independently.")
    if status != "ok":
        print("See docs/agents/workflow.md; preserve pending work and do not bypass shipment guards.")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
