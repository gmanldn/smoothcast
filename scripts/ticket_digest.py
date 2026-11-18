#!/usr/bin/env python3
"""Bounded, read-only GitHub Issue digest for SmoothCast agents.

GitHub Issues remain the only backlog authority. This command prints compact
metadata so an agent can choose one issue without downloading every body or
comment. It never creates, edits, assigns, comments on or closes an issue, and
it does not keep a committed cache that could become a second backlog.

Typical use:
    python3 scripts/ticket_digest.py --next
    python3 scripts/ticket_digest.py --priority P0 --limit 20
    python3 scripts/ticket_digest.py --show 23 [--comments]

The printed sizes are characters/bytes, not measured model tokens. Provider
token savings still require an A/B run with real usage accounting.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable, Sequence

DEFAULT_REPOSITORY = "gmanldn/smoothcast"
DEFAULT_LIMIT = 30
DEFAULT_SCAN = 300
MAX_LIMIT = 200
MAX_SCAN = 500
TITLE_LIMIT = 88
LABEL_LIMIT = 24
PRIORITY_RE = re.compile(r"^\[(P[0-2])\]")
LEGACY_RE = re.compile(r"\[(SC-\d{3})\]")
DISPLAY_PREFIX_RE = re.compile(r"^\[P[0-2]\](?:\[SC-\d{3}\])?\s*")
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
LIST_FIELDS = "number,title,state,labels,assignees,updatedAt,url"
VIEW_FIELDS = "number,title,state,labels,assignees,updatedAt,url,body"


class DigestError(RuntimeError):
    """A bounded, user-actionable failure."""


def clamp_limit(value: int) -> int:
    return max(1, min(int(value), MAX_LIMIT))


def clamp_scan(value: int) -> int:
    return max(1, min(int(value), MAX_SCAN))


def priority_of(title: str) -> str:
    match = PRIORITY_RE.match(title.strip())
    return match.group(1) if match else "P3"


def legacy_id_of(title: str) -> str:
    match = LEGACY_RE.search(title)
    return match.group(1) if match else ""


def display_title(title: str) -> str:
    return DISPLAY_PREFIX_RE.sub("", title, count=1)


def _logins(people: Any) -> list[str]:
    if not isinstance(people, list):
        return []
    names = []
    for person in people:
        if isinstance(person, dict) and person.get("login"):
            names.append(str(person["login"]))
    return names


def normalize(issue: dict[str, Any]) -> dict[str, Any]:
    title = " ".join(str(issue.get("title") or "").split())
    labels = sorted(
        str(label["name"])
        for label in issue.get("labels") or []
        if isinstance(label, dict) and label.get("name")
    )
    return {
        "number": int(issue["number"]),
        "title": title,
        "priority": priority_of(title),
        "legacy": legacy_id_of(title),
        "state": str(issue.get("state") or "OPEN").lower(),
        "labels": labels,
        "claim": _logins(issue.get("assignees")),
        "updated": str(issue.get("updatedAt") or ""),
        "url": str(issue.get("url") or ""),
    }


def sort_for_listing(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        issues,
        key=lambda issue: (
            PRIORITY_RANK.get(issue["priority"], 99),
            _descending(issue["updated"]),
            issue["number"],
        ),
    )


def sort_for_next(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        issues,
        key=lambda issue: (
            PRIORITY_RANK.get(issue["priority"], 99),
            issue["updated"],
            issue["number"],
        ),
    )


def _descending(text: str) -> tuple[int, ...]:
    # ISO-8601 UTC timestamps sort lexicographically. Negating ordinals keeps
    # the same key type without reversing the whole sort.
    return tuple(-ord(char) for char in text)


def matches(
    issue: dict[str, Any],
    priorities: Sequence[str] = (),
    labels: Sequence[str] = (),
    claimed: bool | None = None,
) -> bool:
    if priorities and issue["priority"] not in priorities:
        return False
    if labels:
        available = {label.casefold() for label in issue["labels"]}
        if any(label.casefold() not in available for label in labels):
            return False
    if claimed is True and not issue["claim"]:
        return False
    if claimed is False and issue["claim"]:
        return False
    return True


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_issue(issue: dict[str, Any]) -> str:
    legacy = f" {issue['legacy']}" if issue["legacy"] else ""
    claim = ",".join(issue["claim"]) or "-"
    labels = truncate(",".join(issue["labels"]), LABEL_LIMIT) or "-"
    updated = issue["updated"][:10] or "----------"
    title = truncate(display_title(issue["title"]), TITLE_LIMIT)
    return (
        f"#{issue['number']} {issue['priority']}{legacy} {claim} "
        f"{updated} {labels} {title}"
    )


def priority_counts(issues: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {priority: 0 for priority in ("P0", "P1", "P2", "P3")}
    for issue in issues:
        counts[issue["priority"]] = counts.get(issue["priority"], 0) + 1
    return counts


def _run_gh(args: Sequence[str], timeout: int = 30) -> str:
    if shutil.which("gh") is None:
        raise DigestError(
            "GitHub CLI 'gh' is not installed. Install it and run 'gh auth login'."
        )
    try:
        result = subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise DigestError(f"gh timed out after {timeout}s") from None
    except OSError as exc:
        raise DigestError(f"gh could not start: {type(exc).__name__}") from None
    if result.returncode != 0:
        detail = " ".join((result.stderr or "").split())[:600]
        raise DigestError(f"gh exited {result.returncode}: {detail or 'no detail'}")
    return result.stdout


def fetch_issues(
    repository: str,
    state: str,
    scan: int,
    search: str | None = None,
    labels: Sequence[str] = (),
) -> list[dict[str, Any]]:
    args = [
        "issue",
        "list",
        "--repo",
        repository,
        "--state",
        state,
        "--limit",
        str(clamp_scan(scan)),
        "--json",
        LIST_FIELDS,
    ]
    if search:
        args.extend(["--search", search])
    for label in labels:
        args.extend(["--label", label])
    try:
        payload = json.loads(_run_gh(args))
    except json.JSONDecodeError:
        raise DigestError("gh returned invalid JSON") from None
    if not isinstance(payload, list):
        raise DigestError("gh returned an unexpected issue payload")
    return [
        normalize(issue)
        for issue in payload
        if isinstance(issue, dict) and isinstance(issue.get("number"), int)
    ]


def fetch_issue(repository: str, number: int, comments: bool) -> dict[str, Any]:
    fields = VIEW_FIELDS + (",comments" if comments else "")
    try:
        payload = json.loads(
            _run_gh(
                [
                    "issue",
                    "view",
                    str(number),
                    "--repo",
                    repository,
                    "--json",
                    fields,
                ]
            )
        )
    except json.JSONDecodeError:
        raise DigestError("gh returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise DigestError("gh returned an unexpected issue payload")
    issue = normalize(payload)
    issue["body"] = str(payload.get("body") or "")
    if comments:
        issue["comments"] = payload.get("comments") or []
    return issue


def summary_line(
    repository: str, state: str, scanned: int, matched: int, issues: Sequence[dict[str, Any]]
) -> str:
    counts = priority_counts(issues)
    claimed = sum(1 for issue in issues if issue["claim"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    order = " ".join(f"{name}={counts[name]}" for name in ("P0", "P1", "P2", "P3"))
    return (
        f"SmoothCast issues repo={repository} state={state} generated={stamp} "
        f"scanned={scanned} matched={matched} {order} claimed={claimed}"
    )


def _print_issue(issue: dict[str, Any], comments: bool) -> None:
    legacy = f" [{issue['legacy']}]" if issue["legacy"] else ""
    claim = ",".join(issue["claim"]) or "-"
    labels = ",".join(issue["labels"]) or "-"
    print(f"#{issue['number']} [{issue['priority']}]{legacy} {display_title(issue['title'])}")
    print(
        f"state={issue['state']} claim={claim} updated={issue['updated'] or '-'} "
        f"labels={labels}"
    )
    if issue["url"]:
        print(issue["url"])
    print("---")
    print(issue["body"].rstrip())
    if comments:
        print("--- comments ---")
        for comment in issue.get("comments") or []:
            if not isinstance(comment, dict):
                continue
            author = str((comment.get("author") or {}).get("login") or "unknown")
            created = str(comment.get("createdAt") or "")
            body = str(comment.get("body") or "").rstrip()
            print(f"@{author} {created}")
            print(body)
            print("---")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print a bounded, read-only SmoothCast GitHub issue digest.",
    )
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help="owner/name")
    parser.add_argument(
        "--state", choices=("open", "closed", "all"), default="open"
    )
    parser.add_argument(
        "--scan",
        type=int,
        default=DEFAULT_SCAN,
        help=f"metadata rows inspected before filtering (default {DEFAULT_SCAN})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"maximum rows printed (default {DEFAULT_LIMIT}, max {MAX_LIMIT})",
    )
    parser.add_argument("--search", help="optional GitHub search query")
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="require a label; repeat for AND matching",
    )
    parser.add_argument(
        "--priority",
        action="append",
        default=[],
        type=str.upper,
        choices=("P0", "P1", "P2", "P3"),
        help="priority prefix, repeatable",
    )
    claim_group = parser.add_mutually_exclusive_group()
    claim_group.add_argument(
        "--claimed", action="store_true", help="only issues with an assignee"
    )
    claim_group.add_argument(
        "--unclaimed", action="store_true", help="only issues without an assignee"
    )
    parser.add_argument(
        "--next",
        action="store_true",
        help="print one highest-priority unclaimed issue and stop",
    )
    parser.add_argument(
        "--show", type=int, metavar="NUMBER", help="read one issue body"
    )
    parser.add_argument(
        "--comments",
        action="store_true",
        help="with --show, include the issue comments",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.comments and args.show is None:
        parser.error("--comments requires --show")
    if args.next and args.claimed:
        parser.error("--next finds unclaimed work; drop --claimed")
    if args.show is not None and args.show < 1:
        parser.error("--show must be a positive issue number")

    try:
        if args.show is not None:
            issue = fetch_issue(args.repo, args.show, args.comments)
            if args.json:
                print(json.dumps(issue, ensure_ascii=False, separators=(",", ":")))
            else:
                _print_issue(issue, args.comments)
            return 0

        scanned = fetch_issues(
            args.repo, args.state, args.scan, args.search, args.label
        )
        claimed = True if args.claimed else False if args.unclaimed else None
        matched = [
            issue
            for issue in scanned
            if matches(issue, args.priority, args.label, claimed)
        ]

        if args.next:
            candidates = [issue for issue in matched if not issue["claim"]]
            selected = sort_for_next(candidates)[:1]
            if args.json:
                print(
                    json.dumps(
                        {
                            "repository": args.repo,
                            "state": args.state,
                            "generated_at": dt.datetime.now(
                                dt.timezone.utc
                            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "scanned": len(scanned),
                            "matched": len(matched),
                            "issues": selected,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            elif selected:
                print(format_issue(selected[0]))
                print(
                    f"Read it with: python3 scripts/ticket_digest.py --show "
                    f"{selected[0]['number']}"
                )
            else:
                print("next=none unclaimed=0")
            return 0

        shown = sort_for_listing(matched)[: clamp_limit(args.limit)]
        if args.json:
            print(
                json.dumps(
                    {
                        "repository": args.repo,
                        "state": args.state,
                        "generated_at": dt.datetime.now(dt.timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "scanned": len(scanned),
                        "matched": len(matched),
                        "counts": priority_counts(matched),
                        "issues": shown,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 0

        print(
            summary_line(
                args.repo, args.state, len(scanned), len(matched), matched
            )
        )
        for issue in shown:
            print(format_issue(issue))
        if len(shown) < len(matched):
            print(
                f"… {len(matched) - len(shown)} more; use --limit or --priority"
            )
        return 0
    except DigestError as exc:
        print(f"ticket_digest: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
