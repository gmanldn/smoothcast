"""Browse shared library folders as a tree (issue #413).

Pure SQL helpers over the local index and the peer replicas: group each
entry's *relative* path into directories and files one level at a time, paged
and bounded. Absolute paths never exist at this layer.
"""
from __future__ import annotations

import re
import sqlite3

import search_engine

PAGE = 100
MAX_PATH = 512
_BAD_SEGMENT = re.compile(r"(^|/)\.\.?(/|$)")


class BrowseError(ValueError):
    """The requested path is not a valid relative folder path."""


def clean_path(path: object) -> str:
    """Normalise a client path to ``''`` or ``'dir/sub/'``; refuse anything unsafe."""
    text = str(path or "").replace("\\", "/")
    if len(text) > MAX_PATH or text.startswith("/") or "\x00" in text or _BAD_SEGMENT.search(text):
        raise BrowseError("That folder path is not valid.")
    text = text.strip("/")
    return text + "/" if text else ""


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def listing(conn: sqlite3.Connection, table: str, scope_sql: str, scope_args: list,
            path: str, offset: int = 0, limit: int = PAGE) -> tuple[list[dict], list[str], bool]:
    """One folder level: (directories with counts, content keys of files, more?)."""
    prefix = clean_path(path)
    cut = len(prefix) + 1
    rest = f"substr(rel_path, {cut})"
    rows = conn.execute(
        f"SELECT seg, is_dir, MIN(content_key), COUNT(*) FROM ("
        f" SELECT CASE WHEN instr({rest}, '/') > 0 THEN substr({rest}, 1, instr({rest}, '/') - 1)"
        f"        ELSE {rest} END AS seg,"
        f"        instr({rest}, '/') > 0 AS is_dir, content_key"
        f" FROM {table} WHERE {scope_sql} AND rel_path LIKE ? ESCAPE '\\')"
        f" GROUP BY seg, is_dir ORDER BY is_dir DESC, seg LIMIT ? OFFSET ?",
        [*scope_args, _like_prefix(prefix), limit + 1, offset]).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    dirs = [{"name": seg, "count": count} for seg, is_dir, _key, count in rows if is_dir and seg]
    keys = [key for _seg, is_dir, key, _count in rows if not is_dir]
    return dirs, keys, more


def rows_for(conn: sqlite3.Connection, source: search_engine.Source, scope_sql: str,
             scope_args: list, keys: list[str]) -> list[dict]:
    if not keys:
        return []
    marks = ",".join("?" * len(keys))
    cur = conn.execute(
        f"SELECT {source.select} FROM {source.table} e WHERE {scope_sql}"
        f" AND e.content_key IN ({marks}) ORDER BY e.sort_title", [*scope_args, *keys])
    return [dict(zip(source.cols, row)) for row in cur.fetchall()]


def folder_summaries(conn: sqlite3.Connection, table: str, where: str, args: list,
                     label_col: str) -> list[dict]:
    rows = conn.execute(
        f"SELECT {label_col}, COUNT(*) FROM {table} WHERE {where} GROUP BY {label_col} "
        f"ORDER BY {label_col}", args).fetchall()
    return [{"label": label, "count": count} for label, count in rows if label]
