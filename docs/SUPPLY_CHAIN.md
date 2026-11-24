# Supply chain (#218)

## SBOM and licence gate

```sh
pip install .                                   # the SBOM reflects the installed environment
python3 scripts/ci/gen_sbom.py --check-licences -o sbom.cdx.json
```

`scripts/ci/gen_sbom.py` (stdlib only, Python 3.11+) writes a CycloneDX 1.5 JSON
SBOM of the runtime dependencies declared in `pyproject.toml`, followed
transitively through installed metadata. Output is deterministic: sorted, no
timestamp, and a serial number derived from the content, so two runs over the
same environment are byte-identical.

`--check-licences` fails (exit 1) when any component's licence is unknown or not
in `ALLOWED_LICENCES`; exit 2 means a declared dependency is not installed.
`LICENCE_OVERRIDES` records the few packages whose metadata is wrong, each
resolved from the licence file the package ships. Never add an override or an
allow-list entry to silence a real finding; review the licence first.

Not yet done on #218: hash-locked requirement files, `pip-audit` in CI,
release-artifact attestations, `THIRD_PARTY_NOTICES` and wiring this script into
the release workflow.
