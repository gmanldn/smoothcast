"""Complexity ratchet (#516): measure growth; fail only on large unexplained jumps."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("complexity_report", ROOT / "scripts/ci/complexity_report.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def _tree(tmp_path, files):
    (tmp_path / "src").mkdir()
    for name, body in files.items():
        (tmp_path / "src" / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def test_measure_counts_lines_functions_and_top_level_imports(tmp_path):
    root = _tree(tmp_path, {
        "a.py": "import os\nimport sys\n\ndef big():\n    x = 1\n    y = 2\n    return x + y\n",
        "b.py": "def small():\n    return 1\n\ndef lazy():\n    import json\n    return json\n",
        "broken.py": "def (:\n",
    })
    report = cr.measure(root, with_git=False)
    assert report["src_modules"] == 3
    assert report["modules"]["a.py"] == 7
    assert report["longest_functions"][0] == ("a.py:big", 4)
    assert dict(report["most_top_level_imports"])["a.py"] == 2
    assert dict(report["most_top_level_imports"])["b.py"] == 0  # function-level import is not startup cost
    assert report["modules_added_since_last_tag"] is None


def test_compare_tolerates_small_growth_and_flags_big_jumps():
    base = {"src_lines": 1000, "modules": {"a.py": 400, "tiny.py": 50}}
    cur = lambda total, a, tiny=50, extra=None: {  # noqa: E731
        "src_lines": total, "modules": {"a.py": a, "tiny.py": tiny, **(extra or {})}}
    assert cr.compare(cur(1100, 438), base) == []
    assert any("over baseline" in p for p in cr.compare(cur(1300, 450), base))
    assert any("a.py grew" in p for p in cr.compare(cur(1100, 441), base))\n    assert any("a.py grew" in p for p in cr.compare(cur(1100, 600), base))
    assert cr.compare(cur(1100, 438, tiny=200), base) == []  # tiny modules are exempt
    assert any("new module" in p for p in cr.compare(cur(1100, 438, extra={"huge.py": 1500}), base))


def test_repository_stays_within_the_committed_baseline():
    baseline = json.loads(cr.BASELINE.read_text(encoding="utf-8"))
    problems = cr.compare(cr.measure(ROOT, with_git=False), baseline)
    assert not problems, "\n".join(problems) + (
        "\nIf justified, run python3 scripts/ci/complexity_report.py --write-baseline "
        "and say why in the commit message.")
