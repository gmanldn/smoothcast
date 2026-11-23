#!/usr/bin/env python3
"""Measure code and agent-context complexity; ratchet it against a baseline (#516).

Standard library only; never imports project code, GTK or the network. Use it
as a report (default), refresh the baseline with ``--write-baseline`` (give a
one-line justification in the commit message) or gate with ``--check``.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "complexity-baseline.json"
LARGE_MODULE = 1200
TOTAL_TOLERANCE = 0.10   # growth over baseline that fails --check
MODULE_TOLERANCE = 0.10
TOP = 10


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _module_imports(tree: ast.Module) -> int:
    return sum(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)


def _functions(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno:
            yield f"{name}:{node.name}", node.end_lineno - node.lineno + 1


def _added_since_last_tag(root: Path) -> int | None:
    try:
        tag = subprocess.run(["git", "tag", "--sort=-creatordate"], cwd=root, check=True,
                             capture_output=True, text=True, timeout=10).stdout.split()[0]
        out = subprocess.run(["git", "diff", "--name-status", f"{tag}..HEAD", "--", "src"],
                             cwd=root, check=True, capture_output=True, text=True, timeout=20).stdout
    except (OSError, IndexError, subprocess.SubprocessError):
        return None
    return sum(1 for line in out.splitlines() if line.startswith("A") and line.endswith(".py"))


def measure(root: Path = ROOT, *, with_git: bool = True) -> dict:
    src = root / "src"
    lines: dict[str, int] = {}
    funcs: list[tuple[str, int]] = []
    imports: dict[str, int] = {}
    for path in sorted(src.glob("*.py")):
        lines[path.name] = _line_count(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        imports[path.name] = _module_imports(tree)
        funcs.extend(_functions(tree, path.name))
    handbook = [root / "AGENTS.md", *sorted((root / "docs" / "agents").glob("*.md"))]
    ranked = sorted(lines.items(), key=lambda item: (-item[1], item[0]))
    return {
        "src_lines": sum(lines.values()),
        "src_modules": len(lines),
        "modules": lines,
        "largest_modules": ranked[:TOP],
        "modules_over_limit": [name for name, count in ranked if count > LARGE_MODULE],
        "longest_functions": sorted(funcs, key=lambda item: (-item[1], item[0]))[:TOP],
        "most_top_level_imports": sorted(imports.items(), key=lambda item: (-item[1], item[0]))[:TOP],
        "modules_added_since_last_tag": _added_since_last_tag(root) if with_git else None,
        "agents_md_bytes": (root / "AGENTS.md").stat().st_size if (root / "AGENTS.md").exists() else 0,
        "handbook_bytes": sum(p.stat().st_size for p in handbook if p.exists()),
    }


def compare(current: dict, baseline: dict) -> list[str]:
    problems = []
    base_total = baseline.get("src_lines", 0)
    if base_total and current["src_lines"] > base_total * (1 + TOTAL_TOLERANCE):
        problems.append(f"src is {current['src_lines']} lines, over baseline {base_total} "
                        f"by more than {TOTAL_TOLERANCE:.0%}")
    for name, count in current["modules"].items():
        base = baseline.get("modules", {}).get(name)
        if base is not None and count > base * (1 + MODULE_TOLERANCE) and count > 300:
            problems.append(f"{name} grew to {count} lines from {base}")
        if base is None and count > LARGE_MODULE:
            problems.append(f"new module {name} has {count} lines (limit {LARGE_MODULE})")
    return problems


def render(report: dict) -> str:
    out = [f"src: {report['src_lines']} lines in {report['src_modules']} modules; "
           f"AGENTS.md {report['agents_md_bytes']} B, handbook {report['handbook_bytes']} B",
           "largest modules: " + ", ".join(f"{n} {c}" for n, c in report["largest_modules"][:5]),
           "longest functions: " + ", ".join(f"{n} {c}" for n, c in report["longest_functions"][:5]),
           f"modules over {LARGE_MODULE} lines: {len(report['modules_over_limit'])}",
           f"modules added since last tag: {report['modules_added_since_last_tag']}"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = measure()
    if args.write_baseline:
        BASELINE.write_text(json.dumps(
            {k: report[k] for k in ("src_lines", "src_modules", "modules", "agents_md_bytes",
                                    "handbook_bytes")}, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"baseline written: {report['src_lines']} lines")
        return 0
    print(json.dumps(report, indent=1) if args.json else render(report))
    if args.check:
        problems = compare(report, json.loads(BASELINE.read_text(encoding="utf-8")))
        for problem in problems:
            print("COMPLEXITY:", problem, file=sys.stderr)
        if problems:
            print("If the growth is justified, run python3 scripts/ci/complexity_report.py "
                  "--write-baseline and say why in the commit message.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
