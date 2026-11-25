# SmoothCast releases — PyInstaller is canonical

**Integration flow:** package changes are reviewed and tested on `develop`;
`main` receives release merges only. Keep the runtime version authority in
`src/version.py` and do not publish directly from an unqualified feature PR.

**Flatpak (experimental):** The source tree contains a fail-closed GNOME Flatpak recipe and offline structural CI test under `packaging/flatpak/`. It is **not a qualified installable release**; [Flatpak prerequisites, build procedure and blockers](FLATPAK.md) document what is missing (bundled FFmpeg and Debian/Fedora install qualification). Do not list it as a supported package until #263 is validated.

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
  Packaging verification checks these, CATT `--help`, the `--_smoothcast-media-probe`
  JSON contract (exit 0 iff every tool is usable), bundle icon hash, and
  importable GTK4/libadwaita **without creating a window or touching a TV**.
  The build script automatically fails on a broken artefact.
- Windows media-tool layout (#530): a frozen Windows build runs only
  `<folder with SmoothCast.exe>/ffmpeg/{ffmpeg,ffprobe,ffplay}.exe`, resolved by
  `src/media_tools.py`, and never searches PATH. A missing or relocated tool
  fails with `ffmpeg.bundled_missing`. Source checkouts and the Linux/macOS
  bundles keep using PATH. Staging those files is #529's job.
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

## Windows payload manifest (issue #528)

After the Windows build, `scripts/ci/verify_windows_payload.py --dist dist/SmoothCast
--write-manifest` writes `payload-manifest.json` (schema, `windows-x64`, release
version, and each file's forward-slash path, size and SHA-256, in sorted order, so
the same tree gives the same bytes) and verifies it. It reads files and PE headers
only and never runs the application. It reports, by file name: changed, missing or
unlisted files; links and case-duplicate paths; any binary that is not x64; a GUI
`SmoothCast.exe` or console `SmoothCastCLI.exe` with the wrong subsystem; imported
DLLs that are neither Windows system files nor in the payload; and launch files
that point at the build machine (MSYS2). The CI step is advisory until the first
native run confirms the system-DLL allow-list in `scripts/ci/windows_payload.py`.
The tools staged by #529 will be covered by the same manifest.

## Windows MSI build (issue #534)

On Windows x64, from the MSYS2 UCRT64 Python that built the payload:

```sh
dotnet tool install --global wix --version 6.0.2   # once per build machine
python scripts/build_windows_msi.py --check
python scripts/build_windows_msi.py                # unsigned test MSI + SHA-256
```

CI exports `SMOOTHCAST_WIX` to the absolute `wix.exe` path because the msys2
shell does not inherit runner PATH additions; the script also accepts `wix`
from PATH.
The one command validates the UCRT64/GTK/PyInstaller/WiX prerequisites, calls
`scripts/build_release.py` once, optionally stages approved media sidecars
(`--media-dir` with `ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe` from #529),
freezes and verifies `dist/SmoothCast/payload-manifest.json`, generates
`build/msi/Payload.wxs`, runs pinned WiX v6 against
`packaging/windows/Product.wxs`, reads the result back with
`wix msi decompile`, and writes exactly `dist/SmoothCast-<version>-x64.msi`
plus a standard `sha256sum`-format `.sha256` file. The MSI carries the
verified Git commit in `SMOOTHCAST_SOURCE_REVISION`; a dirty tracked tree
fails the build. Failures and failed verification delete the temporary MSI
and leave any existing canonical MSI untouched.

`--skip-pyinstaller` reuses `dist/SmoothCast` only after verifying its
manifest version and every hash, so CI can build the MSI after the normal
native package step. `--json` prints one machine-readable summary; `--check`
builds nothing. The default Manufacturer is `SmoothCast`; the owner-approved
publisher identity replaces it at signing (#536). WiX v6's Open Source
Maintenance Fee terms need the owner's review before any revenue-generating
use.

The output is an **unsigned CI test artefact**. The `Package SmoothCast`
workflow builds and uploads it on manual dispatch or a version tag, but does
not sign it, install it, test upgrades or publish it: those remain #535,
#536, #537 and #538. Until #529 is approved, the MSI contains no bundled
FFmpeg sidecars and is not a qualified public installer.

## Unsigned macOS disk image (issue #556)

The native `macos-15` package job produces `dist/SmoothCast.app` with
PyInstaller, checks its headless package contract, archives the existing
`smoothcast-darwin.tar.gz`, and creates `smoothcast-macos.dmg` using Apple's
`hdiutil`. Both archives have adjacent `.sha256` files. The build deliberately
never starts GTK or contacts a receiver.

For local macOS packaging, after a successful `scripts/build_release.py` run:

```sh
python3 scripts/ci/build_macos_dmg.py
shasum -a 256 -c dist/smoothcast-macos.dmg.sha256
```

The unsigned DMG is a **CI test artefact**, not a notarised release.
Users may encounter macOS Gatekeeper warnings. Do not recommend disabling
Gatekeeper globally. A public release requires signing embedded executables
and the bundle with the appropriate Developer ID identity, validating the
hardened runtime and entitlements, notarising the distributed DMG with Apple's
notary service, stapling tickets, and verifying with `spctl`/stapler on macOS.
Credentials must be provisioned as CI secrets, never committed. Physical
macOS GUI and receiver checks remain a distinct gate in issue #264.
