"""Headless tests for the one-command Windows MSI driver (#534)."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_build_windows_msi", ROOT / "scripts" / "build_windows_msi.py"
)
msi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(msi)


def options(**overrides):
    values = {"check": False, "output_dir": ROOT / "dist", "skip_pyinstaller": True,
              "media_dir": None, "manufacturer": "SmoothCast", "force": False, "json": False}
    values.update(overrides)
    return argparse.Namespace(**values)


class EnvironmentTests(unittest.TestCase):
    def test_wix_version_parser_reads_the_installed_build(self):
        self.assertEqual(msi.parse_wix_version("6.0.2.0"), (6, 0, 2))
        self.assertEqual(msi.parse_wix_version("wix.exe 6.0.11+abc"), (6, 0, 11))
        with self.assertRaises(msi.PrereqError):
            msi.parse_wix_version("not a version")

    def test_check_environment_refuses_non_windows_without_a_build(self):
        with mock.patch.object(msi.sys, "platform", "linux"), \
                mock.patch.object(msi, "_run") as run:
            with self.assertRaises(msi.PrereqError):
                msi.check_environment()
        run.assert_not_called()

    def test_check_environment_requires_pinned_wix_v6(self):
        with mock.patch.object(msi.sys, "platform", "win32"), \
                mock.patch.object(msi.struct, "calcsize", return_value=8), \
                mock.patch.object(msi, "wix_exe", return_value="wix"), \
                mock.patch.object(msi, "_run",
                                  return_value=SimpleNamespace(stdout="5.0.2.0\n")):
            with self.assertRaises(msi.PrereqError):
                msi.check_environment()

    def test_output_directory_must_not_overwrite_sources(self):
        with self.assertRaises(msi.BuildError):
            msi.ensure_output_dir(ROOT)
        with self.assertRaises(msi.BuildError):
            msi.ensure_output_dir(ROOT / "src")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(msi.ensure_output_dir(Path(folder)), Path(folder).resolve())


class PayloadTests(unittest.TestCase):
    def test_reusing_a_payload_requires_the_payload_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(msi, "PAYLOAD", Path(folder) / "missing"):
                with self.assertRaises(msi.BuildError):
                    msi.freeze_payload(skip_pyinstaller=True, media_dir=None)

    def test_frozen_manifest_problems_block_the_msi(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = Path(folder)
            manifest = payload / msi.windows_payload.MANIFEST
            manifest.write_text(json.dumps({"files": [{"path": "a"}]}), encoding="utf-8")
            with mock.patch.object(msi, "PAYLOAD", payload), \
                    mock.patch.object(msi.windows_payload, "write_manifest",
                                      return_value=manifest), \
                    mock.patch.object(msi.windows_payload, "verify",
                                      return_value=["SmoothCast.exe: changed"]):
                with self.assertRaisesRegex(msi.BuildError, "changed"):
                    msi.freeze_payload(skip_pyinstaller=True, media_dir=None)

    def test_frozen_manifest_count_is_returned(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = Path(folder)
            manifest = payload / msi.windows_payload.MANIFEST
            manifest.write_text(json.dumps({"files": [{"path": "a"}, {"path": "b"}]}),
                                encoding="utf-8")
            with mock.patch.object(msi, "PAYLOAD", payload), \
                    mock.patch.object(msi.windows_payload, "write_manifest",
                                      return_value=manifest), \
                    mock.patch.object(msi.windows_payload, "verify", return_value=[]):
                path, count = msi.freeze_payload(skip_pyinstaller=True, media_dir=None)
            self.assertEqual((path, count), (manifest, 2))

    def test_media_staging_requires_three_x64_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "media"
            source.mkdir()
            for name in msi.MEDIA_TOOLS:
                (source / name).write_bytes(b"MZ")
            payload = Path(folder) / "payload"
            payload.mkdir()
            with mock.patch.object(msi, "PAYLOAD", payload), \
                    mock.patch.object(msi.windows_payload, "PE",
                                      return_value=SimpleNamespace(
                                          machine=msi.windows_payload.MACHINE_X64)):
                staged = msi.stage_media(source)
            self.assertEqual(staged, ["ffmpeg/ffmpeg.exe", "ffmpeg/ffprobe.exe",
                                      "ffmpeg/ffplay.exe"])
            for name in msi.MEDIA_TOOLS:
                self.assertTrue((payload / "ffmpeg" / name).is_file())
            (source / "ffplay.exe").unlink()
            with mock.patch.object(msi, "PAYLOAD", payload):
                with self.assertRaisesRegex(msi.BuildError, "incomplete"):
                    msi.stage_media(source)


class WixTests(unittest.TestCase):
    def test_product_embeds_the_verified_source_revision(self):
        product = (ROOT / "packaging" / "windows" / "Product.wxs").read_text(encoding="utf-8")
        self.assertIn('Id="SMOOTHCAST_SOURCE_REVISION" Value="$(SourceRevision)"', product)

    def test_workflow_exports_the_wix_override_for_the_msys2_step(self):
        workflow = (ROOT / ".github" / "workflows" / "package.yml").read_text(encoding="utf-8")
        self.assertIn('SMOOTHCAST_WIX=$env:USERPROFILE\\.dotnet\\tools\\wix.exe', workflow)

    def test_wix_exe_prefers_an_existing_smoothcast_wix_override(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "wix.exe"
            fake.write_bytes(b"")
            with mock.patch.dict(os.environ, {"SMOOTHCAST_WIX": str(fake)}):
                self.assertEqual(msi.wix_exe(), str(fake))

    def test_wix_exe_falls_back_to_path_when_override_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            gone = Path(folder) / "gone.exe"
            with mock.patch.dict(os.environ, {"SMOOTHCAST_WIX": str(gone)}):
                with mock.patch.object(msi.shutil, "which", return_value="C:/tools/wix.exe"):
                    self.assertEqual(msi.wix_exe(), "C:/tools/wix.exe")

    def test_wix_exe_fails_with_the_install_hint_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMOOTHCAST_WIX", None)
            with mock.patch.object(msi.shutil, "which", return_value=None):
                with self.assertRaises(msi.PrereqError) as raised:
                    msi.wix_exe()
        self.assertIn("dotnet tool install", str(raised.exception))

    def test_workflow_exports_the_git_override_for_the_msys2_step(self):
        workflow = (ROOT / ".github" / "workflows" / "package.yml").read_text(encoding="utf-8")
        self.assertIn("SMOOTHCAST_GIT=$((Get-Command git).Source)", workflow)

    def test_git_exe_prefers_an_existing_smoothcast_git_override(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "git.exe"
            fake.write_bytes(b"")
            with mock.patch.dict(os.environ, {"SMOOTHCAST_GIT": str(fake)}):
                self.assertEqual(msi.git_exe(), str(fake))

    def test_git_exe_falls_back_to_the_git_for_windows_installation(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMOOTHCAST_GIT", None)
            with mock.patch.object(msi.shutil, "which", return_value=None):
                with mock.patch.object(msi.Path, "is_file", return_value=False):
                    with self.assertRaises(msi.PrereqError) as raised:
                        msi.git_exe()
        self.assertIn("SMOOTHCAST_GIT", str(raised.exception))

    def test_build_command_is_a_list_with_stable_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            product = Path(folder) / "Product.wxs"
            icon = Path(folder) / "SmoothCast.ico"
            payload = Path(folder) / "payload"
            fragment = Path(folder) / "Payload.wxs"
            for path in (product, icon, fragment):
                path.write_bytes(b"x")
            payload.mkdir()
            calls = []
            with mock.patch.object(msi, "PRODUCT", product), \
                    mock.patch.object(msi, "ICON", icon), \
                    mock.patch.object(msi, "FRAGMENT", fragment), \
                    mock.patch.object(msi, "PAYLOAD", payload), \
                    mock.patch.object(msi, "wix_exe", return_value="wix"), \
                    mock.patch.object(msi, "_run",
                                      side_effect=lambda command: calls.append(command)):
                msi.wix_build(Path(folder) / "out.msi", manufacturer="SmoothCast",
                              version="2.0.38", commit="a" * 40)
            command = calls[0]
            self.assertEqual(command[:3], ["wix", "build", "-arch"])
            self.assertIn("ProductVersion=2.0.38", command)
            self.assertIn("SourceRevision=" + "a" * 40, command)
            self.assertIn(str(product), command)
            self.assertIn(str(fragment), command)

    def _decompile(self, text):
        def run(command):
            target = Path(command[command.index("-o") + 1])
            target.write_text(text, encoding="utf-8")
        return run

    def _msi(self, *, version="2.0.38", files=2, commit="a" * 40, scope="perUser"):
        names = ["SmoothCast.exe", "SmoothCastCLI.exe"][:files]
        file_xml = "".join(f'<File Id="F{i}" Name="{name}" />'
                           for i, name in enumerate(names))
        return (f'<Wix xmlns="{msi.WIX_NS}"><Package Version="{version}" '
                f'UpgradeCode="{msi.product_upgrade_code()}" Scope="{scope}">'
                f'<Property Id="SMOOTHCAST_SOURCE_REVISION" Value="{commit}" />'
                f'{file_xml}</Package></Wix>')

    def test_finished_msi_is_read_back_as_authoring(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(msi, "BUILD_DIR", Path(folder)), \
                mock.patch.object(msi, "wix_exe", return_value="wix"), \
                mock.patch.object(msi, "_run",
                                  side_effect=self._decompile(self._msi())):
            msi.verify_msi(Path(folder) / "test.msi", version="2.0.38",
                           commit="a" * 40, expected_files=2)

    def test_finished_msi_must_match_version_file_table_and_commit(self):
        cases = [
            (self._msi(version="2.0.37"), "ProductVersion"),
            (self._msi(files=1), "file table"),
            (self._msi(commit="b" * 40), "source commit"),
            (self._msi(scope="perMachine"), "perUser"),
        ]
        for text, expected in cases:
            with self.subTest(expected=expected), \
                    tempfile.TemporaryDirectory() as folder, \
                    mock.patch.object(msi, "BUILD_DIR", Path(folder)), \
                    mock.patch.object(msi, "wix_exe", return_value="wix"), \
                    mock.patch.object(msi, "_run", side_effect=self._decompile(text)):
                with self.assertRaisesRegex(msi.BuildError, expected):
                    msi.verify_msi(Path(folder) / "test.msi", version="2.0.38",
                                   commit="a" * 40, expected_files=2)


class BuildTests(unittest.TestCase):
    def test_failure_leaves_no_canonical_msi(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "dist"
            build_dir = Path(folder) / "build"
            final = output / "SmoothCast-2.0.38-x64.msi"

            def fail(msi_path, **_kwargs):
                msi_path.parent.mkdir(parents=True, exist_ok=True)
                msi_path.write_bytes(b"partial")
                raise msi.BuildError("wix failed")

            with mock.patch.object(msi, "check_environment",
                                   return_value={"commit": "a" * 40, "version": "2.0.38",
                                                 "wix": "6.0.2", "python": "3.13"}), \
                    mock.patch.object(msi, "freeze_payload",
                                      return_value=(Path(folder) / "manifest.json", 2)), \
                    mock.patch.object(msi, "generate_fragment", return_value=2), \
                    mock.patch.object(msi, "BUILD_DIR", build_dir), \
                    mock.patch.object(msi, "wix_build", side_effect=fail):
                with self.assertRaises(msi.BuildError):
                    msi.build(options(output_dir=output))
            self.assertFalse(final.exists())
            self.assertFalse((build_dir / final.name).exists())

    def test_success_publishes_only_after_verification_and_hashes_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "dist"
            build_dir = Path(folder) / "build"

            def succeed(msi_path, **_kwargs):
                msi_path.parent.mkdir(parents=True, exist_ok=True)
                msi_path.write_bytes(b"not a real msi")

            with mock.patch.object(msi, "check_environment",
                                   return_value={"commit": "a" * 40, "version": "2.0.38",
                                                 "wix": "6.0.2", "python": "3.13"}), \
                    mock.patch.object(msi, "freeze_payload",
                                      return_value=(Path(folder) / "manifest.json", 2)), \
                    mock.patch.object(msi, "generate_fragment", return_value=2), \
                    mock.patch.object(msi, "BUILD_DIR", build_dir), \
                    mock.patch.object(msi, "wix_build", side_effect=succeed), \
                    mock.patch.object(msi, "verify_msi"):
                result = msi.build(options(output_dir=output))
            final = output / "SmoothCast-2.0.38-x64.msi"
            self.assertTrue(final.is_file())
            checksum = final.with_name(final.name + ".sha256").read_text(encoding="utf-8")
            self.assertEqual(checksum, f"{result['sha256']}  {final.name}\n")
            self.assertFalse(result["signed"])

    def test_existing_msi_is_not_replaced_without_force(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "dist"
            output.mkdir()
            final = output / "SmoothCast-2.0.38-x64.msi"
            final.write_bytes(b"published")
            with mock.patch.object(msi, "check_environment",
                                   return_value={"commit": "a" * 40, "version": "2.0.38",
                                                 "wix": "6.0.2", "python": "3.13"}), \
                    mock.patch.object(msi, "freeze_payload",
                                      return_value=(Path(folder) / "manifest.json", 2)), \
                    mock.patch.object(msi, "generate_fragment", return_value=2):
                with self.assertRaisesRegex(msi.BuildError, "--force"):
                    msi.build(options(output_dir=output))
            self.assertEqual(final.read_bytes(), b"published")


class CliTests(unittest.TestCase):
    def test_check_json_is_machine_readable(self):
        stdout = io.StringIO()
        with mock.patch.object(msi, "check_report", return_value={"status": "ok",
                                                                  "version": "2.0.38"}), \
                contextlib.redirect_stdout(stdout):
            self.assertEqual(msi.main(["--check", "--json"]), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "ok", "version": "2.0.38"})

    def test_failures_return_distinct_exit_codes_and_json(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(msi, "check_report", side_effect=msi.PrereqError("no WiX")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(msi.main(["--check", "--json"]), 2)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "error")
        self.assertIn("missing prerequisite", stderr.getvalue())

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(msi, "check_report", side_effect=msi.BuildError("bad payload")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(msi.main(["--check"]), 1)
        self.assertIn("MSI build failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()