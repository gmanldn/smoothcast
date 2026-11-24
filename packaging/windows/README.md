# SmoothCast Windows installer (WiX v6)

`Product.wxs` is the hand-written per-user package. `Payload.wxs` is generated
into the ignored `build/msi/` from the verified payload manifest (#528).
`python scripts/build_windows_msi.py` does the whole job (#534): it verifies
the payload, generates the fragment, runs WiX v6, reads the MSI back and writes
`dist/SmoothCast-<version>-x64.msi` with an adjacent `.sha256`. See
[docs/PACKAGING.md](../../docs/PACKAGING.md#windows-msi-build-issue-534).

Build inputs passed to `wix build -arch x64 -d ...`:

| Variable | Source |
|---|---|
| `ProductVersion` | `scripts/packaging/wix_payload.py` `msi_version()` of `src/version.py` (three fields, 255.255.65535) |
| `Manufacturer` | the owner-approved publisher name; the test build defaults to `SmoothCast` |
| `PayloadDir` | the verified `dist/SmoothCast` folder |
| `IconFile` | `build/pyinstaller/icons/SmoothCast.ico` |
| `SourceRevision` | the verified Git commit, embedded as `SMOOTHCAST_SOURCE_REVISION` |

Rules this package keeps (checked by `tests/test_windows_msi_authoring.py` and
`tests/test_build_windows_msi.py`):

- Per-user install to `%LOCALAPPDATA%\Programs\SmoothCast`; nothing under Program
  Files or `HKLM`, no services, firewall rules, scheduled tasks or autostart.
- No custom actions and no downloads: it installs only files already in the MSI.
- `UpgradeCode` is permanent. Component ids and GUIDs come from each file's path
  (`uuid5`), so an unchanged path keeps the same component across releases.
- A new release must have a new `ProductVersion`; never ship two payloads under one.

The build script is the only supported builder; it never signs or publishes.
Still separate: signing (#536), upgrade, repair and uninstall testing on Windows
(#532, #535, #537), and the FFmpeg payload and notices (#529). The MSI is an
unsigned test artefact until real Windows CI and signed release qualification
record otherwise.