"""Focused regression tests for the line-independent silent-exception ratchet (#520)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ci"))
import lint_silent_except as lint  # noqa: E402


class SilentExceptLintTests(unittest.TestCase):
    def test_only_broad_silent_handlers_are_flagged(self):
        source = """
def f():
    for item in (1,):
        try:
            work(item)
        except Exception:
            pass
        try:
            other()
        except BaseException as exc:
            continue
        try:
            third()
        except:
            ...
        try:
            expected_failure()
        except OSError:
            pass
        try:
            log_failure()
        except Exception:
            log_error()
"""
        got = lint.scan_source(source, "src/streamer.py")
        self.assertEqual(len(got), 3)
        self.assertEqual([row["key"].split("|")[2] for row in got],
                         ["Exception", "BaseException", "bare"])

    def test_fingerprint_survives_source_line_moves_and_rejects_new_handlers(self):
        source = "def f():\n    try:\n        do_work()\n    except Exception:\n        pass\n"
        a = lint.scan_source(source, "src/streamer.py")[0]["key"]
        b = lint.scan_source("# An unrelated prefix.\n\n" + source,
                             "src/streamer.py")[0]["key"]
        self.assertEqual(a, b)
        later = source + "\n    try:\n        new_operation()\n    except Exception:\n        pass\n"
        self.assertEqual(len(lint.scan_source(later, "src/streamer.py")), 2)
        self.assertIn(a, {item["key"] for item in lint.scan_source(later, "src/streamer.py")})

    def test_duplicate_fingerprints_refuse_to_hide_new_exceptions(self):
        source = """def f():
    try:
        work()
    except Exception:
        pass
    try:
        work()
    except Exception:
        pass
"""
        with self.assertRaisesRegex(ValueError, "duplicate"):
            lint.scan_source(source, "src/streamer.py")

    def test_baseline_requires_reasons_and_is_ratcheted_both_ways(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in lint.PLAYBACK_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            path = root / lint.PLAYBACK_FILES[0]
            source = "def f():\n    try:\n        call()\n    except Exception:\n        pass\n"
            path.write_text(source)
            key = lint.scan_source(source, lint.PLAYBACK_FILES[0])[0]["key"]
            baseline = root / "baseline.json"
            baseline.write_text(json.dumps([{"key": key, "reason": "Existing cleanup"}]))
            _, problems = lint.audit(root, baseline)
            self.assertEqual(problems, [])
            path.write_text(source + "try:\n    something_else()\nexcept Exception:\n    pass\n")
            _, problems = lint.audit(root, baseline)
            self.assertTrue(any(message.startswith("NEW ") for message in problems))
            path.write_text("")
            _, problems = lint.audit(root, baseline)
            self.assertTrue(any(message.startswith("STALE ") for message in problems))
            baseline.write_text(json.dumps([{"key": key, "reason": ""}]))
            _, problems = lint.audit(root, baseline)
            self.assertIn("Exception baseline requires key/reason pairs", problems)


if __name__ == "__main__":
    unittest.main()
