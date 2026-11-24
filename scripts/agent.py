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
import agent_network  # noqa: E402
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


def safe_claim_ttl(raw: str | None) -> int:
    """Malformed GitHub claim metadata never crashes the whole agent fleet.

    A malformed TTL gets the maximum supported lease, conservatively
    preventing duplicate work until that bounded lease naturally expires.
    """
    if raw is None:
        return 90
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return TTL_MAX
    return min(max(value, TTL_MIN), TTL_MAX)


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
            # GitHub's created/updated timestamps are the lease clock.
            # A client's beat field is informative only: trusting it lets a
            # badly skewed clock create a near-permanent lock.
            updated = parse_time(c.get("updated_at") or c["created_at"])
            at = max(created, updated)
            events.append({"kind": marker.group(1), "issue": issue, "agent": fields.get("agent", "?"),
                           "at": at,
                           "ttl": safe_claim_ttl(fields.get("ttl")),
                           "files": {f for f in fields.get("files", "").split(",") if f}, "id": c.get("id", 0)})
        elif re.match(r"\s*(?:\*\*)?claim\b", body, re.IGNORECASE) and "releas" not in body[:200].lower():
            events.append({"kind": "claim", "issue": issue, "agent": "legacy", "at": created,
                           "ttl": LEGACY_TTL, "files": predicted_files(body), "id": c.get("id", 0)})
        elif "claim released" in body.lower() or "releasing the claim" in body.lower() \
                or "release the claim" in body.lower() or "releasing my claim" in body.lower():
            events.append({"kind": "release", "issue": issue, "agent": "legacy", "at": created,
                           "ttl": 0, "files": set(), "id": c.get("id", 0)})
    # IDs record immutable publication order. A heartbeat edits an older
    # claim; ordering by updated_at would resurrect it after a release.
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
    if args and args[0] in agent_network.REMOTE_OPERATIONS:
        r = agent_network.remote_command(list(args), cwd=ROOT)
        if r.returncode:
            guidance = agent_network.failure_guidance(args[0], r)
            if check:
                raise SystemExit(guidance)
            print(guidance, file=sys.stderr)
        return r.stdout
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def recent_comments(hours: float = TTL_MAX / 60 + 0.5, pages: int = 6) -> list[dict]:
    since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[dict] = []
    for page in range(1, pages + 1):
        chunk = gh(f"repos/{REPO}/issues/comments?since={since}&per_page=100&page={page}&sort=created")
        if not isinstance(chunk, list) or any(not isinstance(c, dict) for c in chunk):
            raise td.DigestError("GitHub returned an invalid global claim feed")
        if not chunk:
            return out  # An empty page is a complete feed, not saturation.
        out.extend(chunk)
        if len(chunk) < 100:
            return out
    raise td.DigestError(
        f"global claim feed exceeded {100 * pages} recent comments; "
        "refusing an incomplete conflict check")


def issue_comments(number: int, max_pages: int = 10) -> list[dict]:
    """Read all issue comments needed to arbitrate a lease; never silently truncate.

    GitHub returns oldest-first pages. Claim/release replay is only safe with
    a complete feed: a newer live claim can be beyond page one.
    """
    if number < 1 or max_pages < 1:
        raise ValueError("invalid issue comment pagination request")
    all_comments: list[dict] = []
    for page in range(1, max_pages + 1):
        suffix = "" if page == 1 else f"&page={page}"
        batch = gh(f"repos/{REPO}/issues/{number}/comments?per_page=100{suffix}")
        if not isinstance(batch, list) or any(not isinstance(c, dict) for c in batch):
            raise td.DigestError(f"cannot read complete comments for issue #{number}")
        all_comments.extend(dict(c, issue=number) for c in batch)
        if len(batch) < 100:
            return all_comments
    raise td.DigestError(
        f"issue #{number} has at least {100 * max_pages} comments; "
        "cannot safely arbitrate an incomplete lease history")


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
    # CI is deliberately lazy. Running head_verdict here consumes multiple
    # GitHub requests and almost always reports unknown on rapid pushes.
    # The board should be fast; invoke head_verdict explicitly when needed.
    print(f"develop head {git('rev-parse', 'origin/develop', check=False)[:12]}: "
          "CI deferred; use scripts/ci/head_verdict.py when verifying")
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


