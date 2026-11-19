"""Report-a-problem flow (issue #274): URL builder, template and menu wiring.

Pure string/AST assertions: no GTK, no browser, no network, nothing is sent.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import issue_report as ir
from gui_source import combined_source


def query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_url_targets_the_repo_template_and_prefills_only_version_and_os():
    url = ir.report_url("v1.0.59", "Linux 6.12 x86_64, Python 3.13.5")
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "github.com", "/gmanldn/smoothcast/issues/new")
    assert query(url) == {"template": "bug-report.yml", "title": "[Bug] ",
                          "version": "v1.0.59", "platform": "Linux 6.12 x86_64, Python 3.13.5"}


def test_fields_are_sanitised_and_bounded():
    q = query(ir.report_url("v1\n<script>&x=1", "A" * 5000 + "\x00"))
    assert "\n" not in q["version"] and "<" not in q["version"] and "&" not in q["version"]
    assert len(q["platform"]) <= ir.MAX_FIELD
    assert query(ir.report_url("", ""))["version"] == "unknown"
    assert query(ir.report_url("", ""))["platform"] == "unknown"


def test_no_paths_addresses_or_home_directory_leak_into_the_url():
    url = ir.report_url("v1.0.59")
    assert "/home/" not in url and "192.168" not in url and "@" not in url
    assert len(url) <= ir.MAX_URL


def test_platform_label_is_coarse_and_single_line():
    label = ir.platform_label()
    assert label and "\n" not in label and "Python" in label


def test_template_exists_with_the_prefilled_field_ids():
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / ir.TEMPLATE).read_text()
    ids = re.findall(r"^\s+id: (\w+)$", text, flags=re.M)
    assert {"version", "platform", "what", "diagnostics"} <= set(ids)
    assert "title: \"[Bug] \"" in text
    # Blank issues are disabled, which is why a template is mandatory.
    assert "blank_issues_enabled: false" in (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text()


def test_menu_action_and_handler_are_wired_without_sending_anything():
    source = combined_source()
    assert 'help_menu.append("Report a problem…", "app.report-problem")' in source
    assert 'simple("report-problem", lambda *a: self._window().action_report_problem())' in source
    handler = source.split("def action_report_problem", 1)[1].split("\n    def ", 1)[0]
    assert "issue_report.report_url(version.label())" in handler
    assert "launch_default_for_uri" in handler
    assert not re.search(r"urlopen|requests|HTTPConnection|diagnostics\.export", handler)


def test_module_is_registered_for_installs():
    assert '"issue_report"' in (ROOT / "pyproject.toml").read_text()
