# Preferences, GUI hierarchy and threading safety

## UX and orchestration

Owner directive (24 November 2026): user experience is paramount. Sophisticated
plumbing must remain elegant, fast and largely invisible to the user.

- **One clear journey:** discover or join, choose media, choose a receiver, then
  play or queue. Make shared Up Next prominent, including contributor, actual
  selected target and waiting items. Keep Settings and Live accessible even
  without a mesh; place idle diagnostics behind disclosure, not in the happy path.
- **Automatic plumbing:** use the existing discovery, queue, transfer, dependency
  and worker authorities. Choose eligible routes and workers automatically;
  revalidate and fail over safely. Provision supported prerequisites through
  setup with explicit owner approval. Guests must not install host software or
  manually route work. Unsupported or unavailable features need one actionable
  explanation, not instructions to defeat isolation, policy or receiver ownership.
- **Responsive by design:** GTK owns widgets and state; offload disk, network,
  subprocess and heavy media work to bounded existing worker domains. Coalesce
  updates, reuse models, avoid unchanged DOM/GTK rebuilds and stop idle/hidden
  timers. Bound retained data, queues and retries. Fence stale results against
  session and generation changes. Never add a second controller or poller just
  to make a new view work.
- **Truthful feedback and recovery:** distinguish requested, queued, transferring,
  verifying, accepted, confirmed, failed and uncertain. Show real progress and
  units only when reported; preserve user input and unrelated playback. Retry
  idempotently within a budget and present a useful recovery action when needed.
  A status receipt is not proof of playback. No silent failure or invented metrics.
- **Acceptance:** exercise narrow/mobile and desktop layouts, keyboard focus,
  offline/disabled/slow dependencies, stale callbacks, concurrent clients and
  recovery as applicable. Add deterministic regressions. For performance claims,
  measure CPU/memory, latency, callback/DOM churn or queue scale as relevant;
  distinguish expected gains from measured gains. Never launch a real receiver
  or the normal desktop app for routine tests.

## Media-first presentation

`panel_ui.PanelMixin` builds the window (player beside a tabbed side panel) and
reflows it; `cast_ui.UiMixin` builds the player and the cards placed in the tabs. `cast_settings.SettingsCardMixin`
builds the collapsible inline player settings card; its original widgets
remain active while collapsed. `preferences_ui.PreferencesWindow` is the
searchable native libadwaita window, created only on request.
`preference_choices.py` provides pure options mapped to existing handlers.

The Preferences window reads `MainWindow.cfg` and delegates updates through
the **existing** GTK widget callbacks. Do not persist a second state store,
duplicate subtitle validation, or issue receiver commands in preferences.
The colour scheme uses the registered application action, retaining automatic
theme semantics. GTK-free tests verify mappings and source wiring.

## Threading and module opportunities (19 November 2026)

- Media probing, encoding and LAN work **already use background threads**.
  Prefer profiling event-loop jank to inventing additional workers.
- `cast_widgets.Async.run` creates one daemon thread **per invocation**.
  Bursts of device polling or volume commands can create unbounded workers.
- Short transport/status requests and long DLNA/FFmpeg conversions require
  separate bounded domains. One shared FIFO pool would starve critical
  playback commands behind long conversions.
- Carry receiver/session generation and cancellation identity into callbacks;
  discard stale replies before touching GTK or another receiver. Coordinate
  with existing issues #16, #68 and #93.
- GTK4 widgets stay on the **main GLib context**. Use `GLib.idle_add` for
  worker results, not direct background widget access.
- Configuration persistence is synchronous but bounded; if profiling shows
  UI stalls, coalesce writes with a *serialised* worker and flush on exit.
- Keep new GUI features outside the growing `cast_ui.py` mixin; this change
  extracted `cast_settings.py` specifically to meet code-size budgets.

Tracked worker-lifecycle follow-up:
[#194](https://github.com/gmanldn/smoothcast/issues/194).

## Research and design basis

- [GNOME adaptive layouts](https://developer.gnome.org/hig/guidelines/adaptive.html):
  readable controls across small and large windows.
- [GNOME menu and preferences conventions](https://developer.gnome.org/hig/patterns/controls/menus.html)
  and [Ctrl+, shortcut](https://developer.gnome.org/hig/reference/keyboard.html).
- [libadwaita PreferencesWindow](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/class.PreferencesWindow.html):
  searchable grouped settings with standard accessible rows.
- [GTK threading](https://docs.gtk.org/gtk4/section-threading.html):
  UI object access is restricted to the main loop.