def all_open_issue_pool(tiers: set[str], max_pages: int = 20) -> tuple[dict, set[int]]:
    """One paginated issue snapshot for both work selection and dependencies.

    The earlier tier-filtered queries treated open issues in later/icebox
    as if they were closed, so agents eagerly picked blocked tickets.
    """
    candidates: dict[int, dict] = {}
    open_numbers: set[int] = set()
    for page in range(1, max_pages + 1):
        suffix = "" if page == 1 else f"&page={page}"
        rows = gh(f"repos/{REPO}/issues?state=open&per_page=100{suffix}")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise td.DigestError("cannot read complete open issue list for dependency checks")
        for row in rows:
            if "pull_request" in row:
                continue
            number = row.get("number")
            if type(number) is not int or number <= 0:
                raise td.DigestError("invalid issue number in open issue response")
            open_numbers.add(number)
            labels = {v.get("name") for v in row.get("labels") or [] if isinstance(v, dict)}
            if tiers & labels:
                candidates[number] = row
        if len(rows) < 100:
            return candidates, open_numbers
    raise td.DigestError(
        f"open issue list exceeded {max_pages * 100} records; "
        "refusing incomplete dependency detection")


def ranked_candidates(a: argparse.Namespace) -> tuple[list, list, list, set, str]:
    me, now = agent_id(), utcnow()
    claims = active_claims(parse_events(recent_comments()), now)
    hot = hot_files()
    tiers = ["now", "next"] + (["later"] if a.later else [])
    pool, open_numbers = all_open_issue_pool(set(tiers))
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
        # Older issue comments can span multiple pages. Showing only page
        # one hides the latest handover and makes successors repeat work.
        comments = issue_comments(n)
        slices, progress, handover = summarize_history(comments)
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
    # A latest-only handover often omits completed earlier slices. Preserve
    # several recent pieces of durable evidence so a successor doesn't redo
    # work merely because the last comment mentions only its next action.
    evidence = [(c.get("id"), str(c.get("body") or "")) for c in ordered
                if re.search(r"(?m)^(?:Progress|Implementation|Handover):",
                             str(c.get("body") or ""))]
    snippets = []
    for cid, record in evidence[-4:]:
        if len(record) > 1250:
            record = record[:850] + "\n[evidence abbreviated; see issue comment]\n" + record[-300:]
        snippets.append(f"### Comment {cid or 'unknown'}\n{record}")
    latest = ("\n\n".join(snippets) if snippets
              else "No prior handover; inspect related commits.")
    body = str(issue.get("body") or "")
    if len(body) > 5200:
        # Preserve the objective and tail checklist while avoiding token-heavy
        # historical epics in every agent startup context.
        body = body[:3800] + "\n[background abbreviated; inspect issue link]\n" + body[-1000:]
    named = sorted(predicted_files(str(issue.get("body") or "")))
    # Pure local routing: do not consume the entire handbook or query GitHub
    # again just to decide which source invariants this ticket needs.
    import agent_context
    guidance = agent_context.route_hint([str(issue.get("title") or ""), *named[:3]])
    return (
        f"# SmoothCast issue #{number}: {issue.get('title', '')}\n\n"
        f"Source baseline: {base}\n"
        "Authority: GitHub issue and latest develop source; refresh before each ship.\n"
        f"Full issue: https://github.com/{REPO}/issues/{number}\n"
        f"Likely files: {', '.join(named) or 'not specified; inspect issue and source'}\n"
        "Start here: AGENTS.md then one relevant handbook topic.\n"
        f"Context route: {guidance}\n"
        "Token discipline: .kilo/skills/ponytail/SKILL.md (smallest complete "
        "diff); .kilo/skills/caveman/SKILL.md (terse evidence). "
        "Never trade correctness, tests or evidence for brevity.\n\n"
        f"## Acceptance and background\n{body[:30000]}\n\n"
        f"## Recent durable handovers (oldest to newest; verify source)\n{latest}\n"
    )


