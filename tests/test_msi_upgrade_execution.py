"""Exercise MSI matrix control flow without starting Windows Installer."""
import hashlib
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ci"))
import msi_upgrade_matrix as matrix  # noqa: E402


@pytest.mark.parametrize("versions", ["2.0.40\n2.0.41", "2.0.41\n2.0.41"])
def test_duplicate_registrations_fail(versions):
    with pytest.raises(matrix.UpgradeError, match="multiple"):
        matrix.parse_registered_version(versions)


def test_registration_query_failure_is_not_empty_registration():
    run = Mock(return_value=subprocess.CompletedProcess([], 1, stdout=""))
    with pytest.raises(matrix.UpgradeError, match="could not query"):
        matrix.registered_version(run)


@pytest.mark.parametrize("message", ["MSI operation timed out; discard the target",
                                      "MSI requires reboot (3010); target not qualified",
                                      "Windows Installer failed (1603)"])
def test_unrelated_install_error_does_not_prove_downgrade_rejection(tmp_path, message):
    log = tmp_path / "reject.log"
    log.write_text("A newer SmoothCast is already installed.", encoding="utf-8")
    with patch.object(matrix, "_operation", side_effect=matrix.InstallerError(message)):
        with pytest.raises(matrix.InstallerError):
            matrix._downgrade_rejected(tmp_path / "msiexec.exe", tmp_path / "a.msi", log)
    assert not log.exists()  # A stale log cannot qualify a new failure.


def test_matrix_really_uninstalls_and_checks_registration(tmp_path, monkeypatch):
    windows = tmp_path / "Windows"
    executable = windows / "System32" / "msiexec.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("SystemRoot", str(windows))
    a, b = tmp_path / "a.msi", tmp_path / "b.msi"
    a.write_bytes(b"fixture A")
    b.write_bytes(b"fixture B")
    for fixture in (a, b):
        write_checksum(fixture)
    calls = []
    registrations = iter(["", "2.0.40", "2.0.41", "2.0.41", ""])

    def installer(argv, *, timeout):
        calls.append(argv[1])
        if len(calls) == 3:
            Path(argv[-1]).write_text("A newer SmoothCast is already installed.", encoding="utf-16")
            raise matrix.InstallerError("Windows Installer failed (1603)")

    def registry(*args, **kwargs):
        return subprocess.CompletedProcess([], 0, stdout=next(registrations))

    with patch.object(matrix, "require_disposable"), patch.object(matrix, "run_installer", installer):
        result = matrix.run_matrix(a, b, "2.0.40", "2.0.41", report=tmp_path / "report.json",
                                   os_build="fixture", runner="mock", commit="fixture", run=registry)
    assert result["ok"]
    assert calls == ["/i", "/i", "/i", "/x"]
    assert next(registrations, None) is None


def write_checksum(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def test_fixture_requires_builder_checksum(tmp_path):
    fixture = tmp_path / "a.msi"
    fixture.write_bytes(b"fixture A")
    with pytest.raises(matrix.InstallerError, match="missing"):
        matrix._fixture_digest(fixture)
    digest = write_checksum(fixture)
    assert matrix._fixture_digest(fixture) == digest
    fixture.write_bytes(b"tampered")
    with pytest.raises(matrix.InstallerError, match="SHA-256 mismatch"):
        matrix._fixture_digest(fixture)
    fixture.write_bytes(b"fixture A")
    fixture.with_name(fixture.name + ".sha256").write_text(f"{digest}  wrong.msi\n", encoding="ascii")
    with pytest.raises(matrix.InstallerError, match="filename mismatch"):
        matrix._fixture_digest(fixture)
