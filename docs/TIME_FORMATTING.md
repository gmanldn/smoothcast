# Playback time display contract

Human-visible playback positions, durations and queue/network activity use
`m:ss` below one hour (e.g. `0:05`, `59:59`) and `h:mm:ss` from one
hour (`1:00:00`, `2:05:00`). Only seconds and the minute component of an
hours display are zero-padded. Unknown or non-finite values are `--:--`.
Negative source positions clamp to zero. Remaining time adds `-` to a known
display time. Python's authority is `castctl.fmt_time`, with a matching
`clock` in the embedded web client; `tests/test_display_time.py` validates
their shared vectors, executing JavaScript with Node when available.

The DLNA/UPnP AVTransport `HH:MM:SS` timestamp is a *wire protocol* and
must retain its separate protocol formatter. MPRIS positions and lengths are
numeric microseconds; neither should be converted to display strings.
