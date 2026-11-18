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

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _class(name: str) -> ast.ClassDef:
    return next(node for node in TREE.body
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


if __name__ == "__main__":
    unittest.main()
