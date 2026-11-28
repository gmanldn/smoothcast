"""Sandbox port (ARCH-15, #703): wrap a worker command so it can touch only what it is given.

Pure: ``which`` and the platform are injected, nothing is spawned. ``wrap`` returns the
final argv. ``select`` picks the first usable backend and records a visible reason for
each one skipped; with none usable the caller must decide to refuse, never to run
unconfined without saying so. Windows job objects need a launcher, not an argv prefix,
so that backend reports itself unavailable instead of pretending.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Policy:
    read: tuple[str, ...] = ()      # paths the worker may read
    write: tuple[str, ...] = ()     # paths it may write
    network: bool = False


@dataclass
class Bubblewrap:
    which: Callable[[str], str | None] = lambda _n: None
    platform: str = sys.platform
    name: str = "bubblewrap"

    def available(self):
        if not self.platform.startswith("linux"):
            return False, f"bubblewrap is Linux-only (platform {self.platform})"
        return (True, "bwrap found") if self.which("bwrap") else (False, "bwrap is not installed")

    def wrap(self, argv: list[str], policy: Policy) -> list[str]:
        out = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
               "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/lib", "/lib",
               "--ro-bind-try", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
               "--tmpfs", "/tmp"]
        if policy.network:
            out.append("--share-net")
        for path in policy.read:
            out += ["--ro-bind", path, path]
        for path in policy.write:
            out += ["--bind", path, path]
        return out + ["--", *argv]


@dataclass
class SandboxExec:
    which: Callable[[str], str | None] = lambda _n: None
    platform: str = sys.platform
    name: str = "sandbox-exec"

    def available(self):
        if self.platform != "darwin":
            return False, f"sandbox-exec is macOS-only (platform {self.platform})"
        return (True, "sandbox-exec found") if self.which("sandbox-exec") else (False, "sandbox-exec is not installed")

    def profile(self, policy: Policy) -> str:
        rules = ["(version 1)", "(deny default)", "(allow process-exec)", "(allow sysctl-read)",
                 '(allow file-read* (subpath "/usr") (subpath "/System") (subpath "/Library"))']
        rules += [f'(allow file-read* (subpath "{_q(p)}"))' for p in policy.read]
        rules += [f'(allow file-read* file-write* (subpath "{_q(p)}"))' for p in policy.write]
        if policy.network:
            rules.append("(allow network*)")
        return "\n".join(rules)

    def wrap(self, argv: list[str], policy: Policy) -> list[str]:
        return ["sandbox-exec", "-p", self.profile(policy), *argv]


def _q(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class JobObject:
    platform: str = sys.platform
    name: str = "job-object"

    def available(self):
        if not self.platform.startswith("win"):
            return False, f"job objects are Windows-only (platform {self.platform})"
        return False, "job-object confinement needs a launcher, not implemented"

    def wrap(self, argv: list[str], policy: Policy) -> list[str]:
        raise NotImplementedError("job-object confinement is not implemented")


@dataclass
class Fake:
    name: str = "fake"
    ok: bool = True
    why: str = "fake"

    def available(self):
        return self.ok, self.why

    def wrap(self, argv: list[str], policy: Policy) -> list[str]:
        return ["fake-sandbox", *argv]


@dataclass
class Selection:
    chosen: object | None
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def reason(self) -> str:
        if self.chosen:
            return f"sandboxed with {self.chosen.name}"
        detail = "; ".join(f"{n}: {r}" for n, r in self.skipped) or "no backends"
        return f"NO SANDBOX ({detail})"


def select(ranked: list) -> Selection:
    skipped: list[tuple[str, str]] = []
    for backend in ranked:
        try:
            ok, why = backend.available()
        except Exception as exc:  # noqa: BLE001 - a broken probe must not break launching
            ok, why = False, f"probe failed: {exc}"
        if ok:
            return Selection(backend, skipped)
        skipped.append((backend.name, why))
    return Selection(None, skipped)
