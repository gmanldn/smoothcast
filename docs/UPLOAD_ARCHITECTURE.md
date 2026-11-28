# Browser upload transfer architecture (#568)

Source of truth: `src/portal_uploads.py` (`UploadManager`). Tests:
`tests/test_portal_upload_durability.py`, `tests/test_portal_uploads.py`, and
`tests/test_portal_upload_faults.py`.

## Contract

- **Sequential, owner-bound uploads.** One writer per file; chunks must start at
  the current `received` offset. Gaps and overlaps are rejected. At most
  `MAX_ACTIVE_UPLOADS` (3) run at once; disk quota and `MIN_FREE_BYTES` apply.
- **Chunks.** The server advertises `chunk_size` (`CHUNK_SIZE`, 8 MiB). A request
  is read in `READ_SIZE` (64 KiB) blocks so RAM stays bounded and the GTK thread
  is never involved.
- **Two offsets.** `received` counts bytes written to the file; `committed`
  counts bytes made durable by `fsync`. Both are reported in status responses.
  Clients that only read `received` keep working unchanged.
- **Coalesced checkpoint.** At the end of an accepted chunk, `fsync` runs
  once the unsynced prefix reaches 16 MiB or 5 s have elapsed since the last
  checkpoint. Finalization syncs any remaining unsynced bytes. A successful
  final rename is followed by a directory sync on Linux before finalization
  returns. A progressive cast can retain the original path.
- **Retry and rollback.** Short or disconnected chunks are truncated back to
  their starting offset for retry. If checkpoint sync fails after a full write,
  the file rolls back but the reported received offset can stay ahead, blocking
  that retry. A lost acknowledged prefix is rejected to avoid zero-filled data.
- **Resume.** While the host process is running, the browser can resume at
  `received`. After a restart, the host has no record of the session, even if
  the partial file and some synced bytes still exist. The browser must start a
  new upload. Crash-safe resume requires persisting the session owner, file
  identity and committed offset together, then recovering only that prefix.
- **Chunk sizing.** The current server limit is fixed at 8 MiB. Adaptive
  negotiation from measured network and device capacity remains open in #568.

## 100 MiB RAM-backed comparison (27 Nov 2026)

Five runs per policy on Linux tmpfs (`/dev/shm`), with order alternated.
Both policies used the same `UploadManager.append` and `finalize` code,
8 MiB chunks, in-memory input, and real counted `os.fsync` calls.
The per-chunk comparison set the checkpoint threshold to one byte. The
coalesced runs used the default 16 MiB / 5 s thresholds. The benchmark
disabled early cast, made no receiver request and verified the final SHA-256
in each run. Transfer timing includes finalization and excludes the digest
check. The table reports medians across runs, including the median of each
run's nearest-rank p95 append time.

| Policy | MiB/s | Process CPU (ms) | fsync calls | p95 append (ms) |
| --- | ---: | ---: | ---: | ---: |
| Per chunk | 974.20 | 96.63 | 14 | 11.48 |
| Coalesced | 744.92 | 99.65 | 8 | 17.06 |

Coalescing saved six sync calls per transfer. The RAM-backed runs showed
lower throughput and higher append latency for coalescing. Disk-backed
throughput and browser/LAN performance remain unmeasured.
