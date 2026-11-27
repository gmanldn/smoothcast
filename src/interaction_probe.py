"""Interaction probe core for the native snappiness budget (#627).

The isolated-Xvfb driver supplies the window actions and the frame spin; this
module only measures, loads and records, so it stays pure and unit-testable.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Callable, Mapping

import gui_test_safety

SCHEMA = 1
QUEUE_ITEMS = 1000
PHONE_POLLERS = 32


def measure(actions: Mapping[str, Callable[[], None]], *, spin: Callable[[], None],
            now: Callable[[], float] = time.perf_counter,
            rounds: int = 15) -> dict[str, list[float]]:
    """Milliseconds from each interaction until *spin* saw the acknowledging frame."""
    samples: dict[str, list[float]] = {}
    for name, action in actions.items():
        values = []
        for _ in range(max(int(rounds), 1)):
            started = now()
            action()
            spin()
            values.append(round((now() - started) * 1000.0, 3))
        samples[str(name)] = values
    return samples


def poll_pressure(poll: Callable[[], None], *, pollers: int = PHONE_POLLERS,
                  rounds: int = 1) -> int:
    """Simulate the room's polling phones inside a measurement round."""
    total = max(int(pollers), 0) * max(int(rounds), 0)
    for _ in range(total):
        poll()
    return total


def describe_load(*, queue_items: int = QUEUE_ITEMS,
                  phone_pollers: int = PHONE_POLLERS) -> dict[str, int]:
    return {"queue_items": int(queue_items), "phone_pollers": int(phone_pollers)}


def write_samples(path: str | Path, samples: Mapping[str, list[float]], *,
                  load: Mapping[str, int] | None = None) -> Path:
    """Write the samples JSON the latency budget script consumes."""
    destination = Path(path)
    payload: dict[str, object] = {"schema": SCHEMA,
                                  "load": describe_load(**(load or {}))}
    payload.update({str(name): list(values) for name, values in samples.items()})
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return destination


def require_isolated(env: Mapping[str, str] | None = None) -> None:
    """Refuse to measure outside the authorised isolated-Xvfb environment (#627).

    Samples must never come from the real desktop or a real receiver: the driver
    calls this first, and it is the same fail-closed check the GTK self-tests use
    (marker, X11 display, private XDG directories and a one-use token).
    """
    if not gui_test_safety.is_isolated_gui_test(env):
        raise RuntimeError(
            "interaction samples are only collected in the isolated Xvfb job "
            "(scripts/test_gui_isolated.py); never against the real desktop")
