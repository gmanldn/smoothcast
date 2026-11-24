"""Pure checks for the WiX authoring (#531): ids, versions, scope and forbidden constructs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "packaging"))
import wix_payload as wx  # noqa: E402

NS = {"w": wx.WIX_NS}
PRODUCT = ROOT / "packaging" / "windows" / "Product.wxs"


def manifest(tmp_path, paths, platform="windows-x64"):
    target = tmp_path / "payload-manifest.json"
    target.write_text(json.dumps({"platform": platform, "files": [{"path": p} for p in paths]}), encoding="utf-8")
    return target


BASE = ["SmoothCast.exe", "SmoothCastCLI.exe", "_internal/base_library.zip", "_internal/gi/Gtk-4.0.typelib"]


def test_msi_version_has_three_bounded_fields():
    assert wx.msi_version("2.0.30") == "2.0.30"
    for bad in ("2.0", "2.0.30.1", "256.0.0", "1.256.0", "1.0.65536", "a.b.c", "", "1.0.-1", "2.0.30-rc1"):
        with pytest.raises(wx.WixError):
            wx.msi_version(bad)
    assert wx.msi_version("255.255.65535") == "255.255.65535"


def test_component_identity_depends_only_on_the_path():
    first = wx.render(sorted(BASE))
    assert wx.render(sorted(BASE)) == first
    assert wx.render(sorted([*BASE, "_internal/extra.dll"])).count("<Component ") == len(BASE) + 1
    ids = re.findall(r'<Component Id="(C_[0-9a-f]{24})" Guid="([0-9A-F-]{36})"', first)
    assert len(ids) == len(BASE) == len({i for i, _ in ids}) == len({g for _, g in ids})
    # Adding a file never renames or re-keys an existing one (upgrade stability).
    grown = wx.render(sorted([*BASE, "aaa.dll"]))
    assert all(f'<Component Id="{i}" Guid="{g}"' in grown for i, g in ids)
    # Case differences in a path do not change identity on a case-insensitive file system.
    assert wx.component_guid("SmoothCast.exe") == wx.component_guid("smoothcast.EXE")


def test_known_guid_is_pinned_so_the_namespace_is_never_changed_by_accident():
    assert wx.component_guid("SmoothCast.exe") == "BC283F68-5DAD-5478-AB6C-365212DF19E8"
    assert str(wx.COMPONENT_NAMESPACE) == "6f1c2f0e-83a5-4d1e-9b6e-5f2a0c3d7b41"


def test_generated_fragment_is_wellformed_and_maps_every_file(tmp_path):
    paths = wx.load_files(manifest(tmp_path, ["_internal/ü x/données.dll", *BASE]))
    root = ET.fromstring(wx.render(paths))
    assert root.tag == f"{{{wx.WIX_NS}}}Wix"
    sources = sorted(f.get("Source") for f in root.iter(f"{{{wx.WIX_NS}}}File"))
    assert sources == sorted("$(PayloadDir)\\" + p.replace("/", "\\") for p in paths)
    refs = {r.get("Id") for r in root.iter(f"{{{wx.WIX_NS}}}ComponentRef")}
    assert refs == {c.get("Id") for c in root.iter(f"{{{wx.WIX_NS}}}Component")}
    names = {d.get("Name") for d in root.iter(f"{{{wx.WIX_NS}}}Directory")}
    assert {"_internal", "ü x", "gi"} <= names


@pytest.mark.parametrize("bad", ["../evil.dll", "/abs.dll", "a\\b.dll", "a//b.dll", "a/./b.dll", "x/..", "C:/x.dll",
                                 "a/b?.dll", "trailing./x.dll", " lead/x.dll", "nul\x00.dll", ""])
def test_unsafe_paths_are_rejected(tmp_path, bad):
    with pytest.raises(wx.WixError):
        wx.load_files(manifest(tmp_path, [*BASE, bad]))


def test_collisions_missing_exes_and_wrong_platform_are_rejected(tmp_path):
    with pytest.raises(wx.WixError, match="collides"):
        wx.load_files(manifest(tmp_path, [*BASE, "SMOOTHCAST.EXE"]))
    with pytest.raises(wx.WixError, match="SmoothCastCLI.exe is missing"):
        wx.load_files(manifest(tmp_path, ["SmoothCast.exe"]))
    with pytest.raises(wx.WixError, match="windows-x64"):
        wx.load_files(manifest(tmp_path, BASE, platform="linux"))
    with pytest.raises(wx.WixError, match="unreadable"):
        wx.load_files(tmp_path / "missing.json")


def test_cli_writes_the_fragment_or_fails_clearly(tmp_path, capsys):
    out = tmp_path / "build" / "msi" / "Payload.wxs"
    assert wx.main(["--manifest", str(manifest(tmp_path, BASE)), "--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("<?xml")
    assert wx.main(["--manifest", str(manifest(tmp_path, ["x.dll"])), "--output", str(out)]) == 1
    assert "cannot author the installer" in capsys.readouterr().err


def _product():
    return ET.parse(PRODUCT).getroot()


def test_product_is_a_perUser_x64_package_with_a_permanent_upgrade_code():
    package = _product().find("w:Package", NS)
    assert package.get("Scope") == "perUser"
    assert package.get("Manufacturer") == "$(Manufacturer)"      # owner supplies it; never invented here
    assert package.get("Version") == "$(ProductVersion)"
    assert re.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", package.get("UpgradeCode"))
    assert package.get("UpgradeCode") == "105B2A4E-3854-4080-A3D7-417F855E205A"
    assert package.find("w:MajorUpgrade", NS) is not None
    conditions = [c.get("Condition") for c in package.findall("w:Launch", NS)]
    assert "VersionNT64" in conditions


def test_product_installs_only_under_the_users_profile_with_one_shortcut():
    text = PRODUCT.read_text(encoding="utf-8")
    root = _product()
    standard = [d.get("Id") for d in root.iter(f"{{{wx.WIX_NS}}}StandardDirectory")]
    assert standard == ["LocalAppDataFolder", "ProgramMenuFolder"]
    assert "ProgramFiles" not in text and "Root=\"HKLM\"" not in text and "ALLUSERS" not in text
    assert [r.get("Root") for r in root.iter(f"{{{wx.WIX_NS}}}RegistryValue")] == ["HKCU"]
    shortcuts = list(root.iter(f"{{{wx.WIX_NS}}}Shortcut"))
    assert len(shortcuts) == 1 and shortcuts[0].get("Target") == "[INSTALLFOLDER]SmoothCast.exe"


@pytest.mark.parametrize("element", ["CustomAction", "ServiceInstall", "ServiceControl", "ScheduledTask", "FirewallException",
                                      "Environment", "ProgId", "Extension", "Verb", "Class", "Bundle", "Run", "Binary"])
def test_product_has_no_custom_actions_services_associations_or_environment_changes(element):
    assert not list(_product().iter(f"{{{wx.WIX_NS}}}{element}"))
    assert f"<{element}" not in PRODUCT.read_text(encoding="utf-8")


def test_the_generated_fragment_supplies_what_product_references(tmp_path):
    root = ET.fromstring(wx.render(wx.load_files(manifest(tmp_path, BASE))))
    groups = {g.get("Id") for g in root.iter(f"{{{wx.WIX_NS}}}ComponentGroup")}
    refs = {r.get("Id") for r in _product().iter(f"{{{wx.WIX_NS}}}ComponentGroupRef")}
    assert refs <= groups
    assert {d.get("Id") for d in _product().iter(f"{{{wx.WIX_NS}}}Directory")} >= {"INSTALLFOLDER"}
