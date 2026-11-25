"""Static MSI upgrade policy checks; native rollback remains a Windows CI gate."""
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {"w": "http://wixtoolset.org/schemas/v4/wxs"}


def _package():
    return ET.parse(ROOT / "packaging/windows/Product.wxs").getroot().find("w:Package", NS)


def test_old_version_removal_is_inside_the_install_transaction():
    upgrade = _package().find("w:MajorUpgrade", NS)
    assert upgrade.get("Schedule") == "afterInstallInitialize"
    assert upgrade.get("AllowSameVersionUpgrades") == "no"
    assert upgrade.get("DowngradeErrorMessage")


def test_equal_version_detection_preserves_existing_product_and_maintenance():
    package = _package()
    family = package.find("w:Upgrade", NS)
    assert family.get("Id") == package.get("UpgradeCode")
    rule = family.find("w:UpgradeVersion", NS)
    assert rule.attrib == {
        "Minimum": "$(ProductVersion)", "Maximum": "$(ProductVersion)",
        "IncludeMinimum": "yes", "IncludeMaximum": "yes", "OnlyDetect": "yes",
        "Property": "SMOOTHCAST_SAME_VERSION",
    }
    conditions = {c.get("Condition"): c.get("Message") for c in package.findall("w:Launch", NS)}
    assert conditions["Installed OR NOT SMOOTHCAST_SAME_VERSION"]
