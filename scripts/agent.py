#!/usr/bin/env python3
"""One entry point for agents: pick work, claim it safely, ship it fast.

    python3 scripts/agent.py board            who holds what, hot files, CI head
    python3 scripts/agent.py next [--lane L]  best ticket that collides with nobody
    python3 scripts/agent.py claim N          atomic claim (loser backs off)
    python3 scripts/agent.py ship [--dry-run] rebase, run only affected checks, push
    python3 scripts/agent.py done N --why .. --checklist ..   evidence + release

Design: docs/agents/coordination.md. Claims live in structured issue comments
(``<!-- sc-claim v1 ... -->``) and legacy free-text "Claim:" comments are read
too, because every agent posts as one GitHub user and never sets an assignee.
Never launches a GUI, never force-pushes, never closes without ``--close``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_digest as td  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = "gmanldn/smoothcast"
TTL_MIN, TTL_MAX = 30, 180
LEGACY_TTL = 45
HOT_MINUTES = 45
SKIP_LABELS = {"epic", "icebox", "needs-human", "needs-split"}
TIER_SCORE = {"now": 300, "next": 200, "later": 100}
PRIORITY_SCORE = {"P0": 150, "P1": 50, "P2": 20, "P3": 0}
# Merge-friendly shared files every agent touches: never a reason to avoid a ticket.
SHARED = {"pyproject.toml", "docs/complexity-baseline.json", ".github/workflows/verify.yml",
          "docs/a11y-baseline.json", "docs/silent-except-baseline.json"}
# Cheap static ratchets that a src/ or baseline change can silently trip (red heads so far).
RATCHETS = ("tests/test_complexity_budget.py", "tests/test_a11y_inventory.py",
            "tests/test_no_silent_swallow.py")
PLAN_FIRST = {"src/cast_session.py", "src/streamer.py", "src/startup_cleanup.py", "src/dlna.py"}
_MARK = re.compile(r"<!--\s*sc-(claim|release)\s+v1\s+([^>]*?)\s*-->")
_PATH = re.compile(r"(?<![\w/.-])((?:src|tests|scripts|setup|docs|packaging|fakecast|\.github)/[\w./-]+\.(?:py|md|yml|json|toml|sh))")
_BARE = re.compile(r"`([a-z_0-9]+\.py)`")
_DEPENDS = re.compile(r"depends on:?\s*((?:#\d+[\s,and]*)+)", re.IGNORECASE)


# ------------------------------------------------------------------ pure core
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def predicted_files(*texts: str, root: Path = ROOT) -> set[str]:
    """Source files a ticket will probably touch, from paths named in its text."""
    found: set[str] = set()
    for text in texts:
        found.update(_PATH.findall(text or ""))
        for bare in _BARE.findall(text or ""):
            if (root / "src" / bare).exists():
                found.add(f"src/{bare}")
    return {f for f in found if f not in SHARED and not f.startswith(("docs/", "tests/"))}


def claim_marker(agent: str, files: list[str], ttl: int, beat: float | None = None) -> str:
    return (f"<!-- sc-claim v1 agent={agent} ttl={ttl} beat={int(beat or time.time())} "
            f"files={','.join(sorted(files))} -->")


def parse_events(comments: list[dict]) -> list[dict]:
    """Claim/release events, structured and legacy, oldest first."""
    events = []
    for c in comments:
        body = c.get("body") or ""
        issue = c.get("issue") or int((c.get("issue_url") or "0").rsplit("/", 1)[-1] or 0)
        created = parse_time(c["created_at"])
        marker = _MARK.search(body)
        if marker:
            fields = dict(p.split("=", 1) for p in marker.group(2).split() if "=" in p)
            beat = float(fields.get("beat") or created.timestamp())
            events.append({"kind": marker.group(1), "issue": issue, "agent": fields.get("agent", "?"),
                           "at": datetime.fromtimestamp(max(beat, created.timestamp()), timezone.utc),
                           "ttl": min(max(int(fields.get("ttl", 90)), TTL_MIN), TTL_MAX),
                           "files": {f for f in fields.get("files", "").split(",") if f}, "id": c.get("id", 0)})
        elif re.match(r"\s*(?:\*\*)?claim\b", body, re.IGNORECASE) and "releas" not in body[:200].lower():
            events.append({"kind": "claim", "issue": issue, "agent": "legacy", "at": created,
                           "ttl": LEGACY_TTL, "files": predicted_files(body), "id": c.get("id", 0)})
        elif "claim released" in body.lower() or "releasing the claim" in body.lower() \
                or "release the claim" in body.lower() or "releasing my claim" in body.lower():
            events.append({"kind": "release", "issue": issue, "agent": "legacy", "at": created,
                           "ttl": 0, "files": set(), "id": c.get("id", 0)})
    return sorted(events, key=lambda e: (e["at"], e["id"]))


def active_claims(events: list[dict], now: datetime) -> list[dict]:
    live: dict[tuple[int, str], dict] = {}
    for e in events:
        key = (e["issue"], e["agent"])
        if e["kind"] == "release":
            live.pop(key, None)
        else:
            live[key] = e
    return [e for e in live.values() if e["at"] + timedelta(minutes=e["ttl"]) > now]


def conflicts(issue: int, files: set[str], me: str, claims: list[dict]) -> list[str]:
    """Reasons another live claim blocks this ticket (empty means free)."""
    reasons = []
    for c in claims:
        if c["agent"] == me:
            continue
        if c["issue"] == issue:
            reasons.append(f"#{issue} already claimed by {c['agent']}")
        elif files & c["files"]:
            reasons.append(f"overlaps #{c['issue']} ({c['agent']}): {', '.join(sorted(files & c['files'])[:3])}")
    return reasons


def blockers(body: str, open_numbers: set[int]) -> list[int]:
    found = {int(n) for m in _DEPENDS.findall(body or "") for n in re.findall(r"#(\d+)", m)}
    return sorted(found & open_numbers)


def score(issue: dict, files: set[str], hot: set[str], me_claim: bool, slices: int,
          blocked: tuple[int, ...] = ()) -> tuple[int, list[str]]:
    labels = set(issue["labels"])
    why = []
    total = 0
    tier = next((t for t in TIER_SCORE if t in labels), None)
    total += TIER_SCORE.get(tier, 150)
    why.append(tier or "untiered")
    total += PRIORITY_SCORE.get(issue["priority"], 10)
    why.append(issue["priority"])
    if "agent-ready" in labels:
        total += 60
        why.append("agent-ready")
    if slices:
        total += 25
        why.append(f"{slices} slice(s) done: finish it")
    overlap = files & hot
    if overlap:
        total -= min(80, 40 * len(overlap))
        why.append(f"hot: {', '.join(sorted(overlap)[:2])} changed <{HOT_MINUTES}m ago")
    if files & PLAN_FIRST:
        why.append("plan-first module")
    if "in-flight" in labels and not me_claim:
        total -= 40
        why.append("labelled in-flight without a live claim: read the latest comments")
    if blocked:
        total -= 150  # soft: prose dependencies are often half-met when slices already shipped
        why.append("depends on open " + ", ".join(f"#{b}" for b in blocked))
    if me_claim:
        total += 1000
        why.append("your claim")
    return total, why


def tests_for(changed: list[str], tests: dict[str, str]) -> list[str]:
    """Tests worth running for a change: own test files, name matches, importers."""
    chosen = {f for f in changed if f.startswith("tests/") and f in tests}
    if any(f.startswith("src/") or f.endswith("-baseline.json") for f in changed):
        chosen.update(r for r in RATCHETS if r in tests)
    for f in changed:
        if f.startswith("tests/"):
            continue
        if not f.endswith(".py"):  # data/doc/workflow files: tests that name the file
            chosen.update(n for n, text in tests.items() if Path(f).name in text)
            continue
        if not f.startswith(("src/", "scripts/", "setup/")):
            continue
        mod = Path(f).stem
        pat = re.compile(rf"(^|\n)\s*(import {mod}\b|from {mod} import|.*[\"']{re.escape(f)}[\"'])")
        for name, text in tests.items():
            if Path(name).stem.startswith(f"test_{mod}") or pat.search(text):
                chosen.add(name)
    return sorted(chosen)


# ------------------------------------------------------------------- plumbing
def gh(*args: str) -> object:
    out = td._run_gh(["api", *args])
    return json.loads(out) if out.strip() else None


def agent_id() -> str:
    if os.environ.get("SC_AGENT"):
        return os.environ["SC_AGENT"]
    git_dir = Path(subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip())
    path = git_dir / "sc-agent-id"
    if not path.exists():
        path.write_text(f"agent-{uuid.uuid4().hex[:6]}\n")
    return path.read_text().strip()


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def recent_comments(hours: float = TTL_MAX / 60 + 0.5, pages: int = 6) -> list[dict]:
    since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[dict] = []
    for page in range(1, pages + 1):
        chunk = gh(f"repos/{REPO}/issues/comments?since={since}&per_page=100&page={page}&sort=created")
        if not isinstance(chunk, list) or not chunk:
            break
        out.extend(chunk)
    return out


def hot_files(minutes: int = HOT_MINUTES) -> set[str]:
    git("fetch", "-q", "origin", check=False)
    text = git("log", "origin/develop", f"--since={minutes} minutes ago", "--name-only", "--format=", check=False)
    return {line for line in text.splitlines() if line and line not in SHARED}


def load_issue(n: int) -> dict:
    raw = gh(f"repos/{REPO}/issues/{n}")
    assert isinstance(raw, dict)
    issue = td.normalize(td._rest_issue(raw))
    issue["body"] = raw.get("body") or ""
    return issue


# ------------------------------------------------------------------- commands
def cmd_board(_a: argparse.Namespace) -> int:
    now = utcnow()
    claims = active_claims(parse_events(recent_comments()), now)
    print(f"me={agent_id()}  live claims: {len(claims)}")
    for c in sorted(claims, key=lambda c: c["issue"]):
        mins = int((c["at"] + timedelta(minutes=c["ttl"]) - now).total_seconds() // 60)
        print(f"  #{c['issue']:<4} {c['agent']:<14} {mins:>3}m left  {', '.join(sorted(c['files'])[:3])}")
    hot = sorted(hot_files())
    print(f"hot files (develop, last {HOT_MINUTES}m): {', '.join(hot[:12]) or 'none'}")
    verdict = subprocess.run([sys.executable, "scripts/ci/head_verdict.py", "--software-only", "--json"],
                             cwd=ROOT, capture_output=True, text=True)
    try:
        v = json.loads(verdict.stdout)
        print(f"develop head {str(v.get('head'))[:7]}: software={v.get('software')} (a red head outranks new work)")
    except ValueError:
        print("develop head: verdict unavailable")
    return 0


def cmd_next(a: argparse.Namespace) -> int:
    me, now = agent_id(), utcnow()
    claims = active_claims(parse_events(recent_comments()), now)
    hot = hot_files()
    tiers = ["now", "next"] + (["later"] if a.later else [])
    pool = {}
    for tier in tiers:
        rows = gh(f"repos/{REPO}/issues?state=open&labels={tier}&per_page=100")
        for r in rows if isinstance(rows, list) else []:
            if "pull_request" not in r:
                pool[r["number"]] = r
    open_numbers = set(pool)
    ranked, skipped = [], []
    for n, raw in pool.items():
        issue = td.normalize(td._rest_issue(raw))
        labels = set(issue["labels"])
        if labels & SKIP_LABELS and not a.include_skipped:
            continue
        files = predicted_files(raw.get("body") or "")
        if a.lane and not any(f.startswith(a.lane) or a.lane in f for f in files):
            continue
        bad = conflicts(n, files, me, claims)
        if bad:
            skipped.append((n, bad[0]))
            continue
        wait = tuple(blockers(raw.get("body") or "", open_numbers))
        base, _ = score(issue, files, hot, any(c["issue"] == n and c["agent"] == me for c in claims), 0, wait)
        ranked.append((base, n, issue, files, wait))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    for _base, n, issue, files, wait in ranked[: a.limit]:
        comments = gh(f"repos/{REPO}/issues/{n}/comments?per_page=100")
        slices = sum(1 for c in comments if isinstance(c, dict) and "Implementation:" in (c.get("body") or "")) \
            if isinstance(comments, list) else 0
        total, why = score(issue, files, hot, any(c["issue"] == n and c["agent"] == me for c in claims), slices, wait)
        print(f"#{n:<4} {total:>4}  {td.display_title(issue['title'])[:70]}\n       {', '.join(why)}"
              f"\n       files: {', '.join(sorted(files)[:4]) or '(none named; read the brief)'}"
              f"\n       -> python3 scripts/agent.py claim {n}")
    if not ranked:
        print("nothing free: every candidate is claimed, blocked or excluded")
    for n, reason in skipped[:5]:
        print(f"  skipped #{n}: {reason}")
    return 0


def cmd_claim(a: argparse.Namespace) -> int:
    me = agent_id()
    issue = load_issue(a.number)
    files = set(a.files.split(",")) if a.files else predicted_files(issue["body"])
    ttl = min(max(a.ttl, TTL_MIN), TTL_MAX)

    def check() -> list[str]:
        return conflicts(a.number, files, me, active_claims(parse_events(recent_comments()), utcnow()))

    if (bad := check()):
        print("CONFLICT: " + "; ".join(bad) + "\nPick another ticket: python3 scripts/agent.py next")
        return 3
    body = (f"Claim: {me} · ~{ttl} min lease, refresh with `agent.py heartbeat {a.number}` · "
            f"files: {', '.join(sorted(files)) or 'tbd'}\n{claim_marker(me, sorted(files), ttl)}")
    posted = gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/comments", "-f", f"body={body}")
    assert isinstance(posted, dict)
    # Optimistic lock: after posting, the earliest live claim on the ticket/files wins.
    events = [e for e in parse_events(recent_comments()) if e["id"] <= posted["id"]]
    mine = [e for e in events if e["id"] == posted["id"]]
    rivals = [c for c in active_claims(events, utcnow())
              if c["agent"] != me and (c["issue"] == a.number or files & c["files"]) and c["id"] < posted["id"]]
    if mine and rivals:
        gh("-X", "DELETE", f"repos/{REPO}/issues/comments/{posted['id']}")
        print(f"LOST RACE to {rivals[0]['agent']} on #{rivals[0]['issue']}; claim withdrawn. "
              "Run: python3 scripts/agent.py next")
        return 3
    gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/labels", "-f", "labels[]=in-flight")
    print(f"claimed #{a.number} as {me}; lease {ttl} min (heartbeat to extend). Files: {', '.join(sorted(files)) or 'tbd'}")
    if files & PLAN_FIRST:
        print("NOTE: plan-first module; comment a short plan before editing (CLAUDE.md).")
    return 0


def cmd_heartbeat(a: argparse.Namespace) -> int:
    me = agent_id()
    for c in reversed(gh(f"repos/{REPO}/issues/{a.number}/comments?per_page=100") or []):  # type: ignore[union-attr]
        m = _MARK.search(c.get("body") or "")
        if m and f"agent={me}" in m.group(2) and m.group(1) == "claim":
            new = re.sub(r"beat=\d+", f"beat={int(time.time())}", c["body"])
            gh("-X", "PATCH", f"repos/{REPO}/issues/comments/{c['id']}", "-f", f"body={new}")
            print(f"lease on #{a.number} refreshed")
            return 0
    print(f"no live claim by {me} on #{a.number}")
    return 1


def release(number: int, note: str) -> None:
    me = agent_id()
    gh("-X", "POST", f"repos/{REPO}/issues/{number}/comments", "-f",
       f"body=Released: {me}. {note}\n<!-- sc-release v1 agent={me} -->")
    left = active_claims(parse_events(recent_comments()), utcnow())
    if not any(c["issue"] == number for c in left):
        subprocess.run(["gh", "api", "-X", "DELETE", f"repos/{REPO}/issues/{number}/labels/in-flight"],
                       capture_output=True)


def cmd_release(a: argparse.Namespace) -> int:
    release(a.number, a.note)
    print(f"released #{a.number}")
    return 0


def mypy_gated() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return set(data.get("tool", {}).get("mypy", {}).get("files", []))


def plan_checks(changed: list[str], tests: dict[str, str]) -> list[tuple[str, list[str]]]:
    py = [f for f in changed if f.endswith(".py") and (ROOT / f).exists()]
    steps: list[tuple[str, list[str]]] = []
    if py:
        steps.append(("compile", [sys.executable, "-m", "compileall", "-q", *py]))
        steps.append(("ruff", ["ruff", "check", *py]))
    if any(f in mypy_gated() for f in changed):
        steps.append(("mypy", ["mypy"]))
    chosen = tests_for(changed, tests)
    if chosen:
        xdist = ["-n", "auto"] if len(chosen) > 3 else []
        steps.append((f"pytest ({len(chosen)} files)", [sys.executable, "-m", "pytest", "-q", "-x", *xdist, *chosen]))
    return steps


def cmd_ship(a: argparse.Namespace) -> int:
    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("tracked files are uncommitted: commit them first (stage by name).")
        return 2
    for attempt in range(1, 4):
        git("fetch", "-q", "origin")
        before = git("rev-parse", "HEAD").strip()
        r = subprocess.run(["git", "rebase", "origin/develop"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            conflicted = git("diff", "--name-only", "--diff-filter=U", check=False).split()
            git("rebase", "--abort", check=False)
            print(f"REBASE CONFLICT in {', '.join(conflicted) or '?'}; resolve by hand, never force-push.")
            return 4
        changed = [f for f in git("diff", "--name-only", "origin/develop...HEAD").split() if f]
        if not changed:
            print("nothing to ship: HEAD equals origin/develop")
            return 0
        tests = {str(p.relative_to(ROOT)): p.read_text(errors="replace") for p in (ROOT / "tests").glob("test_*.py")}
        rebased = git("rev-parse", "HEAD").strip() != before
        for label, cmd in plan_checks(changed, tests):
            started = time.time()
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            print(f"  {label}: {'ok' if res.returncode == 0 else 'FAIL'} ({time.time() - started:.1f}s)")
            if res.returncode:
                print((res.stdout + res.stderr)[-1800:])
                return 1
        if a.dry_run:
            print(f"dry run ok: {len(changed)} files, rebased={rebased}")
            return 0
        push = subprocess.run(["git", "push", "origin", "HEAD:develop"], cwd=ROOT, capture_output=True, text=True)
        if push.returncode == 0:
            sha = git("rev-parse", "--short", "HEAD").strip()
            print(f"pushed {sha} to develop (attempt {attempt}). Next: agent.py done N --why ... "
                  "| CI is coalesced; do not poll, check `agent.py board` later.")
            return 0
        print(f"push rejected (someone pushed first); rebasing again [{attempt}/3]")
    print("could not push after 3 attempts; inspect `git fetch && git log HEAD..origin/develop`.")
    return 5


def cmd_done(a: argparse.Namespace) -> int:
    head = git("rev-parse", "HEAD").strip()
    if subprocess.run(["git", "merge-base", "--is-ancestor", head, "origin/develop"], cwd=ROOT).returncode:
        print("HEAD is not on origin/develop yet: run `agent.py ship` first.")
        return 2
    sha = head[:7]
    files = sorted({f for f in git("log", "origin/develop", f"--grep=#{a.number}\\b", "--name-only", "--format=").split() if f})
    body = (f"Implementation: {sha}. Why: {a.why}. Files: {', '.join(files[:12]) or 'see commits'}. "
            f"Checklist: {a.checklist}. Verification: {a.verification}.")
    gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/comments", "-f", f"body={body}")
    release(a.number, "work complete.")
    if a.close:
        subprocess.run(["gh", "issue", "close", str(a.number), "--reason", "completed"], cwd=ROOT)
        print(f"closed #{a.number}")
    else:
        print(f"evidence posted on #{a.number}; add --close once every acceptance item passes")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board").set_defaults(fn=cmd_board)
    n = sub.add_parser("next")
    n.add_argument("--limit", type=int, default=5)
    n.add_argument("--lane", default="", help="only tickets touching this path prefix/substring (e.g. src/portal, mesh)")
    n.add_argument("--later", action="store_true", help="also consider the `later` tier")
    n.add_argument("--include-skipped", action="store_true")
    n.set_defaults(fn=cmd_next)
    c = sub.add_parser("claim")
    c.add_argument("number", type=int)
    c.add_argument("--files", default="", help="comma-separated files you will edit (default: from the ticket)")
    c.add_argument("--ttl", type=int, default=90, help="lease minutes (30-180)")
    c.set_defaults(fn=cmd_claim)
    h = sub.add_parser("heartbeat")
    h.add_argument("number", type=int)
    h.set_defaults(fn=cmd_heartbeat)
    r = sub.add_parser("release")
    r.add_argument("number", type=int)
    r.add_argument("--note", default="no work in progress.")
    r.set_defaults(fn=cmd_release)
    s = sub.add_parser("ship")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_ship)
    d = sub.add_parser("done")
    d.add_argument("number", type=int)
    d.add_argument("--why", required=True)
    d.add_argument("--checklist", required=True)
    d.add_argument("--verification", default="portable=pass; isolated GTK=not run; device=n/a")
    d.add_argument("--close", action="store_true")
    d.set_defaults(fn=cmd_done)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except td.DigestError as exc:
        print(f"GitHub unavailable: {exc}")
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
