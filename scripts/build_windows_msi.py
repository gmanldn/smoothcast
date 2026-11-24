#!/usr/bin/env python3
"""Build, verify and hash the SmoothCast Windows MSI with one command (#534).

Run on Windows x64 from the MSYS2 UCRT64 Python that can import GTK4,
libadwaita and PyInstaller. The script never installs tools, signs the MSI,
starts the GUI or contacts a receiver. PyInstaller stays the only payload
authority (`scripts/build_release.py`); WiX v6 turns the verified payload
manifest into the canonical per-user MSI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "scripts", ROOT / "scripts" / "ci",
              ROOT / "scripts" / "packaging"):
    sys.path.insert(0, str(extra))

import version as source_version  # noqa: E402
import windows_payload  # noqa: E402
import wix_payload  # noqa: E402

PAYLOAD = ROOT / "dist" / "SmoothCast"
MANIFEST = PAYLOAD / windows_payload.MANIFEST
PRODUCT = ROOT / "packaging" / "windows" / "Product.wxs"
ICON = ROOT / "build" / "pyinstaller" / "icons" / "SmoothCast.ico"
FRAGMENT = ROOT / "build" / "msi" / "Payload.wxs"
BUILD_DIR = ROOT / "build" / "msi"
BUILD_RELEASE = ROOT / "scripts" / "build_release.py"
WIX_MAJOR = 6
WIX_PIN = "6.0.2"
MEDIA_TOOLS = ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")
PROTECTED_OUTPUTS = (ROOT / "src", ROOT / "scripts", ROOT / "packaging",
                     ROOT / "tests", ROOT / ".github")
WIX_NS = wix_payload.WIX_NS


class PrereqError(RuntimeError):
    """The machine lacks a required tool or platform; exit code 2."""


class BuildError(RuntimeError):
    """The payload, MSI build or verification failed; exit code 1."""


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise PrereqError(f"{command[0]} is not on PATH: {exc}") from None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise BuildError(f"{command[0]} failed ({exc.returncode}): {detail[-1500:]}") from None


def parse_wix_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise PrereqError(f"cannot read the WiX version from {text!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def wix_exe() -> str:
    found = shutil.which("wix")
    if not found:
        raise PrereqError("WiX v6 'wix' is not on PATH; install with: "
                          f"dotnet tool install --global wix --version {WIX_PIN}")
    return found


def release_version() -> str:
    return source_version.__version__


def source_revision() -> str:
    if not shutil.which("git"):
        raise PrereqError("git is required to bind the MSI to a source commit")
    revision = _run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"]).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise BuildError(f"cannot resolve the source commit (got {revision!r})")
    dirty = _run(["git", "-C", str(ROOT), "status", "--porcelain",
                  "--untracked-files=no"]).stdout.strip()
    if dirty:
        raise BuildError("tracked files are modified; commit them before building an MSI")
    return revision


def check_environment() -> dict[str, str]:
    if sys.platform != "win32":
        raise PrereqError("the MSI build needs native Windows x64 (PyInstaller and WiX do not "
                          "cross-compile)")
    if struct.calcsize("P") * 8 != 64:
        raise PrereqError("a 64-bit (UCRT64) Python is required")
    wix = wix_exe()
    wix_version = parse_wix_version(_run([wix, "--version"]).stdout)
    if wix_version[0] != WIX_MAJOR:
        raise PrereqError(f"WiX {wix_version[0]} is installed; this package needs pinned WiX "
                          f"v{WIX_MAJOR} ({WIX_PIN})")
    if wix_version < (6, 0, 2):
        raise PrereqError(f"WiX {'.'.join(map(str, wix_version))} is older than the pinned "
                          f"{WIX_PIN}")
    import build_release
    try:
        build_release.check_environment()
    except build_release.BuildError as exc:
        raise PrereqError(str(exc)) from None
    return {"python": sys.version.split()[0], "wix": ".".join(map(str, wix_version)),
            "version": release_version(), "commit": source_revision()}


def ensure_output_dir(output_dir: Path) -> Path:
    target = output_dir.expanduser().resolve()
    if target == ROOT.resolve():
        raise BuildError("refusing to write release artefacts into the repository root")
    if any(target == path.resolve() or path.resolve() in target.parents
           for path in PROTECTED_OUTPUTS):
        raise BuildError(f"refusing to write release artefacts into {target}")
    return target


def stage_media(media_dir: Path | None) -> list[str]:
    if media_dir is None:
        return []
    source = media_dir.expanduser().resolve()
    if not source.is_dir():
        raise BuildError(f"{source} is not a directory")
    missing = [name for name in MEDIA_TOOLS if not (source / name).is_file()]
    if missing:
        raise BuildError(f"approved media sidecars are incomplete: {', '.join(missing)}")
    target = PAYLOAD / "ffmpeg"
    target.mkdir(parents=True, exist_ok=True)
    for name in MEDIA_TOOLS:
        image = windows_payload.PE((source / name).read_bytes())
        if image.machine != windows_payload.MACHINE_X64:
            raise BuildError(f"{name}: media sidecars must be x64")
        shutil.copy2(source / name, target / name)
    return [f"ffmpeg/{name}" for name in MEDIA_TOOLS]


def freeze_payload(*, skip_pyinstaller: bool, media_dir: Path | None) -> tuple[Path, int]:
    if not skip_pyinstaller:
        _run([sys.executable, str(BUILD_RELEASE)])
    elif not PAYLOAD.is_dir():
        raise BuildError("--skip-pyinstaller needs the pre-built dist/SmoothCast payload")
    stage_media(media_dir)
    manifest = windows_payload.write_manifest(PAYLOAD, release_version())
    problems = windows_payload.verify(PAYLOAD, release_version())
    if problems:
        shown = "\n".join(f"- {problem}" for problem in problems[:20])
        raise BuildError(f"payload is not MSI-ready:\n{shown}")
    try:
        count = len(json.loads(manifest.read_text(encoding="utf-8"))["files"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BuildError(f"cannot read the frozen manifest: {exc}") from None
    return manifest, count


def generate_fragment(manifest: Path) -> int:
    try:
        paths = wix_payload.load_files(manifest)
        text = wix_payload.render(paths)
    except wix_payload.WixError as exc:
        raise BuildError(f"cannot author the WiX fragment: {exc}") from None
    FRAGMENT.parent.mkdir(parents=True, exist_ok=True)
    FRAGMENT.write_text(text, encoding="utf-8", newline="\n")
    return len(paths)


def wix_build(msi: Path, *, manufacturer: str, version: str, commit: str) -> None:
    if not re.fullmatch(r"[^\r\n\x00]{1,200}", manufacturer):
        raise BuildError("the installer manufacturer is empty or contains a newline")
    if not ICON.is_file():
        raise BuildError(f"installer icon is missing: {ICON} (rerun the PyInstaller build)")
    if not PRODUCT.is_file():
        raise BuildError(f"installer authoring is missing: {PRODUCT}")
    msi.parent.mkdir(parents=True, exist_ok=True)
    _run([wix_exe(), "build", "-arch", "x64", "-pdbtype", "none",
          "-d", f"ProductVersion={wix_payload.msi_version(version)}",
          "-d", f"Manufacturer={manufacturer}",
          "-d", f"PayloadDir={PAYLOAD.resolve()}",
          "-d", f"IconFile={ICON.resolve()}",
          "-d", f"SourceRevision={commit}",
          "-o", str(msi), str(PRODUCT), str(FRAGMENT)])


def product_upgrade_code() -> str:
    package = ET.parse(PRODUCT).getroot().find(f"{{{WIX_NS}}}Package")
    if package is None or not package.get("UpgradeCode"):
        raise BuildError(f"{PRODUCT} has no permanent UpgradeCode")
    return package.get("UpgradeCode")  # type: ignore[return-value]


def verify_msi(msi: Path, *, version: str, commit: str, expected_files: int) -> None:
    """Read the finished MSI back as authoring; no installation or signing."""
    output = BUILD_DIR / "decompiled.wxs"
    _run([wix_exe(), "msi", "decompile", "-o", str(output), str(msi)])
    try:
        root = ET.fromstring(output.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        raise BuildError(f"cannot read the built MSI: {exc}") from None
    package = root.find(f".//{{{WIX_NS}}}Package")
    if package is None:
        raise BuildError("the built MSI has no Package identity")
    if package.get("Version") != wix_payload.msi_version(version):
        raise BuildError(f"MSI ProductVersion {package.get('Version')} does not match {version}")
    if package.get("UpgradeCode") != product_upgrade_code():
        raise BuildError("MSI UpgradeCode changed; Windows would treat it as a new product")
    if package.get("Scope") not in (None, "perUser"):
        raise BuildError(f"MSI scope is {package.get('Scope')}, expected perUser")
    files = list(root.iter(f"{{{WIX_NS}}}File"))
    if len(files) != expected_files:
        raise BuildError(f"MSI file table has {len(files)} files; the manifest has "
                         f"{expected_files}")
    names = {(element.get("Name") or element.get("Source") or "").replace("\\", "/")
             .rsplit("/", 1)[-1].casefold() for element in files}
    for required in (windows_payload.GUI_EXE, windows_payload.CLI_EXE):
        if required.casefold() not in names:
            raise BuildError(f"MSI file table is missing {required}")
    properties = {element.get("Id"): element.get("Value")
                  for element in root.iter(f"{{{WIX_NS}}}Property")}
    if properties.get("SMOOTHCAST_SOURCE_REVISION") != commit:
        raise BuildError("MSI does not carry the verified source commit")


def write_sha256(msi: Path) -> tuple[str, Path]:
    digest = hashlib.sha256()
    with msi.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    checksum = msi.with_name(msi.name + ".sha256")
    checksum.write_text(f"{digest.hexdigest()}  {msi.name}\n", encoding="utf-8", newline="\n")
    return digest.hexdigest(), checksum


def build(options: argparse.Namespace) -> dict[str, object]:
    environment = check_environment()
    output_dir = ensure_output_dir(options.output_dir)
    commit = environment["commit"]
    version = environment["version"]
    final = output_dir / f"SmoothCast-{version}-x64.msi"
    if final.exists() and not options.force:
        raise BuildError(f"{final} already exists; pass --force to replace this test build")
    manifest, expected_files = freeze_payload(
        skip_pyinstaller=options.skip_pyinstaller, media_dir=options.media_dir)
    generate_fragment(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    temporary = BUILD_DIR / final.name
    temporary.unlink(missing_ok=True)
    try:
        wix_build(temporary, manufacturer=options.manufacturer, version=version, commit=commit)
        verify_msi(temporary, version=version, commit=commit, expected_files=expected_files)
        os.replace(temporary, final)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    digest, checksum = write_sha256(final)
    return {"status": "ok", "signed": False, "version": version, "commit": commit,
            "msi": str(final), "sha256": digest, "checksum": str(checksum),
            "files": expected_files, "manifest": str(manifest),
            "manufacturer": options.manufacturer}


def check_report() -> dict[str, object]:
    environment = check_environment()
    manifest = MANIFEST
    payload = "missing"
    if manifest.is_file():
        problems = windows_payload.verify(PAYLOAD, environment["version"])
        payload = "verified" if not problems else f"{len(problems)} problem(s)"
    return {"status": "ok", **environment, "payload": payload, "icon": ICON.is_file()}


def _print_failure(message: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"status": "error", "error": message}, sort_keys=True))
    print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report prerequisites and payload state without building")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist",
                        help="where the MSI and .sha256 are written (default: dist/)")
    parser.add_argument("--skip-pyinstaller", action="store_true",
                        help="reuse a pre-built dist/SmoothCast only after verifying it")
    parser.add_argument("--media-dir", type=Path,
                        help="approved x64 ffmpeg/ffprobe/ffplay sidecars to stage")
    parser.add_argument("--manufacturer", default=os.environ.get(
        "SMOOTHCAST_WINDOWS_MANUFACTURER", "SmoothCast"),
        help="installer publisher identity (default: SmoothCast)")
    parser.add_argument("--force", action="store_true", help="replace an existing test MSI")
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    options = parser.parse_args(argv)
    try:
        if options.check:
            report = check_report()
            if options.json:
                print(json.dumps(report, sort_keys=True))
            else:
                print(f"MSI build prerequisites OK: Python {report['python']}, "
                      f"WiX {report['wix']}, version {report['version']}, "
                      f"payload {report['payload']}.")
            return 0
        result = build(options)
        if options.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"Unsigned test MSI: {result['msi']}\nSHA-256: {result['sha256']}  "
                  f"{Path(str(result['msi'])).name}")
        return 0
    except PrereqError as exc:
        _print_failure(f"missing prerequisite: {exc}", options.json)
        return 2
    except BuildError as exc:
        _print_failure(f"MSI build failed: {exc}", options.json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())