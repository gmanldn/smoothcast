# SmoothCast releases — PyInstaller is canonical

**Use PyInstaller for distributed applications.** A Python wheel is still
validated for library/install contract tests; it is not the end-user release
format. The existing `setup/linuxsetup.sh`, `setup/macsetup.sh` and
`setup/winsetup.bat` remain source/developer setup paths, not release packaging.

## Build on the target operating system

PyInstaller does **not** cross-compile; GTK4/libadwaita and PyGObject must be
importable by the *same native Python* that runs PyInstaller. See
[setup instructions](../setup/README.md) for OS-native dependencies.

```sh
# First install the platform native GTK4/libadwaita/PyGObject runtime.
python -m pip install -e '.[packaging]'
python scripts/build_release.py --check
python scripts/build_release.py
```

Use a virtual environment with `--system-site-packages` if GTK bindings are
distro/Homebrew/MSYS2-managed. On Windows, use MSYS2 UCRT64 Python for both
PyGObject and PyInstaller; do **not** mix it with python.org CPython.
Use pacman for native PyInstaller, Pillow and zeroconf: UCRT64 pip may
otherwise attempt unsupported source builds instead of Windows wheels. On macOS,
use the Homebrew Python matching the installed PyGObject. Builds use
`packaging/SmoothCast.spec` and the canonical release version in
`src/version.py`; neither spec nor build script increments it.

Output is `dist/SmoothCast/` with `SmoothCast` (windowed application on
Windows/macOS) and `SmoothCastCLI` (console diagnostics). macOS also creates
`dist/SmoothCast.app`. Distribute the **whole** onedir folder or .app,
not the binary copied out of it. Assets, Python dependencies, CATT/yt-dlp,
GTK4 GI hooks and Adwaita theme are included by the spec. Generated native
icons use the source-controlled application PNG. Build and dist directories
are ignored by Git.

## Runtime and safety

- The frozen application dispatches `--_smoothcast-hls-server` to its own
  isolated HTTP server and `--_smoothcast-catt` to the bundled CATT CLI.
  A frozen `sys.executable` is **not** a Python interpreter: never pass it
  a `.py` pathname, nor silently substitute a system `catt`.
- `SmoothCastCLI --version` and `--_smoothcast-package-check` are headless.
  Packaging verification checks these, CATT `--help`, bundle icon hash, and
  importable GTK4/libadwaita **without creating a window or touching a TV**.
  The build script automatically fails on a broken artefact.
- FFmpeg, ffprobe and ffplay are **still native external executables**,
  not redistributed in the bundle. Install compatible versions on the host
  and ensure they are on PATH. This avoids silently changing FFmpeg's
  licensing/distribution obligations. Gtk's native GStreamer backend and
  hardware drivers can require host libraries/plugins; packaging success does
  not prove every decoder or preview mode.
- Do not treat a wheel/syntax check, CATT help, headless typelib import, or
  a Linux runner build as Windows/macOS GUI or Chromecast qualification.
  Check actual launch, icon, UI, local preview, FFmpeg, subtitles, casts and
  single-instance behaviour **on each OS and physical receiver**.

`python -m pytest -q tests/test_frozen_runtime.py` exercises child dispatch
without launching helpers. The `Package SmoothCast` workflow builds/test-smokes
native artefacts and retains them as downloadable CI artefacts, but does not
publish a signed release or automatically run the GUI. Code signing,
notarisation, Windows signing/installer generation and hardware qualification
remain separate release gates. See GitHub issue #192.

Reference: https://pyinstaller.org/en/stable/spec-files.html
