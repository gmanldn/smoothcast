# When a cast fails: one-click recovery (#13)

If starting a cast or seeking fails, SmoothCast keeps your place and offers the
most useful next step as a single button on the error message. Nothing happens
until you press it, and it never interrupts something else you started.

| Button | When it appears | What it does |
| --- | --- | --- |
| **Try again** | The failure may be temporary (for example a busy or briefly offline receiver). | Casts the same file again, from your saved place, with the same settings. |
| **Convert and retry** | The same receiver already failed twice with the original file. | Casts again from your saved place, but converts the stream (HLS) instead of sending the original file. |
| **Continue on *name*** | This receiver cannot help (offline, or no format it accepts) and another receiver is available. | Switches to that receiver and casts from your saved place. |

The message says why that step is suggested. A receiver and mode that failed
twice is not offered again, so the button moves on instead of looping. If you
start something else first, or close the window, the button does nothing and
tells you playback changed.

## For developers

* `src/cast_recovery.py` is the pure planner (`plan_recovery`, `plan_for_window`);
  it reads only the failure details and returns ordered options with reasons.
* `src/cast_retry_ui.py` (`RetryMixin`) turns the first option into the toast
  button. Every action goes through the normal `_cast_path`; there is no new
  session-control path, signal, PID logic or direct teardown.
* `_cast_path` records `_attempt_mode` (`direct` or `transcode`) and resets
  `_cast_tried` for fresh user-started casts; `_cast_failed` appends the failed
  (receiver, mode) pair. `_force_transcode_once` is a one-shot override of
  `use_direct`.
* Headless tests: `tests/test_cast_recovery.py`, `tests/test_cast_retry_action.py`.
  No GUI is launched and no real receiver is used.
