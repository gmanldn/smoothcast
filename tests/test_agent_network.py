"""Offline tests for the on-demand agent network diagnostic."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "agent_network", Path(__file__).resolve().parents[1] / "scripts/agent_network.py"
)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class NetworkTests(unittest.TestCase):
    def test_git_errors(self):
        for code, message, expected in (
            (0, "", "ok"), (2, "", "missing-ref"),
            (128, "Could not resolve host: github.com", "dns"),
            (128, "SSL certificate problem", "tls-or-host-key"),
            (128, "Permission denied (publickey)", "authentication-or-access"),
            (128, "Repository not found", "repository-or-access"),
            (128, "Connection refused", "transport"),
            (128, "unexpected", "other-git-failure"),
        ):
            with self.subTest(message=message):
                self.assertEqual(network.git_failure(code, message), expected)

    @patch.object(network.subprocess, "run")
    def test_bounded_and_noninteractive(self, run):
        run.return_value = subprocess.CompletedProcess([], 128, "", "Could not resolve host")
        self.assertEqual(network.probe(["git"], 15, git=True), "dns")
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    @patch.object(network.subprocess, "run")
    def test_timeout_and_unavailable(self, run):
        run.side_effect = subprocess.TimeoutExpired([], 5)
        self.assertEqual(network.probe(["python"], 5), "timeout")
        run.side_effect = FileNotFoundError()
        self.assertEqual(network.probe(["git"], 15, git=True), "unavailable")

    @patch.object(network, "probe", side_effect=["dns-failed", "dns-failed", "dns-failed", "ok"])
    @patch("builtins.print")
    def test_proxy_git_success_is_authoritative(self, _print, _probe):
        self.assertEqual(network.main(), 0)

    @patch.object(network, "probe", side_effect=["ok", "ok", "ok", "dns"])
    @patch("builtins.print")
    def test_git_failure_not_hidden_by_dns_success(self, _print, _probe):
        self.assertEqual(network.main(), 1)
