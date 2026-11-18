# SmoothCast — 100 high-value improvement proposals

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
16. **[P0 · M · IMPLEMENTED / CI PENDING] Subtitle encoding detection.** Detect UTF-8/UTF-16/legacy SRT safely; normalise sidecars to a private bounded UTF-8 file when required, without changing originals.
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
47. **[P2 · S · IMPLEMENTED / CI PENDING] Encoder dry-run preflight.** For an unfamiliar MKV, render a short private sample and report missing codecs/subtitle support before touching the TV.
48. **[P2 · M] Playback-quality benchmark wizard.** Measure machine encode speed vs source frame rate and recommend 720p/1080p/4K settings with explicit trade-offs.
49. **[P2 · M] Sandboxed subtitle and media-file handling.** Tighten temporary file limits, process timeouts, parser fuzz tests and secure cleanup of FFmpeg-produced files.
50. **[P2 · M] Release qualification dashboard.** Track CI, GTK self-tests, real-device model matrix, installer checks, codec/subtitle samples and known failures per release.

## Code audit follow-up: proposals 51–100

These proposals come from comparing the checkout with the user and setup guides, architecture notes, existing tests and proposals 1–50. They are not hardware test results. Start with 51–55: they protect unrelated processes, live playback and first launch, and their regressions can be tested without a TV.

### Receiver safety and launch blockers

51. **[P0 · S] Make saved-PID checks non-destructive on Windows.** `streamer.pid_alive` uses `os.kill(pid, 0)`, which is not an existence-only probe on Windows. With a stale saved PID, verify restore and stop never signal an unverified process; still stop children owned through live `Popen` handles.
52. **[P0 · M] Isolate the GTK self-test from real sessions.** `MainWindow` schedules discovery, adoption and sleep checks even during window construction for `--self-test`. Seed a saved cast and expired timer in an isolated home; construct the full window with no receiver commands, discovery or changes to the seeded files.
53. **[P0 · S] Lock manual target entry during playback.** `_add_cast_target` writes the device preference independently of dropdown sensitivity. While starting or playing on A, enter B using both Return and Add IP; Stop must still target A. Both input methods must work when idle.
54. **[P0 · S] Launch the desktop installer as users do.** `scripts/install_desktop.py` registers `--pin` with `action="true"`, and installation and `--check` disagree on the launcher path. In a temporary XDG home with no `smoothcast` on `PATH`, run the actual CLI twice from a checkout with spaces; both desktop IDs must invoke that checkout and pass `--check`.
55. **[P0 · S] Use the `catt` executable setup verified.** `bootstrap.py` checks the environment's package, but `castctl._find_catt` searches ambient executables. With the environment unactivated and a conflicting older `catt` on `PATH`, verify scan and cast use the verified runtime on Unix and Windows.
56. **[P0 · S] Make idle Stop harmless.** `stop_stream` can fall through to a device stop without a session or observed external playback. Invoke the shortcut and action before the first poll: send no command. Stopping a local preview must affect only the preview; stopping known TV playback must still work.
57. **[P0 · M] Distinguish film completion from loss of status.** `castctl.player_state` defaults a missing field to `IDLE`; `playback_state.playback_ended` can then trigger repeat, Up Next or auto-close. Feed partial, offline, canceled and naturally finished reports through polling; only supported evidence of natural completion for the owned film may advance it, exactly once.
58. **[P0 · M] Recover an HLS cast while its final segments drain.** `startup_cleanup` preserves the live server, but `_adopt_session` consults `Session.active`, which expects a live encoder. Relaunch after FFmpeg exits: restore controls when the receiver is playing the saved stream; neither adopt nor stop unrelated content.
59. **[P0 · M] Close safely during cast startup.** `_cast_path` publishes a new session in a worker callback; `_on_close` may run before then. Delay that callback until after close: Keep off must retire helpers, and Keep on must leave either a recoverable session or a clean cancellation, never an orphan.
60. **[P0 · M] Accept completed one-segment HLS clips.** `Session._wait_for_segments` expects a running encoder and two segments. Cast a two-second fixture and seek into a film's final two seconds: a finalized playlist referencing one complete segment must pass without retry; a missing segment or failed encode must not.

