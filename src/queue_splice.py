"""Incremental queue model updates (#462). Pure, GTK-free: old keys -> new keys as ``splice`` operations.

Each op is ``(position, n_removed, added)`` and is applied in order, exactly like ``Gio.ListStore.splice``.
Common edits are tiny: append/insert/remove = 1 op touching only that span, single move = 2 ops of 1 item.
Anything messier collapses to one splice of the changed middle, never a rebuild of the whole list.
"""
from __future__ import annotations

Op = tuple[int, int, list]


def splice_ops(old: list, new: list) -> list[Op]:
    n_old, n_new = len(old), len(new)
    lo = 0
    limit = min(n_old, n_new)
    while lo < limit and old[lo] == new[lo]:
        lo += 1
    hi = 0
    while hi < limit - lo and old[n_old - 1 - hi] == new[n_new - 1 - hi]:
        hi += 1
    o_mid, n_mid = old[lo:n_old - hi], new[lo:n_new - hi]
    if not o_mid and not n_mid:
        return []
    if len(o_mid) >= 2 and len(o_mid) == len(n_mid):
        if o_mid[1:] == n_mid[:-1] and o_mid[0] == n_mid[-1]:          # one item moved down
            return [(lo, 1, []), (lo + len(o_mid) - 1, 0, [n_mid[-1]])]
        if o_mid[:-1] == n_mid[1:] and o_mid[-1] == n_mid[0]:          # one item moved up
            return [(lo + len(o_mid) - 1, 1, []), (lo, 0, [n_mid[0]])]
    return [(lo, len(o_mid), list(n_mid))]


def apply_ops(items: list, ops: list[Op]) -> list:
    out = list(items)
    for pos, removed, added in ops:
        out[pos:pos + removed] = added
    return out


def touched(ops: list[Op]) -> int:
    """Rows the view must rebind: removed + added."""
    return sum(r + len(a) for _, r, a in ops)
