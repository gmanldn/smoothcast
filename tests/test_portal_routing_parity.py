"""The route table must agree with the published API contract (#689): no policy drift."""
import api_spec
import portal_routing as pr


def _declared(route):
    op = api_spec.PATHS.get(route.path, {}).get(route.method.lower())
    if op is None:
        return None
    sec = op.get("security") or [{}]
    names = {k for entry in sec for k in entry}
    return "session" in names, "csrf" in names


def test_auth_and_csrf_match_api_spec_where_declared():
    drift = {}
    for r in pr.ROUTES:
        if r.prefix:
            continue
        got = _declared(r)
        if got is not None and got != (r.auth, r.csrf):
            drift[f"{r.method} {r.path}"] = {"spec(auth,csrf)": got, "table": (r.auth, r.csrf)}
    assert not drift, drift
