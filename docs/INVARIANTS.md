# SmoothCast safety invariant traceability

Each architecture guarantee labelled with an INV identifier is backed by an
executable pytest node on the current source tree. The inverse reference is in
the guarding test's docstring, and the CI syntax lane checks both directions
using `python3 scripts/ci/check_invariants.py`. This is a traceability map,
**not** an additional work queue. Physical-device qualification is separate.

| ID | Safety invariant | Owner module | Guarding pytest node ID |
| --- | --- | --- | --- |
| INV-001 | Duplicate, absent or ambiguous receiver identity cannot retarget the selection | src/cast_queue.py | tests/test_discovery_identity.py::test_ambiguous_or_missing_uuid_never_silently_retargets |
| INV-002 | Watchdog limits owned HLS restart to one per playback generation | src/stream_watchdog.py | tests/test_stream_watchdog.py::test_encoder_stall_restarts_once_and_stays_bounded_across_generation |
| INV-003 | Direct-to-HLS fallback never hijacks foreign receiver playback | src/direct_probe.py | tests/test_direct_failover_probe.py::test_foreign_active_stream_blocks_auto_hls_and_never_sends_stop |
| INV-004 | Subtitle restart validates saved selection before stopping an existing cast | src/subtitle_restart.py | tests/test_subtitle_restart.py::test_handler_validation_precedes_destructive_stop_and_keeps_gui_under_budget |
| INV-005 | Every HLS encoder start uses a distinct generation ID and URLs | src/streamer.py | tests/test_hls_generation_identity.py::test_each_encoder_start_generates_unreused_url_and_segment_template |
| INV-006 | HTTP never serves new media bytes to stale-generation requests | src/server.py | tests/test_hls_generation_identity.py::test_delayed_http_requests_never_receive_new_timeline_bytes |
| INV-007 | Blocking workers deliver callbacks on the main context, not worker threads | src/async_jobs.py | tests/test_async_jobs.py::test_callbacks_are_dispatched_not_called_on_workers |
| INV-008 | Late transport callbacks cannot mutate a replaced session or device | src/cast_session.py | tests/test_transport_serialization.py::test_stale_callbacks_never_modify_a_replaced_session_or_device |
| INV-009 | Ordinary tests refuse to contact the active user desktop | src/gui_test_safety.py | tests/test_gui_test_safety.py::GuiTestSafetyTests::test_live_desktop_refused_even_when_selftest_argument_explicit |
| INV-010 | Opt-in network probes discard replies for obsolete targets | src/network_route_ui.py | tests/test_network_route_gui.py::test_selection_changed_while_worker_runs_never_shows_previous_tv_result |
| INV-011 | GTK modules remain split into bounded maintainable units | src/cast_control.py | tests/test_agent_token_efficiency.py::AgentTokenEfficiencyTests::test_gui_modules_stay_small_enough_to_read_narrowly |

Add a new row and guarding pytest test **together** when introducing a new
documented safety invariant, then annotate its architecture section with
`<!-- invariant: INV-nnn -->` and its test docstring with `INV-nnn:`.
Broken owner paths, node IDs, assertion bodies, missing or orphaned IDs, and
unlinked architecture markers fail the CI gate. Run the named tests as part of
the complete headless pytest suite; a surviving name alone is not evidence
of a passing test. For relevant source paths, `agent_context.py route`
includes the corresponding invariant identifiers.
