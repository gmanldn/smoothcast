import local_api as api


def req(**kw):
    base = {"v": 1, "id": 7, "cmd": "status", "args": {}}
    base.update(kw)
    return base


def test_valid_commands_parse():
    assert api.parse_request(req()) == ("status", {}, 7)
    assert api.parse_request(req(cmd="seek", args={"position": 12}))[1] == {"position": 12.0}


def test_version_negotiation_and_unknown_command():
    assert api.parse_request(req(v=2))["error"]["code"] == "unsupported_version"
    assert api.parse_request(req(v=True))["error"]["code"] == "unsupported_version"
    assert api.parse_request(req(cmd="rm -rf"))["error"]["code"] == "unknown_command"


def test_argument_validation_is_strict():
    for bad in ({"position": "1"}, {"position": float("nan")}, {"position": 1, "x": 2}, {}):
        assert api.parse_request(req(cmd="seek", args=bad))["error"]["code"] == "bad_arguments"
    assert api.parse_request(req(cmd="play", args={"media": ""}))["error"]["code"] == "bad_arguments"
    assert api.parse_request(req(cmd="play", args={"media": "x" * 5000}))["ok"] is False


def test_non_object_and_envelopes():
    assert api.parse_request("hi")["error"]["code"] == "bad_request"
    assert api.ok({"state": "idle"}, 3) == {"v": 1, "id": 3, "ok": True, "result": {"state": "idle"}}
    assert api.error("bad_request", "x")["error"]["status"] == 400
