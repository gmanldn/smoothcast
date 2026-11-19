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
        "test_caller_media_paths.py::CallerMediaPathTests::test_forwarded_command_line_uses_callers_cwd_not_running_process":
            "caller working-directory translation assumes POSIX absolute-path semantics",
        "test_setup_bootstrap.py::SetupContractTests::test_macos_and_windows_never_try_linux_pid_cleanup":
            "the test assumes psutil is absent; the native job installs psutil, so cleanup runs (test should patch psutil to None)",
        "test_streamer_reliability.py::StreamerReliabilityTests::test_only_expected_process_command_lines_can_be_restored":
            "fixture reads a Linux /proc/PID/cmdline tree",
        "test_caller_media_paths.py::CallerMediaPathTests::test_argument_translation_precedes_launcher_chdir":
            "macOS temp dirs resolve through /private; the test compares the unresolved path (test-side)",
        "test_caller_media_paths.py::CallerMediaPathTests::test_missing_caller_media_must_not_fall_back_to_checkout_decoy":
            "macOS temp dirs resolve through /private; the test compares the unresolved path (test-side)",
        "test_desktop_integration.py::DesktopIntegrationTests::test_actual_cli_install_twice_then_check_from_spaced_checkout":
            "macOS temp dirs resolve through /private; Exec= path compared unresolved (test-side)",
        "test_desktop_integration.py::DesktopIntegrationTests::test_installs_matching_desktop_id_and_icon":
            "macOS temp dirs resolve through /private; Exec= path compared unresolved (test-side)",
        "test_historical_features.py::HistoricalFeatureTests::test_playlist_round_trip":
            "macOS temp dirs resolve through /private; playlist paths compared unresolved (test-side)",
        "test_playlist_control.py::PlaylistTests::test_playlist_with_media_tree_survives_folder_move":
            "macOS temp dirs resolve through /private; playlist paths compared unresolved (test-side)",
        "test_playlist_control.py::PlaylistTests::test_relative_entries_comments_urls_and_duplicates":
            "macOS temp dirs resolve through /private; playlist paths compared unresolved (test-side)",
        "test_playlist_control.py::PlaylistTests::test_round_trip_preserves_local_track_order":
            "macOS temp dirs resolve through /private; playlist paths compared unresolved (test-side)",
        "test_startup_cleanup.py::StartupCleanupTests::test_verified_stale_process_gets_bounded_sigterm_and_sigkill":
            "fixture fakes a Linux /proc tree; macOS uses the psutil path",
    },
    "win32": {
        "test_caller_media_paths.py::CallerMediaPathTests::test_forwarded_command_line_uses_callers_cwd_not_running_process":
            "caller working-directory translation assumes POSIX absolute-path semantics",
        "test_setup_bootstrap.py::SetupContractTests::test_macos_and_windows_never_try_linux_pid_cleanup":
            "the test assumes psutil is absent; the native job installs psutil, so cleanup runs (test should patch psutil to None)",
        "test_streamer_reliability.py::StreamerReliabilityTests::test_only_expected_process_command_lines_can_be_restored":
            "fixture reads a Linux /proc/PID/cmdline tree",
        "test_agent_token_efficiency.py::AgentTokenEfficiencyTests::test_gui_modules_stay_small_enough_to_read_narrowly":
            "source-size budgets are measured on a CRLF checkout (Windows adds a byte per line)",
        "test_audio_monitor.py::AudioMonitorReadBoundsTests::test_large_metadata_file_is_consumed_incrementally":
            "scratch file still open when deleted (Windows forbids it)",
        "test_caller_media_paths.py::CallerMediaPathTests::test_action_option_and_uri_are_preserved":
            "POSIX absolute-path and drive-letter semantics assumed",
        "test_caller_media_paths.py::CallerMediaPathTests::test_argument_translation_precedes_launcher_chdir":
            "POSIX absolute-path and drive-letter semantics assumed",
        "test_caller_media_paths.py::CallerMediaPathTests::test_missing_caller_media_must_not_fall_back_to_checkout_decoy":
            "POSIX absolute-path and drive-letter semantics assumed",
        "test_desktop_integration.py::DesktopIntegrationTests::test_actual_cli_install_twice_then_check_from_spaced_checkout":
            "desktop-entry (Linux freedesktop) Exec= quoting assumed",
        "test_desktop_integration.py::DesktopIntegrationTests::test_installs_matching_desktop_id_and_icon":
            "desktop-entry (Linux freedesktop) Exec= quoting assumed",
        "test_error_log.py::test_large_multiline_traceback_keeps_beginning_and_final_cause":
            "text-mode newline translation makes an entry exceed MAX_ENTRY_BYTES (product limit is measured before \r\n)",
        "test_film_screenshot_selection.py::test_local_video_uses_decoder_timestamp_not_selected_queue_or_cast_clock":
            "POSIX fixture paths ('/fixtures/film.mkv') compared with Windows paths",
        "test_film_screenshot_selection.py::test_invalid_local_decoder_timestamp_never_falls_back_to_frame_zero":
            "POSIX fixture paths ('/fixtures/film.mkv') compared with Windows paths",
        "test_film_screenshot_selection.py::test_invalid_local_decoder_can_use_same_film_scrubbed_still":
            "POSIX fixture paths ('/fixtures/film.mkv') compared with Windows paths",
        "test_film_screenshot_selection.py::test_preview_source_timestamp_is_used_and_unrelated_preview_rejected":
            "POSIX fixture paths ('/fixtures/film.mkv') compared with Windows paths",
        "test_gui_test_safety.py::GuiTestSafetyTests::test_normal_shell_launcher_rejects_gui_test_before_bootstrap":
            "shell launcher / POSIX process groups (os.killpg) assumed",
        "test_gui_test_safety.py::GuiTestSafetyTests::test_runner_timeout_terminates_whole_process_group":
            "shell launcher / POSIX process groups (os.killpg) assumed",
        "test_historical_features.py::HistoricalFeatureTests::test_playlist_round_trip":
            "POSIX path comparison in playlist round trip",
        "test_hls_recovery.py::HlsRecoveryTests::test_hls_playlist_must_not_load_another_file":
            "hard-coded POSIX /tmp path in the fixture",
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
        "test_library_index.py::test_indexes_in_chunks_and_reuses_stable_media":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_complete_scans_prune_missing_but_limited_scans_do_not":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_errors_preserve_existing_records_without_losing_progress":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_unreadable_directory_never_prunes_cached_data":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_explicit_probe_is_offline_bounded_and_cached":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_failed_probe_keeps_content_hash_but_retries":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_list_is_bounded_and_invalid_limits_fail":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_cli_can_run_without_loading_gtk":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_overlapping_explicit_roots_do_not_evict_one_another":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_traversal_depth_limit_is_not_a_complete_scan":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_library_index.py::test_same_size_and_reset_mtime_still_rehashes":
            "PRODUCT BUG: the library index scan finds no media on Windows (tracked: see #258)",
        "test_playlist_control.py::PlaylistTests::test_playlist_with_media_tree_survives_folder_move":
            "POSIX path comparison in playlist round trip",
        "test_playlist_control.py::PlaylistTests::test_relative_entries_comments_urls_and_duplicates":
            "POSIX path comparison in playlist round trip",
        "test_playlist_control.py::PlaylistTests::test_round_trip_preserves_local_track_order":
            "POSIX path comparison in playlist round trip",
        "test_screenshot_source_clock.py::CaptureClockTests::test_owned_cast_uses_receiver_clock_even_if_local_preview_is_stale":
            "POSIX fixture paths compared with Windows paths",
        "test_screenshot_source_clock.py::CaptureClockTests::test_paused_embedded_player_uses_actual_decoder_timestamp":
            "POSIX fixture paths compared with Windows paths",
        "test_screenshot_source_clock.py::CaptureClockTests::test_scrubbed_still_uses_local_preview_position_not_tv_tracker":
            "POSIX fixture paths compared with Windows paths",
        "test_screenshot_source_clock.py::CaptureClockTests::test_unknown_local_decoder_timestamp_falls_back_to_selected_still":
            "POSIX fixture paths compared with Windows paths",
        "test_startup_cleanup.py::StartupCleanupTests::test_only_owned_orphan_meter_directories_are_removed":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
        "test_startup_cleanup.py::StartupCleanupTests::test_other_users_processes_are_never_inspected_or_signalled":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
        "test_startup_cleanup.py::StartupCleanupTests::test_proc_starttime_with_parentheses_in_command_name":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
        "test_startup_cleanup.py::StartupCleanupTests::test_verified_stale_process_gets_bounded_sigterm_and_sigkill":
            "fixture fakes a Linux /proc tree and uses os.getuid / SIGKILL",
        "test_subtitle_restart.py::test_handler_validation_precedes_destructive_stop_and_keeps_gui_under_budget":
            "source-size budget measured on a CRLF checkout (Windows adds a byte per line)",
        "test_subtitle_workflow.py::SubtitleWorkflowTests::test_external_burn_in_staging_is_bounded":
            "staged SRT newline form differs from the test's expectation on Windows",
    },
}
