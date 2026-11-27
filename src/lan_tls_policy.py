"""Fail-closed policy checks for the optional LAN HTTPS listener (#340). Pure + stat only.

Certificate facts are passed in as parsed values (not_after, SAN names/IPs) so
the policy is testable without a TLS stack. Every check returns
``(ok, plain-language reason)``; the listener must refuse to start on any False.
"""
from __future__ import annotations

import ipaddress
import os
import stat

EXPIRY_WARN_DAYS = 14


def bind_ok(address: str) -> tuple[bool, str]:
    """Only an explicit private/link-local LAN address; never wildcard or public."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False, "Choose the TV network address to serve HTTPS on."
    if ip.is_unspecified:
        return False, "HTTPS can't listen on every network. Pick one local address."
    if not (ip.is_private or ip.is_link_local) or ip.is_loopback:
        return False, "HTTPS is only offered on your private home network."
    return True, ""


def key_file_ok(path: str) -> tuple[bool, str]:
    try:
        st = os.stat(path)
    except OSError:
        return False, "The private key file can't be read."
    if not stat.S_ISREG(st.st_mode):
        return False, "The private key must be a regular file."
    if os.name == "posix" and st.st_mode & 0o077:
        return False, "The private key is readable by other users. Restrict it to your account (chmod 600)."
    return True, ""


def cert_ok(not_before: float, not_after: float, san: list[str], serve_name: str, now: float) -> tuple[bool, str]:
    if now < not_before:
        return False, "The certificate is not valid yet. Check this computer's clock."
    if now > not_after:
        return False, "The certificate has expired. Renew it to keep using HTTPS."
    names = [s.lower() for s in san]
    target = serve_name.lower().rstrip(".")
    if target in names:
        return True, ""
    try:
        want = ipaddress.ip_address(target)
        if any(_same_ip(n, want) for n in names):
            return True, ""
    except ValueError:
        for n in names:                                   # single-label wildcard only
            if n.startswith("*.") and "." in target and target.split(".", 1)[1] == n[2:]:
                return True, ""
    return False, f"The certificate does not cover {serve_name}. Create one that lists it."


def _same_ip(text: str, want) -> bool:
    try:
        return ipaddress.ip_address(text) == want
    except ValueError:
        return False


def expiry_warning(not_after: float, now: float) -> str:
    days = int((not_after - now) // 86400)
    return f"The certificate expires in {days} days." if 0 <= days <= EXPIRY_WARN_DAYS else ""


def trust_note() -> str:
    return ("A self-signed certificate is not trusted by phones automatically. SmoothCast will not install "
            "certificates or bypass warnings; use a certificate your devices already trust.")


def redirect_ok(target: str, serve_host: str) -> bool:
    """Never redirect credentials to another host or downgrade to http."""
    return target.startswith("https://") and target[8:].split("/", 1)[0].lower() == serve_host.lower()


def cookie_flags(https: bool) -> str:
    return "HttpOnly; SameSite=Strict" + ("; Secure" if https else "")
