# Native GTK setup on GitHub Actions (#548)

The `Startup import budget` job still executes the **real system-Python**
`scripts/ci/import_budget.py` on every `develop` push without opening GTK
or the user's desktop.

Before that gate, `scripts/ci/install_gtk_import_deps.py` checks whether
`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` and `python3-psutil`
are already installed on the Ubuntu runner. It only installs missing packages
with `--no-install-recommends` and existing apt indexes. If the install
fails (for example stale package metadata), it refreshes the indexes **once**
and retries **once**, returning failure on any further error.

The preflight then requires `/usr/bin/python3` to import GTK4, Adwaita 1 and
psutil. Package metadata alone is not accepted as proof the native ABI works.
No CI checks are skipped or weakened, and no persistent cache is introduced.

For diagnostics inspect the `Install GTK bindings (system Python)` step
in the Verify SmoothCast run. The script reports which path it took and
preserves a bounded error excerpt. A faster path is possible, **not yet a
measured speedup**. Compare step duration on similar successful hosted
runners before reporting actual savings.
