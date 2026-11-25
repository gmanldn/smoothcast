"""Trusted candidate acquisition (#580): offline Git fixtures, no network."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import managed_source

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def run(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                          check=True, capture_output=True, text=True, env=ENV)


@pytest.fixture
def origin(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    run(work, "init", "-q", "-b", "develop")
    (work / "src").mkdir()
    (work / "src" / "version.py").write_text("PATCH = 1\n", encoding="utf-8")
    (work / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    run(work, "add", "-A")
    run(work, "commit", "-qm", "one")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "develop", str(bare)],
                   check=True, capture_output=True, text=True, env=ENV)
    run(work, "push", "-q", str(bare), "develop:refs/heads/develop")
    return bare


@pytest.fixture
def checkout(tmp_path, origin):
    repo = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)],
                   check=True, capture_output=True, text=True, env=ENV)
    return repo


def test_pin_channel_commit_returns_the_exact_pushed_sha(checkout):
    sha = run(checkout, "rev-parse", "refs/remotes/origin/develop").stdout.strip()
    assert managed_source.pin_channel_commit(checkout, "develop") == sha


def test_unknown_channel_is_refused(checkout):
    with pytest.raises(managed_source.SourceError):
        managed_source.pin_channel_commit(checkout, "feature")


def test_candidate_manifest_matches_the_exported_tree(checkout):
    sha = managed_source.pin_channel_commit(checkout, "develop")
    manifest = managed_source.candidate_manifest(checkout, sha, verify=lambda *a: True)
    assert set(manifest) == {"src/a.py", "src/version.py"}
    assert manifest["src/version.py"]["size"] == len("PATCH = 1\n")


def test_unsigned_candidate_is_never_staged(tmp_path, checkout):
    with pytest.raises(managed_source.SourceError):
        managed_source.stage_trusted_candidate(tmp_path / "inst", checkout, channel="develop")


def test_staged_candidate_is_checksum_verified_and_never_activated(tmp_path, checkout):
    sha = managed_source.pin_channel_commit(checkout, "develop")
    root = tmp_path / "inst"
    staged = managed_source.stage_trusted_candidate(root, checkout, channel="develop",
                                                    verify=lambda *a: True)
    assert staged == root / "releases" / sha
    assert (staged / "src" / "version.py").read_text(encoding="utf-8") == "PATCH = 1\n"
    assert not (root / "current").exists() and not (root / "previous").exists()


def test_malformed_commit_is_refused(checkout):
    with pytest.raises(managed_source.SourceError):
        managed_source.candidate_manifest(checkout, "not-a-sha", verify=lambda *a: True)
    assert managed_source.signed_provenance(checkout, "not-a-sha") is False


@pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg is not installed")
def test_signed_commit_passes_the_keyring_trust_policy(tmp_path, checkout, monkeypatch):
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("GNUPGHOME", str(home))
    env = {**ENV, "GNUPGHOME": str(home)}
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-generate-key",
                    "SmoothCast Test <t@t>", "ed25519", "sign", "0"],
                   check=True, capture_output=True, text=True, env=env)
    (checkout / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    run(checkout, "add", "-A")
    subprocess.run(["git", "-C", str(checkout), "commit", "-qS", "-m", "signed"],
                   check=True, capture_output=True, text=True, env=env)
    sha = run(checkout, "rev-parse", "HEAD").stdout.strip()
    assert managed_source.signed_provenance(checkout, sha) is True


def test_failed_stage_leaves_an_existing_generation_untouched(tmp_path, checkout):
    root = tmp_path / "inst"
    first = managed_source.stage_trusted_candidate(root, checkout, channel="develop",
                                                   verify=lambda *a: True)
    with pytest.raises(managed_source.SourceError):
        managed_source.stage_trusted_candidate(root, tmp_path / "missing", channel="develop",
                                               verify=lambda *a: True)
    assert first.is_dir() and (first / "src" / "version.py").is_file()
    assert not (root / "current").exists() and not (root / "previous").exists()
