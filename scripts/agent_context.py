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
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "docs" / "agents"
TOPICS = {
    "workflow": (
        "Issue ownership, worktrees, commits and releases",
        ("issue", "issues", "ticket", "tickets", "backlog", "pr", "pull",
         "branch", "worktree", "workflow", "merge", "version",
         "release", "git", "status"),
    ),
    "testing": (
        "Headless tests, CI, Xvfb and device safety",
        ("test", "tests", "testing", "pytest", "unittest", "ci", "action",
         "xvfb", "gui smoke", "focus", "display", "regression", "verify"),
    ),
    "architecture": (
        "Module map for playback, GTK, DLNA, subtitles and setup",
        ("src/", "setup/", "cast_", "stream", "streamer", "streaming",
         "media", "dlna", "subtitle", "subtitles", "receiver", "preview",
         "ffmpeg", "sound", "audio", "gtk", "playback", "queue",
         "widget", "device", ".py"),
    ),
    "efficiency": (
        "Caveman, Ponytail and context/tool-output discipline",
        ("token", "tokens", "context", "agent", "agents", "caveman",
         "ponytail", "prompt", "cost", "budget", "compact",
         "compression", "efficiency"),
    ),
}
MAX_HINT_CHARS = 1500
MAX_READ_CHARS = 9000


_PATH_MARKERS = {"src/", "setup/", "cast_", ".py"}


def _term_count(query: str, term: str) -> int:
    """Keep source-path markers, but match ordinary words only as whole terms.

    The legacy substring rule interpreted the PR keyword inside 'preview',
    'improve' and 'problem' as a workflow request.
    """
    if term in _PATH_MARKERS:
        return query.count(term)
    return len(re.findall(
        rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", query
    ))


def route(words: list[str]) -> list[str]:
    """Rank task-specific guides without broad substring false matches."""
    query = " ".join(words).lower()
    if not query.strip():
        return []
    scores = {
        name: sum(_term_count(query, term) for term in terms)
        for name, (_, terms) in TOPICS.items()
    }
    # An explicit handbook path is a stronger signal than other query words.
    for name in TOPICS:
        if f"docs/agents/{name}.md" in query:
            scores[name] += 4
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


def related_invariants(words: list[str]) -> str:
    """Annotate a relevant source path from the sole invariant matrix authority."""
    paths = set(re.findall(r"src/[a-z0-9_]+\.py", " ".join(words).lower()))
    if not paths:
        return ""
    identifiers = []
    try:
        with (ROOT / "docs" / "INVARIANTS.md").open(encoding="utf-8") as manifest:
            for line in manifest:
                if not line.startswith("| INV-"):
                    continue
                parts = [value.strip() for value in line.strip().strip("|").split("|")]
                if len(parts) == 4 and parts[2].lower() in paths:
                    identifiers.append(parts[0])
    except OSError:
        return ""
    return (" Guarding invariants: " + ", ".join(identifiers)
            + " (docs/INVARIANTS.md)." if identifiers else "")


def route_hint(words: list[str]) -> str:
    matches = route(words)
    if not matches:
        return ("No confident route. Read docs/agents/README.md, then search "
                "symbols/files narrowly; do not load the entire archive.")
    first = matches[0]
    suffix = "; also consider " + ", ".join(matches[1:3]) if len(matches) > 1 else ""
    return (f"Read docs/agents/{first}.md for "
            f"{TOPICS[first][0].lower()}{suffix}. "
            "Open only task-relevant source ranges and direct callers."
            + related_invariants(words))


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
