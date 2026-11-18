#!/usr/bin/env python3
"""Small, deterministic agent-context router. Pure stdlib; never starts GTK.

Usage:
    python3 scripts/agent_context.py list
    python3 scripts/agent_context.py route src/cast_av.py subtitles
    python3 scripts/agent_context.py read architecture

The default output is a short navigation hint, not the entire handbook.
Read an individual guide only when needed. Never silently truncate a guide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "docs" / "agents"
TOPICS = {
    "workflow": (
        "Issue ownership, worktrees, commits and releases",
        ("issue", "issues", "ticket", "backlog", "pr", "pull", "branch",
         "worktree", "merge", "version", "release", "git", "status"),
    ),
    "testing": (
        "Headless tests, CI, Xvfb and device safety",
        ("test", "pytest", "unittest", "ci", "action", "xvfb",
         "gui smoke", "focus", "display", "regression", "verify"),
    ),
    "architecture": (
        "Module map for playback, GTK, DLNA, subtitles and setup",
        ("src/", "setup/", "cast_", "stream", "media", "dlna", "subtitle",
         "receiver", "preview", "ffmpeg", "sound", "audio", "gtk",
         "playback", "queue", "widget", "device", ".py"),
    ),
    "efficiency": (
        "Caveman, Ponytail and context/tool-output discipline",
        ("token", "context", "agent", "caveman", "ponytail", "prompt",
         "cost", "budget", "compact", "compression", "efficiency"),
    ),
}
MAX_HINT_CHARS = 1500
MAX_READ_CHARS = 8000


def route(words: list[str]) -> list[str]:
    """Rank topics from local keyword matches; no repo read or network call."""
    query = " ".join(words).lower()
    if not query.strip():
        return []
    scores = {
        name: sum(query.count(term) for term in terms)
        for name, (_, terms) in TOPICS.items()
    }
    return [name for name in sorted(scores, key=lambda k: (-scores[k], k))
            if scores[name] > 0]


def guide(name: str) -> Path:
    if name not in TOPICS:
        raise ValueError(f"Unknown topic: {name}")
    return HANDBOOK / f"{name}.md"


def list_topics() -> str:
    return "\n".join(
        f"{name:13} {desc} — docs/agents/{name}.md"
        for name, (desc, _) in TOPICS.items()
    )


def route_hint(words: list[str]) -> str:
    matches = route(words)
    if not matches:
        return ("No confident route. Read docs/agents/README.md, then search "
                "symbols/files narrowly; do not load the entire archive.")
    first = matches[0]
    suffix = "; also consider " + ", ".join(matches[1:3]) if len(matches) > 1 else ""
    return (f"Read docs/agents/{first}.md for "
            f"{TOPICS[first][0].lower()}{suffix}. "
            "Open only task-relevant source ranges and direct callers.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show brief topic map")
    lookup = sub.add_parser("route", help="Select a task-specific guide")
    lookup.add_argument("query", nargs="+", help="Paths or task keywords")
    read = sub.add_parser("read", help="Print one guide, never all docs")
    read.add_argument("topic", choices=sorted(TOPICS))
    args = parser.parse_args(argv)

    if args.command == "list":
        output = list_topics()
    elif args.command == "route":
        output = route_hint(args.query)
        if len(output) > MAX_HINT_CHARS:
            print("Navigation hint too long; narrow your search.", file=sys.stderr)
            return 2
    else:
        path = guide(args.topic)
        try:
            output = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Unable to read {path}: {exc}", file=sys.stderr)
            return 2
        if len(output) > MAX_READ_CHARS:
            print(f"Guide exceeds {MAX_READ_CHARS} characters: {path}. "
                  "Read a targeted section; refusing lossy truncation.",
                  file=sys.stderr)
            return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
