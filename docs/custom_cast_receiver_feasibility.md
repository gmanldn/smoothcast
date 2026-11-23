# Custom Google Cast receiver feasibility

Research for [issue #276](https://github.com/gmanldn/smoothcast/issues/276),
checked against Google Cast's official documentation on 21 November 2026.

## Recommendation

Proceed with a small, optional prototype of a Custom Web Receiver. Keep the
Default Media Receiver as the production default and fallback until an actual
Cast device demonstrates a user-visible gain. The prototype should test
subtitle styling and receiver status first; it should measure seek behavior
before claiming better precision. A custom receiver provides hooks for
application logic, but does not by itself change the stream's seek points,
container, or decoder behavior.

Google also offers a Styled Media Receiver. It provides hosted playback UI
with CSS customization and is a lower-effort experiment for appearance alone.
It is not a substitute for custom playback logic, which is the reason to choose
the Custom Web Receiver here.

## Feasibility by requested capability

- **Seeking:** The Web Receiver SDK exposes `PlayerManager.seek()` and seek
  message interception. This can support custom seek policy and accurate
  status reporting. The Cast seek protocol carries a position in seconds, but
  actual landing precision remains dependent on the media, stream format,
  receiver player, and keyframe layout. Prototype by comparing requested and
  observed positions on representative local files and HLS streams.
- **Subtitle appearance:** The receiver SDK exposes `TextTracksManager` for
  track selection and styling, including font scale, family, foreground,
  background, edge, and window styling. SmoothCast currently has sender-side
  subtitle handling and style settings; a receiver prototype should check how
  those map to Cast text tracks and which styles are retained by devices.
- **Richer status:** The receiver can listen to player/media events and send
  status to senders. SmoothCast's PyChromecast backend now receives Cast
  status callbacks, so first compare the status already available through
  standard Cast messages. Use a custom receiver only for information that is
  unavailable or demonstrably inadequate there.

These APIs make a prototype technically feasible. They do not guarantee every
feature works on every Chromecast model or firmware; device qualification is
required.

## Hosting and registration

A Custom Web Receiver is an HTML5/JavaScript app loaded by the Cast device.
Its URL must be reachable by that device when the receiver app launches. The
Google Cast SDK Developer Console registration supplies an application ID;
SmoothCast must launch that ID for the custom receiver. A Cast device must be
registered for testing before the receiver is published. Google documents
HTTP as acceptable during development and HTTPS as required when publishing.
The Google documentation and setup flow should be checked for current account
and fee requirements before registration; no fee amount is assumed here.

For the first prototype, serve static receiver assets from a stable SmoothCast
development host on the same LAN, and register the reachable URL and a test
device. This avoids building a server-side playback service. Confirm that
target devices can resolve and fetch the host URL and any SDK resources. A
dynamic LAN address or port makes registration and repeatable testing fragile.
For general distribution, plan on a stable HTTPS URL with publicly trusted
TLS and an app ID managed by the project; do not require each user to register
their own receiver. The receiver can remain static, with the existing
SmoothCast process continuing to serve media and control playback.

## Bounded prototype

1. Add an opt-in receiver choice and app-ID setting, defaulting to the existing
   receiver.
2. Host a minimal static CAF receiver page with the built-in media player.
3. Test one subtitle style and event/status round-trip against existing
   SmoothCast media metadata and commands.
4. Compare seek request position with observed playback position for a small
   matrix of local and HLS media on at least one registered Cast device.
5. Keep default-receiver fallback available if app launch, load, or status
   handling fails.

Do not bundle the prototype into a release until registration ownership,
hosting, supported-device behavior, privacy, and a rollback path are settled.

## Official references

- [Web Receiver overview](https://developers.google.com/cast/docs/web_receiver)
- [Custom Web Receiver](https://developers.google.com/cast/docs/web_receiver/basic)
- [Receiver registration](https://developers.google.com/cast/docs/registration)
- [PlayerManager API](https://developers.google.com/cast/docs/reference/web_receiver/cast.framework.PlayerManager)
- [Text track styling and management](https://developers.google.com/cast/docs/reference/web_receiver/cast.framework.TextTracksManager)
- [Cast seek message](https://developers.google.com/cast/docs/media/messages#seek)
