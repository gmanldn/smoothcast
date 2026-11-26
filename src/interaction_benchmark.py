"""Isolated-Xvfb driver for the native interaction budget (#627).

Refuses to run anywhere but the isolated GUI job (``interaction_probe.
require_isolated``) and only when ``SMOOTHCAST_INTERACTION_SAMPLES`` names an
output file. It seeds a 1,000-item queue, measures each interaction until the
frame that acknowledges it, keeps a 32-phone poll burst inside every round,
writes the samples JSON the budget script consumes, and then quits the window.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time

import cast_portal_queue
import interaction_probe

SAMPLES_ENV = "SMOOTHCAST_INTERACTION_SAMPLES"
ROUNDS = 10
SPIN_LIMIT_S = 5.0
QUEUE_ITEMS = interaction_probe.QUEUE_ITEMS
PHONE_POLLERS = interaction_probe.PHONE_POLLERS


def samples_path(env: dict[str, str] | None = None) -> Path | None:
    """Where to write samples, or None when this run is not a benchmark."""
    raw = (os.environ if env is None else env).get(SAMPLES_ENV, "")
    value = str(raw).strip()
    return Path(value) if value else None


class InteractionBenchmarkMixin:
    """Drive the interaction benchmark once the window is interactive."""

    def _run_interaction_benchmark(self) -> None:
        target = samples_path()
        if target is None:
            return
        self.selftest = False   # the benchmark replaces the scripted journey
        try:
            interaction_probe.require_isolated()
            samples = self._collect_interaction_samples()
            interaction_probe.write_samples(target, samples)
            print(f"INTERACTION: samples written to {target}")
        except Exception as exc:
            # A broken benchmark must not wedge the isolated run.
            print(f"INTERACTION FAILED: {exc}", file=sys.stderr)
        finally:
            self.quit()

    def _collect_interaction_samples(self) -> dict[str, list[float]]:
        window = self._window()
        self._seed_interaction_queue(window)
        def poll() -> None:
            cast_portal_queue.PortalQueueMixin._portal_queue_status(window)

        def spin() -> None:
            interaction_probe.poll_pressure(poll, pollers=PHONE_POLLERS)
            self._spin_frame(window)

        samples: dict[str, list[float]] = {}
        for name, action in self._interaction_actions(window).items():
            samples.update(interaction_probe.measure({name: action}, spin=spin,
                                                    rounds=ROUNDS))
        return samples

    def _seed_interaction_queue(self, window: object) -> None:
        window.queue[:] = [f"/library/bench/track-{index:04d}.mp3"
                           for index in range(QUEUE_ITEMS)]
        if getattr(window, "queue_durations", None) is None:
            window.queue_durations = {}

    def _interaction_actions(self, window: object) -> dict[str, object]:
        actions = {"play_pause": window.toggle_play,
                   "seek": lambda: window.seek_to(30.0),
                   "queue_rebuild_1000": window._rebuild_queue}
        volume = getattr(window, "volume_step", None) or getattr(window, "_volume_step", None)
        if callable(volume):
            actions["volume"] = lambda: volume(1)
        return actions

    def _spin_frame(self, window: object) -> None:
        """Drain the main loop until the frame clock reports the paint."""
        from gi.repository import GLib
        context = GLib.MainContext.default()
        clock = window.get_frame_clock()
        painted: list[bool] = []
        handler = (clock.connect("after-paint", lambda *_args: painted.append(True))
                   if clock is not None else None)
        deadline = time.monotonic() + SPIN_LIMIT_S
        while not painted and time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.001)
        if clock is not None and handler is not None:
            clock.disconnect(handler)
