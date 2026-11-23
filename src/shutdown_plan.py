"""Ordered, bounded application shutdown with a clean-exit ledger (issue #465).

``ShutdownPlan`` runs named steps in order, each with a deadline, inside a total
budget (1 s). Steps that do not touch GTK may run on a worker thread so a hung
one is abandoned (and logged by name) instead of freezing the exit; GTK steps run
inline and are only timed. ``ShutdownLedger`` persists whether the previous run
ended cleanly so the next start can count unclean exits. GTK-free, stdlib only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from typing import Callable

BUDGET = 1.0           # seconds for the whole shutdown
STEP_DEADLINE = 0.25   # default per step
MAX_STEPS = 64


class ShutdownPlan:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, budget: float = BUDGET,
                 log: Callable[[str], None] | None = None) -> None:
        self._clock, self.budget, self._log = clock, budget, log or (lambda _msg: None)
        self._started = clock()
        self._steps: list[dict] = []
        self._names: set[str] = set()
        self._lock = threading.Lock()

    def run(self, name: str, fn: Callable[[], object], *, deadline: float = STEP_DEADLINE,
            threaded: bool = False) -> bool:
        """Run one step once; True when it finished inside its deadline."""
        with self._lock:
            if name in self._names or len(self._steps) >= MAX_STEPS:
                return True
            self._names.add(name)
        begin, error = self._clock(), None
        finished = True
        if threaded:
            outcome: dict = {}

            def target() -> None:
                try:
                    fn()
                except Exception as exc:        # a failing step must never block the exit
                    outcome["error"] = type(exc).__name__
            worker = threading.Thread(target=target, name=f"smoothcast-shutdown-{name}", daemon=True)
            worker.start()
            worker.join(deadline)
            finished = not worker.is_alive()
            error = outcome.get("error")
        else:
            try:
                fn()
            except Exception as exc:
                error = type(exc).__name__
        elapsed = self._clock() - begin
        overran = elapsed > deadline or not finished
        record = {"name": name, "ms": round(min(elapsed, deadline * 4) * 1000, 1) if not finished
                  else round(elapsed * 1000, 1), "overran": overran, "abandoned": not finished,
                  "error": error}
        with self._lock:
            self._steps.append(record)
        if overran:
            self._log(f"Shutdown step '{name}' took {record['ms']:.0f} ms "
                      f"(limit {deadline * 1000:.0f} ms)" + (" and was abandoned" if not finished else ""))
        if error:
            self._log(f"Shutdown step '{name}' failed: {error}")
        return not overran and error is None

    @property
    def elapsed(self) -> float:
        return self._clock() - self._started

    def report(self) -> dict:
        with self._lock:
            steps = list(self._steps)
        total = self.elapsed * 1000
        return {"total_ms": round(total, 1), "budget_ms": self.budget * 1000,
                "within_budget": total <= self.budget * 1000,
                "overruns": [s["name"] for s in steps if s["overran"]],
                "steps": steps}


def default_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "smoothcast" / "shutdown.json"


class ShutdownLedger:
    """Counts clean and unclean previous exits; survives crashes by design."""

    def __init__(self, path: Path | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self.path, self._clock = Path(path) if path else default_path(), clock

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        import tempfile          # only needed when writing; keeps it off the startup import path
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix="shutdown.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"))
            os.replace(name, self.path)
        except OSError:
            pass   # a ledger problem must never affect the app

    @staticmethod
    def _count(value: object) -> int:
        return value if isinstance(value, int) and 0 <= value < 10 ** 9 else 0

    def begin(self) -> str:
        """Call once at startup: classify the previous run and mark this one running."""
        data = self._read()
        state = data.get("state")
        previous = "clean" if state == "clean" else ("unclean" if state == "running" else "none")
        clean, unclean = self._count(data.get("clean")), self._count(data.get("unclean"))
        if previous == "clean":
            clean += 1
        elif previous == "unclean":
            unclean += 1
        self._write({"state": "running", "clean": clean, "unclean": unclean,
                     "last_ms": data.get("last_ms"), "last_overruns": data.get("last_overruns", []),
                     "started": int(self._clock())})
        return previous

    def end(self, report: dict) -> None:
        """Call when shutdown has finished: the next start will see a clean exit."""
        data = self._read()
        self._write({"state": "clean", "clean": self._count(data.get("clean")),
                     "unclean": self._count(data.get("unclean")),
                     "last_ms": report.get("total_ms"), "last_overruns": report.get("overruns", [])[:8],
                     "ended": int(self._clock())})

    def summary(self) -> dict:
        data = self._read()
        return {"clean_exits": self._count(data.get("clean")),
                "unclean_exits": self._count(data.get("unclean")),
                "last_shutdown_ms": data.get("last_ms"),
                "last_overruns": data.get("last_overruns", [])}


def begin_ledger() -> str:
    """Startup hook: classify the previous exit; never raises."""
    try:
        return ShutdownLedger().begin()
    except Exception:
        return "none"
