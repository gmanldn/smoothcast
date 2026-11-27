"""Pure formatting regressions for the shared changelog."""
from scripts.ci import changelog


def test_changelog_resolves_provisional_and_preserves_history():
    old = "a" * 40
    new = "b" * 40
    source = ("# Changelog\n\n<!-- sc-changelog-through: " + old + " -->\n\n"
              "## 2026-11-26 · UTC\n\n"
              "- 🟥 **10:00:00 · Fix** — historical\n\n"
              "- 🟩 **11:00:00 · Feature** — provisional <!-- sc-changelog-pending -->\n")
    result = changelog.render(source, new, [
        (new, "2026-11-26T11:00:01Z", "feat(room): <name>"),
        (None, "2026-11-27T01:00:00Z", "fix: new"),
    ])
    assert changelog.anchor(result) == new
    assert "historical" in result and "provisional" not in result
    assert result.count(changelog.PENDING) == 1
    assert "&lt;name&gt;" in result and new in result
    assert result.index("## 2026-11-27") < result.index("## 2026-11-26")


def test_generated_changelog_survives_retry_without_losing_code(tmp_path):
    from subprocess import run

    def git(*args):
        return run(["git", *args], cwd=tmp_path, check=True, capture_output=True,
                   text=True).stdout.strip()

    git("init")
    git("config", "user.name", "Changelog test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "code.txt").write_text("old")
    git("add", "code.txt")
    git("commit", "-m", "feat: initial")
    initial = git("rev-parse", "HEAD")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n<!-- sc-changelog-through: " + initial + " -->\n\n",
        encoding="utf-8")
    git("add", "CHANGELOG.md")
    git("commit", "-m", "docs: bootstrap")
    base = git("rev-parse", "HEAD")
    (tmp_path / "code.txt").write_text("new")
    git("add", "code.txt")
    git("commit", "-m", "fix: actual work")
    code = git("rev-parse", "HEAD")
    assert changelog.refresh(tmp_path, base)
    assert code in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.recover(tmp_path, base)
    assert git("rev-parse", "HEAD") == code
    assert (tmp_path / "code.txt").read_text() == "new"
    assert changelog.refresh(tmp_path, base)
    assert not changelog.recover(tmp_path, git("rev-parse", "HEAD"))
