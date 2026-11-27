# Browser upload transfer architecture (#568)

Source of truth: `src/portal_uploads.py` (`UploadManager`). Tests:
`tests/test_portal_upload_durability.py`, `tests/test_portal_uploads.py`.

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
- **Coalesced checkpoint.** `fsync` runs when `received - committed >=
  CHECKPOINT_BYTES` (16 MiB) or `CHECKPOINT_SECONDS` (5 s) have elapsed, instead
  of after every chunk. Finalize always fsyncs the file and then the directory
  entry before the upload is reported complete.
- **Retry and rollback.** A failed or disconnected chunk is truncated back to its
  starting offset, so the browser can resend it. A lost acknowledged prefix is
  rejected rather than zero-filled.
- **Crash recovery.** After a process crash, resume from `committed`, never from
  `received`: bytes past it were volatile. Network resume without a crash may use
  `received`.

## Trade-offs

Coalescing trades up to one checkpoint window (16 MiB / 5 s) of re-sent bytes
after a crash for far fewer fsyncs. Durability is never claimed for volatile
bytes. Throughput and fsync-count measurements for the old per-chunk policy
versus coalescing are not yet published (UNVERIFIED); do not cite a speedup
until a 100 MiB localhost/RAM-backed comparison is recorded here.
