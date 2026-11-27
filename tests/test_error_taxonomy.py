"""Typed error taxonomy ratchet (#207).

A failure code the app raises or records must exist in ``errors.CATALOGUE``;
otherwise it degrades to the internal fallback with no plain-language message or
remediation. Catalogue entries must also be sound and referenced outside the
catalogue itself, so the taxonomy cannot accumulate dead or malformed codes.
"""
from __future__ import annotations

import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import errors

CODE_LITERAL = re.compile(r'(?:code=|errors\.record\()"([a-z_]+\.[a-z_]+)"')
CATALOGUE_ONLY = {
    "src/errors.py",
    "docs/ERRORS.md",
    "tests/test_error_taxonomy.py",
}
SCANNED_SUFFIXES = (".py", ".md", ".json", ".js", ".mjs", ".sh")


def _raised_codes() -> dict[str, str]:
    found: dict[str, str] = {}
    for source in sorted((ROOT / "src").glob("*.py")):
        for code in CODE_LITERAL.findall(source.read_text(encoding="utf-8")):
            found.setdefault(code, source.name)
    return found


def _references() -> str:
    texts = []
    for folder in ("src", "scripts", "tests", "docs"):
        for path in sorted((ROOT / folder).rglob("*")):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            if path.relative_to(ROOT).as_posix() in CATALOGUE_ONLY:
                continue
            texts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(texts)


def test_every_raised_code_is_catalogued():
    unknown = {code: where for code, where in _raised_codes().items()
               if code not in errors.CATALOGUE}
    assert unknown == {}, unknown


def test_catalogue_entries_are_sound_and_referenced():
    references = _references()
    for code, spec in errors.CATALOGUE.items():
        assert spec.category in errors.CATEGORIES, code
        assert spec.category == code.split(".", 1)[0], code
        assert spec.severity in errors.SEVERITIES, code
        assert isinstance(spec.retryable, bool), code
        assert spec.message.strip(), code
        assert all(step.strip() for step in spec.steps), code
        assert code in references, f"{code} is only defined in the catalogue"


# The failure classes #207 names as the "top 20" must each have a catalogued code.
_REQUIRED_PREFIXES = ("discovery.", "cast.receiver_offline", "ffmpeg.decoder_failed",
                      "ffmpeg.too_old", "ffmpeg.missing", "subtitle.", "dlna.",
                      "network.port_in_use", "upload.disk_full", "media.unavailable")


def test_issue_207_named_failure_classes_are_all_catalogued():
    codes = list(errors.CATALOGUE)
    for prefix in _REQUIRED_PREFIXES:
        assert any(c.startswith(prefix) for c in codes), prefix
    assert len(codes) >= 20


def test_coded_tags_legacy_exceptions_and_ignores_unknown_codes():
    import failure_boundary
    tagged = errors.coded(RuntimeError("SSDP multicast discovery failed: /home/u/x"), "discovery.failed")
    failure = failure_boundary.describe(tagged)
    assert failure.code == "discovery.failed"
    assert failure.title == errors.CATALOGUE["discovery.failed"].message
    assert "/home/" not in failure.title
    assert not hasattr(errors.coded(RuntimeError("x"), "no.such_code"), "code")
    assert failure_boundary.describe(errors.coded(RuntimeError("x"), "no.such_code")).code == errors.FALLBACK.code


def test_discovery_dlna_and_port_sites_raise_coded_errors():
    root = Path(__file__).resolve().parents[1] / "src"
    sites = {"dlna.py": ('"discovery.failed"', '"dlna.command_failed"'),
             "pychromecast_backend.py": ('"discovery.failed"',),
             "streamer.py": ('"network.port_in_use"',)}
    for name, needles in sites.items():
        text = (root / name).read_text(encoding="utf-8")
        for needle in needles:
            assert "errors.coded(" in text and needle in text, (name, needle)
