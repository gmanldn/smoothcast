"""Persistent audio and subtitle language preferences (issue #38 / SC-029).

GTK-free, standard library only. A user states ordered language preferences in
``config.json``; ``streamer`` consults them when a film has no explicit per-file
track choice. With no preferences set nothing changes: the callers fall back to
the previous behaviour (default audio track; forced, then default, then English
subtitles).

Config keys (all optional)::

    "preferred_audio_languages":    ["ja", "en"]
    "preferred_subtitle_languages": ["en"]
    "language_overrides": {"some show": {"audio": ["fr"], "subtitles": ["en"]}}

Language names are ISO 639-1/2 codes or English names, with optional regions
(``en``, ``eng``, ``English``, ``pt-BR`` all work). Overrides are keyed by the
series name derived from a file name such as ``Some.Show.S01E02.mkv``; a file
without an episode marker is a film and never matches an override.

Policy
* Audio: the first preference with a matching track wins; commentary and audio
  description tracks are only used when nothing else matches; ties go to the
  file's default track, then the lowest index.
* Subtitles distinguish *forced* tracks (foreign-language dialogue only) from
  *full* ones. If the chosen audio is already in a preferred subtitle language
  the viewer understands it: use that language's forced track if there is one,
  otherwise no subtitles. If the audio is in another language, use the first
  preferred language's full track (a forced one only if no full track exists).
* If no preference matches, the decision is left to the caller's old behaviour.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Protocol, Sequence, TypeVar

MAX_LANGUAGES = 8
MAX_LANGUAGE_LEN = 40
MAX_OVERRIDES = 64
MAX_SERIES_LEN = 120

# Canonical code is ISO 639-2/T. Each row lists every alias we accept.
_LANGUAGES = {
    "eng": "en english", "fra": "fr fre french", "deu": "de ger german",
    "spa": "es spanish castilian", "ita": "it italian", "por": "pt portuguese",
    "jpn": "ja japanese", "kor": "ko korean", "zho": "zh chi chinese mandarin cmn yue cantonese",
    "rus": "ru russian", "ara": "ar arabic", "hin": "hi hindi", "nld": "nl dut dutch flemish",
    "swe": "sv swedish", "nor": "no norwegian nob nno", "dan": "da danish",
    "fin": "fi finnish", "pol": "pl polish", "tur": "tr turkish", "ces": "cs cze czech",
    "ell": "el gre greek", "heb": "he hebrew", "hun": "hu hungarian",
    "ron": "ro rum romanian", "tha": "th thai", "vie": "vi vietnamese",
    "ind": "id indonesian", "ukr": "uk ukrainian", "cat": "ca catalan",
    "bul": "bg bulgarian", "hrv": "hr croatian", "srp": "sr serbian",
    "slk": "sk slo slovak", "slv": "sl slovenian", "fas": "fa per persian farsi",
    "isl": "is ice icelandic", "lav": "lv latvian", "lit": "lt lithuanian",
    "est": "et estonian", "msa": "ms may malay", "tam": "ta tamil", "tel": "te telugu",
}
_ALIASES = {alias: code for code, row in _LANGUAGES.items() for alias in (code, *row.split())}
_UNDETERMINED = frozenset({"", "und", "mis", "mul", "zxx", "qaa", "unknown", "undetermined"})
_COMMENTARY = re.compile(r"commentary|audio description|descriptive|\bAD\b|visually impaired", re.I)
_EPISODE = re.compile(r"^(?P<name>.+?)[\s\-]+(?:s\d{1,2}\s?e\d{1,3}|\d{1,2}x\d{2,3})(?![0-9a-z])", re.I)


def normalize(language: object) -> str:
    """Canonical lower-case code for a language tag or name; '' if undetermined."""
    if not isinstance(language, str):
        return ""
    text = re.split(r"[-_]", language.strip().lower(), maxsplit=1)[0]
    if text in _UNDETERMINED:
        return ""
    return _ALIASES.get(text, text if len(text) <= MAX_LANGUAGE_LEN else "")


def series_key(path: object) -> str | None:
    """Lower-case series name from ``Show.Name.S01E02...`` / ``Show 1x02``; None for films."""
    stem = Path(str(path)).stem if path else ""
    match = _EPISODE.match(re.sub(r"[._]+", " ", stem))
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group("name")).strip(" -").lower()
    return name[:MAX_SERIES_LEN] or None


def clean_languages(value: object) -> list[str]:
    """A bounded list of distinct canonical codes; junk entries are dropped."""
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value[:MAX_LANGUAGES * 4]:
        code = normalize(item)
        if code and code not in result:
            result.append(code)
        if len(result) == MAX_LANGUAGES:
            break
    return result


def clean_overrides(value: object) -> dict[str, dict[str, list[str]]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    for key, entry in list(value.items())[:MAX_OVERRIDES * 2]:
        if not isinstance(key, str) or not key.strip() or not isinstance(entry, dict):
            continue
        cleaned = {name: clean_languages(entry.get(name)) for name in ("audio", "subtitles")
                   if name in entry}
        if any(cleaned.values()):
            result[key.strip().lower()[:MAX_SERIES_LEN]] = cleaned
        if len(result) == MAX_OVERRIDES:
            break
    return result


@dataclass(frozen=True)
class LanguagePrefs:
    audio: tuple[str, ...] = ()
    subtitles: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.audio or self.subtitles)


def prefs_from_config(config: object, series: str | None = None) -> LanguagePrefs:
    """Global preferences, with a series override replacing whichever lists it sets."""
    raw: dict[str, Any] = config if isinstance(config, dict) else {}
    audio = clean_languages(raw.get("preferred_audio_languages"))
    subtitles = clean_languages(raw.get("preferred_subtitle_languages"))
    override = clean_overrides(raw.get("language_overrides")).get(series or "")
    if override:
        audio = override.get("audio") or audio
        subtitles = override.get("subtitles") or subtitles
    return LanguagePrefs(tuple(audio), tuple(subtitles))


def config_path() -> Path:
    import paths  # one place decides where config lives (#701)
    return paths.config_dir() / "config.json"


def load(media_path: object = None, path: Path | None = None) -> LanguagePrefs:
    """Preferences for *media_path* from config.json; never raises, no side effects."""
    try:
        raw = json.loads((path or config_path()).read_text())
    except (OSError, ValueError, RuntimeError):
        return LanguagePrefs()
    return prefs_from_config(raw, series_key(media_path))


# --- track selection (duck-typed so streamer's dataclasses need no import) ----

class _Track(Protocol):
    @property
    def index(self) -> int: ...
    @property
    def language(self) -> str: ...
    @property
    def default(self) -> bool: ...


class _AudioTrack(_Track, Protocol):
    @property
    def title(self) -> str: ...


class _SubtitleTrack(_Track, Protocol):
    @property
    def forced(self) -> bool: ...


A = TypeVar("A", bound=_AudioTrack)
S = TypeVar("S", bound=_SubtitleTrack)


def choose_audio(tracks: Sequence[A], prefs: LanguagePrefs) -> A | None:
    """The preferred audio track, or None when no preference applies."""
    for wanted in prefs.audio:
        matches = [t for t in tracks if normalize(t.language) == wanted]
        if matches:
            return min(matches, key=lambda t: (bool(_COMMENTARY.search(t.title or "")),
                                               not t.default, t.index))
    return None


class Decision:
    """Outcome of ``choose_subtitle``: ``decided`` False means 'use the old default'."""

    __slots__ = ("track", "decided")

    def __init__(self, track: Any = None, decided: bool = False) -> None:
        self.track, self.decided = track, decided

    def __repr__(self) -> str:
        return f"Decision(track={self.track!r}, decided={self.decided})"


UNDECIDED = Decision()


def choose_subtitle(tracks: Sequence[S], prefs: LanguagePrefs,
                    audio: _Track | None) -> Decision:
    """Pick among supported text or bitmap tracks using the forced/full policy."""
    if not prefs.subtitles:
        return UNDECIDED
    audio_language = normalize(audio.language) if audio is not None else ""
    if audio_language and audio_language in prefs.subtitles:
        forced = [t for t in tracks if t.forced and normalize(t.language) == audio_language]
        return Decision(min(forced, key=lambda t: (not t.default, t.index)) if forced else None, True)
    for wanted in prefs.subtitles:
        full = [t for t in tracks if not t.forced and normalize(t.language) == wanted]
        if full:
            return Decision(min(full, key=lambda t: (not t.default, t.index)), True)
        forced = [t for t in tracks if t.forced and normalize(t.language) == wanted]
        if forced:
            return Decision(min(forced, key=lambda t: (not t.default, t.index)), True)
    return UNDECIDED
