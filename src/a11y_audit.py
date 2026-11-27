"""Desktop accessibility checks (#449). Pure, GTK-free; the AT-SPI walker feeds it plain dicts.

A node is ``{role, name, description?, value_text?, focusable?, children?}``. ``audit`` returns findings for
unnamed interactive widgets, range widgets (seekbar/volume) without value text, and unlabeled icon buttons.
``row_label`` builds the queue-row announcement ("Title, 3 of 12, playing"). ``scaled_fits`` flags text that
would clip at a given text-scale for a minimum window width.
"""
from __future__ import annotations

INTERACTIVE = {"push button", "toggle button", "check box", "radio button", "menu item", "link", "combo box", "text", "entry",
               "slider", "scroll bar", "spin button", "switch", "tab", "page tab"}
RANGE = {"slider", "scroll bar", "spin button", "progress bar", "level bar"}
MAX_NODES = 20_000
STATES = {"playing": "playing", "paused": "paused", "next": "up next", "played": "played", "error": "unavailable"}


def row_label(title: str, position: int, total: int, state: str | None = None) -> str:
    """Accessible name for a queue row: title, position, state."""
    parts = [(title or "Untitled").strip()[:120] or "Untitled", f"{max(1, position)} of {max(total, position, 1)}"]
    if state in STATES:
        parts.append(STATES[state])
    return ", ".join(parts)


def audit(tree: dict) -> list[dict]:
    """-> [{path, role, problem}] ; empty means the tree passes."""
    out: list[dict] = []
    seen = 0
    stack = [(tree, "")]
    while stack:
        node, path = stack.pop()
        seen += 1
        if seen > MAX_NODES or not isinstance(node, dict):
            if seen > MAX_NODES:
                out.append({"path": path, "role": "", "problem": "tree too large to audit"})
                break
            continue
        role = str(node.get("role", "")).lower()
        name = str(node.get("name") or "").strip()
        here = f"{path}/{role or '?'}[{name or '-'}]"
        if role in INTERACTIVE and not name and not str(node.get("description") or "").strip():
            out.append({"path": here, "role": role, "problem": "unnamed interactive widget"})
        if role in RANGE and role != "progress bar" and not str(node.get("value_text") or "").strip():
            out.append({"path": here, "role": role, "problem": "range widget has no value text"})
        if role == "push button" and name and len(name) <= 1 and not str(node.get("description") or "").strip():
            out.append({"path": here, "role": role, "problem": "icon-only button name is a glyph, not a label"})
        for c in reversed(node.get("children") or []):
            stack.append((c, here))
    return sorted(out, key=lambda f: f["path"])


def scaled_fits(label_px: dict[str, float], scale: float, min_width_px: float, padding_px: float = 24.0) -> list[str]:
    """Labels whose natural width at ``scale`` (e.g. 2.0) exceeds the minimum window width."""
    return sorted(k for k, w in label_px.items() if w * scale + padding_px > min_width_px)
