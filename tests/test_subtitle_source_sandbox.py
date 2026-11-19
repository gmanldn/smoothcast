"""SC-049: hostile caption source and parser regressions, no GUI or FFmpeg."""
from __future__ import annotations

import os
from pathlib import Path
import random
import tempfile
from unittest import mock

import pytest
import subtitle_encoding


CAPTION = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"


def test_symlink_to_regular_caption_is_rejected_without_modifying_prior_output(tmp_path):
    secret = tmp_path / "private-user-data.txt"
    secret.write_bytes(CAPTION)
    alias = tmp_path / "sneaky.srt"
    try:
        alias.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is restricted on this platform")
    dest = tmp_path / "private" / "staged.srt"
    dest.parent.mkdir()
    dest.write_bytes(b"previous good output")
    with pytest.raises(subtitle_encoding.SubtitleEncodingError, match="symlink"):
        subtitle_encoding.stage_srt(alias, dest)
    assert dest.read_bytes() == b"previous good output"
    assert not list(dest.parent.glob(".smoothcast-srt-*"))


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "mkfifo"),
                    reason="FIFO is POSIX-specific")
def test_fifo_cannot_block_srt_staging_or_overwrite_destination(tmp_path):
    fifo = tmp_path / "blocking.srt"
    os.mkfifo(fifo)
    dest = tmp_path / "staged.srt"
    dest.write_bytes(b"valid previous captions")
    # O_NONBLOCK lets us open the FIFO, then descriptor fstat rejects it.
    with pytest.raises(subtitle_encoding.SubtitleEncodingError, match="regular file"):
        subtitle_encoding.stage_srt(fifo, dest)
    assert dest.read_bytes() == b"valid previous captions"


def test_actual_descriptor_checked_and_input_length_is_bounded(tmp_path):
    input_path = tmp_path / "captions.srt"
    input_path.write_bytes(CAPTION)
    output = tmp_path / "private" / "captions.srt"
    original_open = subtitle_encoding.os.open
    flags_seen = []

    def capture_open(path, flags, *args, **kwargs):
        flags_seen.append(flags)
        return original_open(path, flags, *args, **kwargs)

    with mock.patch.object(subtitle_encoding.os, "open", side_effect=capture_open):
        staged, codec = subtitle_encoding.stage_srt(input_path, output)
    assert staged.read_bytes() == CAPTION
    assert codec == "utf-8"
    assert flags_seen[0] & os.O_RDONLY == 0  # O_RDONLY is zero on POSIX
    if hasattr(os, "O_NOFOLLOW"):
        assert flags_seen[0] & os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        assert flags_seen[0] & os.O_NONBLOCK


def test_oversized_regular_source_is_rejected_before_copy(tmp_path):
    src = tmp_path / "oversized.srt"
    with src.open("wb") as handle:
        handle.truncate(subtitle_encoding.MAX_SUBTITLE_BYTES + 1)
    target = tmp_path / "captions.srt"
    target.write_bytes(b"existing")
    with pytest.raises(subtitle_encoding.SubtitleEncodingError, match="16 MiB"):
        subtitle_encoding.stage_srt(src, target)
    assert target.read_bytes() == b"existing"


def test_zero_byte_and_binary_source_leave_staged_file_untouched(tmp_path):
    src = tmp_path / "broken.srt"
    target = tmp_path / "captions.srt"
    target.write_bytes(b"existing")
    for data in (b"", b"\x00\x01\x02", b"not subtitle cues"):
        src.write_bytes(data)
        with pytest.raises(subtitle_encoding.SubtitleEncodingError):
            subtitle_encoding.stage_srt(src, target)
        assert target.read_bytes() == b"existing"
        assert not list(tmp_path.glob(".smoothcast-srt-*"))


def test_malformed_srt_parser_corpus_is_bounded_without_undecodable_output():
    rng = random.Random(54049)
    for size in range(0, 513, 7):
        payload = bytes(rng.randrange(256) for _ in range(size))
        try:
            result, codec = subtitle_encoding.decode_srt(payload)
        except subtitle_encoding.SubtitleEncodingError:
            continue
        assert codec in {"utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252"}
        assert 0 < len(result) <= subtitle_encoding.MAX_SUBTITLE_BYTES
        result.decode("utf-8", errors="strict")


def test_input_source_does_not_change_during_atomic_stage(tmp_path):
    src = tmp_path / "original.srt"
    src.write_bytes(CAPTION)
    dest = tmp_path / "private" / "copy.srt"
    subtitle_encoding.stage_srt(src, dest)
    assert src.read_bytes() == CAPTION
    assert dest.read_bytes() == CAPTION
    if os.name != "nt":
        assert dest.stat().st_mode & 0o777 == 0o600
