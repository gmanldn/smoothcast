"""Plain-text rows for the stream-health console (#49 slice). Pure, GTK-free.

Renders only what ``StreamHealth.snapshot`` measured; an unmeasured value reads
"not measured", never a guess. The GTK console and the portal both consume rows.
"""
from __future__ import annotations


def _stat(stat: dict | None, unit: str, scale: float = 1.0, digits: int = 0) -> str:
    if not stat:
        return "not measured"
    f = lambda v: f"{v / scale:.{digits}f}"
    return f"{f(stat['last'])} {unit} (median {f(stat['median'])}, p95 {f(stat['p95'])}, n={stat['samples']})"


def rows(snapshot: dict | None) -> list[tuple[str, str]]:
    if not snapshot:
        return [("Stream health", "not measured")]
    failed, ok = snapshot.get("segments_failed", 0), snapshot.get("segments_ok", 0)
    rate = snapshot.get("failure_rate")
    seg = f"{ok} ok, {failed} failed" + (f" ({rate * 100:.1f}% failing)" if rate else "")
    return [
        ("Throughput", _stat(snapshot.get("throughput_kbps"), "Mbit/s", 1000.0, 1)),
        ("HLS latency", _stat(snapshot.get("latency_ms"), "ms")),
        ("Decoder", str(snapshot.get("decoder") or "unknown")),
        ("Segments", seg),
        ("Recoveries", str(snapshot.get("recoveries", 0))),
    ]


def recent_events(snapshot: dict | None, limit: int = 10) -> list[str]:
    events = (snapshot or {}).get("recent_events") or []
    return [f"{e.get('kind', '?')}: {e.get('detail', '')}".rstrip(": ") for e in events[-limit:]]
