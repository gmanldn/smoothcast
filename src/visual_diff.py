"""Perceptual screenshot comparison (#455). Pure: raw RGB(A) byte buffers in, verdict + diff image out.

``compare`` tolerates anti-aliasing noise (per-channel ``tolerance``) and fails only when the share of
differing pixels exceeds ``threshold``. Size mismatch always fails. ``diff_image`` marks changed pixels red on a
dimmed copy of the baseline so CI can upload it as an artefact. The scenario matrix is fixed so output is deterministic.
"""
from __future__ import annotations

SCENARIOS = [("desktop", w, t) for w in ("compact", "wide") for t in ("light", "dark")] + [("web", f"{px}px", "default") for px in (360, 1024)]
DEFAULT_TOLERANCE, DEFAULT_THRESHOLD = 8, 0.002
MAX_PIXELS = 16_000_000


def _check(w: int, h: int, ch: int, a: bytes, b: bytes) -> str | None:
    if ch not in (3, 4) or w <= 0 or h <= 0 or w * h > MAX_PIXELS:
        return "bad image geometry"
    if len(a) != w * h * ch or len(b) != w * h * ch:
        return "size mismatch"
    return None


def compare(base: bytes, new: bytes, width: int, height: int, channels: int = 3, tolerance: int = DEFAULT_TOLERANCE,
            threshold: float = DEFAULT_THRESHOLD) -> dict:
    err = _check(width, height, channels, base, new)
    if err:
        return {"ok": False, "error": err, "changed": None, "ratio": 1.0}
    changed = 0
    if base != new:
        step = channels
        for i in range(0, len(base), step):
            if any(abs(base[i + c] - new[i + c]) > tolerance for c in range(3)):
                changed += 1
    ratio = changed / (width * height)
    return {"ok": ratio <= threshold, "changed": changed, "ratio": round(ratio, 6)}


def diff_image(base: bytes, new: bytes, width: int, height: int, channels: int = 3, tolerance: int = DEFAULT_TOLERANCE) -> bytes | None:
    if _check(width, height, channels, base, new):
        return None
    out = bytearray(len(base))
    for i in range(0, len(base), channels):
        if any(abs(base[i + c] - new[i + c]) > tolerance for c in range(3)):
            out[i:i + 3] = b"\xff\x00\x00"
        else:
            out[i:i + 3] = bytes(v // 3 + 170 for v in base[i:i + 3])
        if channels == 4:
            out[i + 3] = 255
    return bytes(out)


def report(results: dict[str, dict]) -> tuple[bool, list[str]]:
    """results: scenario name -> compare() result. -> (all ok, failing lines)."""
    lines = [f"{k}: {'size mismatch' if r.get('error') else str(round(r['ratio'] * 100, 3)) + '% pixels differ'}" for k, r in sorted(results.items()) if not r["ok"]]
    return (not lines, lines)


def scenario_names() -> list[str]:
    return [f"{k}-{a}-{b}" for k, a, b in SCENARIOS]
