"""Deterministic synthetic libraries for performance gates (#415).

Rows go straight into SQLite (no files on disk), seeded so every run measures
the same data. Titles come from word lists so FTS and trigram behave like real
film, show and music libraries.
"""
from __future__ import annotations

import random
import sqlite3

WORDS = ("night day dark light red blue river mountain city lost found last first love war peace "
         "king queen secret silent golden broken wild young old summer winter midnight morning "
         "ocean desert garden shadow storm fire ice stone paper glass iron silver crimson hollow "
         "paddington amelie alien arrival thriller dancing queen casablanca vertigo metropolis").split()
ARTISTS = ("ABBA", "Queen", "Miles Davis", "Björk", "Nina Simone", "Daft Punk", "Radiohead",
           "Aretha Franklin", "Kraftwerk", "Fela Kuti", "Joni Mitchell", "Sigur Rós")
GENRES = ("Rock", "Jazz", "Pop", "Soul", "Electronic", "Classical", "Drama", "Comedy", "Sci-Fi")


def titles(count: int, seed: int) -> list[tuple]:
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        title = " ".join(rng.choice(WORDS).title() for _ in range(rng.randint(1, 4)))
        music = rng.random() < 0.6
        rows.append((f"qh:{seed:08x}{i:024x}", "music" if music else "video", title,
                     title.casefold(), rng.randint(1950, 2024),
                     None if music or rng.random() < 0.7 else title.split()[0],
                     rng.choice(ARTISTS) if music else None,
                     (f"{rng.choice(WORDS).title()} {rng.choice(WORDS).title()}" if music else None),
                     rng.choice(GENRES), float(rng.randint(60, 7200))))
    return rows


def fill_replica(conn: sqlite3.Connection, origin_id: str, count: int, seed: int) -> None:
    """Bulk-load ``count`` entries into ``rentries`` (FTS triggers keep indexes in sync)."""
    conn.executemany(
        "INSERT INTO rentries(origin_id,content_key,kind,title,sort_title,year,show,artist,album,"
        "genre,duration,folder_label,rel_path) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(origin_id, k, kind, t, st, y, show, artist, album, genre, dur, "Lib", f"{k}.mkv")
         for k, kind, t, st, y, show, artist, album, genre, dur in titles(count, seed)])
    conn.commit()


def fill_local(conn: sqlite3.Connection, count: int, seed: int) -> None:
    conn.executemany(
        "INSERT INTO entries(content_key,folder_id,rel_path,kind,title,sort_title,year,show,artist,"
        "album,genre,duration,size,mtime_ns,ino,updated_seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(k, "f_1", f"{k}.mkv", kind, t, st, y, show, artist, album, genre, dur, 1, 1, str(n), 0)
         for n, (k, kind, t, st, y, show, artist, album, genre, dur) in enumerate(titles(count, seed))])
    conn.commit()
