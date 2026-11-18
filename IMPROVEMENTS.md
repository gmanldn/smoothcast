# SmoothCast — 50 high-value improvement proposals

This is a prioritised engineering backlog, **not a list of shipped features**.
Each idea targets a real user outcome and names an observable completion criterion.
**Priority:** P0 = compatibility/reliability blocker, P1 = major experience or
capability gain, P2 = strategically valuable. **Effort:** S = small, M = medium,
L = substantial. Prioritise verified end-to-end behaviour over feature count.

## Actual compatibility baseline

- Two distinct sender backends now exist: **Google Cast via catt** and
  **DLNA AVTransport (beta) via SSDP/SOAP**. Google Cast can discover
  Chromecast devices, Google TV / Android TV Cast receivers, Google Cast-enabled
  smart TVs, Google TV Streamer and Cast-capable smart displays. The receiver
  must expose Google Cast; having an HDMI port, Wi-Fi or a TV app is not enough.
  Manual private-LAN IPv4 selection can help when mDNS discovery fails.
- FFmpeg transcodes common Matroska/MKV video and audio codecs such as H.264,
  HEVC, VP9, AV1, AAC, E-AC-3, AC-3, DTS, FLAC and Opus to a conservative
  H.264/AAC HLS output, subject to local decoder/encoder availability.
- External **.srt**, **.vtt** and **.ttml** are supported through the receiver
  subtitle path or FFmpeg burn-in. External **.ass/.ssa** require burn-in.
  Embedded MKV text tracks can be selected and burned by FFmpeg/libass.
  **Bitmap PGS/VobSub/DVB subtitles are not yet rendered.**
- **DLNA/UPnP MediaRenderers** now have a first progressive-MP4 playback
  adapter, with HTTP Range, SOAP control, and optional offline MKV conversion.
  Physical TV qualification and capability negotiation remain **open**.
  **AirPlay-only devices, Roku without Cast and Miracast** still require their
  own adapters and device tests.
- This describes implementation intent, not a claim of comprehensive
  hardware qualification. Portable CI does not validate network or GPU
  playback on physical TVs.

