#!/usr/bin/env python3
"""One entry point for agents: pick work, claim it safely, ship it fast.

    python3 scripts/agent.py board            who holds what, hot files, CI head
    python3 scripts/agent.py next [--lane L]  best ticket that collides with nobody
    python3 scripts/agent.py claim N          atomic claim (loser backs off)
    python3 scripts/agent.py ship [--skip-checks]  rebase and push; checks optional
    python3 scripts/agent.py done N --why .. --checklist ..   evidence + release

Design: docs/agents/coordination.md. Claims live in structured issue comments
(``<!-- sc-claim v1 ... -->``) and legacy free-text "Claim:" comments are read
too, because every agent posts as one GitHub user and never sets an assignee.
Never launches a GUI, never force-pushes, never closes without ``--close``.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_digest as td  # noqa: E402
from ci import ship_patch  # noqa: E402

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
    # IDs record immutable publication order. A heartbeat edits an older claim's
    # beat in place; ordering by the beat would resurrect it after a release.
    return sorted(events, key=lambda e: e["id"])


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


def summarize_history(comments: list[dict]) -> tuple[int, str, str]:
    """Bounded last-progress preview from durable issue comments; no extra API calls.

    The most recent progress-bearing comment is authoritative for the preview:
    do not attach an older Handover line to a later Implementation update.
    """
    slices, latest, remaining = 0, "", ""
    ordered = sorted((c for c in comments if isinstance(c, dict)),
                     key=lambda c: int(c.get("id") or 0))
    for comment in ordered:
        body = str(comment.get("body") or "")
        progress, handover = "", ""
        for line in body.splitlines():
            match = re.match(r"^\s*(Implementation|Progress|Handover|Remaining):\s*(.+)$",
                             line, re.IGNORECASE)
            if not match:
                continue
            label, value = match.groups()
            value = " ".join(value.split())[:160]
            if label.lower() == "implementation":
                slices += 1
            if label.lower() in {"implementation", "progress"}:
                progress = value
            else:
                handover = value
        if progress or handover:
            latest, remaining = progress, handover
    return slices, latest, remaining


def ranked_candidates(a: argparse.Namespace) -> tuple[list, list, list, set, str]:
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
    return ranked, skipped, claims, hot, me


def cmd_next(a: argparse.Namespace) -> int:
    ranked, skipped, claims, hot, me = ranked_candidates(a)
    for _base, n, issue, files, wait in ranked[: a.limit]:
        comments = gh(f"repos/{REPO}/issues/{n}/comments?per_page=100")
        slices, progress, handover = summarize_history(comments if isinstance(comments, list) else [])
        total, why = score(issue, files, hot, any(c["issue"] == n and c["agent"] == me for c in claims), slices, wait)
        print(f"#{n:<4} {total:>4}  {td.display_title(issue['title'])[:70]}\n       {', '.join(why)}"
              f"\n       files: {', '.join(sorted(files)[:4]) or '(none named; read the brief)'}")
        if progress:
            print(f"       last progress: {progress}")
        if handover:
            print(f"       handover: {handover}")
        print(f"       -> review comments/commits; python3 scripts/agent.py claim {n}")
    if not ranked:
        print("nothing free: every candidate is claimed, blocked or excluded")
    for n, reason in skipped[:5]:
        print(f"  skipped #{n}: {reason}")
    return 0



def issue_context_packet(number: int, issue: dict, comments: list[dict], base: str) -> str:
    """Persist a bounded, source-grounded brief outside the tracked checkout."""
    ordered = sorted((c for c in comments if isinstance(c, dict)),
                     key=lambda c: int(c.get("id") or 0))
    handovers = [str(c.get("body") or "") for c in ordered
                 if re.search(r"(?m)^(?:Progress|Implementation|Handover):", str(c.get("body") or ""))]
    latest = handovers[-1][:5000] if handovers else "No prior handover; inspect related commits."
    body = str(issue.get("body") or "")
    named = sorted(predicted_files(body))
    return (
        f"# SmoothCast issue #{number}: {issue.get('title', '')}\n\n"
        f"Source baseline: {base}\n"
        "Authority: GitHub issue and latest develop source; refresh before each ship.\n"
        f"Likely files: {', '.join(named) or 'not specified; inspect issue and source'}\n"
        "Start here: AGENTS.md then one routed handbook topic.\n\n"
        f"## Acceptance and background\n{body[:30000]}\n\n"
        f"## Most recent durable handover\n{latest}\n"
    )


def private_task() -> dict | None:
    """Return this detached worktree's task marker; never trust a shared checkout."""
    if not (ROOT / ".git").is_file():
        return None
    try:
        folder = Path(git("rev-parse", "--absolute-git-dir").strip())
        payload = json.loads((folder / "sc-agent-task.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or type(payload.get("issue")) is not int:
            return None
        return payload
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def cmd_start(a: argparse.Namespace) -> int:
    """Pick or resume a ticket with a fresh private checkout and durable context."""
    git("fetch", "-q", "origin", "develop")
    if a.number is None:
        ranked, _, _, _, _ = ranked_candidates(a)
        if not ranked:
            print("no available ticket; inspect agent.py board or supply an issue number")
            return 3
        number = ranked[0][1]
    else:
        number = a.number
    issue = load_issue(number)
    if issue.get("state") == "closed":
        print(f"issue #{number} is already closed; no claim made")
        return 3
    chosen_files = a.files or ",".join(sorted(predicted_files(issue.get("body") or "")))
    # Do not inherit the shared checkout's identity: repeated starts are
    # independent agents even when the same automation account launches them.
    previous = os.environ.get("SC_AGENT")
    identity = f"{previous or 'agent'}-{uuid.uuid4().hex[:8]}"
    os.environ["SC_AGENT"] = identity
    target = ROOT.parent / f"smoothcast-issue-{number}-{uuid.uuid4().hex[:8]}"
    claimed = created = False
    try:
        code = cmd_claim(argparse.Namespace(number=number, files=chosen_files, ttl=a.ttl))
        if code:
            return code
        claimed = True
        run = subprocess.run(["git", "worktree", "add", "--detach", str(target), "origin/develop"],
                             cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError((run.stderr or run.stdout).strip()[:500])
        created = True
        admin = subprocess.run(["git", "-C", str(target), "rev-parse", "--absolute-git-dir"],
                               capture_output=True, text=True, check=True).stdout.strip()
        folder = Path(admin)
        folder.joinpath("sc-agent-id").write_text(identity + "\n", encoding="utf-8")
        head = git("rev-parse", "origin/develop").strip()
        metadata = {"issue": number, "title": issue.get("title") or "",
                    "files": sorted(p for p in chosen_files.split(",") if p),
                    "source_head": head, "started_at": utcnow().isoformat()}
        folder.joinpath("sc-agent-task.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        comments = gh(f"repos/{REPO}/issues/{number}/comments?per_page=100")
        packet = issue_context_packet(number, issue, comments if isinstance(comments, list) else [], head)
        brief = folder / "sc-agent-brief.md"
        brief.write_text(packet, encoding="utf-8")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, td.DigestError) as exc:
        if created:
            subprocess.run(["git", "worktree", "remove", "--force", str(target)],
                           cwd=ROOT, capture_output=True)
        if claimed:
            release(number, f"start failed: {type(exc).__name__}")
        print(f"could not initialise private worktree for #{number}: {exc}")
        return 4
    finally:
        if previous is None:
            os.environ.pop("SC_AGENT", None)
        else:
            os.environ["SC_AGENT"] = previous
    print(f"READY issue #{number}: {issue.get('title', '')}")
    print(f"  worktree: {target}")
    print(f"  context: {brief} (read the issue and latest handover)")
    print(f"  cd {__import__('shlex').quote(str(target))}")
    print("  python3 scripts/agent.py ship --message 'what changed' [--files src/new.py]")
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
    if not isinstance(posted, dict) or not isinstance(posted.get("id"), int):
        raise td.DigestError("GitHub did not return a claim comment ID")
    # Verify publication before taking an assignment. The global comment feed
    # can lag; consult this issue directly only when our claim is missing.
    recent = recent_comments()
    if not any(c.get("id") == posted["id"] for c in recent):
        direct = gh(f"repos/{REPO}/issues/{a.number}/comments?per_page=100")
        if isinstance(direct, list):
            seen = {c.get("id") for c in recent}
            recent.extend(c for c in direct if isinstance(c, dict) and c.get("id") not in seen)
    # Optimistic lock: only an earlier published claim can beat our claim.
    events = [e for e in parse_events(recent) if e["id"] <= posted["id"]]
    mine = [e for e in events if e["id"] == posted["id"] and e["kind"] == "claim"]
    rivals = [c for c in active_claims(events, utcnow())
              if c["agent"] != me and (c["issue"] == a.number or files & c["files"]) and c["id"] < posted["id"]]
    if not mine or rivals:
        gh("-X", "DELETE", f"repos/{REPO}/issues/comments/{posted['id']}")
        if rivals:
            print(f"LOST RACE to {rivals[0]['agent']} on #{rivals[0]['issue']}; claim withdrawn. "
                  "Run: python3 scripts/agent.py next")
        else:
            print("CLAIM NOT CONFIRMED in GitHub comment feed; withdrawn, retry or pick another.")
        return 3
    gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/labels", "-f", "labels[]=in-flight")
    login = gh("user")
    if isinstance(login, dict) and login.get("login"):  # AGENTS.md: claim by assignment + comment
        gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/assignees", "-f", f"assignees[]={login['login']}")
    print(f"claimed #{a.number} as {me}; lease {ttl} min (heartbeat to extend). Files: {', '.join(sorted(files)) or 'tbd'}")
    if files & PLAN_FIRST:
        print("NOTE: plan-first module; comment a short plan before editing (CLAUDE.md).")
    return 0


def ensure_live_task_claim(task: dict) -> bool:
    """Refuse a successor's active lease; safely reclaim an expired task."""
    number = task["issue"]
    me = agent_id()
    files = set(task.get("files") or [])
    comments = gh(f"repos/{REPO}/issues/{number}/comments?per_page=100")
    if not isinstance(comments, list):
        raise td.DigestError(f"cannot inspect live claims on #{number}")
    events = parse_events([dict(c, issue=number) for c in comments if isinstance(c, dict)])
    live = active_claims(events, utcnow())
    bad = conflicts(number, files, me, live)
    if bad:
        print("another agent now owns this scope: " + "; ".join(bad))
        return False
    mine = [c for c in live if c["issue"] == number and c["agent"] == me]
    if mine:
        remaining = (mine[-1]["at"] + timedelta(minutes=mine[-1]["ttl"]) - utcnow()).total_seconds()
        if remaining < 900:
            return cmd_heartbeat(argparse.Namespace(number=number)) == 0
        return True
    # Claim expiry grants no ownership. Existing race arbitration must win.
    print(f"claim on #{number} expired; attempting a fresh short-lived lease")
    return cmd_claim(argparse.Namespace(number=number, files=",".join(sorted(files)),
                                        ttl=90)) == 0


def cmd_progress(a: argparse.Namespace) -> int:
    """Persist the work/evidence/next-action independently of the expiring claim."""
    if not a.done.strip() or not a.next.strip():
        print("both --done and --next must describe completed and remaining work")
        return 2
    body = (f"Progress: {a.done.strip()}\n"
            f"Handover: {a.next.strip()}\n"
            f"Commit: {a.commit.strip() or 'not pushed'}\n"
            f"Verification: {a.verification.strip() or 'not run (unverified)'}\n"
            f"Files: {a.files.strip() or 'see commit'}")
    posted = gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/comments",
                "-f", f"body={body}")
    if not isinstance(posted, dict) or not isinstance(posted.get("id"), int):
        raise td.DigestError(f"GitHub did not confirm handover on #{a.number}")
    print(f"durable handover on #{a.number}: comment {posted['id']}")
    if a.release:
        release(a.number, f"Handover recorded in comment {posted['id']}.")
        print(f"released #{a.number}")
    return 0


def cmd_heartbeat(a: argparse.Namespace) -> int:
    me = agent_id()
    comments = gh(f"repos/{REPO}/issues/{a.number}/comments?per_page=100")
    if not isinstance(comments, list):
        raise td.DigestError(f"cannot inspect claims on #{a.number}")
    live = active_claims(parse_events(comments), utcnow())
    owned = {c["id"] for c in live if c["agent"] == me and c["issue"] == a.number}
    for c in reversed(comments):
        if c.get("id") not in owned:
            continue
        m = _MARK.search(c.get("body") or "")
        if m and m.group(1) == "claim":
            new = re.sub(r"beat=\d+", f"beat={int(time.time())}", c["body"])
            gh("-X", "PATCH", f"repos/{REPO}/issues/comments/{c['id']}", "-f", f"body={new}")
            print(f"lease on #{a.number} refreshed")
            return 0
    print(f"no live claim by {me} on #{a.number}; claim again instead of reviving an expired lease")
    return 1


def release(number: int, note: str) -> None:
    me = agent_id()
    gh("-X", "POST", f"repos/{REPO}/issues/{number}/comments", "-f",
       f"body=Released: {me}. {note}\n<!-- sc-release v1 agent={me} -->")
    left = active_claims(parse_events(recent_comments()), utcnow())
    if not any(c["issue"] == number for c in left):
        subprocess.run(["gh", "api", "-X", "DELETE", f"repos/{REPO}/issues/{number}/labels/in-flight"],
                       capture_output=True)
        me_login = gh("user")
        if isinstance(me_login, dict) and me_login.get("login"):
            subprocess.run(["gh", "api", "-X", "DELETE", f"repos/{REPO}/issues/{number}/assignees",
                            "-f", f"assignees[]={me_login['login']}"], capture_output=True)


def cmd_release(a: argparse.Namespace) -> int:
    release(a.number, a.note)
    print(f"released #{a.number}")
    return 0


def mypy_gated() -> set[str]:
    """Read the simple list of mypy-gated files with Python 3.10 stdlib only."""
    contents = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = contents.split("[tool.mypy]", 1)
    if len(section) != 2:
        return set()
    body = section[1].split("\n[", 1)[0]
    match = re.search(r"(?ms)^files\s*=\s*(\[[^\]]*\])", body)
    if not match:
        return set()
    try:
        files = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError) as exc:
        raise ValueError("invalid [tool.mypy] files list in pyproject.toml") from exc
    if not isinstance(files, list) or any(not isinstance(f, str) for f in files):
        raise ValueError("[tool.mypy] files must be a list of strings")
    return set(files)


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
        steps.append((f"pytest ({len(chosen)} files)", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *xdist, *chosen]))
    return steps


