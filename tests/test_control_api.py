"""Token-protected local control API (issue #269): real loopback server, fake handlers.

No receiver, no GTK, no ffmpeg: ``cli_control.HANDLERS`` are replaced by fakes,
and the server only ever binds 127.0.0.1 on an ephemeral port.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import cli_control
import control_api as api

TOKEN = "t" * 32
PRISTINE = dict(cli_control.HANDLERS)  # restored after every rig, whatever order they close in


class Rig:
    def __init__(self, roots, handlers):
        self.calls = []
        for name, fn in handlers.items():
            cli_control.HANDLERS[name] = self._wrap(name, fn)
        self.server = api.ControlServer(("127.0.0.1", 0), TOKEN, roots)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()

    def _wrap(self, name, fn):
        def call(args):
            self.calls.append((name, args))
            return fn(args)
        return call

    def request(self, method, path, body=None, token=TOKEN, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = dict(headers or {})
        if token is not None:
            hdr["Authorization"] = f"Bearer {token}"
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        conn.request(method, path, body=data, headers=hdr)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, (json.loads(raw) if raw else {}), resp

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        cli_control.HANDLERS.clear()
        cli_control.HANDLERS.update(PRISTINE)


OK = lambda args: {"device": args.device, "message": "ok"}  # noqa: E731


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(roots=None, handlers=None):
        r = Rig(roots if roots is not None else [], handlers or {n: OK for n in cli_control.COMMANDS})
        made.append(r)
        return r
    yield make
    for r in reversed(made):
        r.close()


# --- authentication ---------------------------------------------------------

@pytest.mark.parametrize("token", [None, "", "wrong", "t" * 31, TOKEN + "x"])
def test_every_endpoint_needs_the_exact_token(rig, token):
    r = rig()
    for method, path in (("GET", "/v1/health"), ("GET", "/v1/status?device=TV"),
                         ("POST", "/v1/pause"), ("POST", "/v1/cast"), ("GET", "/nope")):
        status, body, resp = r.request(method, path, {"device": "TV"} if method == "POST" else None, token=token)
        assert status == 401 and body["ok"] is False and body["error"] == "unauthorized", (method, path)
        assert "Bearer" in resp.getheader("WWW-Authenticate")
    assert r.calls == []


def test_non_bearer_schemes_are_rejected(rig):
    r = rig()
    status, _, _ = r.request("GET", "/v1/health", token=None, headers={"Authorization": f"Basic {TOKEN}"})
    assert status == 401
    status, _, _ = r.request("GET", "/v1/health", token=None, headers={"Authorization": TOKEN})
    assert status == 401


def test_health_with_token(rig):
    status, body, resp = rig().request("GET", "/v1/health")
    assert status == 200 and body["ok"] and body["version"].startswith("v")
    assert resp.getheader("Cache-Control") == "no-store"
    assert resp.getheader("X-Content-Type-Options") == "nosniff"


def test_no_cors_headers_are_ever_sent(rig):
    r = rig()
    for token in (TOKEN, None):
        _, _, resp = r.request("GET", "/v1/health", token=token)
        assert not [h for h, _ in resp.getheaders() if h.lower().startswith("access-control")]
    status, _, resp = r.request("OPTIONS", "/v1/pause", token=None)
    assert status == 405 and resp.getheader("Access-Control-Allow-Origin") is None


# --- commands ---------------------------------------------------------------

def test_pause_resume_stop_status_use_the_cli_handlers(rig):
    r = rig()
    for cmd in ("pause", "resume", "stop"):
        status, body, _ = r.request("POST", f"/v1/{cmd}", {"device": "Living Room"})
        assert (status, body["ok"], body["command"], body["device"]) == (200, True, cmd, "Living Room")
    status, body, _ = r.request("GET", "/v1/status?device=Living%20Room")
    assert status == 200 and body["device"] == "Living Room" and body["command"] == "status"
    assert [c for c, _ in r.calls] == ["pause", "resume", "stop", "status"]


def test_seek_accepts_seconds_or_clock_text_and_rejects_junk(rig):
    r = rig()
    for value in (90, 90.5, "1:02:03", "45"):
        assert r.request("POST", "/v1/seek", {"device": "TV", "time": value})[0] == 200
    assert [str(a.time) for c, a in r.calls] == ["90", "90.5", "1:02:03", "45"]
    for bad in (None, True, [], {"a": 1}):
        status, body, _ = r.request("POST", "/v1/seek", {"device": "TV", "time": bad})
        assert status == 400 and body["error"] == "bad_request"


@pytest.mark.parametrize("device", [None, "", "  ", "-d", "--help", "x" * 201, 5, ["TV"]])
def test_device_is_required_and_validated(rig, device):
    r = rig()
    status, body, _ = r.request("POST", "/v1/pause", {"device": device})
    assert status == 400 and body["ok"] is False
    assert r.calls == []


def test_handler_errors_map_to_http_statuses(rig):
    def boom(code):
        def fn(args):
            raise cli_control.CliError(code, f"code {code}")
        return fn
    cases = {cli_control.EXIT_USAGE: 400, cli_control.EXIT_UNREACHABLE: 503,
             cli_control.EXIT_MEDIA: 422, cli_control.EXIT_FAILED: 502}
    for code, expected in cases.items():
        r = rig(handlers={"pause": boom(code)})
        status, body, _ = r.request("POST", "/v1/pause", {"device": "TV"})
        assert status == expected and body["message"] == f"code {code}"


def test_unexpected_exceptions_are_hidden_and_do_not_kill_the_server(rig):
    def explode(args):
        raise RuntimeError("secret internal detail /home/user/x")
    r = rig(handlers={"pause": explode, "resume": OK})
    status, body, _ = r.request("POST", "/v1/pause", {"device": "TV"})
    assert status == 500 and "secret" not in json.dumps(body)
    assert r.request("POST", "/v1/resume", {"device": "TV"})[0] == 200


# --- routing and body handling ------------------------------------------------

def test_unknown_paths_and_wrong_methods(rig):
    r = rig()
    assert r.request("GET", "/")[0] == 404
    assert r.request("GET", "/v2/status")[0] == 404
    assert r.request("POST", "/v1/nothing", {})[0] == 404
    assert r.request("GET", "/v1/pause")[0] == 405          # POST-only
    assert r.request("POST", "/v1/status", {})[0] == 405    # GET-only
    for method in ("PUT", "DELETE", "PATCH"):
        assert r.request(method, "/v1/pause", {})[0] == 405


@pytest.mark.parametrize("raw", [b"not json", b"[1,2]", b'"s"', b"\xff\xfe", b"null"])
def test_body_must_be_a_json_object(rig, raw):
    status, body, _ = rig().request("POST", "/v1/pause", raw)
    assert status == 400 and body["ok"] is False


def test_oversized_body_is_refused_without_reading_it(rig):
    r = rig()
    status, body, _ = r.request("POST", "/v1/pause", b"{" + b" " * (api.MAX_BODY + 10) + b"}")
    assert status == 413 and body["error"] == "too_large"
    assert r.calls == []


def test_bad_content_length_is_rejected(rig):
    r = rig()
    status, _, _ = r.request("POST", "/v1/pause", b"{}", headers={"Content-Length": "abc"})
    assert status == 400


# --- cast and media roots -----------------------------------------------------

def test_cast_is_refused_when_no_media_root_is_configured(rig, tmp_path):
    movie = tmp_path / "a.mkv"
    movie.write_bytes(b"x")
    r = rig(roots=[])
    status, body, _ = r.request("POST", "/v1/cast", {"device": "TV", "file": str(movie)})
    assert status == 403 and "--media-root" in body["message"] and r.calls == []


def test_cast_only_inside_the_media_root(rig, tmp_path):
    root, outside = tmp_path / "media", tmp_path / "secret"
    root.mkdir()
    outside.mkdir()
    ok_file, bad_file = root / "ok.mkv", outside / "bad.mkv"
    ok_file.write_bytes(b"x")
    bad_file.write_bytes(b"x")
    link = root / "link.mkv"
    try:
        link.symlink_to(bad_file)
    except OSError:
        link = None
    r = rig(roots=[root.resolve()],
            handlers={"cast": lambda a: {"device": a.device, "file": Path(a.file).name}})
    status, body, _ = r.request("POST", "/v1/cast", {"device": "TV", "file": str(ok_file)})
    assert status == 200 and body["file"] == "ok.mkv"
    attempts = [str(bad_file), str(root / ".." / "secret" / "bad.mkv"), str(root)]
    if link is not None:
        attempts.append(str(link))
    for attempt in attempts:
        status, body, _ = r.request("POST", "/v1/cast", {"device": "TV", "file": attempt})
        assert status == 403, attempt
    status, _, _ = r.request("POST", "/v1/cast", {"device": "TV", "file": str(root / "missing.mkv")})
    assert status == 422
    assert len(r.calls) == 1


def test_cast_options_are_validated_and_defaulted(rig, tmp_path):
    root = tmp_path.resolve()
    movie = root / "m.mkv"
    movie.write_bytes(b"x")
    r = rig(roots=[root], handlers={"cast": lambda a: {"device": a.device}})
    assert r.request("POST", "/v1/cast", {"device": "TV", "file": str(movie)})[0] == 200
    a = r.calls[0][1]
    assert (a.mode, a.quality, a.audio, a.no_subs, a.subs, a.offset, a.title) == (
        "auto", "balanced", "original", False, None, None, None)
    for field, value in (("mode", "x"), ("quality", "ultra"), ("audio", 3), ("title", "t" * 300), ("offset", "9" * 50)):
        status, _, _ = r.request("POST", "/v1/cast", {"device": "TV", "file": str(movie), field: value})
        assert status == 400, field
    sub = tmp_path.parent / "elsewhere.srt"
    sub.write_text("1")
    status, _, _ = r.request("POST", "/v1/cast", {"device": "TV", "file": str(movie), "subs": str(sub)})
    assert status == 403


def test_commands_never_run_concurrently(rig):
    state = {"active": 0, "max": 0}
    gate = threading.Lock()

    def slow(args):
        with gate:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        threading.Event().wait(0.05)
        with gate:
            state["active"] -= 1
        return {"device": args.device}
    r = rig(handlers={"pause": slow})
    threads = [threading.Thread(target=lambda: r.request("POST", "/v1/pause", {"device": "TV"})) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert state["max"] == 1


# --- configuration ------------------------------------------------------------

@pytest.mark.parametrize("bad", ["0.0.0.0", "8.8.8.8", "1.1.1.1", "::", "::1", "example.com", "", "224.0.0.1", "300.1.1.1"])
def test_bind_refuses_wildcard_public_and_names(bad):
    with pytest.raises(api.ControlApiError):
        api.validate_bind(bad)


@pytest.mark.parametrize("good,expected", [("127.0.0.1", "127.0.0.1"), ("localhost", "127.0.0.1"),
                                           ("192.168.1.20", "192.168.1.20"), ("10.0.0.5", "10.0.0.5")])
def test_bind_accepts_loopback_and_private_lan(good, expected):
    assert api.validate_bind(good) == expected


@pytest.mark.parametrize("bad", [0, 80, 1023, 65536, "8800", 8800.0, None, True])
def test_port_must_be_an_unprivileged_integer(bad):
    with pytest.raises(api.ControlApiError):
        api.validate_port(bad)
    assert api.validate_port(8800) == 8800 and api.DEFAULT_PORT == 8800


def test_token_file_is_created_once_with_owner_only_mode(tmp_path, monkeypatch):
    monkeypatch.delenv(api.TOKEN_ENV, raising=False)
    path = tmp_path / "cfg" / "token"
    with pytest.raises(api.ControlApiError):
        api.load_token(path, create=False)             # serving never invents a token
    first = api.load_token(path, create=True)
    assert len(first) >= api.MIN_TOKEN_LENGTH and api.load_token(path) == first
    assert api.load_token(path, create=True) == first  # stable on reuse
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        path.chmod(0o644)
        with pytest.raises(api.ControlApiError, match="readable by others"):
            api.load_token(path)


def test_short_token_in_file_or_env_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv(api.TOKEN_ENV, raising=False)
    path = tmp_path / "token"
    path.write_text("short\n")
    path.chmod(0o600)
    with pytest.raises(api.ControlApiError, match="too short"):
        api.load_token(path)
    monkeypatch.setenv(api.TOKEN_ENV, "short")
    with pytest.raises(api.ControlApiError):
        api.load_token(path)
    monkeypatch.setenv(api.TOKEN_ENV, "e" * 20)
    assert api.load_token(path) == "e" * 20


def test_media_roots_must_be_existing_directories(tmp_path):
    assert api.resolve_media_roots([str(tmp_path)]) == [tmp_path.resolve()]
    with pytest.raises(api.ControlApiError):
        api.resolve_media_roots([str(tmp_path / "missing")])


def test_serve_without_a_token_exits_with_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(api.TOKEN_ENV, raising=False)
    code = api.main(["serve", "--token-file", str(tmp_path / "none")])
    assert code == 2 and "no token" in capsys.readouterr().err


def test_serve_refuses_a_public_bind_before_listening(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(api.TOKEN_ENV, "e" * 20)
    assert api.main(["serve", "--bind", "0.0.0.0"]) == 2
    assert "refusing" in capsys.readouterr().err


# --- isolation ------------------------------------------------------------------

def test_module_and_cli_entry_do_not_import_gtk():
    code = ("import sys; sys.path.insert(0, 'src'); import control_api, cli; "
            "assert 'gi' not in sys.modules and not any(m.startswith('gi.') for m in sys.modules)")
    # Full environment: Python on Windows will not start without SYSTEMROOT and
    # friends. -I already ignores PYTHONPATH and the user site directory.
    subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, check=True, env=os.environ.copy())


def test_cli_routes_the_flag_and_module_is_installed():
    assert '["--control-api"]' in (ROOT / "src" / "cli.py").read_text()
    assert '"control_api"' in (ROOT / "pyproject.toml").read_text()


def test_zz_rigs_leave_the_cli_handlers_untouched(rig):
    """Guards the earlier leak: several rigs in one test must not poison other test files."""
    rig(handlers={"pause": OK})
    rig(handlers={"pause": OK})
    assert cli_control.HANDLERS["pause"] is not PRISTINE["pause"]  # patched while in use
    # (restoration itself is asserted by the next test file's real handlers, and below)


def test_zzz_handlers_are_pristine_after_every_previous_test():
    assert dict(cli_control.HANDLERS) == PRISTINE
