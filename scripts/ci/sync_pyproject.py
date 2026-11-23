#!/usr/bin/env python3
"""Keep pyproject.toml's two long module lists canonical and conflict-free.

* ``[tool.setuptools] py-modules`` is *derived*: it must equal ``src/*.py``.
* ``[tool.mypy] files`` is curated, kept deduplicated and sorted.

Both are written one entry per line, so concurrent additions merge cleanly in
Git. If a rebase still leaves conflict markers inside these two lists, this
script resolves them by keeping the union of both sides.

    python3 scripts/ci/sync_pyproject.py            # fix the file in place
    python3 scripts/ci/sync_pyproject.py --check    # exit 1 if not canonical

After a conflicted rebase of pyproject.toml:
    python3 scripts/ci/sync_pyproject.py && git add pyproject.toml && git rebase --continue
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
MARKER = re.compile(r"^(<{7}|={7}|>{7})( .*)?$")
# (section header, list opener); each list ends at the first line that is just "]".
LISTS = (("[tool.setuptools]", "py-modules = [\n"), ("[tool.mypy]", "files = [\n"))


class SyncError(Exception):
    pass


def _entries(block: str) -> list[str]:
    return re.findall(r'"([^"\n]+)"', block)


def _render(entries: list[str]) -> str:
    return "".join(f'    "{entry}",\n' for entry in entries)


def source_modules(src: Path = SRC) -> list[str]:
    return sorted(p.stem for p in src.glob("*.py") if p.name != "__init__.py")


def find_list(text: str, header: str, opener: str) -> tuple[int, int]:
    """Character span of a list's entries (between its opener line and closing bracket)."""
    start = text.find(header)
    if start < 0:
        raise SyncError(f"missing {header} section")
    begin = text.find("\n" + opener, start)
    if begin < 0:
        raise SyncError(f"missing {opener.strip()} in {header}")
    begin += 1 + len(opener)
    end = text.find("\n]\n", begin - 1)
    if end < 0:
        raise SyncError(f"unterminated {opener.strip()} list")
    return begin, end + 1


def _strip_markers(text: str) -> str:
    """Drop conflict markers, but only when every one sits inside a managed list."""
    lines = text.splitlines(keepends=True)
    if not any(MARKER.match(line.rstrip("\n")) for line in lines):
        return text
    spans = [find_list(text, header, opener) for header, opener in LISTS]
    offset, kept = 0, []
    for line in lines:
        if MARKER.match(line.rstrip("\n")):
            if not any(start <= offset <= end for start, end in spans):
                raise SyncError("conflict markers outside the module lists; "
                                "resolve those by hand first")
        else:
            kept.append(line)
        offset += len(line)
    return "".join(kept)


def canonical(text: str, modules: list[str]) -> str:
    text = _strip_markers(text)
    for (header, opener), wanted in zip(LISTS, (modules, None)):
        begin, end = find_list(text, header, opener)
        entries = wanted if wanted is not None else sorted(set(_entries(text[begin:end])))
        text = text[:begin] + _render(entries) + text[end:]
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only report; exit 1 if not canonical")
    parser.add_argument("--file", type=Path, default=ROOT / "pyproject.toml")
    parser.add_argument("--src", type=Path, default=SRC)
    args = parser.parse_args(argv)
    try:
        current = args.file.read_text(encoding="utf-8")
        wanted = canonical(current, source_modules(args.src))
    except (SyncError, OSError) as exc:
        print(f"sync_pyproject: {exc}", file=sys.stderr)
        return 2
    if wanted == current:
        print("pyproject.toml lists are canonical")
        return 0
    if args.check:
        print("pyproject.toml lists are not canonical; run: python3 scripts/ci/sync_pyproject.py",
              file=sys.stderr)
        return 1
    args.file.write_text(wanted, encoding="utf-8")
    print("pyproject.toml lists updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
