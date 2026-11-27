"""Intro / recap / credits markers (#377). Pure.

Phase 1: ``from_chapters`` classifies chapter titles (case-insensitive, multi-language).
Phase 2: ``common_segment`` finds the longest run of identical spectral hashes shared by two
episodes' opening hashes (hash sequences come from decoded 8 kHz mono audio; decoding is the
caller's job). ``button`` / ``auto_skip`` decide what the player shows and does, in source time.
"""
from __future__ import annotations

import re

KINDS = {
    "intro": re.compile(r"^(intro(duction)?|opening|op|title(s| sequence)?|theme|générique(\s+d.ouverture)?|vorspann|introducción|apertura|sigla|オープニング)$", re.I),
    "recap": re.compile(r"^(recap|previously( on)?|previously|résumé|rückblick|resumen|riassunto)$", re.I),
    "credits": re.compile(r"^(end\s*)?(credits?|ending|ed|outro|closing|générique(\s+de\s+fin)?|abspann|créditos|titoli di coda|エンディング)$", re.I),
}
MIN_INTRO_S, MAX_INTRO_S = 15.0, 180.0
LABEL = {"intro": "Skip intro", "recap": "Skip recap", "credits": "Skip credits"}


def classify(title: str) -> str | None:
    t = re.sub(r"[\s_]+", " ", (title or "").strip().strip("[]()-:.")).strip()
    t = re.sub(r"\s*\d+$", "", t)                        # "Intro 2", "Credits 1"
    for kind, rx in KINDS.items():
        if rx.match(t):
            return kind
    return None


def from_chapters(chapters: list[dict]) -> list[dict]:
    """chapters: {title, start, end}. Returns markers {kind, start, end, source:'chapter'}."""
    out = []
    for c in chapters or []:
        try:
            s, e = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        k = classify(c.get("title", ""))
        if k and e > s:
            out.append({"kind": k, "start": s, "end": e, "source": "chapter"})
    return out


def common_segment(a: list[int], b: list[int], hop_s: float, min_s: float = MIN_INTRO_S, max_s: float = MAX_INTRO_S) -> dict | None:
    """Longest common run of equal hashes at the SAME offset in both openings (intro starts at similar times).
    Allows a start shift of up to 60 s between episodes (cold open lengths differ)."""
    need = int(min_s / hop_s)
    best = (0, 0, 0)                                     # (length, start_a, start_b)
    max_shift = int(60 / hop_s)
    for shift in range(-max_shift, max_shift + 1):
        run = 0
        for i in range(max(0, -shift), min(len(a), len(b) - shift if shift >= 0 else len(b) - shift)):
            j = i + shift
            if 0 <= j < len(b) and a[i] == b[j]:
                run += 1
                if run > best[0]:
                    best = (run, i - run + 1, j - run + 1)
            else:
                run = 0
    if best[0] < need:
        return None
    length = min(best[0] * hop_s, max_s)
    return {"kind": "intro", "start": best[1] * hop_s, "end": best[1] * hop_s + length, "source": "audio-match", "start_b": best[2] * hop_s}


def button(markers: list[dict], position: float, duration: float | None = None) -> dict | None:
    """The skip button to show now: label + target in source seconds."""
    for m in sorted(markers, key=lambda m: m["start"]):
        if m["start"] <= position < m["end"] - 1.0:
            target = m["end"] if not (m["kind"] == "credits" and duration and m["end"] >= duration - 1) else duration
            return {"label": LABEL[m["kind"]], "kind": m["kind"], "target": target, "next_episode": m["kind"] == "credits"}
    return None


def auto_skip(marker_btn: dict | None, enabled: bool, episode_number: int, seconds_shown: float, already_skipped: set) -> bool:
    """Auto-skip is opt-in, never on a season's first episode, waits ~1 s so it isn't jarring, once per marker."""
    if not marker_btn or not enabled or episode_number <= 1:
        return False
    return seconds_shown >= 1.0 and (marker_btn["kind"], marker_btn["target"]) not in already_skipped


def merge(chapter_markers: list[dict], audio_markers: list[dict], manual: list[dict] = ()) -> list[dict]:
    """Manual beats chapters beats audio-match for the same kind."""
    chosen: dict[str, dict] = {}
    for rank, group in enumerate((audio_markers, chapter_markers, manual)):
        for m in group:
            chosen[m["kind"]] = m
    return sorted(chosen.values(), key=lambda m: m["start"])
