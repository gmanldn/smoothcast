# SmoothCast Windows installer (WiX v6)

`Product.wxs` is the hand-written per-user package. `Payload.wxs` is generated
into the ignored `build/msi/` from the verified payload manifest (#528):

    python scripts/packaging/wix_payload.py --manifest dist/SmoothCast/payload-manifest.json --output build/msi/Payload.wxs

Build inputs passed to `wix build -arch x64 -d ...`:

| Variable | Source |
|---|---|
| `ProductVersion` | `scripts/packaging/wix_payload.py` `msi_version()` of `src/version.py` (three fields, 255.255.65535) |
| `Manufacturer` | the owner-approved publisher name; not set in this repo |
| `PayloadDir` | the verified `dist/SmoothCast` folder |
| `IconFile` | `build/pyinstaller/icons/SmoothCast.ico` |

Rules this package keeps (checked by `tests/test_windows_msi_authoring.py`):

- Per-user install to `%LOCALAPPDATA%\Programs\SmoothCast`; nothing under Program
  Files or `HKLM`, no services, firewall rules, scheduled tasks or autostart.
- No custom actions and no downloads: it installs only files already in the MSI.
- `UpgradeCode` is permanent. Component ids and GUIDs come from each file's path
  (`uuid5`), so an unchanged path keeps the same component across releases.
- A new release must have a new `ProductVersion`; never ship two payloads under one.

Not done here (other tickets): building the MSI (#534), signing (#536), upgrade,
repair and uninstall testing on Windows (#532, #535), the FFmpeg payload and
notices (#529). **This authoring has never been compiled by WiX or installed on
Windows.**
