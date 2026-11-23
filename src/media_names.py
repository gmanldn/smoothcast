"""Pure filename parsing for episodes and years (issue #408)."""
from __future__ import annotations

import re

_SXXEYY = re.compile(r"(?i)\bS(\d{1,2})[ ._-]*E(\d{1,3})(?:[ ._-]*E?\d{1,3})*\b")
_NXMM = re.compile(r"(?i)\b(\d{1,2})x(\d{2,3})\b")
_SEASON_DIR = re.compile(r"(?i)^(?:season|series|s)[ ._-]*(\d{1,2})$")
_EP_ONLY = re.compile(r"(?i)^(?:episode|ep|e)[ ._-]*(\d{1,3})\b")
_YEAR = re.compile(r"(?<!\d)(19[2-9]\d|20[0-4]\d)(?!\d)")
_JUNK = re.compile(r"(?i)\b(480p|576p|720p|1080p|2160p|4k|x264|x265|h264|h265|hevc|bluray|"
                   r"brrip|webrip|web-dl|hdtv|dvdrip|aac|ac3|dts|remux)\b.*$")


def _tidy(text: str) -> str:
    text = re.sub(r"[._]+", " ", text)
    return " ".join(text.split(" -")[0].split()).strip(" -")


def parse_episode(name: str, parent: str = "") -> tuple[str, int, int] | None:
    """Return (show, season, episode) from a file name (and its folder)."""
    stem = name.rsplit(".", 1)[0]
    match = _SXXEYY.search(stem) or _NXMM.search(stem)
    if match:
        show = _tidy(stem[:match.start()]) or _tidy(parent)
        return (show, int(match.group(1)), int(match.group(2))) if show else None
    season = _SEASON_DIR.match(parent.strip())
    episode = _EP_ONLY.match(stem.strip()) or re.match(r"(?i)^(\d{1,3})\b", stem.strip())
    if season and episode:
        return ("", int(season.group(1)), int(episode.group(1)))
    return None


def parse_year(name: str) -> int | None:
    stem = name.rsplit(".", 1)[0]
    years = _YEAR.findall(stem)
    return int(years[-1]) if years else None


def clean_title(name: str) -> str:
    """Readable title from a file name: strip extension, year/quality junk."""
    stem = name.rsplit(".", 1)[0]
    stem = _YEAR.sub(" ", _JUNK.sub("", re.sub(r"[._]+", " ", stem)))
    return " ".join(stem.replace("(", " ").replace(")", " ").replace("[", " ").replace("]", " ").split()) or name
