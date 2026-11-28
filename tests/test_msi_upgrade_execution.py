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


def test_user_settings_path_uses_appdata_and_shared_app_directory(tmp_path):
    assert matrix.user_settings_path({"APPDATA": str(tmp_path)}) == (
        tmp_path / matrix.app_paths.APP_DIR / "config.json"
    )
    assert matrix.user_settings_path({"APPDATA": "relative"}, home=tmp_path) == (
        tmp_path / "AppData" / "Roaming" / matrix.app_paths.APP_DIR / "config.json"
    )


def test_user_settings_fixture_restores_existing_and_absent_state(tmp_path):
    absent = tmp_path / "new" / matrix.app_paths.APP_DIR / "config.json"
    expected, existed, made = matrix._prepare_user_settings(absent)
    assert not existed and absent.read_bytes() == matrix._SETTINGS_FIXTURE
    absent.write_bytes(b"changed by hypothetical installer")
    matrix._restore_user_settings(absent, expected, existed, made)
    assert not absent.exists()
    assert not absent.parent.exists()

    present = tmp_path / "existing" / matrix.app_paths.APP_DIR / "config.json"
    present.parent.mkdir(parents=True)
    original = b'{"existing":"settings"}\n'
    present.write_bytes(original)
    snapshot, existed, made = matrix._prepare_user_settings(present)
    present.write_bytes(b"changed by hypothetical installer")
    matrix._restore_user_settings(present, snapshot, existed, made)
    assert existed and present.read_bytes() == original


def test_matrix_really_uninstalls_and_checks_registration(tmp_path, monkeypatch):
    windows = tmp_path / "Windows"
    executable = windows / "System32" / "msiexec.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("SystemRoot", str(windows))
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(appdata))
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
    assert all("user settings preserved" in step["detail"] for step in result["steps"])
    assert calls == ["/i", "/i", "/i", "/x"]
    assert next(registrations, None) is None
    assert not appdata.exists()  # the disposable settings sentinel and dirs are restored


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