def private_task() -> dict | None:
    """Read the private task marker without treating corruption as no ownership."""
    if not (ROOT / ".git").is_file():
        return None
    folder = Path(git("rev-parse", "--absolute-git-dir").strip())
    marker = folder / "sc-agent-task.json"
    try:
        raw = marker.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise td.DigestError(f"cannot read private task journal {marker}: {exc}") from exc
    except UnicodeError as exc:
        raise td.DigestError(f"invalid encoding in private task journal {marker}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise td.DigestError(f"invalid JSON in private task journal {marker}") from exc
    if (not isinstance(payload, dict) or type(payload.get("issue")) is not int
            or payload["issue"] < 1):
        raise td.DigestError(f"invalid issue identity in private task journal {marker}")
    if "files" in payload and (not isinstance(payload["files"], list)
                               or not all(isinstance(p, str) for p in payload["files"])):
        raise td.DigestError(f"invalid file scope in private task journal {marker}")
    for key in ("pending_push", "pending_handover"):
        if key in payload and not isinstance(payload[key], dict):
            raise td.DigestError(f"invalid {key} in private task journal {marker}")
    if "pending_push" in payload and "pending_handover" in payload:
        raise td.DigestError(f"conflicting delivery receipts in private task journal {marker}")
    return payload


def worktree_pool() -> Path:
    """Container for private agent worktrees, deliberately outside the checkout.

    A worktree per ticket is required, but dropping them beside the repo (in the
    user's project directory) buries the real checkout under dozens of siblings.
    Keep every private worktree in one pool under the user data directory so the
    project directory stays clean; override with ``SC_WORKTREE_POOL``.
    """
    override = os.environ.get("SC_WORKTREE_POOL")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "smoothcast" / "worktrees"


def cmd_start(a: argparse.Namespace) -> int:
    """Pick or resume a ticket with a fresh private checkout and durable context."""
    git("fetch", "-q", "origin", "develop")
    if a.number is None:
        ranked, _, _, _, _ = ranked_candidates(a)
        if not ranked:
            print("no available ticket; inspect agent.py board or supply an issue number")
            return 3
        # Explicit open prerequisites are not eligible for automatic pickup.
        # The operator can still choose a specific issue to work on a safe
        # independent slice, but don't assign blocked work to lesser agents.
        available = [candidate for candidate in ranked if not candidate[4]]
        if not available:
            print("all candidate tickets have open prerequisites; inspect agent.py next")
            return 3
        number = available[0][1]
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
    target = worktree_pool() / f"smoothcast-issue-{number}-{uuid.uuid4().hex[:8]}"
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
        comments = issue_comments(number)
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
    print("  python3 scripts/agent.py ship --message 'fix: concrete outcome'")
    return 0


def cmd_claim(a: argparse.Namespace) -> int:
    me = agent_id()
    issue = load_issue(a.number)
    if issue.get("state", "open") != "open":
        print(f"issue #{a.number} is no longer open; refusing to claim stale work")
        return 3
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
    # Never leave an orphan claim when a post succeeded but the follow-up
    # freshness request times out or returns an incomplete comment ledger.
    # A rejected claim must be deleted even if a second GitHub read fails.
    confirmed = False
    try:
        recent = recent_comments()
        # Always inspect this issue directly; a bounded global feed can omit
        # an older live rival even if our own marker is already visible.
        direct = issue_comments(a.number)
        seen = {c.get("id") for c in recent}
        recent.extend(c for c in direct if c.get("id") not in seen)
        events = [e for e in parse_events(recent) if e["id"] <= posted["id"]]
        mine = [e for e in events if e["id"] == posted["id"] and e["kind"] == "claim"]
        rivals = [c for c in active_claims(events, utcnow())
                  if c["agent"] != me
                  and (c["issue"] == a.number or files & c["files"])
                  and c["id"] < posted["id"]]
        if not mine or rivals:
            if rivals:
                print(f"LOST RACE to {rivals[0]['agent']} on #{rivals[0]['issue']}; "
                      "withdrawing claim. Run: python3 scripts/agent.py next")
            else:
                print("CLAIM NOT CONFIRMED in GitHub comments; withdrawing and retrying")
            return 3
        confirmed = True
    finally:
        if not confirmed:
            try:
                gh("-X", "DELETE", f"repos/{REPO}/issues/comments/{posted['id']}")
            except td.DigestError as exc:
                print(f"WARNING: could not remove unconfirmed claim {posted['id']}: {exc}; "
                      "lease will expire", file=sys.stderr)
    # The confirmed structured comment is the lock. GitHub labels/assignees
    # are advisory and must never turn a successful lease into a false failure.
    # Otherwise start() can leave an invisible orphan lease on metadata 403.
    try:
        gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/labels", "-f", "labels[]=in-flight")
        login = gh("user")
        if isinstance(login, dict) and login.get("login"):
            gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/assignees",
               "-f", f"assignees[]={login['login']}")
    except td.DigestError as exc:
        print(f"claim confirmed; advisory labels/assignees unavailable: {exc}")
    print(f"claimed #{a.number} as {me}; lease {ttl} min (heartbeat to extend). Files: {', '.join(sorted(files)) or 'tbd'}")
    if files & PLAN_FIRST:
        print("NOTE: plan-first module; comment a short plan before editing (CLAUDE.md).")
    return 0


