"""Characterization (#689): every authenticated route in the table refuses an anonymous caller.

Pins the auth gate before ``do_GET``/``do_POST`` dispatch through ``portal_routing``.
"""
from __future__ import annotations

import pytest

import portal_routing
from test_portal import PortalRig

DENIED = {401, 403}
AUTHED = [r for r in portal_routing.ROUTES if r.auth and not r.prefix and "{" not in r.path]


@pytest.fixture()
def rig():
    r = PortalRig()
    yield r
    r.server.shutdown()
    r.server.server_close()


@pytest.mark.parametrize("route", AUTHED, ids=lambda r: f"{r.method} {r.path}")
def test_anonymous_caller_is_refused(rig, route):
    body = {} if route.method == "POST" else None
    got = rig.request(route.method, route.path, body)
    status = got[0] if isinstance(got, tuple) else got.status
    assert status in DENIED, f"{route.method} {route.path} answered {status} without a session"
