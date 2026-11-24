"""Bounded local subtitle search over user-supplied folders (SC-042 / #51).

Pure and GTK-free. The search never downloads, never reads subtitle contents,
never follows symlinks, and stops after a small entry budget so a huge or
hostile folder cannot stall a cast start. Only sidecar files whose name
matches the film stem are considered; similarly named films are rejected.
"""
from __future__ import annotations

from collections.abc import Iterable
import os
from pathlib import Path
import re

SUBTITLE_EXTS = frozenset({".srt", ".vtt", ".ttml", ".ass", ".ssa"})
CAST_SUBTITLE_EXTS = frozenset({".srt", ".vtt", ".ttml"})
MAX_FOLDERS = 8
MAX_PATH = 4096
MAX_ENTRIES = 2000
MAX_DEPTH = 4
MAX_CANDIDATES = 8
_LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[a-z]{2})?")


def clean_folders(value: object) -> list[str]:
    """Validated, deduplicated user folders; malformed rows are dropped."""
    if not isinstance(value, (list, tuple)):
        return []
    folders: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, os.PathLike):
            item = os.fspath(item)
        if not isinstance(item, str) or len(item) > MAX_PATH:
            continue
        expanded = os.path.expanduser(item.strip())
        if not expanded or not os.path.isabs(expanded):
            continue
        key = os.path.normcase(os.path.normpath(expanded))
        if key in seen:
            continue
        seen.add(key)
        folders.append(expanded)
        if len(folders) >= MAX_FOLDERS:
            break
    return folders


def language_of(path: Path | str, media_stem: str = "") -> str:
    """Language tag in the sidecar suffix, or an empty string.

    Tokens inside the film title are ignored when ``media_stem`` is supplied,
    so ``It.2017.en.srt`` reports ``en`` rather than ``it``.
    """
    candidate = Path(path)
    stem = candidate.stem.casefold()
    if media_stem:
        prefix = media_stem.casefold()
        if stem == prefix:
            return ""
        if not stem.startswith(prefix + "."):
            return ""
        tokens = stem[len(prefix) + 1:].split(".")
    else:
        tokens = stem.split(".")
    for token in tokens:
        if _LANGUAGE.fullmatch(token):
            return token
    return ""


def _matches(stem: str, media_stem: str) -> bool:
    return stem == media_stem or stem.startswith(media_stem + ".")


def _scan(folder: str, media_stem: str):
    """Yield matching subtitle paths under *folder*, bounded and symlink-free."""
    stack = [(Path(folder), 0)]
    seen = 0
    while stack:
        directory, depth = stack.pop()
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for entry in entries:
                seen += 1
                if seen > MAX_ENTRIES:
                    return
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth < MAX_DEPTH and not entry.name.startswith("."):
                            stack.append((Path(entry.path), depth + 1))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                suffix = os.path.splitext(entry.name)[1].lower()
                if suffix not in SUBTITLE_EXTS:
                    continue
                stem = os.path.splitext(entry.name)[0].casefold()
                if _matches(stem, media_stem):
                    yield Path(entry.path)


def _rank(path: Path, media_stem: str, wanted: set[str]):
    stem = path.stem.casefold()
    language = language_of(path, media_stem)
    suffix = path.suffix.lower()
    return (
        0 if language and language in wanted else 1,
        0 if stem == media_stem else 1,
        0 if suffix in CAST_SUBTITLE_EXTS else 1,
        0 if suffix == ".srt" else 1,
        str(path).casefold(),
    )


def candidates(media: Path | str, folders: object,
               preferred: Iterable[str] = ()) -> list[Path]:
    """Ranked matching sidecars from the configured search folders."""
    media_path = Path(media)
    media_stem = media_path.stem.casefold()
    wanted = {lang.casefold() for lang in preferred
              if isinstance(lang, str) and lang}
    found: list[Path] = []
    for folder in clean_folders(folders):
        found.extend(_scan(folder, media_stem))
        if len(found) >= MAX_CANDIDATES * 2:
            break
    unique: dict[str, Path] = {}
    for path in found:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        unique.setdefault(key, path)
    ordered = sorted(unique.values(), key=lambda path: _rank(path, media_stem, wanted))
    return ordered[:MAX_CANDIDATES]


def find_subtitle(media: Path | str, folders: object,
                  preferred: Iterable[str] = ()) -> Path | None:
    """Best matching local sidecar, or None; never raises for bad folders."""
    found = candidates(media, folders, preferred)
    return found[0] if found else None