import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import lan_tls_policy as tp


@pytest.mark.parametrize("addr,ok", [("192.168.1.20", True), ("10.0.0.5", True), ("0.0.0.0", False),
                                      ("8.8.8.8", False), ("127.0.0.1", False), ("tv.local", False), ("::", False)])
def test_bind_only_private_explicit(addr, ok):
    assert tp.bind_ok(addr)[0] is ok


def test_key_permissions_fail_closed(tmp_path):
    k = tmp_path / "k.pem"; k.write_text("x")
    os.chmod(k, 0o644); assert not tp.key_file_ok(str(k))[0]
    os.chmod(k, 0o600); assert tp.key_file_ok(str(k))[0]
    assert not tp.key_file_ok(str(tmp_path / "nope"))[0] and not tp.key_file_ok(str(tmp_path))[0]


def test_cert_validity_and_name_matching():
    san = ["smoothcast.lan", "192.168.1.20", "*.home.example"]
    assert tp.cert_ok(0, 100, san, "smoothcast.lan", 50)[0]
    assert tp.cert_ok(0, 100, san, "192.168.1.20", 50)[0]
    assert tp.cert_ok(0, 100, san, "tv.home.example", 50)[0]
    assert not tp.cert_ok(0, 100, san, "a.b.home.example", 50)[0]
    assert "expired" in tp.cert_ok(0, 100, san, "smoothcast.lan", 101)[1]
    assert "not valid yet" in tp.cert_ok(10, 100, san, "smoothcast.lan", 5)[1]
    assert "does not cover" in tp.cert_ok(0, 100, san, "other.lan", 50)[1]


def test_redirects_cookies_and_warnings():
    assert tp.redirect_ok("https://192.168.1.20/room", "192.168.1.20")
    assert not tp.redirect_ok("http://192.168.1.20/", "192.168.1.20")
    assert not tp.redirect_ok("https://evil.example/", "192.168.1.20")
    assert "Secure" in tp.cookie_flags(True) and "Secure" not in tp.cookie_flags(False)
    assert tp.expiry_warning(86400 * 3, 0).startswith("The certificate expires in 3") and tp.expiry_warning(86400 * 90, 0) == ""
    assert "not install" in tp.trust_note()
