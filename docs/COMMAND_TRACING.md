# Correlated command diagnostics (#451)

SmoothCast now keeps a **memory-only** ring of up to 96 command traces. Each
trace records an opaque 24-hex-character identifier, a restricted origin and
action, and at most 24 monotonic elapsed-time stages. The most recent 32 traces
appear as \`command_traces\` in a redacted diagnostics bundle.

A web command receives a stable HMAC-derived trace ID from its
\`(client_id, command_id)\`, so retries refer to one trace without exposing
guest IDs. Desktop, CLI and local-control commands use random IDs.
Log entries emitted during a traced command include \`[command:<id>]\`.
No paths, media titles, receiver names, payloads or raw exception strings
are stored in the trace records. Support bundles are bounded and require
explicit export; nothing is sent automatically.

Stages include \`received\`, \`fenced\`, \`dispatched\`, \`worker_queued\`,
\`receiver_call\`, \`receiver_ack\`, \`receiver_failed\`, \`rejected\` and
\`completed\`. Receiver command acknowledgement is **not** proof of playback.
\`status_observed\` means a receiver status response was obtained, not that
the requested transition was verified. The \`receiver_confirmed\` stage is
reserved for future verification of the exact transition. Do not claim a
remote success from a local HTTP receipt.

The portal request carries context explicitly to the GTK idle callback;
\`Async.run\` preserves it through worker and completion callbacks, without
introducing a new polling thread. Plain GTK controls generate their own
trace context; a nested portal command reuses the portal trace.

Run the two targeted tests with:
\`python3 -m pytest -q tests/test_command_trace.py tests/test_command_trace_integration.py\`

Remaining qualification: correlation for legacy non-enveloped portal
mutations; semantic receiver status confirmation across heterogeneous
Cast/DLNA protocols, including device-specific fake-receiver and physical
tests (#208). This is a diagnostic infrastructure increment, **not** a
claim that all #451 acceptance criteria are complete.
