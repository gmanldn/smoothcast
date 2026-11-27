"""Per-resident accessibility preferences (#389). Pure.

``clean`` enforces the resident record schema ``a11y``. ``choose`` picks audio / audio-description /
subtitle tracks from a stream layout; the *starter's* prefs apply, and ``add_my_captions`` turns captions
on for a second resident without touching audio. Bad AD flags can be overridden per content_key.
``dialogue_filter`` maps boost 0-3 to an ffmpeg audio filter; ``audit_html`` is a static a11y check.
Tracks: {index, language, title?, ad?, hearing_impaired?, forced?}.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

CAPTIONS = ("always", "auto", "off")
SIZES = ("small", "medium", "large", "xlarge")
STYLES = ("default", "outline", "box", "yellow")
DEFAULT = {"captions": "auto", "caption_size": "medium", "caption_style": "default", "ad_track": False,
           "dialogue_boost": 0, "large_text": False, "reduce_motion": False}
NO_CAPTIONS_MSG = "No captions for this film."
_AD = re.compile(r"audio.?descri|descriptive|visually.?impaired|\bAD\b", re.I)


def clean(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT)
    if r.get("captions") in CAPTIONS:
        out["captions"] = r["captions"]
    if r.get("caption_size") in SIZES:
        out["caption_size"] = r["caption_size"]
    if r.get("caption_style") in STYLES:
        out["caption_style"] = r["caption_style"]
    for k in ("ad_track", "large_text", "reduce_motion"):
        if type(r.get(k)) is bool:
            out[k] = r[k]
    if type(r.get("dialogue_boost")) is int and 0 <= r["dialogue_boost"] <= 3:
        out["dialogue_boost"] = r["dialogue_boost"]
    return out


def is_ad(t: dict) -> bool:
    return bool(t.get("ad")) or bool(_AD.search(t.get("title") or ""))


def _lang(t: dict) -> str:
    return (t.get("language") or "").lower()[:2]


def choose(audio: list[dict], subs: list[dict], a11y: dict, langs: list[str], content_key: str = "",
           ad_overrides: dict | None = None, toasted: set | None = None) -> dict:
    """-> {audio, subtitle, toast}: indexes (or None). Pure over the layout."""
    a = clean(a11y)
    langs = [l.lower()[:2] for l in langs or []]
    ov = (ad_overrides or {}).get(content_key)             # manual per-film choice beats a wrong AD flag
    real = [t for t in audio if (not is_ad(t) if ov is None else t["index"] != ov)]
    pool = real or audio
    pick = next((t for l in langs for t in pool if _lang(t) == l), pool[0] if pool else None)
    ad = None
    if a["ad_track"]:
        cands = [t for t in audio if (t["index"] == ov if ov is not None else is_ad(t))]
        ad = next((t for t in cands if pick and _lang(t) == _lang(pick)), cands[0] if cands else None)
    chosen_audio = ad or pick
    want_subs = a["captions"] == "always" or (a["captions"] == "auto" and bool(pick) and langs and _lang(pick) not in langs)
    sub, toast = None, None
    if want_subs:
        usable = [s for s in subs if not s.get("forced")] or []
        hi = [s for s in usable if s.get("hearing_impaired")]
        order = (hi + [s for s in usable if s not in hi]) if a["captions"] == "always" else usable
        sub = next((s for l in langs for s in order if _lang(s) == l), order[0] if order else None)
        if sub is None and a["captions"] == "always" and (toasted is None or content_key not in toasted):
            toast = NO_CAPTIONS_MSG
            if toasted is not None:
                toasted.add(content_key)
    return {"audio": chosen_audio["index"] if chosen_audio else None, "subtitle": sub["index"] if sub else None, "toast": toast}


def add_my_captions(current: dict, subs: list[dict], langs: list[str]) -> dict:
    """Second resident: captions on, audio selection untouched."""
    usable = [s for s in subs if not s.get("forced")]
    sub = next((s for l in langs or [] for s in usable if _lang(s) == l.lower()[:2]), usable[0] if usable else None)
    return {**current, "subtitle": sub["index"] if sub else current.get("subtitle"), "toast": None if sub else NO_CAPTIONS_MSG}


def prefs_for(starter: dict | None, guests: dict | None = None) -> dict:
    """The starter's prefs apply to the room; unknown starter -> defaults."""
    return clean((starter or {}).get("a11y"))


def dialogue_filter(boost: int) -> str:
    """ffmpeg audio filter chain: 0 none, 1-3 centre-channel lift + gentle compression."""
    b = boost if type(boost) is int and 0 <= boost <= 3 else 0
    return "" if b == 0 else f"pan=stereo|FL=FC+0.{4 + b}*FL+0.{b}*BL|FR=FC+0.{4 + b}*FR+0.{b}*BR,acompressor=ratio={1 + b}:threshold=-24dB"


class _Audit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self._btn: dict | None = None
        self.labels: set[str] = set()
        self.inputs: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label" and a.get("for"):
            self.labels.add(a["for"])
        if tag == "button" or a.get("role") == "button":
            self._btn = {"name": bool(a.get("aria-label") or a.get("title")), "text": False}
        if tag == "img" and "alt" not in a:
            self.problems.append("img without alt")
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button"):
            self.inputs.append(a)

    def handle_data(self, data):
        if self._btn is not None and data.strip():
            self._btn["text"] = True

    def handle_endtag(self, tag):
        if tag == "button" and self._btn is not None:
            if not (self._btn["name"] or self._btn["text"]):
                self.problems.append("button without accessible name")
            self._btn = None


def audit_html(html: str) -> list[str]:
    """Static a11y problems: unnamed buttons, unlabeled inputs, images without alt, tiny touch targets, motion without a guard."""
    p = _Audit()
    p.feed(html or "")
    for i in p.inputs:
        if not (i.get("aria-label") or i.get("aria-labelledby") or i.get("id") in p.labels):
            p.problems.append(f"input '{i.get('name') or i.get('id') or '?'}' without label")
    if re.search(r"animation|transition", html or "") and "prefers-reduced-motion" not in (html or ""):
        p.problems.append("animation without prefers-reduced-motion guard")
    if ".tap" in (html or "") and not re.search(r"\.tap[^{]*\{[^}]*min-(?:height|width):\s*(4[4-9]|[5-9]\d|\d{3,})px", html):
        p.problems.append("touch target below 44px")
    return p.problems
