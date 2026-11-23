"""Local full-text search over the library index (issue #409).

FTS5 (diacritic-insensitive) with a trigram fallback for substrings and typos,
BM25 ranking with deterministic boosts, and grouped results.
"""
from __future__ import annotations

import base64
import binascii
import sqlite3
import time

import search_query

DEADLINE = 0.25
PROGRESS_OPS = 10000
COLS = ("content_key", "kind", "title", "sort_title", "year", "show", "season", "episode",
        "artist", "album", "duration", "folder_id")
REPLICA_COLS = (*COLS[:-1], "origin_id", "folder_label", "rel_path")


class Source:
    """Which tables a query runs against (local index or peer replicas)."""

    def __init__(self, table: str, fts: str, tri: str, cols: tuple[str, ...]) -> None:
        self.table, self.fts, self.tri, self.cols = table, fts, tri, cols
        self.select = ", ".join(f"e.{c}" for c in cols)


LOCAL = Source("entries", "entries_fts", "entries_tri", COLS)
REPLICA = Source("rentries", "rentries_fts", "rentries_tri", REPLICA_COLS)
SELECT = LOCAL.select

SCHEMA = """
PRAGMA recursive_triggers=ON;
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, show, artist, album, album_artist, genre,
    content='entries', tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE IF NOT EXISTS entries_tri USING fts5(
    sort_title, content='entries', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
  INSERT INTO entries_fts(rowid,title,show,artist,album,album_artist,genre)
    VALUES(new.rowid,new.title,new.show,new.artist,new.album,new.album_artist,new.genre);
  INSERT INTO entries_tri(rowid,sort_title) VALUES(new.rowid,new.sort_title);
END;
CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
  INSERT INTO entries_fts(entries_fts,rowid,title,show,artist,album,album_artist,genre)
    VALUES('delete',old.rowid,old.title,old.show,old.artist,old.album,old.album_artist,old.genre);
  INSERT INTO entries_tri(entries_tri,rowid,sort_title) VALUES('delete',old.rowid,old.sort_title);
END;
"""


INDEXES = "CREATE INDEX IF NOT EXISTS entries_kind_year ON entries(kind, year, sort_title);"


def ensure_schema(conn: sqlite3.Connection) -> None:
    fresh = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='entries_fts'").fetchone() is None
    conn.executescript(SCHEMA + INDEXES)
    if fresh:
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO entries_tri(entries_tri) VALUES('rebuild')")
    conn.commit()


def _filter_sql(filters: dict[str, str]) -> tuple[str, list]:
    clauses: list[str] = []
    args: list = []
    kind = filters.get("kind")
    if kind in ("music", "video", "photo"):
        clauses.append("e.kind=?")
        args.append("music" if kind == "music" else kind)
    elif kind == "film":
        clauses.append("e.kind='video' AND e.show IS NULL")
    elif kind == "show":
        clauses.append("e.kind='video' AND e.show IS NOT NULL")
    years = search_query.year_range(filters.get("year", ""))
    if years:
        clauses.append("e.year BETWEEN ? AND ?")
        args += list(years)
    return ("".join(f" AND ({c})" for c in clauses), args)


def run(conn: sqlite3.Connection, text: object, limit: int = 50, offset: int = 0,
        *, deadline: float = DEADLINE, clock=time.monotonic,
        source: Source = LOCAL) -> tuple[list[dict], bool]:
    """Return (rows ranked best first, partial)."""
    query = search_query.parse(text)
    extra, args = _filter_sql(query.filters)

    def _row(values) -> dict:
        return dict(zip(source.cols, values))
    select, table, fts, tri = source.select, source.table, source.fts, source.tri
    column_terms = []
    for column in ("artist", "album"):
        words = search_query.parse(query.filters.get(column, "")).terms
        if words:
            column_terms.append(f'{column} : "{" ".join(words)}"')
    stop = clock() + deadline
    conn.set_progress_handler(lambda: 1 if clock() > stop else 0, PROGRESS_OPS)
    rows: list[tuple[float, dict]] = []
    try:
        if query.terms or column_terms:
            match = " ".join([search_query.fts_expression(query.terms), *column_terms]).strip()
            for r in conn.execute(
                    f"SELECT {select}, bm25({fts},10,6,6,5,4,1) FROM {fts} "
                    f"JOIN {table} e ON e.rowid={fts}.rowid "
                    f"WHERE {fts} MATCH ?{extra} LIMIT 500", [match, *args]):
                rows.append((r[-1], _row(r[:-1])))
            # Typo tolerance only for loose text: an artist:/album: filter means exact intent.
            if (query.terms and not column_terms and len(rows) < 5
                    and len(query.text.replace(" ", "")) >= 3):
                have = {row["content_key"] for _s, row in rows}
                grams = sorted(search_query.trigrams(query.text))
                if grams:
                    expr = " OR ".join(f'"{g}"' for g in grams)
                    for r in conn.execute(
                            f"SELECT {select}, bm25({tri}) FROM {tri} "
                            f"JOIN {table} e ON e.rowid={tri}.rowid "
                            f"WHERE {tri} MATCH ?{extra} LIMIT 200", [expr, *args]):
                        row = _row(r[:-1])
                        if row["content_key"] in have:
                            continue
                        overlap = len(set(grams) & search_query.trigrams(row["sort_title"]))
                        if overlap / len(grams) >= 0.5:
                            rows.append((10.0 + r[-1], row))
        elif query.filters:
            for r in conn.execute(
                    f"SELECT {select} FROM {table} e WHERE 1=1{extra} "
                    "ORDER BY e.sort_title LIMIT 500", args):
                rows.append((0.0, _row(r)))
        else:
            return [], False
    except sqlite3.OperationalError:
        return [], True
    finally:
        conn.set_progress_handler(None, 0)
    typed = query.text
    scored = []
    for score, row in rows:
        title = search_query.normalise(row["title"])
        if typed and title == typed:
            score -= 5
        elif typed and title.startswith(typed):
            score -= 3
        scored.append((score, row["sort_title"], row["content_key"], row))
    scored.sort(key=lambda t: t[:3])
    return [t[3] for t in scored][offset:offset + limit + 1], False


