# Correlated command diagnostics (#451)

SmoothCast retains a **memory-only** ring of up to 96 command traces, with up to
24 monotonic elapsed-time stages each. The latest 32 appear as `command_traces`
in the explicitly exported, redacted support bundle. Every trace has an opaque
24-character hex ID. Web retries with the same `(client_id, command_id)` map
to one HMAC-derived trace; desktop, CLI and control-API commands generate IDs.
Errors inside the trace carry `[command:<id>]`.

The trace export **never** contains receiver names, IP addresses, device
identities, media titles, paths, request payloads, client IDs or raw exceptions.
Expected receiver state is held temporarily in memory with an HMAC-fingerprinted
device identifier. No extra device polling, threads or network requests are
introduced for tracing.

A successful Google Cast command or UPnP/DLNA SOAP mutation records
`receiver_ack`, **not** `receiver_confirmed`. For Play/Pause/Stop, the same
trace waits for a later status observation of the **same receiver**, with
the expected state within 20 seconds. Only that matching observation records
`receiver_confirmed`. A mismatching explicit state records `unconfirmed`
without precluding a later match. Foreign receivers, stale observations,
unknown states, and missing status do not create false confirmations.
Other operations (seeks, volume, metadata or toggles without a known desired
state) remain ACK-only until their semantics can be verified.

Stages also include `received`, `fenced`, `dispatched`, `worker_queued`,
`receiver_call`, `receiver_failed`, `rejected`, `status_observed`,
`replayed` and `completed`. The latter means the request handler returned,
not that the receiver applied the command. A missing confirmation remains
uncertain. Receiver status is not polled automatically, so traces whose
handlers don't observe a later matching state remain ACK-only.

The portal context is propagated through GTK idle callbacks and bounded async
workers. Legacy Up Next queue edits and replays also carry one trace; guest
identifiers are not exported. Do not interpret a local HTTP command receipt
as proof of remote playback.

Headless targeted tests:
`python3 -m pytest -q tests/test_command_trace.py tests/test_command_trace_integration.py tests/test_command_trace_receiver.py`

Physical receiver qualification is tracked separately in #208. Tests use
fake receiver responses, not the user's live desktop or TV.
