<!-- Pull requests are for external contributors (target `develop`) and the automatic
release PR. Maintainers and agents commit directly to `develop`: see CONTRIBUTING.md. -->

## Issue
Fixes #  <!-- use "Refs #" if device verification is still pending -->

## What changed and why

## Acceptance checklist
- [ ] Each acceptance item of the issue is met (list any that are not)

## Verification class
- Fast lane (patch): <!-- compileall; ruff check; mypy -->
- Full lane (MINOR/MAJOR): <!-- python3 -m pytest -q tests -n auto -->
- Isolated GTK (Xvfb): <!-- run / not applicable -->
- Real device (Chromecast / DLNA / macOS / Windows): <!-- done / pending / not applicable -->

## Risks and limitations
<!-- Compatibility, ownership, privacy and anything not verified. Do not claim
hardware verification from CI alone. -->