def _item(row: dict) -> dict:
    return {"id": row["content_key"], "title": row["title"], "kind": row["kind"],
            "year": row["year"], "artist": row["artist"], "album": row["album"],
            "duration": row["duration"], "show": row["show"],
            "season": row["season"], "episode": row["episode"],
            "copies": row.get("copies") or [{"origin": "local", "online": True}]}


_BLANK = {c: None for c in (*REPLICA_COLS, "sort_title")}


def group(rows: list[dict]) -> list[dict]:
    rows = [{**_BLANK, **row} for row in rows]  # peers may omit optional fields
    films, songs, other = [], [], []
    shows: dict[str, dict] = {}
    artists: dict[str, int] = {}
    albums: dict[tuple, int] = {}
    for row in rows:
        if row["kind"] == "music":
            songs.append(_item(row))
            if row["artist"]:
                artists[row["artist"]] = artists.get(row["artist"], 0) + 1
            if row["album"]:
                key = (row["album"], row["artist"])
                albums[key] = albums.get(key, 0) + 1
        elif row["show"]:
            show = shows.setdefault(row["show"], {"id": "sh:" + row["show"].casefold(),
                                                   "name": row["show"], "count": 0, "episodes": []})
            show["count"] += 1
            if len(show["episodes"]) < 3:
                show["episodes"].append(_item(row))
        elif row["kind"] == "video":
            films.append(_item(row))
        else:
            other.append(_item(row))
    groups = []
    if films:
        groups.append({"type": "films", "items": films})
    if shows:
        groups.append({"type": "shows", "items": list(shows.values())})
    if artists:
        groups.append({"type": "artists", "items": [
            {"id": "ar:" + a.casefold(), "name": a, "count": n}
            for a, n in sorted(artists.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]})
    if albums:
        groups.append({"type": "albums", "items": [
            {"id": "al:" + a.casefold(), "name": a, "artist": ar, "count": n}
            for (a, ar), n in sorted(albums.items(), key=lambda kv: (-kv[1], kv[0][0]))[:5]]})
    if songs:
        groups.append({"type": "songs", "items": songs})
    if other:
        groups.append({"type": "other", "items": other})
    return groups


def search(conn: sqlite3.Connection, text: object, limit: int = 50, cursor: str | None = None,
           **kwargs) -> dict:
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError, OverflowError):
        limit = 50
    # The local fallback API receives the same untrusted cursor as federated
    # search. Do not accept signed/ambiguous offsets or unbounded integers.
    offset = 0
    if isinstance(cursor, str) and 0 < len(cursor) <= 16:
        try:
            raw = base64.b64decode(cursor, altchars=b"-_", validate=True)
            if (0 < len(raw) <= 6 and raw.isascii() and raw.isdigit()
                    and (raw == b"0" or not raw.startswith(b"0"))
                    and base64.urlsafe_b64encode(raw).decode() == cursor):
                candidate = int(raw)
                if candidate <= 200000:  # maximum indexed entries per node
                    offset = candidate
        except (ValueError, UnicodeError, binascii.Error):
            pass
    rows, partial = run(conn, text, limit, offset, **kwargs)
    # An expired cursor from a changed index must not strand a user on an
    # empty page; only retry when the search genuinely finished (not partial).
    if offset and not rows and not partial:
        offset = 0
        rows, partial = run(conn, text, limit, offset, **kwargs)
    more = len(rows) > limit
    page = rows[:limit]
    nxt = base64.urlsafe_b64encode(str(offset + limit).encode()).decode() if more else None
    return {"q": str(text)[:search_query.MAX_QUERY], "partial": partial,
            "groups": group(page), "next": nxt}
