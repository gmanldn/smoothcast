"""The GUI-launch guard refuses real launches but not text that merely mentions them."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "claude_hooks"))
import block_gui_launch as hook


def blocked(command: str) -> bool:
    return hook.decide(command) is not None


def test_real_launches_are_still_refused():
    for command in ("./smoothcast", "smoothcast-gui", "gtk-launch local.cast-control",
                    "python3 src/cast_control.py", "cd x && ./smoothcast --self-test",
                    "python3 -m cast_control", "env FOO=1 ./smoothcast file.mkv"):
        assert blocked(command), command


def test_safe_invocations_are_allowed():
    for command in ("./smoothcast --version", "python3 scripts/agent.py board",
                    "python3 -m pytest -q tests", "python3 scripts/test_gui_isolated.py"):
        assert not blocked(command), command


def test_heredoc_bodies_are_data_not_commands():
    script = ("python3 - <<'E'\n"
              "t=t.replace('Git SHA; ./smoothcast --self-test is forbidden', 'x')\n"
              "print('gtk-launch is mentioned only as text')\n"
              "./smoothcast\n"
              "E\n"
              "python3 -m pytest -q tests\n")
    assert not blocked(script)
    assert hook.strip_heredoc_bodies(script).count("\n") == 2


def test_the_heredoc_command_line_and_what_follows_are_still_checked():
    assert blocked("cat <<'E'\ntext\nE\n./smoothcast")
    assert blocked("./smoothcast <<'E'\nbody\nE")
    assert blocked("python3 - <<EOF\nx\nEOF\n./smoothcast --self-test")


def test_unterminated_heredoc_hides_only_the_lines_after_it():
    assert blocked("./smoothcast\ncat <<'E'\nbody")
    assert not blocked("cat <<'E'\n./smoothcast")
