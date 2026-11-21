# SmoothCast setup — fresh desktop to registered app

**No Python needs to be installed first.** Run the platform installer from a
downloaded SmoothCast source archive or checkout. It probes for Python 3.10+
and, if missing, acquires it using the OS package manager (Linux), verified
Homebrew (macOS), or WinGet / a verified Python installer (Windows).
Internet access and OS-native administrator approval may be necessary.

| Platform | Run | Default application folder | Runtime provider |
|---|---|---|---|
| Debian/Ubuntu/Fedora/Arch | `bash setup/linuxsetup.sh` | `~/.local/opt/SmoothCast` | apt/dnf/pacman |
| macOS Intel/Apple Silicon | `bash setup/macsetup.sh` | `~/Applications/SmoothCast` | Homebrew |
| Windows 10/11 x64 | Double-click `setup/winsetup.bat` | `%LOCALAPPDATA%\Programs\SmoothCast` | PowerShell + MSYS2 UCRT64 |

**The installer prompts for an installation folder**, proposing the OS default
or the last successful destination. Press Enter to accept or type another
user-writable location. Noninteractive options:

- `--install-dir "<full path>"` — select where app files and .venv are installed;
  paths containing spaces work.
- `--yes` — accept the default/remembered location without prompting.
- `--check` — read-only check of an existing installation: no downloads,
  source copies, native package changes or shortcut updates.
- `--no-shortcuts` — install runtime without menu registration.
- `--in-place` — explicitly install the existing checkout (developer mode);
  this is intentionally not the end-user default.

Rerunning setup repairs missing dependencies. Updates replace only app-managed
source files; a failed source copy, bootstrap or shortcut registration restores
their prior versions. User files and existing .venv are preserved. A failed
*new* installation is cleaned up. The copy rollback cannot reverse native OS
packages or in-place Python package changes already made to an existing .venv.
On macOS, the app bundle is assembled beside its registered path and replaced
only after its icon, launcher and metadata are complete; setup refuses to
replace a different or unrecognized `SmoothCast.app` bundle.

## Dependency inventory

| Layer | Required |
|---|---|
| Interpreter | Python 3.10+; venv/ensurepip |
| GUI | GTK4, libadwaita, PyGObject/GObject Introspection and Cairo |
| Media | FFmpeg 5+ with ffmpeg, ffprobe, ffplay; GStreamer base/good/libav and GTK media support |
| Python runtime in .venv | `catt>=0.12,<0.14`, `PyChromecast>=13.1.0,<15`, `psutil>=5.9,<8`, `zeroconf>=0.132,<1`, `segno>=1.6,<2` and editable SmoothCast |
| Native installation | Linux apt/dnf/pacman; macOS Homebrew; Windows MSYS2 UCRT64 native Python, PyGObject, GTK4, libadwaita and FFmpeg |
| Optional developers | pytest, ruff, mypy, PyInstaller and Pillow are not needed to launch |

Each script installs native dependencies, creates an isolated environment
allowing native PyGObject via `--system-site-packages`, verifies GTK
imports and the installed Python packages, then starts ffmpeg/ffprobe/ffplay
bounded `-version` probes to confirm they actually execute.

Application registration points at the installed location, never the source
archive: Linux XDG desktop/icon, a macOS `~/Applications/SmoothCast.app`
with branded ICNS, and a Windows Start Menu link with branded ICO.

## Platform caveats

- Very old Linux releases whose normal repositories only provide Python older
  than 3.10 are not supported. The installer stops instead of running it.
- A virgin Mac may need an Apple-managed Xcode Command Line Tools confirmation
  when Homebrew is installed. The reviewed Homebrew script has a pinned commit
  and checksum duplicated in `setup/bootstrap.py` and
  `setup/macsetup.sh`; update both together.
- On Windows, the initial Python is only the setup interpreter; the app's
  actual GTK runtime comes from MSYS2 UCRT64 Python. A pinned fallback Python
  3.14.10 installer from python.org is verified by SHA-256 **and**
  Authenticode; no unverifiable download is executed.
- Windows/macOS native GUI, FFmpeg/codec and receiver paths still require
  actual machine qualification: see GitHub issue #209. Offline contract tests
  are not real-device certification.

## Security and portability

After Python acquisition, the Windows bootstrap downloads the latest official MSYS2 x64 installer from
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
installing the external Cast dependencies during wheel inspection, so the
headless artifact contract cannot establish real TV playback or native GTK
availability. Those require the platform setup process and device smoke tests.

Developers can rerun the isolated check after installing `build`, `wheel`,
and a current `setuptools`: `python3 scripts/ci/verify_installed_artifact.py`.
No graphical application is opened.

## What this does **not** establish yet

The dependency bootstrap, smoke checks and OS shortcut creation are automated,
but **Windows and macOS playback are not verified on real systems**. MSYS2
Python has different binary-wheel compatibility from CPython for some
dependencies, and Cast dependency installation may require additional packaging work.
Chromecast discovery/firewall permissions and native GTK window behaviour
also need testing. On Windows/macOS the encoder starts with software libx264;
the Linux VAAPI acceleration path is deliberately not attempted.

Do not call the Windows/macOS builds production-ready until the cross-platform
GUI, file dialogs, audio meter, FFmpeg encode, LAN discovery, cast controls,
sleep/resume and uninstall/reinstall have passed actual-machine smoke tests.

## Development validation

```bash
python3 -m unittest discover -s tests -p 'test_setup_bootstrap.py' -v
python3 -m unittest discover -s tests -p 'test_installer_locations.py' -v
python3 -m compileall -q setup src tests
ruff check setup tests
```

The `.github/workflows/verify.yml` setup-contract matrix runs those
portable checks on Ubuntu, macOS and Windows without installing GTK.
