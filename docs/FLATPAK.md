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

## Build inputs (all pinned, all offline inside the sandbox)

- **Python dependencies:** `packaging/flatpak/python3-deps.json` lists every
  runtime wheel (plus the setuptools/wheel build backend) by URL and sha256 for
  the SDK's CPython 3.14 on x86_64; `requirements.lock.txt` is the same set in
  readable form. Regenerate both with
  `python3 packaging/flatpak/lock_python_deps.py` after changing
  `[project].dependencies` (pip `--dry-run` resolution; nothing executes).
- **FFmpeg:** GNOME's codec extensions ship libraries, not the `ffmpeg`,
  `ffprobe` and `ffplay` executables SmoothCast runs, so the manifest builds
  x264 (pinned `stable` commit) and FFmpeg `n8.1.3` (pinned commit) with
  `--enable-gpl --enable-libx264 --enable-vaapi`: libx264 is the universal
  fallback encoder and VAAPI the primary Linux path. The result is GPL.
- The app module fails the build if GTK/libadwaita/PyGObject or the Python
  dependencies do not import, or if any FFmpeg tool or encoder is missing.

## Building

CI builds it: `.github/workflows/flatpak.yml` runs on every develop push that
touches `packaging/flatpak/**` (marked experimental, so a red build does not
fail the develop head). Locally, on a machine with `flatpak-builder`:

```sh
flatpak install --user flathub org.gnome.Platform//51 org.gnome.Sdk//51
flatpak-builder --user --install --force-clean build \
  packaging/flatpak/io.github.gmanldn.SmoothCast.json
flatpak run --command=smoothcast io.github.gmanldn.SmoothCast --version
```

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
