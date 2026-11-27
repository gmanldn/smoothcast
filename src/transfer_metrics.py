"""Transfer benchmark metrics (#573): pure aggregation, fairness, baseline gate, bottleneck hypothesis, redaction."""
from __future__ import annotations

import math
import re

MIB = 1024 * 1024


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile; empty -> 0."""
    v = sorted(x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))
    if not v:
        return 0.0
    k = max(1, math.ceil(p / 100 * len(v)))
    return float(v[min(k, len(v)) - 1])


def jain(xs: list[float]) -> float:
    """Jain's fairness index: 1.0 = perfectly equal shares."""
    xs = [x for x in xs if x >= 0]
    s = sum(xs)
    return 1.0 if not xs or s == 0 else (s * s) / (len(xs) * sum(x * x for x in xs))


def summarise(run: dict) -> dict:
    """run: bytes, elapsed_s, link_bps?, ttfb_s, playable_s, chunk_ms[], per_client_bytes[], corrupt_bytes, retransmitted, cpu_pct, rss_mb, fsyncs, fds_before/after, stalls."""
    el = max(float(run.get("elapsed_s") or 0), 1e-9)
    b = float(run.get("bytes") or 0)
    link = run.get("link_bps")
    ch = list(run.get("chunk_ms") or [])
    return {"mib_s": round(b / MIB / el, 3), "link_fraction": round(b / el * 8 / link, 3) if link else None,
            "ttfb_s": run.get("ttfb_s"), "playable_s": run.get("playable_s"),
            "chunk_ms": {f"p{p}": percentile(ch, p) for p in (50, 95, 99)},
            "fairness": round(jain(list(run.get("per_client_bytes") or [])), 3),
            "corrupt_bytes": int(run.get("corrupt_bytes") or 0), "retransmitted": int(run.get("retransmitted") or 0),
            "cpu_pct": run.get("cpu_pct"), "rss_mb": run.get("rss_mb"), "fsyncs": int(run.get("fsyncs") or 0),
            "leaked_fds": int(run.get("fds_after") or 0) - int(run.get("fds_before") or 0), "stalls": int(run.get("stalls") or 0)}


def invariants(s: dict) -> list[str]:
    """Hard faults only: independent of hardware speed, so CI is never flaky."""
    bad = []
    if s["corrupt_bytes"]:
        bad.append(f"corrupt bytes: {s['corrupt_bytes']}")
    if s["leaked_fds"] > 0:
        bad.append(f"leaked file descriptors: {s['leaked_fds']}")
    if s["stalls"]:
        bad.append(f"active playback stalled {s['stalls']} time(s)")
    if s["fairness"] < 0.5:
        bad.append(f"unfair shares (Jain {s['fairness']})")
    return bad


def compare(base: dict, now: dict, tolerance: float = 0.25) -> list[str]:
    """Regression vs a runner-labelled baseline: throughput may not drop, latency may not grow, by more than tolerance."""
    out = []
    if base.get("mib_s") and now["mib_s"] < base["mib_s"] * (1 - tolerance):
        out.append(f"throughput {now['mib_s']} MiB/s < baseline {base['mib_s']} by more than {int(tolerance * 100)}%")
    b99 = (base.get("chunk_ms") or {}).get("p99")
    if b99 and now["chunk_ms"]["p99"] > b99 * (1 + tolerance):
        out.append(f"p99 chunk latency {now['chunk_ms']['p99']} ms > baseline {b99}")
    return out


def bottleneck(run: dict) -> str:
    """One-line hypothesis separating disk, network, CPU and receiver."""
    s = summarise(run)
    if (run.get("cpu_pct") or 0) >= 90:
        return "CPU: the machine is saturated; transcoding or hashing is the limit."
    if s["link_fraction"] is not None and s["link_fraction"] >= 0.8:
        return "Network: the link is nearly full."
    if run.get("fsync_ms_p95", 0) and run["fsync_ms_p95"] > 50:
        return "Disk: writes are waiting on the drive."
    if s["stalls"]:
        return "Receiver: it ran out of data faster than the source could supply."
    return "No single bottleneck stands out."


def redact(report: dict) -> dict:
    """Strip client filenames and IPs from diagnostics."""
    def clean(v):
        if isinstance(v, str):
            v = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<ip>", v)
            v = re.sub(r"\b[0-9a-fA-F:]{2,}:[0-9a-fA-F:]{2,}\b", "<ip>", v)
            ext = r"\.(?:mp4|mkv|mp3|flac|webm|mov|avi|m4a|ts)"
            v = re.sub(r"([\"'])[^\"']*" + ext + r"\1", "<file>", v, flags=re.I)     # quoted names may hold spaces
            return re.sub(r"[\w.\-()]+" + ext + r"\b", "<file>", v, flags=re.I)
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v
    return clean(report)
