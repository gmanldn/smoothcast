"""Offline, no-apt/no-sudo regression tests for the FFmpeg CI installer."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
import ensure_ffmpeg as ci


RELEASE = {"ID": "ubuntu", "VERSION_CODENAME": "noble"}


def test_installed_ffmpeg_skips_all_apt_and_network():
    calls = []
    result = ci.ensure_ffmpeg(
        which=lambda name: "/usr/bin/" + name,
        run=lambda *a, **kw: calls.append((a, kw)), release=RELEASE,
    )
    assert result == "preinstalled"
    assert calls == []


def test_ubuntu_sources_are_only_signed_official_archives():
    sources = ci.official_sources("noble")
    lines = sources.splitlines()
    assert len(lines) == 3
    assert all(line.startswith("deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg]")
               for line in lines)
    assert all(line.startswith("deb ") and "https://" in line for line in lines)
    assert "archive.ubuntu.com/ubuntu/" in sources
    assert "security.ubuntu.com/ubuntu/" in sources
    for invalid in ("", "../../evil", "noble;rm -rf /", "NOBLE"):
        with pytest.raises(ValueError):
            ci.official_sources(invalid)


def test_success_uses_private_temp_sources_and_all_required_apt_options():
    installed = [False]
    calls = []
    sources_dir = []

    def run(argv, *, check):
        assert check is True
        assert argv[0:2] == ["sudo", "timeout"]
        calls.append(argv)
        paths = [p.split("=", 1)[1] for p in argv
                 if p.startswith("Dir::Etc::sourcelist=")]
        assert len(paths) == 1
        sources = Path(paths[0])
        assert sources.is_file()
        assert "noble-security" in sources.read_text()
        sources_dir.append(sources.parent)
        if "install" in argv:
            installed[0] = True
        return subprocess.CompletedProcess(argv, 0)

    assert ci.ensure_ffmpeg(
        which=lambda name: "/usr/bin/" + name if installed[0] else None,
        run=run, release=RELEASE,
    ) == "official-archive"
    assert len(calls) == 2
    assert ["apt-get" in args for args in calls] == [True, True]
    assert "update" in calls[0] and "install" in calls[1]
    assert "--no-install-recommends" in calls[1] and "ffmpeg" in calls[1]
    assert str(ci.ARCHIVE_UPDATE_SECONDS) in calls[0]
    assert str(ci.ARCHIVE_INSTALL_SECONDS) in calls[1]
    assert all("Acquire::Retries=1" in args for args in calls)
    assert not sources_dir[0].exists()  # private sources never persist


@pytest.mark.parametrize("failure", ["update", "install"])
def test_mirror_failure_falls_back_to_original_runner_sources(failure):
    calls = []
    installed = [False]

    def run(argv, *, check):
        calls.append(argv)
        if failure == "update" and "update" in argv:
            raise subprocess.CalledProcessError(124, argv)
        if failure == "install" and "Dir::Etc::sourceparts=-" in argv and "install" in argv:
            raise subprocess.CalledProcessError(124, argv)
        if "install" in argv:
            installed[0] = True
        return subprocess.CompletedProcess(argv, 0)

    assert ci.ensure_ffmpeg(
        which=lambda name: "/usr/bin/" + name if installed[0] else None,
        run=run, release=RELEASE,
    ) == "runner-mirror"
    fallback = calls[-1]
    assert fallback[0:3] == ["sudo", "timeout", str(ci.RUNNER_MIRROR_SECONDS)]
    assert "Acquire::Retries=0" in fallback
    assert "Acquire::http::Timeout=20" in fallback
    assert not any(p.startswith("Dir::Etc::sourcelist=") for p in fallback)
    assert fallback[-1] == "ffmpeg"


def test_all_mirrors_failing_is_a_real_ci_error_not_a_skip():
    def fail(argv, *, check):
        raise subprocess.CalledProcessError(124, argv)

    with pytest.raises(subprocess.CalledProcessError):
        ci.ensure_ffmpeg(which=lambda _: None, run=fail, release=RELEASE)


def test_successful_apt_without_required_executables_still_fails():
    with pytest.raises(RuntimeError, match="did not provide"):
        ci.ensure_ffmpeg(
            which=lambda _: None,
            run=lambda argv, *, check: subprocess.CompletedProcess(argv, 0),
            release=RELEASE,
        )


def test_non_ubuntu_or_invalid_release_fails_before_touching_apt():
    for release in ({"ID": "debian", "VERSION_CODENAME": "bookworm"},
                    {"ID": "ubuntu", "VERSION_CODENAME": "../evil"}):
        calls = []
        with pytest.raises(RuntimeError):
            ci.ensure_ffmpeg(which=lambda _: None,
                             run=lambda *a, **k: calls.append(a), release=release)
        assert not calls


def test_workflow_retains_real_codec_and_caption_assertions():
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text()
    assert "python scripts/ci/ensure_ffmpeg.py" in workflow
    assert "Verify required encoders and caption filter" in workflow
    for codec in ("libx264", "mpeg4", "aac", "subtitles"):
        assert "grep -q " + codec in workflow
    assert "tests/test_subtitle_encoding.py tests/test_preflight.py tests/test_dlna.py" in workflow
