# Local media-library index

SmoothCast can build a **local, private SQLite index** of media you explicitly
choose. This is a headless facility: indexing does not open GTK, discover a
Chromecast, scan the LAN or download subtitles or other content.

Use the installed command or run the same parser with
`python3 -m library_index` from a Python environment containing SmoothCast:

```sh
smoothcast --library-index scan ~/Videos
smoothcast --library-index scan ~/Videos --probe
smoothcast --library-index list --limit 50
smoothcast --library-index list --limit 50 --offset 50
smoothcast --library-index --db /tmp/my-media.sqlite3 scan ~/Films
```

The default private database is
`$XDG_CACHE_HOME/smoothcast/library.sqlite3` if XDG_CACHE_HOME is set,
otherwise `~/.cache/smoothcast/library.sqlite3`. The index stores local
absolute file paths, byte size, modification time, device and inode, streamed
**full SHA-256 hashes**, and optionally codec/duration/video geometry metadata.
Treat this private cache as personal data; do not attach it to support reports.
On POSIX, newly created cache directories use mode 0700 and SQLite files are
kept at 0600; database symlinks and nonregular destinations are rejected.

First scans hash supported media files (.mkv, .mp4, .mov, .avi, .webm, .m4v,
.ts, .mpeg, .mpg, .wmv) in fixed 1 MiB chunks. Subsequent scans reuse a digest
when stat identity/size/time are unchanged. Overlapping authorised roots have
independent records. Full rescans prune disappeared entries **only** if
enumeration succeeded completely. A capped scan, missing permissions or a
changing file cannot delete old records.

Limits default to 10,000 media files, 10,000 directories and 16 nested levels.
Change with `--max-files`, `--max-dirs` and `--max-depth`. If any limit is
reached, the command exits nonzero and retains existing records. No recursive
symlinks are followed, nonregular media cannot be hashed, and race checks are
applied to file descriptors when the platform supports `O_NOFOLLOW`.

`--probe` is explicit and optional: it runs **local-only** FFprobe (if
installed) with network protocols disabled, a 12-second per-file timeout and
bounded output. Failure does not discard the content hash and is retried on
future explicit probes. Without `--probe`, Python alone is sufficient.
The GUI's existing file chooser and watch history remain independent; this
ticket adds an index and inspection command, not a new automatic media watcher.

Results are JSON. `complete=false` means the scan did not cover every
directory or file; `errors`, `hashed`, `reused`, `removed` and `probed`
explain what happened. The `list` command reads at most 1,000 rows per
request (100 by default), so even a very large index is paginated.

Verification: `python3 -m pytest -q tests/test_library_index.py` and
`python3 -m compileall -q src`. The tests exercise streamed hashing,
permission failures, symlink safety, incremental cache reuse, removal,
overlapping roots, FFprobe isolation and GTK-free entry points.
