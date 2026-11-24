"""Deterministic manifest and static checks for the Windows ``dist/SmoothCast`` payload (#528).

Standard library only and data-only: it reads files and PE headers, never
runs the application, a helper, a receiver or anything that needs Windows, so
it is unit-tested on every OS. The WiX MSI (#531) consumes a payload only
after ``verify`` returns no problems.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import struct

MANIFEST = "payload-manifest.json"
SCHEMA = 1
PLATFORM = "windows-x64"
GUI_EXE, CLI_EXE = "SmoothCast.exe", "SmoothCastCLI.exe"
MACHINE_X64 = 0x8664
SUBSYSTEM_GUI, SUBSYSTEM_CONSOLE = 2, 3
PE_SUFFIXES = (".exe", ".dll", ".pyd")
TEXT_SUFFIXES = (".cfg", ".pth", ".json", ".txt", ".bat", ".cmd", ".ps1", ".ini", ".env")
BUILD_ROOT_MARKERS = ("msys64", "msys2", "\\mingw64\\", "\\ucrt64\\", "/ucrt64/")

# Imports the operating system always provides. Anything else a PE imports
# must travel inside the payload (compared by file name, case-insensitively).
SYSTEM_DLLS = frozenset("""
advapi32 authz bcrypt bcryptprimitives cabinet cfgmgr32 combase comctl32 comdlg32 crypt32
cryptbase cryptsp d2d1 d3d11 d3d9 dbghelp dnsapi dsound dwmapi dwrite dxgi gdi32 gdi32full glu32
hid imm32 iphlpapi kernel32 kernelbase mf mfplat mfreadwrite mmdevapi mpr msctf msimg32 msvcrt
mswsock ncrypt netapi32 normaliz ntdll ole32 oleaut32 opengl32 powrprof profapi propsys psapi
rpcrt4 sechost secur32 setupapi shcore shell32 shlwapi ucrtbase urlmon user32 userenv usp10
uxtheme version wevtapi wininet winhttp winmm winspool wintrust wldap32 ws2_32 wsock32
windowscodecs wtsapi32 avrt dcomp
""".split())
SYSTEM_PREFIXES = ("api-ms-win-", "ext-ms-win-")


class PayloadError(ValueError):
    """The tree cannot be described (unsafe path, link or duplicate)."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def payload_files(dist: Path) -> list[str]:
    """Sorted forward-slash paths of every payload file, excluding the manifest."""
    root = dist.resolve()
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if _is_link(path):
            raise PayloadError(f"{path.relative_to(root).as_posix()}: links are not allowed in the payload")
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST:
            continue
        if any(part in ("", ".", "..") for part in PurePosixPath(relative).parts):
            raise PayloadError(f"{relative}: unsafe path")
        folded = relative.casefold()
        if folded in found:
            raise PayloadError(f"{relative}: duplicates {found[folded]} when case is ignored")
        found[folded] = relative
    return sorted(found.values())


def build_manifest(dist: Path, version: str) -> dict:
    root = dist.resolve()
    files = [{"path": rel, "size": (root / rel).stat().st_size, "sha256": _sha256(root / rel)}
             for rel in payload_files(root)]
    return {"schema": SCHEMA, "platform": PLATFORM, "version": version, "files": files}


def write_manifest(dist: Path, version: str) -> Path:
    target = dist / MANIFEST
    text = json.dumps(build_manifest(dist, version), indent=2, sort_keys=True) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


