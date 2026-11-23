"""Fail-closed, side-effect-free Chrome receiver advertisement policy (#565).

This policy does NOT advertise a Cast receiver or establish a distributed lease.
Only a future native integration that proves production authentication and an
exclusive owner lease can provide the corresponding facts.  The default is
therefore never to publish a virtual Google Cast service.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Facts:
    user_enabled: bool = False
    production_auth_verified: bool = False
    native_helper_healthy: bool = False
    listener_bound: bool = False
    private_lan_interface: bool = False
    node_is_advisory_primary: bool = False
    exclusive_lease_verified: bool = False
    output_permitted_and_ready: bool = False
    shutdown_requested: bool = False
    split_brain_suspected: bool = False


@dataclass(frozen=True)
class Readiness:
    may_advertise: bool
    reason: str


# Ordered guards are part of the contract.  Each fact must be a *real* bool;
# neither untrusted mesh data nor Python truthiness can authenticate a sender.
_GUARDS: tuple[tuple[str, bool, str], ...] = (
    ("user_enabled", True, "disabled"),
    ("shutdown_requested", False, "shutting_down"),
    ("production_auth_verified", True, "production_auth_missing"),
    ("native_helper_healthy", True, "helper_unhealthy"),
    ("listener_bound", True, "listener_unbound"),
    ("private_lan_interface", True, "non_lan_interface"),
    ("node_is_advisory_primary", True, "not_primary"),
    ("exclusive_lease_verified", True, "lease_unverified"),
    ("split_brain_suspected", False, "split_brain"),
    ("output_permitted_and_ready", True, "output_unavailable"),
)


def evaluate(facts: Facts) -> Readiness:
    """Evaluate a verified snapshot; no caching, multicast, sockets or mutation.

    For a newly installed app, all fields default to False and advertising is
    disabled.  Even a primary mesh role is not an exclusive receiver lease.
    """
    if not isinstance(facts, Facts):
        return Readiness(False, "invalid_facts")
    for name, expected, reason in _GUARDS:
        value = getattr(facts, name)
        if type(value) is not bool:
            return Readiness(False, "invalid_facts")
        if value is not expected:
            return Readiness(False, reason)
    return Readiness(True, "ready")
