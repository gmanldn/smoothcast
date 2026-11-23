"""Headless acceptance for fail-closed Chrome receiver readiness (#565)."""
from __future__ import annotations

from dataclasses import replace
import ast
import importlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chrome_mesh_readiness import Facts, Readiness, evaluate


READY = Facts(
    user_enabled=True, production_auth_verified=True,
    native_helper_healthy=True, listener_bound=True,
    private_lan_interface=True, node_is_advisory_primary=True,
    exclusive_lease_verified=True, output_permitted_and_ready=True,
    shutdown_requested=False, split_brain_suspected=False,
)


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("user_enabled", False, "disabled"),
    ("shutdown_requested", True, "shutting_down"),
    ("production_auth_verified", False, "production_auth_missing"),
    ("native_helper_healthy", False, "helper_unhealthy"),
    ("listener_bound", False, "listener_unbound"),
    ("private_lan_interface", False, "non_lan_interface"),
    ("node_is_advisory_primary", False, "not_primary"),
    ("exclusive_lease_verified", False, "lease_unverified"),
    ("split_brain_suspected", True, "split_brain"),
    ("output_permitted_and_ready", False, "output_unavailable"),
])
def test_each_missing_hard_gate_blocks_advertising(field, value, reason):
    assert evaluate(replace(READY, **{field: value})) == Readiness(False, reason)
    assert evaluate(READY) == Readiness(True, "ready")
    assert evaluate(Facts()).may_advertise is False


def test_reason_priority_is_deterministic():
    assert evaluate(replace(READY, user_enabled=False, shutdown_requested=True)).reason == "disabled"
    assert evaluate(replace(READY, shutdown_requested=True,
                            production_auth_verified=False)).reason == "shutting_down"
    assert evaluate(replace(READY, exclusive_lease_verified=False,
                            split_brain_suspected=True)).reason == "lease_unverified"
    assert evaluate(replace(READY, output_permitted_and_ready=False,
                            split_brain_suspected=True)).reason == "split_brain"


def test_advisory_primary_is_not_exclusive_lease():
    assert not evaluate(replace(READY, exclusive_lease_verified=False)).may_advertise
    assert not evaluate(replace(READY, node_is_advisory_primary=False)).may_advertise
    # Neither of two partitioned primaries can claim exclusive ownership merely
    # because its own view believes it is primary.
    left = replace(READY, exclusive_lease_verified=False)
    right = replace(READY, exclusive_lease_verified=False)
    assert not evaluate(left).may_advertise and not evaluate(right).may_advertise
    assert evaluate(replace(right, exclusive_lease_verified=True)).may_advertise


def test_partition_conflict_fails_closed():
    assert evaluate(replace(READY, split_brain_suspected=True)) == Readiness(False, "split_brain")
    assert evaluate(replace(READY, split_brain_suspected=True,
                            node_is_advisory_primary=False)).may_advertise is False


def test_revocation_shutdown_listener_loss_block_immediately():
    sequence = [READY, replace(READY, user_enabled=False), READY,
                replace(READY, listener_bound=False),
                replace(READY, shutdown_requested=True), READY]
    assert [evaluate(s).may_advertise for s in sequence] == [True, False, True, False, False, True]


def test_invalid_values_fail_closed_without_truthiness_or_exceptions():
    assert evaluate(None) == Readiness(False, "invalid_facts")
    assert evaluate(replace(READY, exclusive_lease_verified=1)) == Readiness(False, "invalid_facts")
    assert evaluate(replace(READY, user_enabled="yes")) == Readiness(False, "invalid_facts")


def test_module_has_no_gtk_network_or_mdns_side_effect():
    module_path = Path(__file__).resolve().parents[1] / "src/chrome_mesh_readiness.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert set(imported) <= {"__future__", "dataclasses"}
    module = importlib.import_module("chrome_mesh_readiness")
    assert module.evaluate(Facts()).reason == "disabled"
