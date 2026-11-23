"""Pure search-query parsing for the house library (issue #409)."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

MAX_QUERY = 200
FILTER_KEYS = ("kind", "on", "year", "artist", "album")
KINDS = {"film", "show", "music", "video", "photo"}
_FILTER = re.compile(r"(?i)\b(kind|on|year|artist|album):(\"[^\"]*\"|\S+)")


@dataclass
class Query:
    terms: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(self.terms)


def normalise(text: object) -> str:
    """NFKC, casefold, accents stripped, whitespace collapsed, length capped."""
    value = unicodedata.normalize("NFKC", str(text or ""))[:MAX_QUERY]
    value = "".join(ch for ch in unicodedata.normalize("NFD", value.casefold())
                    if not unicodedata.combining(ch))
    return " ".join(value.split())


def parse(text: object) -> Query:
    raw = unicodedata.normalize("NFKC", str(text or ""))[:MAX_QUERY]
    filters: dict[str, str] = {}

    def take(match: re.Match) -> str:
        filters[match.group(1).lower()] = normalise(match.group(2).strip('"'))
        return " "

    rest = _FILTER.sub(take, raw)
    terms = [t for t in re.findall(r"[^\W_]+", normalise(rest)) if t]
    return Query(terms, filters)


def year_range(value: str) -> tuple[int, int] | None:
    """``1999`` -> (1999, 1999); ``1990s`` -> (1990, 1999)."""
    match = re.fullmatch(r"(\d{4})(s?)", value.strip())
    if not match:
        return None
    start = int(match.group(1))
    return (start, start + 9) if match.group(2) else (start, start)


def fts_expression(terms: list[str], *, prefix_last: bool = True) -> str:
    """Quote every token so FTS5 syntax in user text can never raise."""
    if not terms:
        return ""
    quoted = [f'"{t}"' for t in terms]
    if prefix_last:
        quoted[-1] += "*"
    return " ".join(quoted)


def trigrams(text: str) -> set[str]:
    text = normalise(text).replace(" ", "")
    return {text[i:i + 3] for i in range(len(text) - 2)}
