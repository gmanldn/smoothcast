"""Turn the verified Windows payload manifest into a WiX v6 fragment (#531).

Pure Python, no WiX, Windows or network needed. Output is deterministic: the
same manifest always yields the same bytes, and every Component id and GUID is
derived from the file's relative path, so an upgrade sees the same component
for an unchanged path. Nothing here is random or time-based.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import uuid
from xml.sax.saxutils import quoteattr

WIX_NS = "http://wixtoolset.org/schemas/v4/wxs"       # the namespace WiX v6 still uses
# Fixed forever: component GUIDs are uuid5(this, lower-cased path). Changing it re-keys every component.
COMPONENT_NAMESPACE = uuid.UUID("6f1c2f0e-83a5-4d1e-9b6e-5f2a0c3d7b41")
MAX_MAJOR_MINOR, MAX_BUILD = 255, 65535
_VERSION = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,5})$")
_RESERVED = re.compile(r'[<>:"|?*\x00-\x1f]')


class WixError(ValueError):
    """The manifest or version cannot become an installer."""


def msi_version(version: str) -> str:
    """The three-field MSI ProductVersion, rejecting values Windows Installer ignores or truncates."""
    match = _VERSION.match(str(version))
    if not match:
        raise WixError(f"version {version!r} must be MAJOR.MINOR.PATCH numbers")
    major, minor, build = map(int, match.groups())
    if major > MAX_MAJOR_MINOR or minor > MAX_MAJOR_MINOR or build > MAX_BUILD:
        raise WixError(f"version {version} is outside the MSI limits 255.255.65535")
    return f"{major}.{minor}.{build}"


def _clean(path: str) -> PurePosixPath:
    pure = PurePosixPath(path)
    if (not path or pure.as_posix() != path or pure.is_absolute() or "\\" in path or _RESERVED.search(path)
            or any(part in ("", ".", "..") or part != part.strip() or part.endswith(".")
                   for part in pure.parts)):
        raise WixError(f"{path!r}: unsafe payload path")
    return pure


def component_guid(path: str) -> str:
    return str(uuid.uuid5(COMPONENT_NAMESPACE, path.casefold())).upper()


def _identifier(prefix: str, path: str) -> str:
    return f"{prefix}_{hashlib.sha256(path.casefold().encode('utf-8')).hexdigest()[:24]}"


def load_files(manifest_path: Path) -> list[str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = [entry["path"] for entry in manifest["files"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WixError(f"payload manifest unreadable: {exc}") from None
    if manifest.get("platform") != "windows-x64":
        raise WixError("payload manifest is not for windows-x64")
    seen: dict[str, str] = {}
    for path in paths:
        _clean(path)
        folded = path.casefold()
        if folded in seen:
            raise WixError(f"{path}: collides with {seen[folded]} when case is ignored")
        seen[folded] = path
    for required in ("SmoothCast.exe", "SmoothCastCLI.exe"):
        if required not in paths:
            raise WixError(f"{required} is missing from the payload manifest")
    return sorted(paths)


def render(paths: list[str], source_dir: str = "$(PayloadDir)") -> str:
    """The ``Payload.wxs`` text: one Component per file, GUIDs and ids fixed by path."""
    tree: dict = {}
    for path in paths:
        node = tree
        parts = _clean(path).parts
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = path
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<Wix xmlns="{WIX_NS}">',
        "  <Fragment>",
        '    <DirectoryRef Id="INSTALLFOLDER">',
    ]
    components: list[str] = []

    def walk(node: dict, trail: tuple[str, ...], depth: int) -> None:
        pad = "  " * (depth + 3)
        for name in sorted(node, key=str.casefold):
            child = node[name]
            if isinstance(child, dict):
                folder = "/".join((*trail, name))
                lines.append(f'{pad}<Directory Id="{_identifier("D", folder)}" Name={quoteattr(name)}>')
                walk(child, (*trail, name), depth + 1)
                lines.append(f"{pad}</Directory>")
            else:
                cid = _identifier("C", child)
                components.append(cid)
                lines.append(
                    f'{pad}<Component Id="{cid}" Guid="{component_guid(child)}" Bitness="always64">'
                    f'<File Id="{_identifier("F", child)}" KeyPath="yes" Name={quoteattr(name)} '
                    f"Source={quoteattr(source_dir + chr(92) + child.replace('/', chr(92)))} /></Component>")

    walk(tree, (), 0)
    lines += ["    </DirectoryRef>", "  </Fragment>", "  <Fragment>", '    <ComponentGroup Id="PayloadFiles">']
    lines += [f'      <ComponentRef Id="{cid}" />' for cid in components]
    lines += ["    </ComponentGroup>", "  </Fragment>", "</Wix>", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Write Payload.wxs from payload-manifest.json")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        text = render(load_files(args.manifest))
    except WixError as exc:
        print(f"cannot author the installer: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
