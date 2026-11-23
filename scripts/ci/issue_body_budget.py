#!/usr/bin/env python3
"""Report oversized open GitHub issue bodies without printing private issue text.

Read a JSON export with --input, or explicitly fetch issue metadata via --fetch.
Oversize findings are advisory: this command exits 0 unless retrieval fails.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

LIMIT_BYTES = 6000
PAGE_SIZE = 100
MAX_PAGES = 20
DEFAULT_REPO = "gmanldn/smoothcast"


class BudgetError(ValueError):
    """Invalid issue input or unavailable GitHub API."""


def inspect(issues: list[dict], limit: int = LIMIT_BYTES) -> dict:
    if limit < 1:
        raise BudgetError("max-bytes must be positive")
    oversized: list[dict] = []
    considered = skipped = 0
    for issue in issues:
        if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
            raise BudgetError("issue metadata must contain a numeric number")
        # GitHub /issues also lists pull requests; they are not backlog items.
        title = issue.get("title") or ""
        raw_labels = issue.get("labels") or []
        if not isinstance(title, str) or not isinstance(raw_labels, list):
            raise BudgetError("invalid issue title or labels")
        labels = set()
        for item in raw_labels:
            value = item.get("name") if isinstance(item, dict) else item
            if not isinstance(value, str):
                raise BudgetError("invalid issue label")
            labels.add(value.casefold())
        if ("pull_request" in issue or "epic" in labels
                or "[epic]" in title.casefold()
                or str(issue.get("state", "open")).casefold() not in {"open", ""}):
            skipped += 1
            continue
        body = issue.get("body")
        if body is None:
            body = ""
        if not isinstance(body, str):
            raise BudgetError("issue body must be text")
        considered += 1
        size = len(body.encode("utf-8"))
        if size > limit:
            oversized.append({"number": issue["number"], "body_bytes": size})
    oversized.sort(key=lambda item: (-item["body_bytes"], item["number"]))
    return {"limit_bytes": limit, "checked": considered,
            "skipped": skipped, "oversized_count": len(oversized), "oversized": oversized}


def fetch_open_issues(repo: str, token: str, *, base: str = "https://api.github.com") -> list[dict]:
    if not token:
        raise BudgetError("GITHUB_TOKEN is required for --fetch")
    if len(repo.split("/")) != 2 or any(not part or not all(
            c.isalnum() or c in "-_." for c in part) for part in repo.split("/")):
        raise BudgetError("--repo must be an owner/name repository")
    issues: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{base}/repos/{repo}/issues?state=open&per_page={PAGE_SIZE}&page={page}"
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "smoothcast-issue-body-budget",
        })
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.load(response)
        except (OSError, urllib.error.HTTPError, ValueError) as exc:
            raise BudgetError(f"GitHub issue metadata unavailable: {type(exc).__name__}") from None
        if not isinstance(data, list):
            raise BudgetError("unexpected GitHub issue metadata response")
        issues.extend(data)
        if len(data) < PAGE_SIZE:
            return issues
    raise BudgetError(f"issue scan exceeded {MAX_PAGES * PAGE_SIZE} entries; no partial result")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="GitHub /issues JSON array (offline)")
    source.add_argument("--fetch", action="store_true", help="read GitHub API, never mutate issues")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--max-bytes", type=int, default=LIMIT_BYTES)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        issues = (fetch_open_issues(args.repo, os.environ.get("GITHUB_TOKEN", ""))
                  if args.fetch else json.loads(args.input.read_text(encoding="utf-8")))
        if not isinstance(issues, list):
            raise BudgetError("issue export must be a JSON list")
        report = inspect(issues, args.max_bytes)
    except (BudgetError, OSError, ValueError) as exc:
        print(f"issue-body-budget: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, separators=(",", ":")))
    else:
        print(f"Issue bodies: {report['checked']} checked, {report['oversized_count']} "
              f"over {report['limit_bytes']} bytes (advisory; no issue bodies shown)")
        for item in report["oversized"][:20]:
            print(f"  #{item['number']}: {item['body_bytes']} bytes")
        if len(report["oversized"]) > 20:
            print(f"  ... {len(report['oversized']) - 20} more (use --json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