### Streaming and media correctness

61. **[P1 · M] Resume after a long HLS pause.** The `streamer.py` encoder deletes old segments while `toggle_play` pauses only receiver playback. Pause past a full playlist rollover; resume within one segment of the saved source position at 1× and 2×, with bounded disk use. Verify the result on a Cast receiver.
62. **[P1 · M] Give each HLS start distinct media URLs.** `streamer.py` reuses playlist and segment names served by `server.py`. After switching films or seeking, a delayed request for an old URL must return old bytes or not-found, never frames from the new timeline; retain the server's narrow allowlist.
63. **[P1 · S] Send stable HLS content types.** `server.py` inherits host-dependent MIME mappings. With empty or conflicting host mappings, GET and HEAD must return `application/vnd.apple.mpegurl` for playlists and `video/mp2t` for segments; HEAD must carry the correct length and no body.
64. **[P1 · M] Select motion video instead of attached artwork.** `streamer.ffprobe` takes the first video stream and the encoder maps `0:v:0`. Put cover art before motion video in a fixture; metadata, transcode, preview and screenshot must all select the film. Artwork alone must not be reported as a movie.
65. **[P1 · M] Size the encoded picture after rotation.** `Session._filter_args` decides whether to scale using source dimensions even when rotating. Probe real output for a rotated 1080p clip, an odd-sized clip and a wide clip: dimensions must be even, fit the output bounds and preserve display aspect within rounding tolerance.
66. **[P1 · M] Measure and apply trim on the chosen soundtrack.** `measure_mean_volume` measures track zero and `audio_filters` omits negative gain. With two tracks of different levels, verify measurement, encoded gain and the meter agree on the selected track, including attenuation; Original mode must skip trim.
67. **[P1 · M] Bound the meter's raw scratch data.** `AudioMonitor` retains two FFmpeg metadata files and `_Reader.poll` reads all pending text at once. Use a multi-hour-equivalent stream and a slow reader; enforce documented scratch and per-read limits while preserving compact samples for seeking.
68. **[P1 · S] Show when the meter has no sample yet.** `AudioMonitor.sample_at` can reuse its last value for a position beyond analyzed audio. Analyze one second, seek to 60 seconds and verify the meter reports no data until that interval arrives, without hiding the last valid measured window.
69. **[P1 · M] Sample encoder progress off the GTK thread.** `_tick` and `_update_details` repeatedly read progress and count segment files. Inject slow storage: neither GTK callback may access the filesystem; buffer health and the seekbar must use the same snapshot and ignore results from a retired session.
70. **[P1 · S] Capture the frame currently on screen.** `_screenshot` reads the Cast tracker even though embedded playback and the still preview have a separate playhead. Scrub locally to 42 seconds, pause local video at 91 seconds, then capture during a cast; verify the worker receives the appropriate source timestamp in each case.

### Playback controls and saved preferences

