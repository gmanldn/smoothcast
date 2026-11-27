import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_source_offer", ROOT / "scripts" / "ci" / "check_source_offer.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

SHA = "a" * 40
LIC = (ROOT / "LICENSE").read_text(encoding="utf-8")
NOTICE = (ROOT / "packaging" / "SmoothCast-NOTICE.txt").read_text(encoding="utf-8")
OFFER = {"repo": C.REPO, "tag": "v2.3.15", "sha": SHA}
FF = {"licence": "LGPL-3.0-or-later", "source_url": "https://example.org/ffmpeg.tar.xz", "source_sha256": "b" * 64, "build_flags": "--disable-gpl"}


def run(**kw):
    a = dict(license_text=LIC, notice_text=NOTICE, offer=OFFER, version="2.3.15", tag_sha=SHA, about_text=C.REPO)
    a.update(kw)
    return C.check(a.pop("license_text"), a.pop("notice_text"), a.pop("offer"), **a)


def test_real_repository_files_pass():
    assert run() == []


def test_missing_or_modified_licence():
    assert run(license_text="MIT") == ["LICENSE is not the unmodified GNU GPL version 3 text"]


def test_notice_defects_are_each_named():
    assert run(notice_text="x") == ["NOTICE lacks 'SPDX-License-Identifier: GPL-3.0-or-later'", "NOTICE lacks the no-warranty statement",
                                    "NOTICE lacks the third-party licence statement", "NOTICE does not name the source repository"]
    assert "GPL-3.0-only is not the project licence" in run(notice_text=NOTICE + "GPL-3.0-only")


def test_source_offer_must_match_tag_and_sha():
    assert run(offer={**OFFER, "sha": "c" * 40}) == ["source offer SHA does not match the release tag commit"]
    assert run(offer={**OFFER, "tag": "v2.3.14"}) == ["source offer tag 'v2.3.14' does not match v2.3.15"]
    assert run(offer={**OFFER, "sha": "abc"}) == ["source offer SHA is not a full 40-character commit"]
    assert run(offer={**OFFER, "repo": "https://evil.example/x"}) == ["source offer names a different repository"]
    assert run(offer=None) == ["source offer is missing"]


def test_about_must_expose_source():
    assert run(about_text="SmoothCast 2.3.15") == ["About/help does not expose the source repository"]


def test_ffmpeg_disclosure_required_when_shipped():
    assert run(offer={**OFFER, "ffmpeg": FF}) == []
    assert run(offer={**OFFER, "ffmpeg": {"licence": "proprietary"}}) == [
        "FFmpeg licence is not declared as a known GPL/LGPL variant", "FFmpeg corresponding-source URL is missing or not https",
        "FFmpeg source archive SHA-256 is missing", "FFmpeg build configuration is not recorded"]