def ensure_live_task_claim(task: dict) -> bool:
    """Refuse a successor's active lease; safely reclaim an expired task."""
    number = task["issue"]
    me = agent_id()
    files = set(task.get("files") or [])
    comments = issue_comments(number)
    # An issue-specific ledger catches same-ticket successors; the global
    # comment feed also fences other tickets claiming the SAME source files.
    # Ignore neither feed: a recent cross-issue claimant can otherwise race
    # a worker still holding an apparently valid own-ticket lease.
    global_comments = recent_comments()
    by_id = {c.get("id"): c for c in global_comments}
    by_id.update({c.get("id"): dict(c, issue=number) for c in comments})
    live = active_claims(parse_events(list(by_id.values())), utcnow())
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


def ensure_task_scope(task: dict, changed: list[str]) -> bool:
    """Fenced lease expansion for source files first discovered during work.

    A task brief predicts files, but tests/refactors may reveal a second
    production file. Do not push it under a narrower claim: another agent
    could already own that file on a different issue. A new comment is
    race-arbitrated before updating the private, untracked worktree marker.
    """
    scoped = {f for f in changed
              if f not in SHARED and f.startswith(
                  ("src/", "scripts/", "setup/", "packaging/", "fakecast/"))}
    owned = set(task.get("files") or [])
    missing = scoped - owned
    if not missing:
        return True
    combined = sorted(owned | scoped)
    print(f"source scope expanded: {', '.join(sorted(missing)[:8])}; checking other leases")
    claimed = cmd_claim(argparse.Namespace(number=task["issue"],
                                           files=",".join(combined), ttl=90))
    if claimed:
        print("new source files conflict with another lease; worktree preserved")
        return False
    try:
        folder = Path(git("rev-parse", "--absolute-git-dir").strip())
        dest = folder / "sc-agent-task.json"
        newer = dict(task, files=combined)
        staged = folder / f"sc-agent-task-{uuid.uuid4().hex}.tmp"
        try:
            staged.write_text(json.dumps(newer, indent=2) + "\n", encoding="utf-8")
            staged.replace(dest)
        finally:
            staged.unlink(missing_ok=True)
    except OSError as exc:
        print(f"scope lease obtained but task marker could not be saved: {exc}")
        return False
    task["files"] = combined
    return True


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
    comments = issue_comments(a.number)
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
            updated = gh("-X", "PATCH", f"repos/{REPO}/issues/comments/{c['id']}",
                         "-f", f"body={new}")
            if not isinstance(updated, dict) or updated.get("id") != c["id"]:
                raise td.DigestError(f"GitHub did not confirm heartbeat on #{a.number}")
            print(f"lease on #{a.number} refreshed")
            return 0
    print(f"no live claim by {me} on #{a.number}; claim again instead of reviving an expired lease")
    return 1


def release(number: int, note: str) -> None:
    me = agent_id()
    posted = gh("-X", "POST", f"repos/{REPO}/issues/{number}/comments", "-f",
                f"body=Released: {me}. {note}\n<!-- sc-release v1 agent={me} -->")
    if not isinstance(posted, dict) or not isinstance(posted.get("id"), int):
        raise td.DigestError(f"GitHub did not confirm release on #{number}")
    # This issue's complete authoritative ledger is more reliable than the
    # globally bounded recent-comment feed when cleaning advisory labels.
    current = issue_comments(number)
    if not any(c.get("id") == posted["id"] for c in current):
        print(f"release {posted['id']} confirmed but not yet visible; advisory cleanup deferred")
        return
    left = active_claims(parse_events(current), utcnow())
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


DOC_FILES = {"AGENTS.md", "CONTRIBUTING.md", "README.md", "CLAUDE.md"}


def doc_guard_steps(changed: list[str], tests: dict[str, str]) -> list[tuple[str, list[str]]]:
    """Tests that pin the wording/contract of changed docs and workflows.

    These run even under --skip-checks: doc and workflow rewrites were the
    commonest cause of a red develop because their contract tests assert exact
    wording and nobody ran them. They take seconds.
    """
    docs = [f for f in changed if f in DOC_FILES or f.startswith(("docs/", ".github/workflows/"))]
    chosen = tests_for(docs, tests) if docs else []
    chosen = [t for t in chosen if t not in RATCHETS] or chosen
    if not chosen:
        return []
    xdist = ["-n", "auto"] if len(chosen) > 3 else []
    return [(f"doc-guard pytest ({len(chosen)} files)",
             [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *xdist, *chosen])]