71. **[P1 · M] Track URL casts initiated by SmoothCast.** `_cast_remote_url` labels its own successful request external, while `_sleep_tick` requires ownership. On successful handoff, stop local audio and let the timer stop that URL cast; if another app replaces it first, leave the replacement playing.
72. **[P1 · S] Keep queue selection separate from active media.** The cache-hit branch of `set_selection` can replace active metadata. While casting A, select previously probed B: tracks, clock and capture source must stay on A until B starts. Repeat with an empty cache and require identical behavior.
73. **[P1 · S] Unload a preview removed from the queue.** `_remove_queue` and `clear_queue` rebuild rows independently of pending preview work. Remove the last item during local playback and during frame decoding: stop local audio, clear the selection and reject late frames without stopping an active TV cast.
74. **[P1 · M] Preserve pause across encoder restarts.** `_restart_at` starts the tracker as playing. Seek, change speed and switch soundtrack while paused: verify the receiver and tracker settle paused at the intended source position; repeat while playing and verify they remain playing.
75. **[P1 · S] Display caption state, not merely subtitle availability.** `_refresh_controls` derives the CC toggle from subtitle presence even after `_on_cc_toggled` sends Off. After an acknowledged Off, two status refreshes must leave it off; a failed command must restore the prior state, and burned captions must not appear switchable.
76. **[P1 · S] Bind delayed volume changes to the intended TV.** `_commit_volume` resolves the target when its debounce timer fires. Adjust A, then select B within the debounce interval: B must receive nothing. Repeated changes on A must coalesce, and a rejected change must not display as confirmed.
77. **[P1 · M] Distinguish active settings from next-cast settings.** `_restart_at` takes quality and rotation from the session but gain from current preferences. Edit these during playback, then seek: the resulting settings must match the stated UI policy for each field. Rejecting a live speed change must not silently save it.
78. **[P1 · S] Recover individual invalid preferences.** `load_config` filters keys but passes values to widgets that expect lists, numbers and known choices. Test valid JSON containing null recents, nonnumeric gain and an unknown profile: open the window, retain valid neighboring values and use independent mutable defaults on each load.
79. **[P1 · M] Choose named playlists without blocking the window.** `_load_playlist` and `_save_playlist` use one home-directory filename and do I/O inline. Round-trip two named playlists through a chooser; cancellation or read failure must leave the queue unchanged, and a slow mounted directory must not delay UI events.
80. **[P1 · S] Make saved playlists portable with their media.** `playlist_control.load_playlist` supports relative entries but `save_playlist` writes only absolute paths. Move a saved playlist and its film directory together: loading must recover the same order. Define and test a fallback for media on another Windows volume.

### DLNA adapter and diagnostics

These tasks target the separate `src/dlna.py` adapter, not DLNA support in `catt` or a claim of TV compatibility.

81. **[P1 · M] Bound the entire DLNA scan.** `discover` applies a deadline to SSDP, then fetches renderer descriptions sequentially. With one fast responder and several slow ones, return the responsive renderer within a documented total budget; canceling a rescan must not publish old results.
82. **[P1 · S] Resolve renderer services against the advertised base.** `parse_renderer` joins `controlURL` to the description location. Test a description with a different same-host `URLBase`, one without it and one pointing off-host: resolve the first two correctly without relaxing the host restriction.
83. **[P1 · S] Report actionable renderer faults.** `dlna._soap` reduces non-200 responses to an HTTP status. Given a bounded UPnP fault for an unsupported seek, surface the action and renderer error code; malformed or oversized replies must still yield a concise error without dumping the response body.
84. **[P1 · M] Cancel long DLNA MP4 preparation.** `prepare_mp4` waits in `subprocess.run` for up to two hours. Cancel halfway through a slow conversion: promptly retire FFmpeg, remove the partial output and allow another selection without sending the unfinished URI to the TV.
85. **[P0 · S] Do not stop a renderer after local preparation fails.** `dlna.Session.start` assigns the renderer before preparation and calls `stop(send_stop=True)` on failure. Simulate insufficient disk before `SetAVTransportURI`: clean up scratch without sending Stop or disturbing the renderer's existing film.
86. **[P1 · S] Check the codec of the soundtrack actually mapped for DLNA.** `prepare_mp4` decides whether to copy from `media.acodec` but maps `audio_track`. With an AAC default and selected DTS track, inspect the prepared MP4: deliver the selected dialogue in a supported codec; keep lossless remux for an eligible selected track.
87. **[P1 · S] Keep original exceptions visible when logging fails.** `error_log.install_excepthook` supplies an exception tuple but `ErrorLog.add` consults `sys.exc_info()`; a write error can also bypass the previous hook. Invoke both hooks outside an `except` block and with unwritable storage: preserve the original traceback and chain each previous hook exactly once.
88. **[P2 · M] Bound logging cost during repeated failures.** `ErrorLog._persist` rewrites its entire history per entry and `_load` reads the full file before trimming. Exercise an oversized existing log and a burst of multiline errors; cap read memory, retained bytes and write volume while keeping the newest traceback readable after restart.

