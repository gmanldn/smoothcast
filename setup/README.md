# SmoothCast setup

**Initial manual prerequisite: Python 3.10 or newer.** Internet access and
permission to install operating-system packages are needed for first setup.
The scripts use Python's standard library and OS-provided Bash/PowerShell,
not a preinstalled pip environment.

| Host | Install command | Native dependencies |
|---|---|---|
| Debian/Ubuntu, Fedora, Arch Linux | `bash setup/linuxsetup.sh` | Distro packages: GTK4, libadwaita, PyGObject, FFmpeg |
| macOS (Apple Silicon or Intel) | `bash setup/macsetup.sh` | Homebrew: Python, PyGObject, GTK4, libadwaita, FFmpeg |
| Windows 10/11 x64 | Double-click `setup/winsetup.bat` | MSYS2 UCRT64: Python, PyGObject, GTK4, libadwaita, FFmpeg |

The installer checks the native packages and creates a project-local `.venv`
with access to the system GTK bindings. It installs `catt` using pip in that
environment. It then verifies that the actual environment can import GTK4 and
libadwaita, that stable `catt >= 0.12` is installed (prerelease builds
below that floor are rejected even with `python -O`), and that `ffmpeg`,
`ffprobe`, and `ffplay` **actually start and return success** from bounded
`-version` probes; PATH presence alone is not sufficient. It registers a per-user application shortcut:
Linux desktop entry, macOS `~/Applications/SmoothCast.app`, or the Windows
Start Menu. Running setup repeatedly is intended to be safe.

Options:

- `--check`: read-only dependency verification, no installations or shortcuts; on
  Debian/Ubuntu it performs a disposable temporary `venv`/ensurepip creation
  and removes it immediately to detect missing `python3-venv`.
- `--no-shortcuts`: install the runtime but skip desktop registration

The original `./smoothcast` launcher on Linux/macOS also bootstraps a fresh
checkout automatically. After setup, it directly starts the isolated Python
runtime. `python3 sc.py` works as a launcher on all three operating systems;
on Windows run the batch setup first. `./smoothcast --version` remains
side-effect free.

## Security and portability

The Windows bootstrap downloads the latest official MSYS2 x64 installer from
the `msys2/msys2-installer` GitHub release and verifies its published SHA-256
sidecar *before running it*. The official installer is invoked with its
documented unattended command-line switches; then pacman manages the UCRT64
packages. MSYS2 is installed under `C:\msys64` by default; set
`MSYS2_ROOT` for an existing installation in a different location. This
installs native binaries and may require administrator approval. A failed
download, mismatched hash or package-manager error stops setup.

On macOS, the standard Homebrew installer is used if `brew` is missing, in
noninteractive mode. On Linux, `sudo` may request the user's password for
native package installation. No blanket executable downloads or silently
ignored package failures occur.

## What this does **not** establish yet

The dependency bootstrap, smoke checks and OS shortcut creation are automated,
but **Windows and macOS playback are not verified on real systems**. MSYS2
Python has different binary-wheel compatibility from CPython for some
dependencies, and a `catt` pip install may require additional packaging work.
Chromecast discovery/firewall permissions and native GTK window behaviour
also need testing. On Windows/macOS the encoder starts with software libx264;
the Linux VAAPI acceleration path is deliberately not attempted.

Do not call the Windows/macOS builds production-ready until the cross-platform
GUI, file dialogs, audio meter, FFmpeg encode, LAN discovery, cast controls,
sleep/resume and uninstall/reinstall have passed actual-machine smoke tests.

## Development validation

```bash
python3 -m unittest discover -s tests -p 'test_setup_bootstrap.py' -v
python3 -m compileall -q setup src tests
```

The `.github/workflows/verify.yml` setup-contract matrix runs those
portable checks on Ubuntu, macOS and Windows without installing GTK.