def failing_ids(output: str) -> list[str]:
    """Node ids of failed tests from pytest -q output."""
    return sorted({line.split()[1] for line in output.splitlines()
                   if line.startswith(("FAILED ", "ERROR ")) and len(line.split()) > 1})


def failing_on_develop(ids: list[str]) -> set[str]:
    """Which of these tests also fail on a pristine origin/develop (not your regression)."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="sc-base-") as tmp:
        tree = Path(tmp) / "tree"
        if subprocess.run(["git", "worktree", "add", "--detach", "-q", str(tree), "origin/develop"],
                          cwd=ROOT, capture_output=True).returncode:
            return set()  # cannot prove it: treat every failure as yours
        try:
            res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *ids],
                                 cwd=tree, capture_output=True, text=True)
            return set(failing_ids(res.stdout))
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)


def commit_private_slice(a: argparse.Namespace) -> int:
    """Optional atomic commit in an agent-owned worktree; never sweep user files."""
    if not a.message:
        return 0
    task = private_task()
    if task is None:
        print("automatic commits require a private worktree created by agent.py start")
        return 2
    if a.dry_run:
        print("--dry-run cannot be combined with --message (which creates a commit)")
        return 2
    paths = [p.strip() for p in a.files.split(",") if p.strip()]
    if a.files and (not paths or any(
            Path(p).is_absolute() or ".." in Path(p).parts
            or p in {".", "./"} or p.startswith("-") for p in paths)):
        print("--files requires safe, named repository-relative paths")
        return 2
    # Stage ALL tracked edits in this private worktree; --files additionally
    # includes named new files, never an uncontrolled untracked directory sweep.
    staged = subprocess.run(["git", "add", "-u"],
                            cwd=ROOT, capture_output=True, text=True)
    if staged.returncode == 0 and paths:
        staged = subprocess.run(["git", "add", "-A", "--", *paths],
                                cwd=ROOT, capture_output=True, text=True)
    if staged.returncode:
        print("staging failed: " + staged.stderr.strip()[:500])
        return 2
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if diff.returncode == 0:
        print("no changes to commit; shipping any existing unpublished commits")
        return 0
    if diff.returncode != 1:
        print("cannot determine staged changes; refusing to commit")
        return 2
    number = task["issue"]
    message = a.message.strip()
    if not message:
        print("--message must be nonempty")
        return 2
    if not re.search(rf"(?<!\d)#{number}(?!\d)", message):
        message += f" (Refs #{number})"
    committed = subprocess.run(["git", "commit", "-m", message], cwd=ROOT,
                               capture_output=True, text=True)
    if committed.returncode:
        print("commit failed: " + (committed.stderr or committed.stdout).strip()[:500])
        return 2
    print(f"committed private slice for #{number}")
    return 0


def publish_ship_handover(task: dict | None, sha: str, changed: list[str],
                          verification: str, next_action: str) -> None:
    """Best-effort, idempotent evidence; never reinterpret a failed push as success."""
    if task is None:
        return
    number = task["issue"]
    marker = f"<!-- sc-ship v1 sha={sha} -->"
    try:
        comments = gh(f"repos/{REPO}/issues/{number}/comments?per_page=100")
        if isinstance(comments, list) and any(
                marker in str(c.get("body") or "") for c in comments):
            return
        body = (f"Progress: pushed a coherent develop slice at {sha[:12]}\n"
                f"Handover: {next_action or 'Review remaining issue acceptance criteria against develop'}\n"
                f"Commit: {sha}\nVerification: {verification}\n"
                f"Files: {', '.join(changed[:20]) or 'see commit'}\n{marker}")
        posted = gh("-X", "POST", f"repos/{REPO}/issues/{number}/comments",
                    "-f", f"body={body}")
        if not isinstance(posted, dict) or not isinstance(posted.get("id"), int):
            raise td.DigestError("GitHub did not confirm ship handover")
    except td.DigestError as exc:
        print(f"WARNING: develop commit {sha[:12]} landed, but issue handover failed: {exc}")


def cmd_ship(a: argparse.Namespace) -> int:
    result = commit_private_slice(a)
    if result:
        return result
    task = private_task()
    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("tracked files are uncommitted: commit them first (stage by name).")
        return 2
    checked_base = ""  # origin/develop at the moment our checks last passed
    checks_run: list[str] = []
    for attempt in range(1, 6):
        git("fetch", "-q", "origin", "develop")
        remote_before = git("rev-parse", "origin/develop").strip()
        if task is not None:
            # Fast feedback when an issue was closed while the agent worked.
            try:
                state = gh(f"repos/{REPO}/issues/{task['issue']}")
            except td.DigestError as exc:
                print(f"ticket freshness check failed: {exc}; refusing unreviewed push")
                return 3
            if not isinstance(state, dict) or state.get("state") != "open":
                print(f"issue #{task['issue']} is no longer open; review latest state before shipping")
                return 3
            if not ensure_live_task_claim(task):
                print("worktree preserved; review current claims before shipping")
                return 3
        # A contested push may have left our own unpublished version commit.
        # Remove ONLY that verified generated commit before rebasing the code.
        if task is not None:
            try:
                ship_patch.recover_private_patch(ROOT, remote_before)
            except ship_patch.PatchAllocationError as exc:
                print(f"PATCH RECOVERY REFUSED: {exc}")
                return 6
        before = git("rev-parse", "HEAD").strip()
        r = subprocess.run(["git", "-c", "rebase.autoStash=false", "rebase", "origin/develop"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            conflicted = git("diff", "--name-only", "--diff-filter=U", check=False).split()
            git("rebase", "--abort", check=False)
            print(f"REBASE CONFLICT in {', '.join(conflicted) or '?'}; resolve by hand, never force-push.")
            return 4
        changed = [f for f in git("diff", "--name-only", "origin/develop...HEAD").split() if f]
        if not changed:
            print("nothing to ship: HEAD equals origin/develop")
            return 0
        rebased = git("rev-parse", "HEAD").strip() != before
        # Mandatory even with --skip-checks: a concurrent agent must never
        # regress, skip or silently overwrite a canonical version increment.
        # Inspect *every* unpublished commit after rebasing, not only HEAD.
        version_guard = subprocess.run(
            [sys.executable, "scripts/ci/check_version_history.py",
             "--before", git("rev-parse", "origin/develop").strip(),
             "--after", git("rev-parse", "HEAD").strip()],
            cwd=ROOT, capture_output=True, text=True,
        )
        if version_guard.returncode:
            print("VERSION INTEGRITY FAILED; not pushing develop.")
            print((version_guard.stdout + version_guard.stderr)[-1500:])
            return 6
        recheck = True
        if checked_base:  # a contended push: re-test only if the newcomers touched our files
            incoming = set(git("diff", "--name-only", checked_base, "origin/develop").split())
            recheck = bool(incoming & (set(changed) | SHARED))
            if not recheck:
                print(f"  {len(incoming)} incoming file(s) do not touch yours; reusing the earlier checks")
        if not a.skip_checks and recheck:
            tests = {str(p.relative_to(ROOT)): p.read_text(errors="replace")
                     for p in (ROOT / "tests").glob("test_*.py")}
            for label, cmd in plan_checks(changed, tests):
                started = time.time()
                res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
                print(f"  {label}: {'ok' if res.returncode == 0 else 'FAIL'} "
                      f"({time.time() - started:.1f}s)")
                if res.returncode:
                    ids = failing_ids(res.stdout)
                    mine = (set(ids) - failing_on_develop(ids)
                            if ids and label.startswith("pytest") else set(ids or ["?"]))
                    if mine:
                        print((res.stdout + res.stderr)[-1800:])
                        print(f"  YOUR failures: {', '.join(sorted(mine))[:400]}")
                        return 1
                    print(f"  NOT yours: {len(ids)} test(s) already fail on "
                          f"origin/develop; pushing anyway: {', '.join(ids)[:300]}")
                else:
                    checks_run.append(label)
            checked_base = git("rev-parse", "origin/develop").strip()
        elif a.skip_checks:
            print("  checks skipped by request; this push is UNVERIFIED")
        if a.dry_run:
            print(f"dry run ok: {len(changed)} files, rebased={rebased}")
            return 0
        if task is not None and a.assign_patch:
            # Explicit owner-authorised version assignment only. Ordinary
            # agent shipments use immutable Git SHAs as development identities.
            try:
                minted = ship_patch.assign_private_patch(ROOT, remote_before, task["issue"])
            except (ship_patch.PatchAllocationError, OSError) as exc:
                print(f"PATCH ASSIGNMENT REFUSED: {exc}; pending work preserved")
                return 6
            if minted:
                print(f"  assigned next develop PATCH at {minted[:12]} (unpublished until push)")
                changed = sorted(set(changed) | {"src/version.py"})
                # Recheck the full unpublished range including our generated
                # version-only commit, not just the agent's original code.
                guarded = subprocess.run(
                    [sys.executable, "scripts/ci/check_version_history.py",
                     "--before", remote_before, "--after", git("rev-parse", "HEAD").strip()],
                    cwd=ROOT, capture_output=True, text=True)
                if guarded.returncode:
                    print("PATCH INTEGRITY FAILED; no push.")
                    print((guarded.stdout + guarded.stderr)[-1200:])
                    return 6
        push = subprocess.run(["git", "push", "origin", "HEAD:develop"],
                              cwd=ROOT, capture_output=True, text=True)
        sha = git("rev-parse", "HEAD").strip()
        if push.returncode:
            # A lost acknowledgement after a successful remote push is not a
            # reason to replay commits. Fetch and inspect ancestry first.
            fetch = subprocess.run(["git", "fetch", "-q", "origin", "develop"],
                                   cwd=ROOT, capture_output=True, text=True)
            if fetch.returncode:
                print("push outcome uncertain; remote fetch failed. Do not reset or retry blindly.")
                print((push.stderr + fetch.stderr)[-700:])
                return 5
            remote_now = git("rev-parse", "origin/develop").strip()
            contains = subprocess.run(["git", "merge-base", "--is-ancestor", sha, remote_now],
                                      cwd=ROOT, capture_output=True).returncode == 0
            if not contains and remote_now == remote_before:
                print("push failed without a competing change: " + push.stderr.strip()[-800:])
                return 5
            if not contains:
                print(f"remote advanced; safely retrying [{attempt}/5]")
                continue
            print("remote contains the commit: treating failed push acknowledgement as success")
        verification = ("not run (unverified)" if a.skip_checks else
                        (", ".join(sorted(set(checks_run))) or "no affected tests selected"))
        publish_ship_handover(task, sha, changed, verification, a.next)
        print(f"pushed {sha[:12]} to develop (attempt {attempt}); {verification}")
        return 0
    print("could not push after 5 contested attempts; preserve worktree and inspect origin/develop")
    return 5


def close_issue(number: int) -> None:
    """Close through REST and verify the response; gh issue close may hit GraphQL 403."""
    result = gh("-X", "PATCH", f"repos/{REPO}/issues/{number}", "-f", "state=closed",
                "-f", "state_reason=completed")
    if not isinstance(result, dict) or result.get("state") != "closed":
        raise td.DigestError(f"GitHub did not confirm closing #{number}")


def ticket_commits(number: int) -> list[str]:
    """Commits actually mentioning #N, excluding #N0 and other prefix matches."""
    expression = f"(^|[^0-9])#{number}([^0-9]|$)"
    return git("log", "--extended-regexp", f"--grep={expression}",
               "--format=%H", "origin/develop").splitlines()


