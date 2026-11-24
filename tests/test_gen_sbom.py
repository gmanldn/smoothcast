"""#218: deterministic CycloneDX SBOM and licence allow-list gate (stdlib only)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gen_sbom", ROOT / "scripts" / "ci" / "gen_sbom.py")
gs = importlib.util.module_from_spec(spec)
sys.modules["gen_sbom"] = gs
spec.loader.exec_module(gs)  # type: ignore[union-attr]

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason="needs tomllib")


def pkg(name, version="1.0", licences=("MIT",), requires=()):
    return gs.Package(name, version, tuple(licences), tuple(requires))


def fake(*packages):
    table = {p.name: p for p in packages}
    return lambda name: table.get(name)


def test_closure_follows_transitive_requirements_sorted():
    provider = fake(pkg("a", requires=["b"]), pkg("b", requires=["c"]), pkg("c"), pkg("z"))
    assert list(gs.closure(["a"], provider)) == ["a", "b", "c"]


def test_missing_root_is_an_error_but_missing_transitive_is_tolerated():
    with pytest.raises(gs.IncompleteEnvironment):
        gs.closure(["ghost"], fake())
    assert list(gs.closure(["a"], fake(pkg("a", requires=["optional-on-this-os"])))) == ["a"]


def test_cycles_terminate():
    provider = fake(pkg("a", requires=["b"]), pkg("b", requires=["a"]))
    assert list(gs.closure(["a"], provider)) == ["a", "b"]


def test_sbom_shape_and_determinism():
    packages = gs.closure(["a"], fake(pkg("a", "2.1", requires=["b"]), pkg("b", "0.3")))
    first = gs.build_sbom("smoothcast", "9.9.9", packages)
    second = gs.build_sbom("smoothcast", "9.9.9", packages)
    assert first == second and first["serialNumber"].startswith("urn:uuid:")
    assert first["bomFormat"] == "CycloneDX" and first["specVersion"] == "1.5"
    assert [c["purl"] for c in first["components"]] == ["pkg:pypi/a@2.1", "pkg:pypi/b@0.3"]
    root = first["metadata"]["component"]["bom-ref"]
    graph = {d["ref"]: d["dependsOn"] for d in first["dependencies"]}
    assert graph[root] == ["pkg:pypi/a@2.1"]            # b is reached only through a
    assert graph["pkg:pypi/a@2.1"] == ["pkg:pypi/b@0.3"]
    other = gs.build_sbom("smoothcast", "9.9.9", gs.closure(["a"], fake(pkg("a", "2.2"))))
    assert other["serialNumber"] != first["serialNumber"]
    json.dumps(first)                                    # serialisable


def test_no_wallclock_or_host_data_in_the_document():
    text = json.dumps(gs.build_sbom("x", "1", {"a": pkg("a")}))
    assert "timestamp" not in text and "/home" not in text


@pytest.mark.parametrize("raw, expected", [
    ("MIT License", "MIT"), ("  The  MIT   License ", "MIT"),
    ("Apache Software License", "Apache-2.0"), ("BSD License", "BSD-3-Clause"),
    ("Something Custom", "Something Custom"),
])
def test_licence_normalisation(raw, expected):
    assert gs.normalise_licence(raw) == expected


def test_licence_gate_flags_unknown_and_copyleft():
    packages = {
        "ok": pkg("ok", licences=["MIT"]),
        "gpl": pkg("gpl", "3", licences=["GPL-3.0-only"]),
        "mystery": pkg("mystery", licences=["UNKNOWN"]),
    }
    problems = gs.licence_violations(packages)
    assert len(problems) == 2
    assert any("gpl 3" in p for p in problems) and any("mystery" in p for p in problems)
    assert gs.licence_violations({"ok": packages["ok"]}) == []


def test_cli_exit_codes_and_output(tmp_path, capsys):
    good = fake(*(pkg(n) for n in gs.runtime_requirements(ROOT / "pyproject.toml")))
    out = tmp_path / "sbom.json"
    assert gs.main(["--check-licences", "-o", str(out)], provider=good) == 0
    assert json.loads(out.read_text())["components"]
    bad = fake(*(pkg(n, licences=["GPL-3.0-only"])
                 for n in gs.runtime_requirements(ROOT / "pyproject.toml")))
    assert gs.main(["--check-licences"], provider=bad) == 1
    assert gs.main([], provider=fake()) == 2
    assert "not installed" in capsys.readouterr().err


def test_runtime_requirements_match_pyproject_and_exclude_dev_tools():
    names = gs.runtime_requirements(ROOT / "pyproject.toml")
    assert {"catt", "pychromecast", "psutil", "segno", "zeroconf"} <= set(names)
    assert "pytest" not in names and "ruff" not in names


def test_app_version_reads_the_single_authoritative_version():
    import version
    assert gs.app_version() == version.__version__


class _Meta(dict):
    def get_all(self, key):
        return self.get("_all", {}).get(key)


def test_metadata_licence_precedence_and_generic_classifier_is_ignored():
    expr = _Meta({"License-Expression": "MIT OR Apache-2.0"})
    assert gs._licences_from(expr) == ("Apache-2.0", "MIT")
    classified = _Meta({"_all": {"Classifier": [
        "License :: OSI Approved :: BSD License", "License :: Other/Proprietary License"]}})
    assert gs._licences_from(classified) == ("BSD-3-Clause",)
    assert gs._licences_from(_Meta({"License": "UNKNOWN"})) == ("UNKNOWN",)
    assert gs._licences_from(_Meta({"License": "x" * 500})) == ("UNKNOWN",)


def test_overrides_are_few_and_allow_listed():
    assert set(gs.LICENCE_OVERRIDES.values()) <= gs.ALLOWED_LICENCES
    assert len(gs.LICENCE_OVERRIDES) <= 3
