"""Guards against leftover debug probes and a self-test that cannot quit.

A previous investigation left widget-tree measurement hooks in ``cast_control``
that printed the whole tree on every launch and called a ``MainWindow`` method
from ``CastControlApp``, raising AttributeError before ``self.quit()`` so the
``--self-test`` never terminated. These cheap source-level checks fail fast if
either pattern returns.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from gui_source import combined_source, main_window_source

ROOT = Path(__file__).resolve().parents[1]
SOURCE = combined_source()
TREE = ast.parse(SOURCE)
MAIN_SOURCE = main_window_source()
MAIN_TREE = ast.parse(MAIN_SOURCE)
CONTROL_SOURCE = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
CONTROL_TREE = ast.parse(CONTROL_SOURCE)


def _class(name: str) -> ast.ClassDef:
    tree = MAIN_TREE if name == "MainWindow" else CONTROL_TREE
    return next(node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == name)


class SelfTestHygieneTests(unittest.TestCase):
    def test_no_leftover_debug_probe_methods(self):
        offenders = [node.name for node in ast.walk(TREE)
                     if isinstance(node, ast.FunctionDef) and node.name.startswith("_debug_")]
        self.assertEqual(offenders, [], f"leftover debug hooks: {offenders}")

    def test_build_ui_schedules_no_debug_timeouts(self):
        build = next(node for node in _class("MainWindow").body
                     if isinstance(node, ast.FunctionDef) and node.name == "_build_ui")
        for call in (node for node in ast.walk(build) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "timeout_add":
                self.fail("_build_ui must not schedule diagnostic timeouts")

    def test_selftest_quit_actually_quits(self):
        quit_fn = next(node for node in _class("CastControlApp").body
                       if isinstance(node, ast.FunctionDef) and node.name == "_selftest_quit")
        attributes = {node.func.attr for node in ast.walk(quit_fn)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertIn("quit", attributes)
        self.assertNotIn("_debug_measure", SOURCE)

    def test_selftest_quit_runs_in_a_finally_block(self):
        # An exception in the completion probe must not skip self.quit() and
        # hang --self-test; the runner deadline must not be the only exit.
        quit_fn = next(node for node in _class("CastControlApp").body
                       if isinstance(node, ast.FunctionDef) and node.name == "_selftest_quit")
        finally_calls = [
            call
            for node in ast.walk(quit_fn) if isinstance(node, ast.Try)
            for stmt in node.finalbody
            for call in ast.walk(stmt)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "quit"
        ]
        self.assertTrue(finally_calls, "self.quit() must run in a finally block")

    def test_isolated_runner_seeds_and_verifies_private_state(self):
        # The opt-in Xvfb runner must plant a saved cast and an expired sleep
        # timer in its private home and fail if --self-test touches either.
        runner = (ROOT / "scripts" / "test_gui_isolated.py").read_text(encoding="utf-8")
        self.assertIn("seed_isolated_state", runner)
        self.assertIn("sleep_timer_deadline", runner)
        self.assertIn("session.json", runner)
        self.assertIn("touched seeded state", runner)

    def test_selftest_skips_discovery_adoption_and_timers(self):
        init = next(node for node in _class("MainWindow").body
                    if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        segment = ast.get_source_segment(MAIN_SOURCE, init)
        self.assertIn("if not app.selftest:", segment)
        guarded = segment[segment.index("if not app.selftest:"):]
        for scheduled in ("self._tick", "_refresh_responsive_layout", "_meter_tick",
                          "_poll_device", "_initial_scan", "_adopt_session", "_sleep_tick"):
            self.assertIn(scheduled, guarded)

    def test_selftest_failure_is_reported_as_nonzero(self):
        main_fn = next(node for node in CONTROL_TREE.body
                       if isinstance(node, ast.FunctionDef) and node.name == "main")
        segment = ast.get_source_segment(CONTROL_SOURCE, main_fn)
        self.assertIn("selftest_failed", segment)
        self.assertIn("return 1", segment)
        self.assertIn('print("SELFTEST OK")', segment)


if __name__ == "__main__":
    unittest.main()