def cmd_done(a: argparse.Namespace) -> int:
    head = git("rev-parse", "HEAD").strip()
    if subprocess.run(["git", "merge-base", "--is-ancestor", head, "origin/develop"], cwd=ROOT).returncode:
        print("HEAD is not on origin/develop yet: run `agent.py ship` first.")
        return 2
    if a.close and a.verification == "not run (unverified)":
        print("Refusing to close without explicit --verification evidence.")
        return 2
    refs = ticket_commits(a.number)
    if not refs:
        print(f"No published develop commit references #{a.number}; cannot report completion.")
        return 2
    sha = refs[0][:7]
    files = sorted({f for f in git("show", "--format=", "--name-only",
                                   *refs[:8]).split() if f})
    body = (f"Implementation: {sha}. Why: {a.why}. Files: {', '.join(files[:12]) or 'see commits'}. "
            f"Checklist: {a.checklist}. Verification: {a.verification}.")
    gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/comments", "-f", f"body={body}")
    release(a.number, "work complete.")
    if a.close:
        close_issue(a.number)
        print(f"closed #{a.number} (confirmed by GitHub REST)")
    else:
        print(f"evidence posted on #{a.number}; add --close once every acceptance item passes")
    return 0



def cmd_finish(a: argparse.Namespace) -> int:
    """Durable, retry-safe ticket handover; closure only with explicit evidence."""
    task = private_task()
    number = a.number if a.number is not None else (task or {}).get("issue")
    if not number:
        print("finish needs an issue number or a worktree created by agent.py start")
        return 2
    if not a.done.strip() or not a.next.strip():
        print("--done and --next must record actual outcome and remaining work")
        return 2
    if a.close and (not a.verification.strip()
                    or "unverified" in a.verification.lower()
                    or "not run" in a.verification.lower()
                    or not a.checklist.strip()
                    or a.next.strip().lower() not in {"none", "complete", "no remaining work"}):
        print("closure requires --verification, --checklist, and --next none")
        return 2
    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("uncommitted tracked work; ship before finishing")
        return 2
    git("fetch", "-q", "origin", "develop")
    head = git("rev-parse", "HEAD").strip()
    remote = git("rev-parse", "origin/develop").strip()
    if subprocess.run(["git", "merge-base", "--is-ancestor", head, remote],
                      cwd=ROOT, capture_output=True).returncode:
        print("local HEAD is not on develop; ship before finishing")
        return 2
    refs = ticket_commits(number)
    if not refs:
        print(f"no develop commit referencing #{number}; cannot finish")
        return 2
    latest = refs[0]
    marker = f"<!-- sc-finish v1 issue={number} sha={latest} -->"
    comments = gh(f"repos/{REPO}/issues/{number}/comments?per_page=100")
    if not isinstance(comments, list):
        raise td.DigestError("cannot verify prior handovers; refusing duplicate")
    if not any(marker in str(c.get("body") or "") for c in comments):
        body = (f"Progress: {a.done.strip()}\n"
                f"Handover: {a.next.strip()}\n"
                f"Commit: {latest}\n"
                f"Verification: {a.verification.strip() or 'not run (unverified)'}\n"
                f"Checklist: {a.checklist.strip() or 'not supplied'}\n"
                f"{marker}")
        posted = gh("-X", "POST", f"repos/{REPO}/issues/{number}/comments",
                    "-f", f"body={body}")
        if not isinstance(posted, dict) or not isinstance(posted.get("id"), int):
            raise td.DigestError("GitHub did not confirm finish handover")
    if a.close:
        close_issue(number)
        print(f"closed #{number} with recorded acceptance evidence at {latest[:12]}")
    release(number, "durable finish handover recorded.")
    print(f"finished #{number} at {latest[:12]}; claim released")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board").set_defaults(fn=cmd_board)
    start = sub.add_parser("start", help="claim ticket, prepare private worktree and scoped context")
    start.add_argument("number", nargs="?", type=int, help="explicit issue or pick highest unclaimed")
    start.add_argument("--files", default="", help="comma-separated anticipated source paths")
    start.add_argument("--ttl", type=int, default=90, help="short-lived lease minutes")
    start.add_argument("--lane", default="", help="limit automatically chosen tickets to a subsystem")
    start.add_argument("--later", action="store_true")
    start.add_argument("--include-skipped", action="store_true")
    start.add_argument("--limit", type=int, default=1)
    start.set_defaults(fn=cmd_start)
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
    progress = sub.add_parser("progress", help="post durable work evidence and next steps")
    progress.add_argument("number", type=int)
    progress.add_argument("--done", required=True, help="what was actually completed")
    progress.add_argument("--next", required=True, help="specific remaining work; 'none' if complete")
    progress.add_argument("--commit", default="not pushed", help="actual pushed SHA or 'not pushed'")
    progress.add_argument("--verification", default="not run (unverified)")
    progress.add_argument("--files", default="", help="file paths touched")
    progress.add_argument("--release", action="store_true", help="also release the short-lived lease")
    progress.set_defaults(fn=cmd_progress)
    h = sub.add_parser("heartbeat")
    h.add_argument("number", type=int)
    h.set_defaults(fn=cmd_heartbeat)
    r = sub.add_parser("release")
    r.add_argument("number", type=int)
    r.add_argument("--note", default="no work in progress.")
    r.set_defaults(fn=cmd_release)
    s = sub.add_parser("ship")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--message", default="", help="commit tracked edits in a private worktree with this message")
    s.add_argument("--files", default="", help="explicit named paths to stage, including newly created files")
    s.add_argument("--next", default="", help="durable next-action handover after a successful push")
    s.add_argument("--assign-patch", action="store_true",
                   help="explicit owner-authorised release-number allocation; never automatic")
    s.add_argument("--skip-checks", action="store_true",
                   help="fast direct push without running checks (UNVERIFIED)")
    s.set_defaults(fn=cmd_ship)
    d = sub.add_parser("done")
    d.add_argument("number", type=int)
    d.add_argument("--why", required=True)
    d.add_argument("--checklist", required=True)
    d.add_argument("--verification", default="not run (unverified)")
    d.add_argument("--close", action="store_true")
    d.set_defaults(fn=cmd_done)
    finish = sub.add_parser("finish", help="persist progress, release claim, optionally close with evidence")
    finish.add_argument("number", nargs="?", type=int, help="defaults to issue in private worktree")
    finish.add_argument("--done", required=True, help="completed work and acceptance evidence")
    finish.add_argument("--next", required=True, help="precise remaining work; 'none' if complete")
    finish.add_argument("--verification", default="", help="actual checks and outcomes")
    finish.add_argument("--checklist", default="", help="acceptance criteria satisfied")
    finish.add_argument("--close", action="store_true", help="close only with full explicit evidence")
    finish.set_defaults(fn=cmd_finish)
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