### Installation, distribution and verification

89. **[P0 · S] Make GTK self-test completion trustworthy.** `CastControlApp._selftest_quit` calls a measurement method defined on `MainWindow`. Under Xvfb and a session bus, require the actual command to exit within a deadline and print `SELFTEST OK` only on success; an injected callback failure must exit nonzero, not hang.
90. **[P1 · S] Resolve media arguments from the caller's directory.** `setup/launch.py` changes to the checkout and `do_command_line` reads relative paths in the receiving process. Launch from another folder with a same-named decoy in the checkout; both first launch and existing-instance activation must open the caller's file.
91. **[P1 · S] Detect missing venv support before provisioning.** `setup/bootstrap.py` lists `python3-venv` but its Linux package decision is based on GTK and media tools. On a Debian fixture missing only venv support, normal setup must request the prerequisite and `--check` must identify it without installing anything.
92. **[P1 · S] Enforce dependency versions under optimized Python.** `smoothcast` and `setup/bootstrap.py` use `assert` in probes. With and without `PYTHONOPTIMIZE=1`, reject unsupported Python and `catt` versions below the declared floor (including `0.12rc1`); accept `0.12` and distinguish missing from too old.
93. **[P1 · S] Check that FFmpeg tools actually start.** `bootstrap.check_tools` looks up binaries, while the setup guide promises executable tools. Run bounded, headless version probes: distinguish a missing binary, a loader failure and a timeout for each of `ffmpeg`, `ffprobe` and `ffplay`.
94. **[P1 · M] Preserve the native runtime chosen during setup.** `bootstrap.py` accepts runtime prefixes that `launch.py` later rediscovers from defaults or environment. Launch from Finder or a Start Menu fixture with a minimal environment: use the installed prefix, including paths with spaces, or explain that it moved rather than switching runtimes silently.
95. **[P1 · M] Verify the Homebrew installer before execution.** The macOS bootstrap runs a script fetched from mutable `HEAD`. Pin a reviewed artifact and verify it before invoking Bash; offline fixtures for truncated, altered and unavailable downloads must never reach the execution step.
96. **[P1 · S] Isolate MSYS2 installer downloads.** The Windows bootstrap stages the release asset under a shared temporary filename. Race two fixture downloads and interrupt one: use separate private paths, bound downloaded bytes, remove partial files and execute neither incomplete nor unverified content.
97. **[P1 · M] Test the installed artifact away from the checkout.** `pyproject.toml` declares modules and commands, while the GUI locates artwork relative to the source tree. Build a wheel from the sdist and install it in a clean environment with no source `PYTHONPATH`; verify entry points, canonical version, artwork and the HLS helper are usable there.
98. **[P2 · L] Avoid top-level Python module collisions.** Packaging currently installs generic `cli`, `server`, `utils` and `version` modules. Install alongside a fixture distribution with overlapping names: each must resolve its own code and survive uninstalling the other, while `sc` and `smoothcast` retain their public names.
99. **[P1 · S] Test the supported Python floor with the documented commands.** `verify.yml` runs a newer interpreter than the 3.10 floor, and unittest discovery misses pytest-style functions. Run the full portable pytest suite on the floor and primary CI interpreter; document installer-only unittest and actual GTK self-test as separate checks.
100. **[P1 · M] Keep auto-update out of developer checkouts.** `update_control.refresh_checkout` checks only for `.git` and infers change from English pull output. In disposable local repos, skip dirty, detached and noneligible branches; on an eligible branch, show a restart notice only if HEAD changes, regardless of locale or release bump.

## Implementation progress (not hardware-qualified)

