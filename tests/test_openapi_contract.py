"""#434: the OpenAPI description stays in step with the portal's routes."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api_spec
from test_room_conformance import RoomHarness

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("portal.py", "portal_screens_http.py", "portal_mesh_http.py")


def source_routes() -> set[str]:
    found = set()
    for name in SOURCES:
        text = (ROOT / "src" / name).read_text(encoding="utf-8")
        for match in re.finditer(
                r'''["'`](\^?/(?:api|mesh)/[^"'`\s?\\)]*|/screen|/nodes|/silence\.wav)''', text):
            found.add(re.split(r"\(", match.group(1).lstrip("^"))[0])
    return found


def spec_regex(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", re.escape(path).replace(r"\{", "{")
                                   .replace(r"\}", "}")) + "$")


def test_every_route_in_the_portal_source_is_documented():
    paths = list(api_spec.PATHS)
    undocumented = []
    for lit in sorted(source_routes()):
        ok = any(spec_regex(p).match(lit) or p.startswith(lit) for p in paths)
        if not ok:
            undocumented.append(lit)
    assert not undocumented, f"add these routes to src/api_spec.py: {undocumented}"


def test_every_documented_route_still_exists_in_the_source():
    literals = source_routes()
    missing = []
    for path in api_spec.PATHS:
        prefix = path.split("{")[0]
        if not any(lit.startswith(prefix) or prefix.startswith(lit) for lit in literals):
            missing.append(path)
    assert not missing, f"documented but not routed: {missing}"


def test_spec_is_well_formed():
    spec = api_spec.spec()
    assert spec["openapi"].startswith("3.1") and spec["info"]["version"] == api_spec.API_VERSION
    schemas = spec["components"]["schemas"]
    for path, methods in spec["paths"].items():
        declared = set(re.findall(r"\{([^}]+)\}", path))
        for method, op in methods.items():
            assert method in {"get", "post", "put", "delete", "head"}
            assert op["summary"] and op["responses"] and "security" in op
            names = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
            assert declared <= names, (path, method)
            ref = op.get("requestBody", {}).get("content", {}).get("application/json", {}) \
                .get("schema", {}).get("$ref")
            if ref:
                assert ref.rsplit("/", 1)[1] in schemas


def test_docs_file_matches_the_module():
    assert (ROOT / "docs/api/openapi.json").read_text(encoding="utf-8") == api_spec.dumps(), \
        "regenerate: PYTHONPATH=src python3 -c \"import api_spec;open('docs/api/openapi.json','w').write(api_spec.dumps())\""


def test_portal_serves_the_document_without_a_session():
    harness = RoomHarness(count=1)
    try:
        status, body, _ = harness.request("GET", "/api/openapi.json")
        assert status == 200 and body == json.loads(api_spec.dumps())
    finally:
        harness.close()
