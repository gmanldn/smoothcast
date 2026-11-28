import pytest

import donate


@pytest.mark.parametrize("url", [
    "https://buy.stripe.com/test_abc123",
    "https://donate.stripe.com/abc",
])
def test_accepts_stripe_links(url):
    assert donate.donation_url(url) == url


@pytest.mark.parametrize("url", [
    "", "   ", "http://buy.stripe.com/x", "https://evil.example/x",
    "https://buy.stripe.com.evil.example/x", "https://user@buy.stripe.com/x",
    "https://buy.stripe.com:8443/x", "javascript:alert(1)", "https://[bad",
])
def test_rejects_unsafe_links(url):
    assert donate.donation_url(url) is None


def test_env_override(monkeypatch):
    monkeypatch.setenv(donate.ENV_VAR, "https://buy.stripe.com/env")
    assert donate.donation_url() == "https://buy.stripe.com/env"
    monkeypatch.delenv(donate.ENV_VAR)
    assert donate.donation_url() is None