def conflict_help(conflicted: list[str], claims: list[dict]) -> str:
    """Actionable text for a rebase conflict (the rebase has been aborted, nothing is lost)."""
    owners = sorted({f"#{c['issue']} ({c['agent']})" for c in claims for f in conflicted if f in c["files"]})
    lines = [f"REBASE CONFLICT in {', '.join(conflicted) or '?'}; your commits are untouched (rebase aborted).",
             "To resolve: git rebase origin/develop ; edit or pick a side ; git add <file> ; "
             "GIT_EDITOR=true git rebase --continue",
             "Careful: during a rebase `--ours` is origin/develop and `--theirs` is YOUR commit.",
             "Re-read the upstream text first; a doc/policy file usually means another agent is mid-rewrite, "
             "so keep their wording and re-apply only your small change."]
    if any(f == "pyproject.toml" for f in conflicted):
        lines.append("pyproject.toml lists: python3 scripts/ci/sync_pyproject.py && git add pyproject.toml")
    if owners:
        lines.append("Live claims on these files: " + ", ".join(owners))
    return "\n".join(lines)


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


def run_headless_check(cmd: list[str], timeout: int = 180
                       ) -> tuple[subprocess.CompletedProcess | None, str]:
    """Never let a missing or stalled optional checker monopolise an agent."""
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              timeout=timeout), ""
    except (FileNotFoundError, PermissionError) as exc:
        return None, f"{cmd[0]} unavailable: {exc}"
    except subprocess.TimeoutExpired:
        return None, f"{cmd[0]} exceeded {timeout}s time budget"


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
            or p in {".", "./"} or p.startswith(("-", ":"))
            or any(c in p for c in "*?[]\x00")
            or (ROOT / p).is_dir() for p in paths)):
        print("--files requires literal, named repository-relative files, not directories or Git globs")
        return 2
    # Stage ALL tracked edits in this private worktree; --files additionally
    # includes named new files, never an uncontrolled untracked directory sweep.
    staged = subprocess.run(["git", "add", "-u"],
                            cwd=ROOT, capture_output=True, text=True)
    if staged.returncode == 0 and paths:
        staged = subprocess.run(["git", "--literal-pathspecs", "add", "-A", "--", *paths],
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


def persist_private_task(task: dict) -> bool:
    """Atomic, untracked delivery journal for an agent-owned worktree."""
    try:
        folder = Path(git("rev-parse", "--absolute-git-dir").strip())
        destination = folder / "sc-agent-task.json"
        temporary = folder / f"sc-agent-task-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return True
    except OSError as exc:
        print(f"WARNING: cannot persist private handover journal: {exc}")
        return False


def shipment_verification(skip_checks: bool, checks_run: list[str],
                          unverified_checks: list[str]) -> str:
    """Stable evidence for a pushed SHA, including an uncertain push result."""
    detail = ("not run (unverified)" if skip_checks else
              (", ".join(sorted(set(checks_run))) or "no affected tests selected"))
    if unverified_checks:
        detail += "; unverified tools: " + ", ".join(sorted(set(unverified_checks)))
    return detail


def recover_uncertain_push(task: dict) -> bool:
    """Fence a lost push acknowledgement before rebase or another shipment.

    If the remote contains the exact SHA, convert the durable private receipt
    into a replayable GitHub handover. If it does not, preserve the unpublished
    work and resume the ordinary non-force push path. Git errors fail closed.
    """
    pending = task.get("pending_push")
    if "pending_push" not in task:
        return True
    if not isinstance(pending, dict):
        print("invalid pending push receipt; manual review required")
        return False
    sha = pending.get("sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-fA-F0-9]{40,64}", sha):
        print("invalid pending push SHA; manual review required")
        return False
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "origin/develop"],
        cwd=ROOT, capture_output=True,
    )
    if ancestry.returncode not in (0, 1):
        print("cannot establish remote ancestry for uncertain push; retry later")
        return False
    newer = dict(task)
    newer.pop("pending_push", None)
    if ancestry.returncode == 0:
        newer["pending_handover"] = pending
    if not persist_private_task(newer):
        return False
    task.clear()
    task.update(newer)
    if ancestry.returncode == 0:
        print(f"remote contains previously uncertain SHA {sha[:12]}; replaying handover")
    else:
        print(f"remote does not contain uncertain SHA {sha[:12]}; retrying unpublished code")
    return True


