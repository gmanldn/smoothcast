"""Portable lifecycle harness preflight tests; never run Windows Installer."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ci"))
import smoke_windows_msi as smoke  # noqa: E402


class LifecyclePreflightTests(unittest.TestCase):
    def test_candidate_binds_filename_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            msi = root / "SmoothCast-2.1.0-x64.msi"
            msi.write_bytes(b"candidate")
            digest = hashlib.sha256(b"candidate").hexdigest()
            checksum = msi.with_name(msi.name + ".sha256")
            checksum.write_text(f"{digest}  {msi.name}\n", encoding="ascii")
            self.assertEqual(smoke.candidate_from(root), (msi.resolve(), digest, "2.1.0"))
            checksum.write_text(f"{digest}  wrong.msi\n", encoding="ascii")
            with self.assertRaises(smoke.InstallerError):
                smoke.candidate_from(root)

    def test_disposable_host_is_mandatory(self):
        env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
               "RUNNER_OS": "Windows", "SMOOTHCAST_TEST_CONTEXT": "1"}
        smoke.require_disposable(env, "Windows")
        for key in env:
            with self.subTest(key=key), self.assertRaises(smoke.InstallerError):
                smoke.require_disposable({k: v for k, v in env.items() if k != key}, "Windows")
        with self.assertRaises(smoke.InstallerError):
            smoke.require_disposable(env, "Linux")

    def test_developer_environment_not_inherited(self):
        env = smoke.runtime_environment(
            {"PATH": "hostile", "PYTHONPATH": "hostile", "MSYSTEM": "UCRT64",
             "GI_TYPELIB_PATH": "hostile", "TEMP": "safe"}, Path("/Windows"))
        self.assertEqual(env["TEMP"], "safe")
        for name in ("PYTHONPATH", "MSYSTEM", "GI_TYPELIB_PATH"):
            self.assertNotIn(name, env)
        self.assertNotIn("hostile", env["PATH"])

    def test_installed_cli_version_must_match_exactly(self):
        expected = "SmoothCast v2.1.6"
        for output in ("SmoothCast v2.1.60", "prefix " + expected, expected + " extra"):
            with self.subTest(output=output), patch.object(
                smoke.subprocess, "run", return_value=smoke.subprocess.CompletedProcess(
                    [], 0, stdout=output, stderr="")
            ), self.assertRaises(smoke.InstallerError):
                smoke.cli_check(Path("SmoothCastCLI.exe"), ["--version"], expected, {}, Path("."))
        with patch.object(smoke.subprocess, "run", return_value=smoke.subprocess.CompletedProcess(
            [], 0, stdout=expected + "\n", stderr=""
        )):
            smoke.cli_check(Path("SmoothCastCLI.exe"), ["--version"], expected, {}, Path("."))

    def test_installed_legal_files_and_artwork_are_bound_to_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "packaging").mkdir(parents=True)
            icon = source / "src" / "smoothcast_assets" / "local.cast-control.png"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"original artwork")
            (source / "LICENSE").write_bytes(b"original licence")
            (source / "packaging" / "SmoothCast-NOTICE.txt").write_bytes(b"original notice")
            cli = root / "installed" / "SmoothCastCLI.exe"
            legal = cli.parent / "_internal" / "legal"
            legal.mkdir(parents=True)
            (legal / "LICENSE").write_bytes(b"original licence")
            (legal / "SmoothCast-NOTICE.txt").write_bytes(b"original notice")
            expected = hashlib.sha256(b"original artwork").hexdigest()
            with patch.object(smoke, "cli_check") as check:
                smoke.check_installed_package(cli, "2.1.6", {}, root, source)
                self.assertEqual(check.call_count, 2)
                check.assert_any_call(cli, ["--version"], "SmoothCast v2.1.6", {}, root)
                check.assert_any_call(cli, ["--_smoothcast-package-check"], expected, {}, root)
            for filename in ("LICENSE", "SmoothCast-NOTICE.txt"):
                target = legal / filename
                original = target.read_bytes()
                for changed in (None, b"modified"):
                    with self.subTest(filename=filename, changed=changed), patch.object(
                        smoke, "cli_check"
                    ) as check:
                        if changed is None:
                            target.unlink()
                        else:
                            target.write_bytes(changed)
                        with self.assertRaisesRegex(smoke.InstallerError, filename):
                            smoke.check_installed_package(cli, "2.1.6", {}, root, source)
                        check.assert_not_called()
                        target.write_bytes(original)
