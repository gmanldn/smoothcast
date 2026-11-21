"""#444: concurrent config writers never lose keys or leave invalid JSON."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config_control

WRITER = """
import sys, json
sys.path.insert(0, sys.argv[1])
import config_control
from pathlib import Path
path, name = Path(sys.argv[2]), sys.argv[3]
cfg = config_control.load_file(path, {})
for i in range(200):
    cfg[name] = i
    assert config_control.save_file(path, cfg)
    json.loads(path.read_text())  # always valid JSON
"""


def test_two_processes_interleave_without_losing_keys(tmp_path):
    path = tmp_path / "config.json"
    config_control.save_file(path, {"schema_version": config_control.SCHEMA_VERSION})
    src = str(Path(__file__).resolve().parents[1] / "src")
    procs = [subprocess.Popen([sys.executable, "-c", WRITER, src, str(path), n])
             for n in ("alpha", "beta")]
    assert all(p.wait(60) == 0 for p in procs)
    data = json.loads(path.read_text())
    assert data["alpha"] == 199 and data["beta"] == 199


def test_stale_memory_does_not_revert_other_writers_keys(tmp_path):
    path = tmp_path / "config.json"
    mine = config_control.load_file(path, {"a": 1})
    other = json.loads(path.read_text()) if path.exists() else {}
    other.update({"schema_version": config_control.SCHEMA_VERSION, "external": "kept"})
    path.write_text(json.dumps(other))
    mine["a"] = 2
    assert config_control.save_file(path, mine)
    data = json.loads(path.read_text())
    assert data["a"] == 2 and data["external"] == "kept"


def test_no_fixed_tmp_file_left_behind(tmp_path):
    path = tmp_path / "config.json"
    config_control.save_file(path, {"schema_version": config_control.SCHEMA_VERSION})
    assert not (tmp_path / "config.tmp").exists()
    assert [p.name for p in tmp_path.glob("*.tmp")] == []