- **P0 #85 — Failed local preparation never stops the renderer:**
  `dlna.Session.start` resets renderer ownership before preparation, so an
  error such as insufficient disk cleans up scratch without sending Stop or
  SetAVTransportURI and leaves the renderer's own film playing. A regression
  test covers the preparation-failure path (including a reused session).
  Real-renderer confirmation pending.
- **P0 #55 — catt resolved from the verified runtime:** `castctl._find_catt`
  now checks the running interpreter's own scripts directory before PATH, so
  the copy `setup` provisioned and verified wins over a conflicting, older
  ambient install. Regression tests cover the preferred and PATH-fallback
  paths. Cross-platform confirmation pending.
- **P0 #51 — Non-destructive PID probes on Windows:** `streamer.pid_alive` no
  longer calls `os.kill(pid, 0)` on Windows, where that would terminate the
  process; it queries a `PROCESS_QUERY_LIMITED_INFORMATION` handle instead.
  POSIX keeps the existence probe. A regression test proves `os.kill` is not
  reached on the Windows path. Confirmation on a real Windows host pending.
- **P0 #53 — Manual target entry is locked during playback:** `_add_cast_target`
  now applies the dropdown's ownership rule. While a session is live or a cast
  is starting, entering another IPv4 (via Return or Add IP) remembers the
  target without changing the active device, so Stop still targets the playing
  TV; both inputs switch devices normally when idle. Source-level regression
  test in `tests/test_player_action_safety.py`. Real-receiver confirmation
  pending.
- **P0 #56 — Idle Stop is harmless:** `stop_stream` now returns before any
  receiver command when no session or external playback is owned and the
  observed device state is idle/offline/unknown, so the shortcut or action
  invoked before the first poll cannot stop another app's cast. Stopping a
  local preview still affects only the preview. Source-level regression test
  in `tests/test_player_action_safety.py`. Real-receiver confirmation pending.
- **P0 #16 — Subtitle encoding detection:** code, regression tests and user
  documentation pushed. Bounded UTF-8/UTF-16/Windows-1252 SRT detection,
  read-only originals, private UTF-8 staging for receiver and burn-in,
  invalid-file rejection, and crash cleanup. Integration test with FFmpeg
  pending a successful media-runtime CI job. Not yet marked completed.
- **P2 #47 — Encoder dry-run preflight:** code, regression tests and user
  documentation pushed. Unknown MKVs render a private 0.8-second H.264/AAC
  sample and verify actual frames *before* stopping an active receiver;
  checks are cached per file/track fingerprint. Media-runtime CI still
  pending. This tests local software decoders, not hardware receiver models.
  Not yet marked completed.
- **P0 #13 — Multi-audio-track picker:** implemented and under CI verification.
  FFprobe lists language, title, codec and channel layout; selected 0:a:N
  is persisted per film, survives HLS software fallback and seek restart,
  and can be changed while casting. Requires a physical receiver and
  multilingual MKV smoke test before marking it fully done.
- **P2 #46 — Bounded diagnostic bundle:** delivered as `smoothcast --diagnostics
  [PATH]` (GTK-free, also on `./smoothcast`) and the app menu **Save
  diagnostics…**. `src/diagnostics.py` collects version/tool/log/settings
  detail, masks LAN IPs, reduces absolute paths and the home directory, redacts
  credential keys, bounds the log tail and size (256 KiB) and writes owner-only
  (0600) JSON atomically. Tests: `tests/test_diagnostics.py`. GUI wiring still
  needs a real-desktop spot check.
- **Queue search:** delivered independently of this revised 50-item list;
  Ctrl+F filters filename/folder terms without changing playback order.

## Delivery criteria

A proposal is **done** only when its behaviour is implemented, source-level and
runtime tests cover the positive and failure paths, user instructions are
updated, and required hardware claims have been validated on actual devices.
Do not convert this list into unchecked feature claims or increase the release
version for every intermediate fix.
