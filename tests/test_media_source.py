import os

import pytest

import media_source as ms


def test_valid_upload_resolves(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    assert ms.upload_source(tmp_path, "a.mp4") == (tmp_path / "a.mp4").resolve()


@pytest.mark.parametrize("name", ["", ".", "..", "../a.mp4", "sub/a.mp4", "a\\b", "a\0b"])
def test_upload_names_with_separators_or_dots_are_refused(tmp_path, name):
    with pytest.raises(ms.SourceError):
        ms.upload_source(tmp_path, name)


def test_dotdot_traversal_is_refused(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("s")
    with pytest.raises(ms.SourceError):
        ms.resolve_under(root, root / ".." / "secret.txt")


def test_symlink_escape_is_refused(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("s")
    os.symlink(tmp_path / "secret.txt", root / "link.mp4")
    with pytest.raises(ms.SourceError):
        ms.upload_source(root, "link.mp4")


def test_directories_and_missing_files_are_refused(tmp_path):
    (tmp_path / "d").mkdir()
    for name in ("d", "nope.mp4"):
        with pytest.raises(ms.SourceError):
            ms.upload_source(tmp_path, name)


def test_missing_root_is_503_and_library_not_found_is_404(tmp_path):
    with pytest.raises(ms.SourceError) as e:
        ms.upload_source(None, "a.mp4")
    assert e.value.status == 503
    with pytest.raises(ms.SourceError) as e:
        ms.library_source([tmp_path], tmp_path / "gone.mp4")
    assert e.value.status == 404


def test_library_file_inside_any_root_resolves(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (b / "f.mkv").write_bytes(b"x")
    assert ms.library_source([a, b], b / "f.mkv") == (b / "f.mkv").resolve()