def recover_pending_handover(task: dict) -> bool:
    """Retry a previously pushed SHA, never describe an unpublished SHA as shipped."""
    pending = task.get("pending_handover")
    if "pending_handover" not in task:
        return True
    if not isinstance(pending, dict):
        print("invalid pending handover receipt; manual review required")
        return False
    sha = pending.get("sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-fA-F0-9]{40,64}", sha):
        print("invalid private handover receipt; review it before continuing")
        return False
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "origin/develop"],
                              cwd=ROOT, capture_output=True)
    if ancestor.returncode:
        print("pending handover SHA is not on develop; preserving journal")
        return False
    if not publish_ship_handover(task, sha, pending.get("files") or [],
                                 pending.get("verification") or "not run (unverified)",
                                 pending.get("next") or ""):
        return False
    newer = dict(task)
    newer.pop("pending_handover", None)
    if not persist_private_task(newer):
        return False
    task.pop("pending_handover", None)
    return True


def publish_ship_handover(task: dict | None, sha: str, changed: list[str],
                          verification: str, next_action: str) -> bool:
    """Best-effort, idempotent evidence; never reinterpret a failed push as success."""
    if task is None:
        return True
    number = task["issue"]
    marker = f"<!-- sc-ship v1 sha={sha} -->"
    try:
        comments = issue_comments(number)
        if isinstance(comments, list) and any(
                marker in str(c.get("body") or "") for c in comments):
            return True
        body = (f"Progress: pushed a coherent develop slice at {sha[:12]}\n"
                f"Handover: {next_action or 'Review remaining issue acceptance criteria against develop'}\n"
                f"Commit: {sha}\nVerification: {verification}\n"
                f"Files: {', '.join(changed[:20]) or 'see commit'}\n{marker}")
        posted = gh("-X", "POST", f"repos/{REPO}/issues/{number}/comments",
                    "-f", f"body={body}")
        if not isinstance(posted, dict) or not isinstance(posted.get("id"), int):
            raise td.DigestError("GitHub did not confirm ship handover")
        return True
    except td.DigestError as exc:
        print(f"WARNING: develop commit {sha[:12]} landed, but issue handover failed: {exc}")
        return False


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
    unverified_checks: list[str] = []
    for attempt in range(1, 6):
        try:
            git("fetch", "-q", "origin", "develop")
        except SystemExit as exc:
            print(str(exc))
            if task is not None and task.get("pending_push"):
                return 5  # Unknown outcome; leave the original receipt intact.
            if task is not None and task.get("pending_handover"):
                return 7  # Confirmed push, handover still pending.
            return 6
        remote_before = git("rev-parse", "origin/develop").strip()
        if task is not None and not recover_uncertain_push(task):
            print("push outcome remains uncertain; worktree preserved")
            return 5
        if task is not None and not recover_pending_handover(task):
            print("previous pushed slice has an unrecorded handover; retry later")
            return 7
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
            try:
                live = active_claims(parse_events(recent_comments()), utcnow())
            except td.DigestError:
                live = []
            print(conflict_help(conflicted, live))
            return 4
        changed = [f for f in git("diff", "--name-only", "origin/develop...HEAD").split() if f]
        if not changed:
            print("nothing to ship: HEAD equals origin/develop")
            return 0
        if task is not None and not ensure_task_scope(task, changed):
            return 3
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
                res, unavailable = run_headless_check(cmd)
                if res is None:
                    unverified_checks.append(label)
                    print(f"  {label}: UNVERIFIED ({unavailable})")
                    continue
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
            guard_tests = {str(p.relative_to(ROOT)): p.read_text(errors="replace")
                           for p in (ROOT / "tests").glob("test_*.py")}
            for label, cmd in doc_guard_steps(changed, guard_tests):
                started = time.time()
                res, unavailable = run_headless_check(cmd)
                if res is None:
                    print(f"  MANDATORY {label} cannot run: {unavailable}; "
                          "install pytest or hold this documentation change")
                    return 1
                print(f"  {label}: {'ok' if res.returncode == 0 else 'FAIL'} ({time.time() - started:.1f}s)")
                if res.returncode:
                    ids = failing_ids(res.stdout)
                    mine = set(ids) - failing_on_develop(ids) if ids else {"?"}
                    if mine:
                        print((res.stdout + res.stderr)[-1500:])
                        print("  Your doc/workflow edit breaks contract tests that pin its wording: update those "
                              f"tests in the SAME commit. Failing: {', '.join(sorted(mine))[:300]}")
                        return 1
                    print(f"  NOT yours: {len(ids)} doc test(s) already fail on origin/develop; pushing anyway")
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
        sha = git("rev-parse", "HEAD").strip()
        verification = shipment_verification(a.skip_checks, checks_run, unverified_checks)
        receipt = {"sha": sha, "files": changed,
                   "verification": verification, "next": a.next}
        if task is not None:
            # Write-ahead journal: once git push starts, a process kill,
            # timeout or lost response can make the remote outcome unknown.
            # Persist the exact attempted SHA *before* crossing that boundary.
            newer = dict(task, pending_push=receipt)
            if not persist_private_task(newer):
                print("PUSH REFUSED: could not durably record delivery intent; worktree preserved")
                return 5
            task.update(newer)
        push = agent_network.remote_command(["push", "origin", "HEAD:develop"], cwd=ROOT)
        if push.returncode:
            # A lost acknowledgement after a successful remote push is not a
            # reason to replay commits. Fetch and inspect ancestry first.
            fetch = agent_network.remote_command(["fetch", "-q", "origin", "develop"], cwd=ROOT)
            if fetch.returncode:
                print(f"push outcome uncertain for {sha[:12]}; remote fetch failed.")
                if task is not None:
                    print("uncertain push saved; rerun 'agent.py ship' to verify "
                          "remote ancestry and complete its handover")
                print(agent_network.failure_guidance("push", push))
                print(agent_network.failure_guidance("fetch", fetch))
                return 5
            remote_now = git("rev-parse", "origin/develop").strip()
            ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", sha, remote_now],
                                      cwd=ROOT, capture_output=True).returncode
            if ancestry not in (0, 1):
                print(f"cannot establish remote ancestry for {sha[:12]}; worktree preserved")
                return 5
            if ancestry == 1:
                if remote_now == remote_before:
                    print("push failed without a competing change; worktree preserved.")
                    print(agent_network.failure_guidance("push", push))
                    return 5
                print(f"remote advanced; safely retrying [{attempt}/5]")
                # The next attempt reconciles the write-ahead receipt before
                # rebasing or replacing it with another attempted SHA.
                continue
            print("remote contains the commit: treating failed push acknowledgement as success")
        handover_recorded = True
        if task is not None:
            # Remote acknowledgement confirms the write-ahead receipt.
            # If the transition fails, the on-disk pending_push is sufficient
            # to recover. Do not delete it or pretend the handover succeeded.
            newer = dict(task, pending_handover=receipt)
            newer.pop("pending_push", None)
            if not persist_private_task(newer):
                print(f"PUSH SUCCEEDED at {sha[:12]} but journal transition failed; "
                      "rerun 'agent.py ship' in this worktree")
                return 7
            task.clear()
            task.update(newer)
            handover_recorded = publish_ship_handover(
                task, sha, changed, verification, a.next)
            if handover_recorded:
                newer = dict(task)
                newer.pop("pending_handover", None)
                if persist_private_task(newer):
                    task.pop("pending_handover", None)
                else:
                    print("handover confirmed but journal cleanup failed; "
                          "rerun 'agent.py ship' to reconcile it")
                    return 7
        print(f"pushed {sha[:12]} to develop (attempt {attempt}); {verification}")
        if not handover_recorded:
            print("PUSH SUCCEEDED but ISSUE HANDOVER IS PENDING; run 'agent.py ship' again "
                  "from this worktree to reconcile the saved receipt")
            return 7
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
    """Legacy evidence-only handover; finish is the sole closure authority."""
    if a.close:
        print("legacy done cannot close tickets: use 'agent.py finish --close' "
              "from the ticket's private worktree, with acceptance evidence")
        return 2
    if not a.why.strip() or not a.checklist.strip():
        print("legacy done requires a concrete --why and --checklist")
        return 2
    git("fetch", "-q", "origin", "develop")
    head = git("rev-parse", "HEAD").strip()
    if subprocess.run(["git", "merge-base", "--is-ancestor", head, "origin/develop"],
                      cwd=ROOT, capture_output=True).returncode:
        print("HEAD is not on origin/develop yet: run `agent.py ship` first.")
        return 2
    refs = ticket_commits(a.number)
    if not refs:
        print(f"No published develop commit references #{a.number}; cannot report completion.")
        return 2
    sha = refs[0][:12]
    files = sorted({f for f in git("show", "--format=", "--name-only",
                                   *refs[:8]).split() if f})
    body = (f"Implementation: {sha}. Why: {a.why.strip()}. "
            f"Files: {', '.join(files[:12]) or 'see commits'}. "
            f"Checklist: {a.checklist.strip()}. "
            f"Verification: {a.verification.strip() or 'not run (unverified)'}.")
    posted = gh("-X", "POST", f"repos/{REPO}/issues/{a.number}/comments",
                "-f", f"body={body}")
    if not isinstance(posted, dict) or not isinstance(posted.get("id"), int):
        raise td.DigestError(f"GitHub did not confirm legacy handover on #{a.number}")
    # A shared-worktree reporter must not silently revoke a successor's
    # temporary lease. Only release this agent's own live claim, if any.
    live = active_claims(parse_events(issue_comments(a.number)), utcnow())
    if any(c["issue"] == a.number and c["agent"] == agent_id() for c in live):
        release(a.number, f"evidence recorded in comment {posted['id']}.")
        print(f"evidence recorded and own claim released on #{a.number}")
    else:
        print(f"evidence recorded on #{a.number}; no live claim by this agent to release")
    return 0



