"""Portable Windows path alias regressions for WiX authoring (#531)."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "packaging"))
import wix_payload as wx  # noqa: E402


@pytest.mark.parametrize("paths", [
    ["_internal/GTK/a.dll", "_internal/gtk/b.dll"],
    ["a", "a/b.dll"],
    ["a/b.dll", "A"],
    ["abc.dll", "ABC.dll"],
    ["abc.dll", "abc.dll"],
    ["CON.dll"],
    ["dir/NUL.txt"],
    ["COM¹.bin"],
    ["LPT9/child.dll"],
    ["PRN .dll"],
    [None],
])
def test_invalid_paths_rejected_by_both_public_entrypoints(tmp_path, paths):
    paths = ["SmoothCast.exe", "SmoothCastCLI.exe", *paths]
    manifest = tmp_path / "payload.json"
    manifest.write_text(json.dumps({"platform": "windows-x64",
                                    "files": [{"path": p} for p in paths]}), encoding="utf-8")
    with pytest.raises(wx.WixError):
        wx.load_files(manifest)
    with pytest.raises(wx.WixError):
        wx.render(paths)


def test_valid_shared_directory_preserves_all_components():
    result = wx.render(["_internal/GTK/a.dll", "_internal/GTK/b.dll", "COM10.dll"])
    assert result.count("<Component ") == 3
    assert result.count('Name="GTK"') == 1


@pytest.mark.parametrize("value", ["2.1.0\n", "٢.١.٠"])
def test_msi_version_requires_ascii_and_exact_end(value):
    with pytest.raises(wx.WixError):
        wx.msi_version(value)
