# Receiver playback learning (#514)

SmoothCast now uses **confirmed receiver outcomes**, not an assumed device model,
to avoid repeatedly attempting a direct stream the receiver has demonstrably
refused. This is a **preference hint**, never a substitute for the codec,
subtitle, audio, security and session-ownership checks.

## Exact decision rule

- A speculative direct cast is eligible only if the user's **Direct** setting,
  FFprobe's `media.direct_ok`, the active audio/subtitle settings, playback
  speed, rotation and aspect constraints already permit it.
- Two consecutive **confirmed rejected direct attempts** for the same receiver
  and codec signature prefer HLS next time. An attempt is *rejected* only after
  the bounded receiver probe observes three consecutive `IDLE` statuses.
- Three consecutive **confirmed accepted direct attempts** prefer direct play
  again. Only a matching title in actual receiver `PLAYING`/`PAUSED`
  status counts as acceptance. Unknown state, timeouts, errors, conflicting
  title and cancellation provide **no learning evidence**.
- If an identity is unavailable, continue existing behaviour.
- A user who explicitly disables Direct is never overridden. No learned
  recommendation permits playback of a codec the planner rejects.

`receiver_memory.should_try_direct` is pure except for a bounded local read.
All disk access and receiver-status probes occur on the existing background
cast worker, **never on the GTK main thread**. DLNA is unaffected.

## Stored data, limits and privacy

File: `<GLib user config directory>/cast-control/receiver_memory.json`.
For ordinary Linux, this is `~/.config/cast-control/receiver_memory.json`.
Keys are SHA-256 digests of a stable UUID or fallback receiver IP:port and of
container/codec/profile/bit-depth/audio/subtitle descriptors. No clear-text
receiver name, UUID, IP, film title, filesystem path or file metadata is
stored. Hashing is *pseudonymisation*, not complete anonymisation; the file
is owner-only and remains local. Diagnostics export **counts only**, not hashes.

Per receiver: at most **50 codec signatures**; per signature: latest **8**
outcomes; globally: at most **200 receivers**. Outcomes older than **90 days**
expire. The writer creates a private temporary file in the same directory,
flushes and `fsync`s it, then atomically replaces the store. Unknown schema,
corruption or oversized input is quarantined as `.corrupt` and treated as
no prior evidence. Failure to persist is not a reason to stop playback.

## Forget one receiver

From an installed terminal, without GTK, starting playback or network access:

```sh
smoothcast --forget-receiver --uuid 44ad6ed8-44de-48b9-959b-3e4cd075e234
smoothcast --forget-receiver --host 192.168.1.50 --port 8009
```

Use `--store PATH` for a non-default GLib/XDG config directory. This
deletes only the specified receiver's learned entries and does not affect any
ongoing cast. A missing record is a safe no-op.

## Evidence and present limitations

`tests/test_receiver_memory.py` covers fake Cast receivers, decisions,
identity independence, expiry, boundedness, corruption, atomic write failure,
concurrency, diagnostics privacy and the forget command. The fast CI syntax
job runs it. The workflow records a successful HLS outcome **only after**
`Session.start_transcode()` verifies the receiver is playing the actual
generation-specific HLS URL (via `_await_receiver`). FFmpeg or catt startup
alone is not success; failed/uncertain HLS is never learned. Exact H.264 level
is not exposed by `MediaInfo`; pixel format is included as a bit-depth
discriminator and hard codec checks still take precedence.

Do not expand the planner to override a hard rejection. Physical receiver
qualification remains in #208.
