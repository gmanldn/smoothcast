"""One-line JSON error-log entries (opt-in ``SMOOTHCAST_LOG_FORMAT=jsonl``). GTK-free.

Every entry is a single valid JSON object no larger than ``max_bytes``: the
traceback is a field, never extra lines, and oversized text is clipped (the
traceback keeps its tail, where the cause is) rather than truncating the JSON.
"""
from __future__ import annotations

import json


def _clip(value: str, limit: int, tail: bool = False) -> str:
    raw = value.encode("utf-8")
    return (raw[-limit:] if tail else raw[:limit]).decode("utf-8", "ignore")


def entry(stamp: str, message: str, trace_id: object, with_traceback: bool, max_bytes: int) -> str:
    text, _, trace = message.partition("\n")
    if trace_id is not None and text.startswith(f"[command:{trace_id}] "):
        text = text[len(f"[command:{trace_id}] "):]
    for limit in (7000, 2500, 800, 200):
        record: dict[str, object] = {"ts": stamp, "level": "error", "msg": _clip(text, limit)}
        if trace_id is not None:
            record["command"] = str(trace_id)[:64]
        if with_traceback and trace.strip():
            record["traceback"] = _clip(trace.strip(), limit, tail=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if len(line.encode("utf-8")) <= max_bytes:
            return line
    return json.dumps({"ts": stamp, "level": "error", "msg": "entry too large to record"})
