# Platform port evidence (#703)

What exists behind each OS port, what proves it, and what does not. Recorded
**27 November 2026** from the `develop` tree. "Unit" means a headless pytest with injected
probes and fakes; none of these rows is native-hardware evidence, and none is claimed as such.
Native sessions are tracked in [Platform status](PLATFORM_STATUS.md).

| Port | Module | Linux | macOS | Windows | Evidence | Wired into the app? |
| --- | --- | --- | --- | --- | --- | --- |
| HardwareEncoder | `src/hw_port.py` | VAAPI (probed render nodes), NVENC, QSV | VideoToolbox | NVENC, QSV | Unit: `tests/test_hw_port.py`, `tests/test_render_nodes.py` | **No.** `select()` has no caller outside the module; `streamer.py` still owns encoder choice |
| PowerManager | `src/power_port.py` | systemd-inhibit | caffeinate | SetThreadExecutionState | Unit: `tests/test_power_port.py` | **No.** `choose()` has no caller; `sleep_inhibit.Inhibitor` has none either |
| Sandbox | `src/sandbox_port.py` | bubblewrap | sandbox-exec | job object reports itself unavailable (needs a launcher, not an argv prefix) | Unit: `tests/test_sandbox_port.py` | **No.** `select()` has no caller |
| ProcessPriority | `src/process_priority.py` | nice value | nice value | priority class via `launch_kwargs` | Unit: `tests/test_process_priority.py` | Yes: encoder spawns in `src/dlna.py` and `src/streamer.py` |
| ReceiverBackend | not started | — | — | — | — | — |
| Installer | not started | — | — | — | — | — |

## Reading this table

- Every probe is injected, so a green unit test says the decision logic is right for the
  fixture, not that the OS or driver behaves that way. A backend that cannot start must return
  a visible reason and fall to the next ranked option (never silently to software or unconfined).
- Until a port is wired in, the app behaves as before: `#703` acceptance "encoder selection
  calls the port" is **not met**.
- Add a dated row per native run (OS version, GPU or driver, SmoothCast commit, result) beneath
  this table; keep receiver evidence in [Device compatibility](DEVICE_COMPATIBILITY.md).