def cmd_finish(a: argparse.Namespace) -> int:
    """Durable, retry-safe ticket handover; closure only with explicit evidence."""
    task = private_task()
    # 'finish' is an ownership-sensitive lifecycle operation. Standalone
    # historical evidence is still supported via the explicit 'done' command.
    if task is None:
        print("finish requires an agent.py start worktree; use 'done N' for manual reporting")
        return 2
    number = task["issue"]
    if a.number is not None and a.number != number:
        print(f"worktree belongs to issue #{number}; refusing finish on #{a.number}")
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
    # A lost push acknowledgement may also have lost its follow-up fetch.
    # Resolve that exact SHA before completion; never release an unrecorded
    # delivery or treat the remote's new HEAD as sufficient evidence.
    if not recover_uncertain_push(task):
        print("finish blocked by uncertain push; rerun 'agent.py ship'")
        return 5
    # A prior push may have landed before GitHub accepted its delivery
    # evidence. Never release the claim or close the ticket while the
    # durable local receipt is still pending.
    if not recover_pending_handover(task):
        print("finish blocked by unrecorded pushed SHA; run agent.py ship to retry")
        return 7
    if not ensure_live_task_claim(task):
        print("another agent owns this work or the lease could not be renewed")
        return 3
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
    # It is valid for unrelated agents to advance develop, but not for this
    # ticket to change after the owner's worktree snapshot. A successor may
    # have added new work/acceptance evidence. Review those commits before
    # declaring completion or releasing ownership.
    if subprocess.run(["git", "merge-base", "--is-ancestor", latest, head],
                      cwd=ROOT, capture_output=True).returncode:
        print(f"issue #{number} advanced at {latest[:12]} since this worktree; "
              "update/review the ticket before finishing")
        return 3
    marker = f"<!-- sc-finish v1 issue={number} sha={latest} -->"
    comments = issue_comments(number)
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


