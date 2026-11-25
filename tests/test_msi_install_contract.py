"""Portable tests: never start msiexec or touch an installed product."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ci"))
import msi_install_contract as contract  # noqa: E402


class InstallerContractTests(unittest.TestCase):
    def test_hash_and_corrupt_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SmoothCast.msi"
            path.write_bytes(b"candidate")
            expected = hashlib.sha256(b"candidate").hexdigest()
            self.assertEqual(contract.verify_candidate(path, expected), expected)
            path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(contract.InstallerError, "mismatch"):
                contract.verify_candidate(path, expected)
            with self.assertRaisesRegex(contract.InstallerError, "invalid expected"):
                contract.verify_candidate(path, "not a hash")

    def test_operations_preserve_argv_and_forbid_restart(self):
        root = Path.cwd()
        exe = root / "Windows" / "System32" / "msiexec.exe"
        msi = root / "Unicode café folder" / "SmoothCast.msi"
        log = root / "logs" / "install.log"
        for operation, switch in (("install", "/i"), ("repair", "/fa"), ("uninstall", "/x")):
            with self.subTest(operation=operation):
                self.assertEqual(contract.installer_command(exe, operation, msi, log),
                                 [str(exe), switch, str(msi), "/qn", "/norestart", "/L*v", str(log)])
        with self.assertRaises(contract.InstallerError):
            contract.installer_command(exe, "unknown", msi, log)
        with self.assertRaises(contract.InstallerError):
            contract.installer_command(Path("msiexec.exe"), "install", msi, log)

    def test_exit_codes_and_timeout(self):
        argv = ["msiexec.exe"]
        run = Mock(return_value=subprocess.CompletedProcess(argv, 0))
        self.assertEqual(contract.run_installer(argv, run=run), 0)
        run.assert_called_once_with(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                    timeout=180, check=False)
        for code in (1603, 1618, 3010, 1641):
            with self.subTest(code=code):
                run.return_value = subprocess.CompletedProcess(argv, code)
                with self.assertRaisesRegex(contract.InstallerError, str(code)):
                    contract.run_installer(argv, run=run)
        run.side_effect = subprocess.TimeoutExpired(argv, 180)
        with self.assertRaisesRegex(contract.InstallerError, "discard the target"):
            contract.run_installer(argv, run=run)
        run.side_effect = FileNotFoundError()
        with self.assertRaisesRegex(contract.InstallerError, "could not start"):
            contract.run_installer(argv, run=run)

    def test_invalid_deadline_does_not_execute(self):
        run = Mock()
        with self.assertRaises(contract.InstallerError):
            contract.run_installer(["msiexec.exe"], timeout=0, run=run)
        run.assert_not_called()
