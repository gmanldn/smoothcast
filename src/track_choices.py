"""Role-scoped track descriptors and selection validation for the room remote (#335). Pure.

``describe`` publishes opaque ids (never stream indexes or file paths) with an
honest switch mode. ``resolve`` maps a requested id back to the real stream
index only if it belongs to the *current* media generation and the caller holds
``change_tracks``; the receiver-side result must still be confirmed from state.
"""
from __future__ import annotations

import hashlib

BITMAP_SUBS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "pgssub", "dvdsub"}
KINDS = ("audio", "subtitle")


def track_id(media_key: str, generation: object, kind: str, index: int) -> str:
    raw = f"{media_key}|{generation}|{kind}|{index}".encode()
    return "t" + hashlib.sha256(raw).hexdigest()[:12]


def describe(media_key: str, generation: object, tracks: list[dict], *, libass: bool = True,
             remote_url: bool = False, selected: dict | None = None) -> dict:
    """Snapshot block: {'audio': [...], 'subtitle': [...]} with opaque ids."""
    out = {k: [] for k in KINDS}
    for t in tracks or []:
        kind = t.get("kind")
        if kind not in KINDS or not isinstance(t.get("index"), int):
            continue
        codec = str(t.get("codec") or "").lower()
        reason = ""
        if kind == "subtitle":
            if remote_url:
                reason = "Not available for remote links."
            elif codec in BITMAP_SUBS and not libass:
                reason = "This subtitle format needs burn-in support that is not installed."
        tid = track_id(media_key, generation, kind, t["index"])
        out[kind].append({"id": tid, "label": str(t.get("language") or "Unknown")[:24] + (
            " (forced)" if t.get("forced") else ""), "codec": codec,
            "mode": "restart" if kind == "audio" or codec in BITMAP_SUBS else "live",
            "available": not reason, "reason": reason,
            "selected": bool(selected and selected.get(kind) == tid)})
    return out


def resolve(media_key: str, generation: object, tracks: list[dict], kind: str, requested: str | None,
            can_change: bool, **opts) -> tuple[int | None, str]:
    """(stream index | None for Off, "") or (-1, reason). ``requested`` None/'off' means Off."""
    if not can_change:
        return -1, "You do not have permission to change tracks."
    if kind not in KINDS:
        return -1, "Unknown track type."
    if requested in (None, "", "off"):
        return None, ""
    block = describe(media_key, generation, tracks, **opts)[kind]
    for item, raw in zip(block, [t for t in tracks if t.get("kind") == kind and isinstance(t.get("index"), int)]):
        if item["id"] == requested:
            return (raw["index"], "") if item["available"] else (-1, item["reason"])
    return -1, "That track belongs to a different film."
