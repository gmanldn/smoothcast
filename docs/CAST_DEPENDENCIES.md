# Cast backend dependencies and licences (#202)

SmoothCast is MIT. Every dependency of the in-process Cast backend is installed
from PyPI as a separate package (never vendored or statically linked), so
copyleft terms stay with the package.

| Package | Pin (`pyproject.toml`) | Checked version | Licence | MIT-compatible |
|---|---|---|---|---|
| PyChromecast | `>=13.1.0,<15` | 14.1.1 | MIT | yes |
| casttube (via PyChromecast) | transitive | 0.2.1 | MIT | yes |
| protobuf (via PyChromecast) | transitive | 5.29.6 | BSD-3-Clause | yes |
| zeroconf (via PyChromecast) | transitive | 0.147.0 | LGPL-2.1-or-later | yes, as an unmodified separately installed library |
| catt (fallback backend) | optional | 0.13.3 | BSD-2-Clause | yes |

Notes:

- zeroconf is LGPL. SmoothCast imports it dynamically and does not modify it,
  which the LGPL allows. Frozen builds (PyInstaller, Flatpak) must ship it as a
  replaceable library and include its licence text.
- The upper bound `<15` is deliberate: PyChromecast changes its API between
  majors. Raise it only after the backend tests pass against the new major.
- Licences were read from installed package metadata, not from legal review.
  Re-check when a pin changes.
