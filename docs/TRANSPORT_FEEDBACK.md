# On-screen transport feedback (#120 / SC-111)

SmoothCast's Adwaita toast overlay provides temporary (3-second) on-screen
feedback without taking keyboard focus or intercepting mouse/receiver input.
Local preview chapter actions report the chapter and selected source time.
Direct Cast and DLNA chapter/seek confirmation is displayed only after
the asynchronous transport operation acknowledges success; errors display
an error toast rather than a false success message.

Transcoded HLS chapter jumps and speed changes first show a truthful
'seeking' or 'applying' message. Only the successful restart callback
displays the final chapter title/time or speed. Callbacks must still own
the active session; stale callbacks do not produce success toasts.

Existing successful volume confirmations require current receiver identity
and slider value (commit 627e411). Existing seek/speed actions and the
nonblocking Adw.Toast overlay are reused; no new transport, polling or
GUI overlay is introduced.

Portable regression: pytest -q tests/test_transport_feedback.py
Device qualification and perceptual UX checks remain in #208.
