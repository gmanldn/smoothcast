#!/usr/bin/env python3
"""Generate a CycloneDX 1.5 SBOM of SmoothCast's runtime dependencies (#218).

Stdlib only. The runtime requirements come from ``pyproject.toml``; versions and
licences come from the installed distribution metadata, followed transitively.
Output is deterministic (sorted, no timestamp, content-derived serial number) so
two runs over the same environment are byte-identical and diffable.

    python3 scripts/ci/gen_sbom.py [--output sbom.cdx.json] [--check-licences]

``--check-licences`` exits non-zero if any component's licence is unknown or not
covered by the reviewed allow-list below, so a new dependency with an
incompatible licence cannot arrive silently. Exit 2 means the environment is
incomplete (a declared dependency is not installed).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import re
import sys
from typing import Callable, Iterable
import uuid

ROOT = Path(__file__).resolve().parents[2]

# Reviewed dependency licences allowed in the shipped SBOM. Extend only after
# review; matching is on normalised SPDX-style identifiers.
ALLOWED_LICENCES = frozenset({
    "MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Apache-2.0",
    "PSF-2.0", "Python-2.0", "Unlicense", "Zlib", "0BSD",
    "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
    "MPL-2.0",
})

_ALIASES = {
    "mit license": "MIT", "mit": "MIT", "the mit license": "MIT",
    "bsd license": "BSD-3-Clause", "bsd": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause", "bsd-3-clause": "BSD-3-Clause",
    "bsd 2-clause": "BSD-2-Clause", "bsd-2-clause": "BSD-2-Clause",
    "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0",
    "apache software license": "Apache-2.0", "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "isc license": "ISC", "isc": "ISC", "zlib": "Zlib",
    "python software foundation license": "PSF-2.0",
    "gnu lesser general public license v2 or later (lgplv2+)": "LGPL-2.1-or-later",
    "gnu lesser general public license v3 or later (lgplv3+)": "LGPL-3.0-or-later",
    "gnu library or lesser general public license (lgpl)": "LGPL-2.1-or-later",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0", "mpl-2.0": "MPL-2.0",
}
# Packages whose metadata is wrong or ambiguous, resolved by reading the licence
# file shipped in the installed distribution. Reviewed by hand; never extend this
# to silence a real finding.
LICENCE_OVERRIDES = {
    "catt": "BSD-2-Clause",   # classifiers also list "Other/Proprietary"; LICENSE is BSD 2-Clause
}
_GENERIC = frozenset({"Other/Proprietary License", "Other/Proprietary", "OSI Approved"})
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


class IncompleteEnvironment(RuntimeError):
    """A declared dependency is not installed, so the SBOM would be wrong."""


@dataclass(frozen=True)
class Package:
    name: str            # normalised (PEP 503)
    version: str
    licences: tuple[str, ...]   # normalised ids, or the raw text if unrecognised
    requires: tuple[str, ...]   # normalised names of direct requirements


Provider = Callable[[str], "Package | None"]


def normalise_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def normalise_licence(text: str) -> str:
    """Map a licence string to an SPDX-style id when it is a known alias."""
    cleaned = " ".join(text.split())
    return _ALIASES.get(cleaned.lower(), cleaned)


def _licences_from(meta: "md._meta.PackageMetadata") -> tuple[str, ...]:
    found: list[str] = []
    expression = meta.get("License-Expression")
    if expression:
        # "A OR B" offers a choice; "A AND B" imposes both. Record each term.
        found += [t for t in re.split(r"\s+(?:AND|OR)\s+|[()]", expression) if t.strip()]
    if not found:
        found += [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or [])
                  if c.startswith("License ::")]
        found = [item for item in found if item not in _GENERIC] or found
    if not found:
        raw = (meta.get("License") or "").strip()
        if raw and raw.upper() != "UNKNOWN" and len(raw) <= 120 and "\n" not in raw:
            found.append(raw)
    return tuple(sorted({normalise_licence(item) for item in found})) or ("UNKNOWN",)


def installed_provider(name: str) -> "Package | None":
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError:
        return None
    requires: list[str] = []
    for line in dist.requires or []:
        head, _, marker = line.partition(";")
        if "extra" in marker:        # optional extras are not installed by default
            continue
        match = _NAME.match(head)
        if match:
            requires.append(normalise_name(match.group(1)))
    canonical = normalise_name(dist.metadata["Name"] or name)
    licences = ((LICENCE_OVERRIDES[canonical],) if canonical in LICENCE_OVERRIDES
                else _licences_from(dist.metadata))
    return Package(canonical, dist.version, licences, tuple(sorted(set(requires))))


def runtime_requirements(pyproject: Path) -> list[str]:
    """Names of ``[project].dependencies``; needs tomllib (Python 3.11+)."""
    import tomllib
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    names = []
    for item in data["project"]["dependencies"]:
        match = _NAME.match(item)
        if match:
            names.append(normalise_name(match.group(1)))
    return sorted(set(names))


def closure(roots: Iterable[str], provider: Provider) -> dict[str, Package]:
    """Every distribution reachable from *roots*. Raises if one is missing.

    A missing *transitive* requirement is tolerated only when it is an
    environment-marker-gated optional that this platform does not install, which
    ``installed_provider`` cannot distinguish; so we are strict for roots and
    lenient for the rest.
    """
    seen: dict[str, Package] = {}
    stack = [(name, True) for name in sorted(roots)]
    while stack:
        name, is_root = stack.pop()
        if name in seen:
            continue
        package = provider(name)
        if package is None:
            if is_root:
                raise IncompleteEnvironment(f"declared dependency not installed: {name}")
            continue
        seen[package.name] = package
        stack.extend((dep, False) for dep in package.requires)
    return dict(sorted(seen.items()))


def purl(package: Package) -> str:
    return f"pkg:pypi/{package.name}@{package.version}"


def build_sbom(app_name: str, app_version: str, packages: dict[str, Package]) -> dict:
    components = []
    for package in packages.values():
        licences = [({"license": {"id": item}} if item in ALLOWED_LICENCES
                     else {"license": {"name": item}}) for item in package.licences]
        components.append({
            "type": "library", "bom-ref": purl(package), "name": package.name,
            "version": package.version, "purl": purl(package), "licenses": licences,
        })
    root_ref = f"pkg:generic/{app_name}@{app_version}"
    dependencies = [{"ref": root_ref, "dependsOn": sorted(
        purl(packages[name]) for name in packages
        if not any(name in other.requires for other in packages.values()))}]
    for package in packages.values():
        dependencies.append({"ref": purl(package), "dependsOn": sorted(
            purl(packages[dep]) for dep in package.requires if dep in packages)})
    document = {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "metadata": {"component": {
            "type": "application", "bom-ref": root_ref,
            "name": app_name, "version": app_version,
            "licenses": [{"license": {"id": "GPL-3.0-or-later"}}],
        }},
        "components": components, "dependencies": dependencies,
    }
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    document["serialNumber"] = f"urn:uuid:{uuid.UUID(digest[:32])}"
    return document


def licence_violations(packages: dict[str, Package]) -> list[str]:
    problems = []
    for package in packages.values():
        bad = [item for item in package.licences if item not in ALLOWED_LICENCES]
        if bad:
            problems.append(f"{package.name} {package.version}: {', '.join(bad)}")
    return problems


def app_version(root: Path = ROOT) -> str:
    text = (root / "src" / "version.py").read_text(encoding="utf-8")
    parts = [re.search(rf"^{key}\s*=\s*(\d+)", text, re.M) for key in ("MAJOR", "MINOR", "PATCH")]
    if not all(parts):
        raise ValueError("cannot read version from src/version.py")
    return ".".join(m.group(1) for m in parts if m)


def main(argv: list[str] | None = None, provider: Provider = installed_provider) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output", "-o", help="write JSON here (default: stdout)")
    parser.add_argument("--check-licences", action="store_true",
                        help="fail if any component licence is unknown or not allow-listed")
    args = parser.parse_args(argv)
    try:
        packages = closure(runtime_requirements(ROOT / "pyproject.toml"), provider)
    except IncompleteEnvironment as exc:
        print(f"error: {exc}; install the project first (pip install .)", file=sys.stderr)
        return 2
    if args.check_licences:
        problems = licence_violations(packages)
        if problems:
            print("Licences outside the reviewed allow-list:", *problems, sep="\n  ",
                  file=sys.stderr)
            return 1
    text = json.dumps(build_sbom("smoothcast", app_version(), packages),
                      indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
