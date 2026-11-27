import portal_routing as pr


def test_exact_and_prefix_matching():
    assert pr.match("GET", "/api/status").handler == "status"
    assert pr.match("GET", "/api/libraries/abc").handler == "libraries"
    assert pr.match("GET", "/mesh/file/x/y").prefix
    assert pr.match("GET", "/nope") is None


def test_method_is_part_of_the_key():
    assert pr.match("POST", "/api/status") is None
    assert pr.match("POST", "/api/action").csrf


def test_exact_beats_prefix_regardless_of_order():
    rs = (pr.Route("GET", "/a/", "pre", prefix=True), pr.Route("GET", "/a/b", "exact"))
    assert pr.match("GET", "/a/b", rs).handler == "exact"
    assert pr.match("GET", "/a/c", rs).handler == "pre"


def test_policy_lives_in_data():
    assert pr.match("GET", "/api/status").auth
    assert not pr.match("POST", "/api/login").csrf
    assert {"/", "/api/login"} <= pr.public_paths() | {"/api/login"}
    assert all(r.csrf for r in pr.ROUTES if r.method == "POST" and r.path != "/api/login")


def test_upload_routes_are_throttled_as_uploads():
    assert {r.throttle for r in pr.ROUTES if r.path.startswith("/api/uploads")} == {"upload"}
