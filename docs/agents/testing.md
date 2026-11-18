# Agent testing and safety — never focus the user's desktop

**Non-negotiable:** routine tests must not launch SmoothCast, steal focus, alter
GNOME dock pins, discover/control the user's TV, or touch real media. Never use
`gtk-launch`, `./smoothcast` (except `--version`), plain
`python3 src/cast_control.py`, or bare `--self-test` in a test loop.
Do not use the user's live X11/Wayland display or desktop DBus (D-Bus).

Headless portable verification from repo root:

```sh
python3 -m pytest -q tests
python3 -m compileall -q src scripts setup tests
```

Run targeted `python3 -m pytest -q tests/test_affected.py` during iteration,
then the full suite when appropriate. The test harness strips desktop
display/session handles at collection; CI sets `SMOOTHCAST_TEST_CONTEXT=1`.
Never remove these guards or run tests repeatedly to check whether the GUI
raises a window. `tests/gui_source.py` is for source/AST UI assertions
without importing GTK.

**Optional GTK smoke** is a *separate explicit* action:
`python3 scripts/test_gui_isolated.py`. It requires Xvfb/xauth,
private runtime/configuration, one-use token and isolated credentials.
It quits promptly and forcibly terminates its process group on timeout.
Do not call the smoke runner inside pytest or point it at the active desktop.

**Real-device tests:** require an intentionally available receiver and clear
scope. Never report Chromecast/DLNA, macOS or Windows native playback as
verified from portable CI alone. Check regressions in device ownership,
playlist lifecycle, subtitles/encoding and error paths.

Keep full failing logs available, concise success output, reproducible test
commands and honest untested conditions. Do not misrepresent pending CI as
passed.
