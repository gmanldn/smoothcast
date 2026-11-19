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
environment. If a prior `.venv` is unusable, setup moves it to an
inspectable `.venv-incompatible-*` backup before rebuilding. A failure during
native venv creation, pip installation or media verification removes only the
new partial replacement and **restores the prior directory**. Brand-new
partial installs are cleaned up on failure. Compatible venvs repaired in place,
native OS packages, shortcuts and uninstall are not yet fully transactional;
see P0 issue SC-018 (#25). It then verifies that the actual environment can import GTK4 and
libadwaita, that stable `catt >= 0.12, < 0.14` is installed (prerelease builds
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

On macOS, if `brew` is missing, setup downloads the upstream Homebrew
`install.sh` from a **pinned immutable Git commit**, rejects empty/oversize
downloads, compares a **reviewed SHA-256 digest**, and only then invokes Bash
on a private, temporary script in noninteractive mode. If download or integrity
validation fails, it never executes the installer. To upgrade this pinned
installer, review the new upstream source and update both
`HOMEBREW_INSTALL_COMMIT` and `HOMEBREW_INSTALL_SHA256` in
`setup/bootstrap.py`; rerun `tests/test_homebrew_verify.py` before release.
This verifies a reviewed artifact, not the trustworthiness of upstream code.

On Linux, `sudo` may request the user's password for native package
installation. No unverified shell-piped downloads or silently ignored
package-manager failures are permitted.

## Receiver route and media-port diagnostics

When a Chromecast is discovered but a cast cannot start or buffer, run the
explicit headless check from the installed environment:

```sh
smoothcast --network-check 192.168.1.41
```

Substitute the receiver's **private IPv4** address. The command prints JSON
with the OS-selected local source IPv4, the route's interface name (where
available), a bounded Chromecast TCP 8009 probe, possible VPN-interface
indicator, and loopback HTTP health for SmoothCast's HLS server. It also
provides `second_host_health_url`, for example
`http://192.168.1.25:8767/_smoothcast/health`. Open that exact URL from a
phone/second computer on the same LAN to verify the inbound TCP 8767 path.

**Interpretation matters:** a working local UDP route or HLS loopback check
cannot prove the receiver reaches this machine. An unreachable Cast control
port might mean the receiver is off, isolated by VPN/Wi-Fi, or filtered; the
command never labels one cause as proven. On Windows interface names may be
unavailable; the source IP is still reported. No diagnostic scan is run
automatically during launch, and no network I/O is done by routine tests.
The existing redacted support bundle intentionally omits private IPs; this
local command prints them solely for the person troubleshooting.

### In-window Cast connection check

The **Output device → Check connection** button runs the same private-LAN
route and TCP 8009/HLS checks for the **selected Google Cast receiver**.
It is opt-in and runs off the GTK thread; it does not send Play, Seek or
Stop, change the output target, or begin automatic background probing.
DLNA devices have different control protocols and are not checked by this
Cast-specific button.

The result is selectable text, including the exact media-port health URL
to open **from a second device while SmoothCast's HLS server is running**.
A healthy local check is not proof of receiver-to-PC reachability.
If a different receiver is selected before completion, the old result is
discarded. Do not export private receiver/local IPs in a support bundle.

## Clean installed wheel, outside the source checkout

Besides source-checkout setup, the CI artifact matrix checks packaging on
Linux, macOS and Windows. It builds an sdist, rebuilds a wheel **from that
sdist**, then installs it in a fresh, isolated venv from outside the checkout
with no `PYTHONPATH`. The headless checks assert that `smoothcast --version`,
`sc --version` and the GUI-script entry point resolve, that the installed
release version matches metadata, and that the HLS server helper and bundled
application icon are available. The icon is shipped as
`smoothcast_assets/local.cast-control.png` and is used by the GTK icon theme
when the app starts; it no longer requires adjacent `data/` from the Git
checkout. The original `data/cast-control.png` remains available to the
desktop shortcut installer.

CI builds only use development packaging tools; these are not extra
initial prerequisites for the normal setup scripts. They deliberately skip
installing the external `catt` dependency during wheel inspection, so the
headless artifact contract cannot establish real TV playback or native GTK
availability. Those require the platform setup process and device smoke tests.

Developers can rerun the isolated check after installing `build`, `wheel`,
and a current `setuptools`: `python3 scripts/ci/verify_installed_artifact.py`.
No graphical application is opened.

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
