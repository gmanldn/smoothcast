"""Late-bound changelog generation: preserve history, never hand-merge entries."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess

PATH = "CHANGELOG.md"
MARK = re.compile(r"(?m)^<!-- sc-changelog-through: ([0-9a-f]{40}) -->$")
DAY = re.compile(r"(?m)^## (\d{4}-\d{2}-\d{2}) · UTC$")
PENDING = " <!-- sc-changelog-pending -->"
SUBJECT = "chore(changelog): record shipment [sc-auto-changelog]"
URL = "https://github.com/gmanldn/smoothcast/commit/"
CATEGORIES = {"feat": "🟩 Feature", "fix": "🟥 Fix", "perf": "🟦 Performance",
              "refactor": "🟦 Refactor", "test": "🟪 Tests", "ci": "🟪 CI",
              "docs": "🟨 Documentation"}


class ChangelogError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        raise ChangelogError(f"git {args[0]} failed: {p.stderr.strip()[:240]}")
    return p.stdout


def anchor(source: str) -> str:
    found = MARK.findall(source)
    if len(found) != 1:
        raise ChangelogError("missing or ambiguous changelog anchor")
    return found[0]


def entry(sha: str | None, stamp: str, subject: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp):
        raise ChangelogError("invalid UTC commit timestamp")
    category = CATEGORIES.get(re.split(r"[(:]", subject, maxsplit=1)[0], "⬜ Maintenance")
    emoji, label = category.split(" ", 1)
    clean = subject.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    clean = re.sub(r"([\\\x60*_\[\]])", r"\\\1", clean)
    link = f" · [\x60{sha[:12]}\x60]({URL}{sha})" if sha else PENDING
    return f"- {emoji} **{stamp[11:19]} · {label}** — {clean}{link}"


def render(source: str, through: str, commits: list[tuple[str | None, str, str]]) -> str:
    """Replace only the provisional row; accumulate actual Git entries by UTC day."""
    marker = MARK.search(source)
    anchor(source)
    if not re.fullmatch(r"[0-9a-f]{40}", through):
        raise ChangelogError("invalid new anchor")
    groups: dict[str, list[str]] = {}
    day = None
    for line in source[marker.end():].splitlines():
        if m := DAY.fullmatch(line):
            day = m.group(1)
            if day in groups:
                raise ChangelogError("duplicate changelog day")
            groups[day] = []
        elif line.startswith("- ") and day is not None:
            if not line.endswith(PENDING):
                groups[day].append(line)
        elif line.strip() not in ("", "---"):
            raise ChangelogError("unexpected changelog body")
    for sha, stamp, subject in commits:
        groups.setdefault(stamp[:10], []).append(entry(sha, stamp, subject))
    blocks = []
    for day, rows in sorted(groups.items(), reverse=True):
        if rows:
            rows.sort(key=lambda line: line.split("**", 2)[1][:8], reverse=True)
            blocks.append("## " + day + " · UTC\n\n" + "\n\n".join(rows))
    return source[:marker.start()] + f"<!-- sc-changelog-through: {through} -->\n\n" + "\n\n---\n\n".join(blocks) + "\n"


def history(root: Path, old: str, new: str) -> list[tuple[str, str, str]]:
    git(root, "merge-base", "--is-ancestor", old, new)
    raw = git(root, "log", "--format=%H%x09%ct%x09%s", old + ".." + new)
    rows = []
    for line in raw.splitlines():
        sha, epoch, subject = line.split("\t", 2)
        stamp = datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append((sha, stamp, subject))
    return rows


def expected(root: Path, base: str, parent: str, stamp: str) -> str:
    source = git(root, "show", base + ":" + PATH)
    rows = history(root, anchor(source), parent)
    return render(source, parent, [(None, stamp, SUBJECT), *rows])


def refresh(root: Path, base: str) -> bool:
    """Generate after rebase/PATCH. Keep the log's own commit provisional."""
    exists = subprocess.run(["git", "cat-file", "-e", base + ":" + PATH],
                            cwd=root, capture_output=True)
    if exists.returncode:
        if not (root / PATH).exists():
            return False  # historical branches predating the initial changelog
        raise ChangelogError("changelog bootstrap must use a reviewed shipment")
    if not (root / PATH).is_file():
        raise ChangelogError("generated changelog is missing")
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ChangelogError("tracked edits present")
    parent = git(root, "rev-parse", "HEAD").strip()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = expected(root, base, parent, stamp)
    if git(root, "diff", "--name-only", base, parent, "--", PATH).strip():
        raise ChangelogError("do not hand-edit generated CHANGELOG.md")
    (root / PATH).write_text(content, encoding="utf-8")
    try:
        git(root, "add", "--", PATH)
        git(root, "commit", "-m", SUBJECT, "-m", f"SC-Changelog-Base: {base}\nSC-Changelog-Date: {stamp}")
    except ChangelogError:
        git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", PATH)
        raise
    return True


def recover(root: Path, remote: str) -> bool:
    """Discard ONLY the exact unpublished generated log commit before rebase."""
    if git(root, "log", "-1", "--format=%s").strip() != SUBJECT:
        return False
    head = git(root, "rev-parse", "HEAD").strip()
    probe = subprocess.run(["git", "merge-base", "--is-ancestor", head, remote], cwd=root)
    if probe.returncode == 0:
        return False
    if probe.returncode != 1 or git(root, "status", "--porcelain").strip():
        raise ChangelogError("cannot safely recover unpublished log")
    if git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head).strip() != PATH:
        raise ChangelogError("generated log commit changed other files")
    body = git(root, "log", "-1", "--format=%b")
    base = re.search(r"(?m)^SC-Changelog-Base: ([0-9a-f]{40})$", body)
    date = re.search(r"(?m)^SC-Changelog-Date: (\S+)$", body)
    parent = git(root, "rev-parse", "HEAD^").strip()
    if not base or not date or git(root, "show", head + ":" + PATH) != expected(root, base[1], parent, date[1]):
        raise ChangelogError("generated log content not proven")
    git(root, "reset", "--soft", parent)
    git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", PATH)
    return True
