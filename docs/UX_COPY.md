# SmoothCast UX copy contract

SmoothCast is a cooperative media control system, not a protocol debugger.
Messages must tell people **what happened**, **what is known about why**,
and **what action to take** when action is possible. Short successful actions
may simply acknowledge the result. Never claim the receiver confirmed a command
merely because the local dispatcher accepted it.

## Voice and vocabulary

- Use British English, neutral active voice and concise complete sentences.
  Avoid blame, apologies, jokes and raw framework or Python exceptions.
- **Receiver** is the canonical technical noun for Chromecast, Cast TVs and
  DLNA MediaRenderers. Say **TV** only in friendly actions (e.g. Cast to TV).
  Say **room** for the shared control session; **Up Next** for the shared queue.
- Keep state words consistent with `src/state_labels.py`: Playing, Paused,
  Buffering…, Receiver offline and Ready. Use **reconnect** only when a client
  needs authentication, **reload** for incompatible browser code, and **retry**
  for transient input or transport failures.
- Do not reveal absolute media paths, credentials, PINs or raw exceptions in
  status, toast or browser copy. Detailed causes belong in private diagnostic
  logging with redaction.
- Avoid vague phrases such as "Command accepted", "Invalid request body",
  "Something went wrong" and "Device is offline". An HTTP command receipt is
  not receiver playback confirmation.

## Length and punctuation

| Surface | Maximum static text | Style |
| --- | ---: | --- |
| Button, tab, dialog or notification title | 90 characters | Sentence case; no trailing full stop |
| Toast or concise status update | 180 characters | One sentence; no unsupported success claim |
| Structured error message | 220 characters | State the problem and next step |
| Supporting description / label | 240 characters | Up to two short sentences |

Use an ellipsis for an **ongoing** action (Preparing…), not a failure.
Accessible descriptions should name the outcome, not merely the colour/icon.
Numbers, units and elapsed times follow the shared display conventions.

## Before → after

| Before | After | Reason |
| --- | --- | --- |
| Device is offline | Receiver offline. Check its power and network connection. | Consistent noun and remedy |
| Command accepted | Command received; checking receiver state. | Receipt is not playback confirmation |
| Invalid request body | Request could not be read. Retry the action. | Actionable without implementation jargon |
| This control session has expired; refresh the dashboard | Playback changed. Refresh the room before retrying. | Distinguishes stale state from login expiry |
| Stop the current cast before changing TV | Stop this cast before switching receivers. | Precise ownership boundary |
| Local decoder failed: <raw exception> | Preview could not decode this file. Try another format or codec. | No internal error exposure |

## Internationalisation readiness

User-facing text is a literal or f-string at its call site, not assembled by
concatenating translated fragments. For future gettext (#219), preserve named
placeholders for dynamic fields and provide context for ambiguous terms.
Write complete message templates so translators can reorder named fields. For
example, `_("Playing {title}").format(title=title)` keeps a static message ID.
The stdlib AST gate checks room errors, GTK toast, status and label calls, and
dialog or button titles. It checks each static conditional or fallback message
and reads gettext-wrapped templates. Use explicit user-facing reasons from
typed errors. Keep unexpected exception details out of the displayed message.
Run `python3 scripts/ci/ux_copy_lint.py` before committing. The checker runs in
Verify's headless syntax lane. Dynamic messages still require review.

Background jobs deliver a recovery message to the interface and send the
exception to the private error log. For an expected failure with an audited
message, raise `UserFacingError` with the copy to display. Put diagnostic
details in its `detail` argument or chain the original exception.
