"""Known per-platform test gaps for the native portable-suite jobs (issue #258).

Every entry is a test that fails on that OS in CI for the stated reason. They are
skipped *there only* (never on Linux), by exact test id so passing tests keep
running. This file is the register: fix the cause, then delete the entry.
tests/test_platform_gaps.py checks that every entry still names a real test and
that Linux never skips anything. A reason starting "PRODUCT BUG" is a defect in
SmoothCast itself, not in the test.
"""
from __future__ import annotations

# platform -> {test id relative to tests/: reason}
GAPS: dict[str, dict[str, str]] = {
    "darwin": {
        "test_startup_cleanup.py::StartupCleanupTests::test_verified_stale_process_gets_bounded_sigterm_and_sigkill":
            "fixture fakes a Linux /proc tree; macOS uses the psutil path",
    },
    "win32": {
        "test_desktop_integration.py::DesktopIntegrationTests::test_actual_cli_install_twice_then_check_from_spaced_checkout":
            "desktop-entry (Linux freedesktop) Exec= quoting assumed",
        "test_gui_test_safety.py::GuiTestSafetyTests::test_normal_shell_launcher_rejects_gui_test_before_bootstrap":
            "shell launcher / POSIX process groups (os.killpg) assumed",
        "test_gui_test_safety.py::GuiTestSafetyTests::test_runner_timeout_terminates_whole_process_group":
            "shell launcher / POSIX process groups (os.killpg) assumed",
        "test_launch_singleton.py::ProcScanTests::test_exclusions_never_report_own_process":
            "uses os.getuid / signal.SIGKILL / a /proc scan: POSIX only",
        "test_launch_singleton.py::ProcScanTests::test_matches_only_this_checkout":
            "uses os.getuid / signal.SIGKILL / a /proc scan: POSIX only",
        "test_launch_singleton.py::GuardBehaviourTests::test_second_launch_presents_and_does_not_start_again":
            "uses os.getuid / signal.SIGKILL / a /proc scan: POSIX only",
        "test_launch_singleton.py::GuardBehaviourTests::test_stop_instances_escalates_to_sigkill":
            "uses os.getuid / signal.SIGKILL / a /proc scan: POSIX only",
        "test_launch_singleton.py::GuardBehaviourTests::test_unresponsive_instance_is_cleared_before_launch":
            "uses os.getuid / signal.SIGKILL / a /proc scan: POSIX only",
        "test_startup_cleanup.py::StartupCleanupTests::test_only_owned_orphan_meter_directories_are_removed":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
        "test_startup_cleanup.py::StartupCleanupTests::test_other_users_processes_are_never_inspected_or_signalled":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
        "test_startup_cleanup.py::StartupCleanupTests::test_proc_starttime_with_parentheses_in_command_name":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
        "test_startup_cleanup.py::StartupCleanupTests::test_verified_stale_process_gets_bounded_sigterm_and_sigkill":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
    },
}
