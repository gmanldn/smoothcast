"""Headless regressions for the identity of pre-probed queue files."""
import os

import queue_metadata as qm


def test_atomic_replacement_with_preserved_size_and_mtime(tmp_path):
    path = tmp_path / "film.mkv"
    path.write_bytes(b"old")
    before = path.stat()
    old = object()
    fresh = object()
    fingerprint = qm.file_fingerprint(path)
    cache = {str(path): (fingerprint, old)}
    assert qm.cached_media(cache, path) is old
    assert qm.media_for_cast(cache[str(path)], path, lambda _: fresh) == (old, fingerprint)

    replacement = tmp_path / "new.mkv"
    replacement.write_bytes(b"new")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert qm.cached_media(cache, path) is None
    assert qm.media_for_cast(cache[str(path)], path, lambda _: fresh) == (fresh, None)
    published = {}
    qm.publish_media(published, [str(path)], {str(path): qm.MediaProbe(fingerprint, old)})
    assert not published


def test_missing_identity_is_never_a_cache_hit(tmp_path):
    path = tmp_path / "missing.mkv"
    old = object()
    fresh = object()
    cache = {str(path): (None, old)}
    assert qm.cached_media(cache, path) is None
    assert qm.media_for_cast(cache[str(path)], path, lambda _: fresh) == (fresh, None)
    published = {}
    qm.publish_media(published, [str(path)], {str(path): qm.MediaProbe(None, old)})
    assert not published
