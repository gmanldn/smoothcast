# Flatpak packaging prototype — NOT a qualified release

Tracking: [#263](https://github.com/gmanldn/smoothcast/issues/263). This is
a **fail-closed build definition** to make Linux packaging work measurable; it
is **not** a published, verified Flatpak. The canonical current release path
remains PyInstaller (see [PACKAGING.md](PACKAGING.md)).

## Sandboxed behaviour

- Runtime/SDK: GNOME 51 with GTK4, libadwaita and PyGObject.
- Network: enabled for LAN discovery, Cast/DLNA and the room web portal.
- Display: Wayland or fallback X11, shared IPC; PulseAudio socket and DRI for
  optional local preview/accelerated decoding.
- Media: **read-only** access to home for file picking/preview. Application data
  and temporary transcode output belong in sandbox-private writable paths.
- No host filesystem write, host command execution, system D-Bus access or
  unrestricted devices are granted. Do not use `flatpak-spawn --host` to
  bypass packaging missing dependencies.

## Local build prerequisites

On a disposable Linux build machine with matching GNOME runtime and SDK,
install `flatpak-builder` and the GNOME 51 runtime/SDK. Run from the repo root:

```sh
flatpak install --user flathub org.gnome.Platform//51 org.gnome.Sdk//51
python3 -m pip download --dest packaging/flatpak/wheelhouse .
flatpak-builder --user --install-deps-from=flathub --force-clean \
  --repo=flatpak-repo flatpak-build \
  packaging/flatpak/io.github.gmanldn.SmoothCast.json
```

**Important:** the download is a *preparation* step using the build machine's
Python; Flatpak itself installs dependencies with `--no-index`, so no build
step silently fetches the network. The complete Python wheelhouse must match
the GNOME SDK Python ABI and Linux architecture; transitive dependencies,
build backend and compiled wheels are required. Prepare this in the matching
SDK, then lock every resulting wheel and hash for reproducible distribution.
Do not check unreviewed wheel binaries into the repository.

The manifest deliberately fails if that wheelhouse is absent, if GTK/PyGObject
imports fail or if `ffmpeg`, `ffprobe`, or `ffplay` cannot be found. **GNOME's
codec extensions are not proof that these three executables exist.** A real
release needs a reviewed, licensed, bundled FFmpeg executable set; do not work
around the check by invoking host binaries.

The launcher and icon are exported as
`io.github.gmanldn.SmoothCast.desktop` and
`io.github.gmanldn.SmoothCast.png`; the desktop's
`StartupWMClass=local.cast-control` matches SmoothCast's existing GTK window
identity. Do not rename the running app's GApplication ID casually.

## Qualification before closing #263

1. Create an auditable offline dependency/FFmpeg bundle with pinned sources,
   hashes, licences, ABI and runtime imports. Confirm a clean Flatpak build
   succeeds without using the network inside the sandbox.
2. On **Debian and Fedora**, install the built bundle into a fresh user profile;
   verify the launcher, icon, source-file picker, local preview and cleanup.
3. Verify LAN discovery (mDNS/SSDP where permitted), FFmpeg HLS playback,
   receiver control and room portal against a fake receiver first; real
   hardware results belong in #208.
4. Verify app restart, per-user config persistence and isolation, log output,
   denial of host writes, and uninstall without touching personal media.
5. Attach the exact source SHA, runtime version, Flatpak Builder logs and
   distribution versions to #263, then consider the ticket for closure.

Quick syntax/security structure test (not a build test):

```sh
python3 -m unittest discover -s tests -p test_flatpak_manifest.py
```

Do **not** advertise this as a one-click install until the above qualification
is complete.
