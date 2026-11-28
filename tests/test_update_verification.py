"""Update opt-out and signature-verified fast-forward (issue #230).

Uses real temporary git repositories and, where gpg is installed, a real
ephemeral signing key: nothing here touches the network or the user's keyring.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import update_control
import version

# Real signature tests need a POSIX gpg-agent (short socket paths under /tmp); the
# opt-out tests below need only git and run on every platform.
HAVE_GPG = os.name == "posix" and shutil.which("gpg") is not None
VERSION = "MAJOR = 1\nMINOR = 0\nPATCH = {}\n"


def clean_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    env.update(extra or {})
    return env


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env or clean_env(), check=True,
                          capture_output=True, text=True).stdout.strip()


class RepoCase(unittest.TestCase):
    """origin (bare) + local (checkout under test) + dev (pushes updates)."""

    gnupg: str | None = None
    fingerprint = ""

    @classmethod
    def setUpClass(cls):
        if HAVE_GPG:
            cls.gnupg = tempfile.mkdtemp(prefix="g", dir="/tmp")   # short: gpg-agent socket path
            os.chmod(cls.gnupg, 0o700)
            env = clean_env({"GNUPGHOME": cls.gnupg})
            subprocess.run(
                ["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
                 "--quick-generate-key", "Test <t@example.invalid>", "ed25519", "sign", "never"],
                env=env, check=True, capture_output=True, timeout=60)
            listing = subprocess.run(["gpg", "--batch", "--with-colons", "--list-secret-keys"],
                                     env=env, capture_output=True, text=True, check=True).stdout
            cls.fingerprint = next(line.split(":")[9] for line in listing.splitlines()
                                   if line.startswith("fpr:"))

    @classmethod
    def tearDownClass(cls):
        if cls.gnupg:
            subprocess.run(["gpgconf", "--kill", "all"], env=clean_env({"GNUPGHOME": cls.gnupg}),
                           capture_output=True)
            shutil.rmtree(cls.gnupg, ignore_errors=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.origin, self.local, self.dev = base / "origin.git", base / "local", base / "dev"
        git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(base, "clone", "-q", str(self.origin), str(self.dev))
        git(self.dev, "checkout", "-q", "-b", "main")
        self.commit(self.dev, 1)
        git(self.dev, "push", "-q", "origin", "main")
        git(base, "clone", "-q", "-b", "main", str(self.origin), str(self.local))
        patcher = mock.patch.object(version, "__version__", "1.0.1")
        patcher.start()
        self.addCleanup(patcher.stop)

    def commit(self, repo: Path, patch: int, *, signed: bool = False) -> str:
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "version.py").write_text(VERSION.format(patch))
        git(repo, "add", "-A")
        if signed:
            git(repo, "-c", f"user.signingkey={self.fingerprint}", "commit", "-q", "-S",
                "-m", f"release {patch}", env=clean_env({"GNUPGHOME": self.gnupg}))
        else:
            git(repo, "commit", "-q", "-m", f"release {patch}")
        return git(repo, "rev-parse", "HEAD")

    def head(self, repo: Path | None = None) -> str:
        return git(repo or self.local, "rev-parse", "HEAD")

    def refresh(self, **kwargs):
        return update_control.refresh_checkout(self.local, timeout=30,
                                               enabled=True, **kwargs)


class OptOutTests(RepoCase):
    def test_disabled_updates_never_run_git_even_with_a_pending_update(self):
        self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "main")
        before = self.head()
        with mock.patch.object(update_control.subprocess, "run",
                               side_effect=AssertionError("git must not run")):
            self.assertIsNone(update_control.refresh_checkout(self.local, enabled=False))
            self.assertIsNone(update_control.refresh_checkout(self.local, enabled=False, verify=True))
        self.assertEqual(self.head(), before)

    def test_default_behaviour_is_unchanged_a_plain_fast_forward_pull(self):
        target = self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "main")
        notice = self.refresh()
        self.assertEqual(self.head(), target)
        self.assertIn("v1.0.2 downloaded", notice)

    def test_settings_exist_with_the_documented_defaults_and_reach_the_updater(self):
        try:
            import cast_widgets
        except ImportError as exc:  # GTK tests skip without a usable PyGObject, never fail
            if (exc.name or "").split(".")[0] != "gi":
                raise
            self.skipTest("requires a working PyGObject (gi)")
        import settings
        self.assertIs(cast_widgets.DEFAULTS["check_release_updates"], False)
        self.assertIs(cast_widgets.DEFAULTS["release_check_verify"], True)
        defaults = settings.UpdateSettings.from_config({})
        self.assertFalse(defaults.check_releases)            # opt-in
        self.assertTrue(defaults.verify_release)             # verified unless explicitly disabled
        # Legacy keys never switch checking on or verification off.
        legacy = settings.UpdateSettings.from_config({"auto_update": True, "verify_updates": False})
        self.assertFalse(legacy.check_releases)
        self.assertTrue(legacy.verify_release)
        # Only a real boolean opts in, and a junk value never weakens verification.
        self.assertTrue(settings.UpdateSettings.from_config({"check_release_updates": True}).check_releases)
        self.assertFalse(settings.UpdateSettings.from_config({"check_release_updates": "yes"}).check_releases)
        self.assertTrue(settings.UpdateSettings.from_config({"release_check_verify": "no"}).verify_release)
        self.assertFalse(settings.UpdateSettings.from_config({"release_check_verify": False}).verify_release)


    def test_channel_develop_discovery_is_read_only_even_without_version_bump(self):
        git(self.dev, "checkout", "-q", "-b", "develop")
        (self.dev / "README.md").write_text("develop changed without version bump")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", "dev snapshot")
        target = git(self.dev, "rev-parse", "HEAD")
        git(self.dev, "push", "-q", "origin", "develop")
        old_head = self.head()
        notice = update_control.check_release(
            self.local, enabled=True, verify=False, channel="develop", timeout=30,
        )
        self.assertIn("available on develop", notice)
        self.assertIn(target[:12], notice)
        self.assertEqual(self.head(), old_head)
        self.assertFalse(git(self.local, "status", "--porcelain"))

    def test_channel_main_does_not_fall_back_to_develop(self):
        git(self.dev, "checkout", "-q", "-b", "develop")
        self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "develop")
        self.assertIsNone(update_control.check_release(
            self.local, enabled=True, verify=False, channel="main", timeout=30,
        ))

    def test_invalid_channels_are_rejected_without_git_or_network(self):
        with mock.patch.object(update_control.subprocess, "run",
                               side_effect=AssertionError("untrusted channel reached Git")):
            for value in ("feature/x", "", "MAIN", "../../main", None, [], {}):
                self.assertIsNone(update_control.check_release(
                    self.local, enabled=True, verify=False, channel=value,
                ))

    def test_read_only_candidate_check_never_changes_running_checkout(self):
        target = self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "main")
        original = self.head()
        checked = []
        original_run = update_control.subprocess.run

        def observe(cmd, **kwargs):
            if cmd[0] == "git":
                checked.append(cmd[1:])
            return original_run(cmd, **kwargs)

        with mock.patch.object(update_control.subprocess, "run", side_effect=observe):
            notice = update_control.check_release(
                self.local, enabled=True, verify=False, timeout=30)
        self.assertEqual(self.head(), original)
        self.assertNotEqual(target, original)
        self.assertIn("v1.0.2 is available", notice)
        self.assertIn("No files were changed", notice)
        self.assertFalse(any(cmd[0] in {"pull", "merge", "checkout", "reset"}
                             for cmd in checked))
        self.assertFalse(git(self.local, "status", "--porcelain"))
        self.assertEqual(git(self.local, "rev-parse", "refs/remotes/origin/main"), target)

    def test_read_only_check_does_nothing_until_explicitly_opted_in(self):
        self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "main")
        with mock.patch.object(update_control.subprocess, "run",
                               side_effect=AssertionError("no git or network")):
            self.assertIsNone(update_control.check_release(self.local))
            self.assertIsNone(update_control.check_release(
                self.local, enabled=False, verify=True))

    def test_unsigned_candidate_is_not_offered_as_trusted(self):
        target = self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "main")
        before = self.head()
        with mock.patch.object(update_control, "_signature_ok", return_value=False):
            notice = update_control.check_release(
                self.local, enabled=True, verify=True, timeout=30)
        self.assertIn("signature could not be verified", notice)
        self.assertEqual(self.head(), before)
        self.assertNotEqual(self.head(), target)

    def test_verification_is_pinned_to_release_branch_after_tag_fetch(self):
        old = self.head(self.dev)
        target = self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "main")
        # An unrelated annotated tag is deliberately fetched too; it must
        # never change the SHA that the check verifies or announces.
        git(self.dev, "tag", "-a", "-m", "unrelated", "v0.0.1", old)
        git(self.dev, "push", "-q", "origin", "v0.0.1")
        verified = []
        with mock.patch.object(update_control, "_signature_ok",
                               side_effect=lambda _repo, sha, _timeout:
                               verified.append(sha) or True):
            notice = update_control.check_release(
                self.local, enabled=True, verify=True, timeout=30)
        self.assertEqual(verified, [target])
        self.assertIn("v1.0.2 is available", notice)
        self.assertNotEqual(self.head(), target)

    def test_dirty_and_developer_checkout_never_check_the_network(self):
        self.commit(self.dev, 2)
        git(self.dev, "push", "-q", "origin", "main")
        (self.local / "scratch.txt").write_text("uncommitted user work")
        with mock.patch.object(update_control, "_fetch_branch",
                               side_effect=AssertionError("must not fetch")):
            self.assertIsNone(update_control.check_release(
                self.local, enabled=True, verify=False))
            (self.local / "scratch.txt").unlink()
            git(self.local, "checkout", "-q", "-b", "develop")
            self.assertIsNone(update_control.check_release(
                self.local, enabled=True, verify=False))

    def test_same_version_and_invalid_remote_source_do_not_prompt(self):
        (self.dev / "README.md").write_text("only source changed")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", "no release bump")
        git(self.dev, "push", "-q", "origin", "main")
        self.assertIsNone(update_control.check_release(
            self.local, enabled=True, verify=False, timeout=30))
        (self.dev / "src" / "version.py").write_text("def broken(:\n")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", "broken version")
        git(self.dev, "push", "-q", "origin", "main")
        self.assertIsNone(update_control.check_release(
            self.local, enabled=True, verify=False, timeout=30))

@unittest.skipUnless(HAVE_GPG, "gpg is needed for real signature verification")
class VerifiedUpdateTests(RepoCase):
    def push_new(self, patch: int, *, signed: bool) -> str:
        sha = self.commit(self.dev, patch, signed=signed)
        git(self.dev, "push", "-q", "origin", "main")
        return sha

    def verify_env(self):
        return mock.patch.dict(os.environ, {"GNUPGHOME": self.gnupg, "GIT_CONFIG_GLOBAL": os.devnull,
                                            "GIT_CONFIG_SYSTEM": os.devnull})

    def test_signed_commit_is_applied(self):
        target = self.push_new(2, signed=True)
        with self.verify_env():
            notice = self.refresh(verify=True)
        self.assertEqual(self.head(), target)
        self.assertIn("v1.0.2 downloaded", notice)

    def test_unsigned_commit_is_reported_not_applied(self):
        before = self.head()
        target = self.push_new(2, signed=False)
        with self.verify_env():
            notice = self.refresh(verify=True)
        self.assertEqual(self.head(), before)                # working tree untouched
        self.assertIn(target[:8], notice)
        self.assertIn("signature could not be verified", notice)
        self.assertIn("verify_updates", notice)

    def test_signed_tag_on_an_unsigned_commit_is_accepted(self):
        target = self.push_new(2, signed=False)
        git(self.dev, "-c", f"user.signingkey={self.fingerprint}", "tag", "-s", "-m", "v1.0.2", "v1.0.2",
            env=clean_env({"GNUPGHOME": self.gnupg}))
        git(self.dev, "push", "-q", "origin", "v1.0.2")
        with self.verify_env():
            self.refresh(verify=True)
        self.assertEqual(self.head(), target)

    def test_signature_from_a_key_the_user_does_not_trust_is_rejected(self):
        before = self.head()
        self.push_new(2, signed=True)
        with tempfile.TemporaryDirectory(dir="/tmp") as empty:   # a keyring without that key
            os.chmod(empty, 0o700)
            with mock.patch.dict(os.environ, {"GNUPGHOME": empty, "GIT_CONFIG_GLOBAL": os.devnull,
                                              "GIT_CONFIG_SYSTEM": os.devnull}):
                notice = self.refresh(verify=True)
        self.assertEqual(self.head(), before)
        self.assertIn("not applied", notice)

    def test_diverged_local_history_is_never_touched(self):
        local_commit = self.commit(self.local, 7)            # local-only commit, clean tree
        self.push_new(2, signed=True)
        with self.verify_env():
            self.assertIsNone(self.refresh(verify=True))
        self.assertEqual(self.head(), local_commit)

    def test_already_up_to_date_and_unreachable_origin_are_quiet(self):
        with self.verify_env():
            self.assertIsNone(self.refresh(verify=True))      # nothing new
            shutil.rmtree(self.origin)
            self.assertIsNone(self.refresh(verify=True))      # fetch fails

    def test_dirty_tree_and_non_release_branch_are_never_updated_even_when_verified(self):
        self.push_new(2, signed=True)
        (self.local / "scratch.txt").write_text("uncommitted work")
        before = self.head()
        with self.verify_env():
            self.assertIsNone(self.refresh(verify=True))
            (self.local / "scratch.txt").unlink()
            git(self.local, "checkout", "-q", "-b", "feature")
            self.assertIsNone(self.refresh(verify=True))
        self.assertEqual(self.head(), before)


if __name__ == "__main__":
    unittest.main()