Relevant vendor documentation:
[Google Cast supported receivers](https://developers.google.com/cast/docs/overview),
[Google Cast device-dependent media support](https://developers.google.com/cast/docs/media),
[FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1).

## P0 — target breadth and operational correctness

1. **[P0 · L · beta shipped, qualification open] Native DLNA/UPnP MediaRenderer adapter.** SSDP/AVTransport and progressive MP4 HTTP Range implemented; finish target capability negotiation, direct MPEG-TS fallback, seek/volume quirks and LG/Samsung/Sony hardware smoke tests.
2. **[P0 · L] AirPlay video adapter.** Use a maintained, tested implementation with authentication/pairing and explicit protocol-version support; verify Apple TV playback, seek and stop.
3. **[P0 · L] Roku ECP/receiver adapter.** Implement only against a documented receiver route and test on Roku hardware; distinguish Roku from Cast-equipped TVs.
4. **[P0 · M] Target capability negotiation.** Probe MIME, codecs, resolution, subtitle formats, seek/range and playback speed; construct a per-session compatibility plan instead of guessing.
5. **[P0 · M] Model-aware Cast output profiles.** Use receiver model/codec capabilities to choose conservative 1080p H.264 or verified 4K/HDR paths without needless quality loss.
6. **[P0 · M] Cast transfer error recovery.** If launch/seek fails, preserve local position and offer one-click retry, alternate encoding or a different target with clear reason.
7. **[P0 · M] Network-route diagnostics.** Show receiver IP, selected interface, VPN/firewall interference, inbound media-port reachability and HLS health test from a second host.
8. **[P0 · M] Chromecast discovery robustness.** Reconcile mDNS updates, duplicate display names, missing TXT fields and stale IPs without losing saved receiver selections.
9. **[P0 · L] Receiver command state machine.** Serialize cast, seek, pause, resume, stop and transfer with cancellation and idempotent retries; stale callbacks cannot hijack another TV.
10. **[P0 · M] First-frame and stall watchdog.** Distinguish FFmpeg stalled, HLS buffer starved and receiver stopped; recover automatically within bounded attempts.
11. **[P0 · M] Direct-to-transcode failover.** Verify actual decoder acceptance and subtitle capability before switching; preserve selected source timestamp and audio/subtitle tracks.
12. **[P0 · M] End-to-end media matrix CI.** Generate MKV/MP4 fixtures covering H.264/HEVC/VP9/AV1, AC-3/DTS/Opus, external SRT/ASS, multiple streams and 10-bit inputs; assert stream output.
13. **[P0 · M] Multi-audio-track picker.** Enumerate languages, titles and channel layouts, select any valid track, carry its selection through seeks and cast restarts.
14. **[P0 · L] Bitmap subtitle compositor.** Decode PGS, VobSub and DVB subtitle images, overlay with correct timing and palette; validate forced-only and multilingual tracks.
15. **[P0 · M] Reliable subtitle state across transfers.** Preserve selected external/embedded track, delay, forced flag and burn mode when switching targets or restarting an encoder.
16. **[P0 · M] Subtitle encoding detection.** Detect UTF-8/UTF-16/legacy SRT safely; normalise sidecars to a private bounded UTF-8 file when required, without changing originals.
17. **[P0 · M] In-window player runtime smoke test.** Assert real video, audio, seek, pause, EOS and Cast handoff on each OS, not just GTK-free source-level tests.
18. **[P0 · M] Transactional setup/uninstall/repair.** Validate GTK media plugin, codecs, CLI, app icon and launch on macOS/Windows/Linux; failed setup leaves the prior working install usable.

## P1 — powerful film and subtitle experience

19. **[P1 · M] HDR10-to-SDR tone mapping.** Preserve meaningful luminance/colour on older SDR receivers; compare reference clips and record GPU/CPU performance.
20. **[P1 · L] Dolby Vision fallback.** Detect DV profiles and select compatible base-layer HDR10/SDR without green/purple corruption; test popular MKV variants.
21. **[P1 · M] Native 4K/HDR hardware encoders.** Support VAAPI, VideoToolbox and Windows encoders with per-device capability checks and deterministic software fallback.
22. **[P1 · L] Adaptive bitrate and network feedback.** Switch quality on actual throughput/buffer metrics instead of fixed presets; avoid oscillation and excess re-encoding.
23. **[P1 · M] Automatic audio downmix policies.** Handle stereo, 5.1, 7.1, E-AC-3/DTS/TrueHD, dialogue isolation and LFE safely, with A/V sync tests.
24. **[P1 · M] Subtitle delay and live calibration.** Provide ±100 ms controls with persisted offsets and verified burn-in timings.
25. **[P1 · M] Subtitle styling and placement.** Expose font size, margin, border and contrast, with safe presets respecting ASS text styling.
26. **[P1 · M] MKV font attachments.** Extract embedded ASS/SSA fonts into a secure temporary directory; preserve intended typesetting without writing to the user’s font collection.
27. **[P1 · S] Drag-and-drop subtitle loading.** Drop an SRT/VTT/ASS file onto preview and immediately display its language, preview and whether burn-in is required.
28. **[P1 · M] Interactive subtitle track preview.** Preview text at scrub time before casting and allow explicit selection of forced or full-dialogue tracks.
29. **[P1 · M] Persistent language preferences.** Prefer requested audio/subtitle languages per series, with forced captions handled separately from full subtitles.
30. **[P1 · M] Matroska chapter and edition navigation.** Display chapter titles and segment times; support direct chapter jump with exact timeline mapping.
31. **[P1 · M] Frame-step and thumbnail strip.** Generate sparse cached thumbnails for instant scrub previews and frame stepping without spawning a decoder per mouse move.
32. **[P1 · M] Playback handoff accuracy.** Measure local-to-TV start error and compensate for startup latency and receiver buffering within a defined tolerance.
33. **[P1 · M] Smart resume/watch-state database.** Store durations, file fingerprints, chosen tracks, watched percentage and positions transactionally across restarts.
34. **[P1 · M] Progressive file support for DLNA.** Provide HTTP Range/HEAD, MIME and DLNA contentFeatures safely on an allowlisted session resource.
35. **[P1 · L] External browser/web receiver.** Secure opt-in LAN web UI for preview/casting and viewing video on a browser, with pairing and expiration.
36. **[P1 · M] Graceful audio-only cast mode.** Detect Cast speaker/audio-only hardware and transmit AAC/MP3 audio without failing on video content.
37. **[P1 · L] Synchronized multi-room output.** Calibrate receiver clock drift and latency; pause/resume a group without losing sync or shared volume safety.
38. **[P1 · M] Per-device quality and subtitle presets.** Remember a receiver’s safe codec, bit rate, subtitle method and preferred speaker volume with an obvious reset.
39. **[P1 · M] Reliable playlist handoff.** Pre-probe the next film and prewarm a target-safe encoder so queue transitions are bounded and cancellable.
40. **[P1 · M] Real-time stream-health console.** Show measured network throughput, HLS latency, actual decoder state, segment failures and recoveries, not inferred success.

## P2 — product quality and advanced workflows

41. **[P2 · M] Accessible transport and subtitle controls.** Complete GTK keyboard navigation, screen-reader labels, high-contrast focus rings and large touch targets.
42. **[P2 · M] Subtitle search across locally owned files.** Index user-supplied directories for matching language-tagged subtitle files, with no automatic untrusted downloads.
43. **[P2 · S] Receiver favourites and recent targets.** Sort by last successful session, pin devices and keep manual-IP entries clearly distinguishable.
44. **[P2 · M] Local library index.** Incrementally fingerprint local media and cache metadata without loading entire folders into RAM.
45. **[P2 · M] Automatic crop/deinterlace policies.** Detect letterboxing and interlaced input, with previews and reversibility before changing the picture.
46. **[P2 · M] Bounded diagnostic bundle export.** Collect redacted system/decoder/log details and reproduce a failing cast without exposing file paths or receiver credentials.
47. **[P2 · S] Encoder dry-run preflight.** For an unfamiliar MKV, render a short private sample and report missing codecs/subtitle support before touching the TV.
48. **[P2 · M] Playback-quality benchmark wizard.** Measure machine encode speed vs source frame rate and recommend 720p/1080p/4K settings with explicit trade-offs.
49. **[P2 · M] Sandboxed subtitle and media-file handling.** Tighten temporary file limits, process timeouts, parser fuzz tests and secure cleanup of FFmpeg-produced files.
50. **[P2 · M] Release qualification dashboard.** Track CI, GTK self-tests, real-device model matrix, installer checks, codec/subtitle samples and known failures per release.

## Implementation progress (not hardware-qualified)

- **P0 #13 — Multi-audio-track picker:** implemented and under CI verification.
  FFprobe lists language, title, codec and channel layout; selected 0:a:N
  is persisted per film, survives HLS software fallback and seek restart,
  and can be changed while casting. Requires a physical receiver and
  multilingual MKV smoke test before marking it fully done.
- **Queue search:** delivered independently of this revised 50-item list;
  Ctrl+F filters filename/folder terms without changing playback order.

## Delivery criteria

A proposal is **done** only when its behaviour is implemented, source-level and
runtime tests cover the positive and failure paths, user instructions are
updated, and required hardware claims have been validated on actual devices.
Do not convert this list into unchecked feature claims or increase the release
version for every intermediate fix.