class PE:
    """Just enough of a PE image: machine, subsystem and imported DLL names."""

    def __init__(self, data: bytes) -> None:
        if data[:2] != b"MZ" or len(data) < 0x40:
            raise ValueError("not a PE file (no MZ header)")
        offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[offset:offset + 4] != b"PE\0\0":
            raise ValueError("not a PE file (no PE signature)")
        coff = offset + 4
        self.machine, sections, _, _, _, optional_size, _ = struct.unpack_from("<HHIIIHH", data, coff)
        optional = coff + 20
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic != 0x20B:
            self.subsystem, self.imports = 0, []
            self.pe32_plus = False
            return
        self.pe32_plus = True
        self.subsystem = struct.unpack_from("<H", data, optional + 68)[0]
        table = optional + optional_size
        spans = [struct.unpack_from("<IIII", data, table + 40 * i + 8) for i in range(sections)]

        def to_offset(rva: int) -> int | None:
            for virtual_size, virtual_address, raw_size, raw_pointer in spans:
                if virtual_address <= rva < virtual_address + max(virtual_size, raw_size):
                    return raw_pointer + rva - virtual_address
            return None

        count = struct.unpack_from("<I", data, optional + 108)[0]
        import_rva = struct.unpack_from("<I", data, optional + 112 + 8)[0] if count > 1 else 0
        self.imports = []
        position = to_offset(import_rva) if import_rva else None
        while position is not None and position + 20 <= len(data) and len(self.imports) < 512:
            name_rva = struct.unpack_from("<I", data, position + 12)[0]
            if name_rva == 0:
                break
            start = to_offset(name_rva)
            if start is None:
                break
            end = data.index(b"\0", start)
            self.imports.append(data[start:end].decode("ascii", "replace"))
            position += 20


def _is_system(name: str) -> bool:
    folded = name.casefold()
    return folded.startswith(SYSTEM_PREFIXES) or folded.removesuffix(".dll") in SYSTEM_DLLS


def verify(dist: Path, version: str | None = None) -> list[str]:
    """Every problem found, each naming the file; empty means the payload is sound."""
    problems: list[str] = []
    root = dist.resolve()
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        return [f"{MANIFEST} is missing from {dist}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = {entry["path"]: entry for entry in manifest["files"]}
        if manifest["schema"] != SCHEMA or manifest["platform"] != PLATFORM:
            problems.append(f"{MANIFEST}: expected schema {SCHEMA} for {PLATFORM}")
        if version is not None and manifest["version"] != version:
            problems.append(f"{MANIFEST}: version {manifest['version']} does not match {version}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"{MANIFEST} is unreadable: {exc}"]
    try:
        actual = payload_files(root)
    except PayloadError as exc:
        return [*problems, str(exc)]
    for rel in sorted(set(listed) - set(actual)):
        problems.append(f"{rel}: listed in the manifest but missing")
    for rel in sorted(set(actual) - set(listed)):
        problems.append(f"{rel}: present but not in the manifest")
    for rel in sorted(set(listed) & set(actual)):
        path = root / rel
        if path.stat().st_size != listed[rel].get("size") or _sha256(path) != listed[rel].get("sha256"):
            problems.append(f"{rel}: changed since the manifest was written")
    for needed in (GUI_EXE, CLI_EXE):
        if needed not in actual:
            problems.append(f"{needed}: required executable is missing")
    present = {PurePosixPath(rel).name.casefold() for rel in actual}
    for rel in actual:
        path = root / rel
        if rel.lower().endswith(PE_SUFFIXES):
            try:
                image = PE(path.read_bytes())
            except (ValueError, struct.error, OSError) as exc:
                problems.append(f"{rel}: unreadable PE file ({exc})")
                continue
            if image.machine != MACHINE_X64:
                problems.append(f"{rel}: machine type 0x{image.machine:04x} is not x64")
            if rel == GUI_EXE and image.subsystem != SUBSYSTEM_GUI:
                problems.append(f"{rel}: must be a windowed (GUI) program")
            if rel == CLI_EXE and image.subsystem != SUBSYSTEM_CONSOLE:
                problems.append(f"{rel}: must be a console program")
            for name in image.imports:
                if not _is_system(name) and name.casefold() not in present:
                    problems.append(f"{rel}: needs {name}, which is neither a Windows system file nor in the payload")
        elif rel.lower().endswith(TEXT_SUFFIXES) and path.stat().st_size <= 1 << 20:
            text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            for marker in BUILD_ROOT_MARKERS:
                if marker in text:
                    problems.append(f"{rel}: refers to the build machine ({marker.strip(chr(92)).strip('/')})")
                    break
    return problems