def _worktree_issue(path: Path) -> int | None:
    """Issue number encoded in a worktree directory name, if any."""
    match = re.search(r"issue-(\d+)-", path.name)
    return int(match.group(1)) if match else None


def cmd_prune(a: argparse.Namespace) -> int:
    """Remove agent worktrees already merged into develop that hold no local work.

    Only worktrees whose HEAD is an ancestor of ``origin/develop`` and whose
    working tree is clean are removed; unmerged, dirty, currently leased, or
    the caller's own worktree are always preserved. This keeps the pool (and any
    legacy siblings created before the pool existed) from growing without bound.
    """
    git("fetch", "-q", "origin", "develop")
    remote = git("rev-parse", "origin/develop").strip()
    here = Path.cwd().resolve()
    live = {c["issue"] for c in active_claims(parse_events(recent_comments()), utcnow())}
    removed: list[str] = []
    kept = 0
    for block in git("worktree", "list", "--porcelain").split("\n\n"):
        line = next((entry for entry in block.splitlines() if entry.startswith("worktree ")), "")
        if not line:
            continue
        path = Path(line.split(" ", 1)[1])
        try:
            resolved = path.resolve()
        except OSError:
            kept += 1
            continue
        if resolved in {ROOT.resolve(), here} or not (path / ".git").exists():
            kept += 1
            continue
        issue = _worktree_issue(path)
        if issue in live:
            kept += 1
            continue
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        if not head or subprocess.run(["git", "merge-base", "--is-ancestor", head, remote],
                                      cwd=ROOT, capture_output=True).returncode:
            kept += 1
            continue
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            kept += 1
            continue
        if subprocess.run(["git", "worktree", "remove", str(path)], cwd=ROOT,
                          capture_output=True, text=True).returncode:
            kept += 1
            continue
        removed.append(str(path))
    subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True)
    print(f"pruned {len(removed)} merged clean worktrees; preserved {kept}")
    for path in removed:
        print(f"  removed {path}")
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
    sub.add_parser("prune", help="remove merged, clean agent worktrees; keep unmerged, dirty or leased ones"
                   ).set_defaults(fn=cmd_prune)
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
