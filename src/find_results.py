"""GTK-free row model for the desktop "Find in the house" window (#413)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    key: str            # content key to queue ("" for rows that only describe a group)
    title: str
    subtitle: str
    can_add: bool
    group: str


def where(copies: list[dict]) -> str:
    """'On Study PC - also on Lounge PC' / 'Dad's laptop is offline'."""
    online = [c for c in copies if c.get("online")]
    name = lambda c: "this computer" if c.get("origin") == "local" else (c.get("origin_name") or "another computer")  # noqa: E731
    if online:
        return "On " + " - also on ".join(name(c) for c in online)
    if copies:
        return f"{name(copies[0]).capitalize()} is offline"
    return ""


def flatten(data: dict, *, available_only: bool = False) -> list[Row]:
    """Playable results in display order; artist/album/show headers carry no key."""
    rows: list[Row] = []
    for group in data.get("groups", []):
        kind = group.get("type", "")
        for item in group.get("items", []):
            if kind in ("artists", "albums"):
                detail = f"{item.get('count', 0)} songs"
                rows.append(Row("", item.get("name", ""), detail, False, kind))
                continue
            if kind == "shows":
                for episode in item.get("episodes", []):
                    rows.append(_playable(episode, kind, prefix=item.get("name", "")))
                continue
            rows.append(_playable(item, kind))
    if available_only:
        rows = [r for r in rows if r.can_add or not r.key]
    return rows


def _playable(item: dict, kind: str, prefix: str = "") -> Row:
    copies = item.get("copies") or []
    bits = [str(x) for x in (item.get("year"), item.get("artist"), item.get("album")) if x]
    place = where(copies)
    subtitle = " - ".join([*bits, place] if place else bits)
    title = item.get("title") or "Untitled"
    if prefix:
        title = f"{prefix}: {title}"
    return Row(str(item.get("id", "")), title, subtitle,
               bool(item.get("id")) and any(c.get("online") for c in copies), kind)
