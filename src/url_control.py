"""Validate and classify user-provided remote media URLs before invoking catt.

SmoothCast sends a URL straight to the receiver, so only direct HTTP(S) media
is useful. Site pages such as YouTube watch links are classified explicitly
and rejected with an actionable message instead of being mistaken for media
or claimed as universally supported.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

# A page host is never a media URL, even when its path looks like a file.
SITE_PAGES: dict[str, str] = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "m.youtube.com": "YouTube",
    "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "twitch.tv": "Twitch",
    "netflix.com": "Netflix",
    "primevideo.com": "Prime Video",
    "disneyplus.com": "Disney+",
    "hulu.com": "Hulu",
    "bilibili.com": "Bilibili",
    "soundcloud.com": "SoundCloud",
    "spotify.com": "Spotify",
}

MEDIA_EXTENSIONS = frozenset({
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".ts", ".m3u8",
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wav",
})

SITE_PAGE_REMEDY = (
    "SmoothCast casts direct media files only. Paste a direct HTTP(S) media "
    "URL (for example an .mp4 or .m3u8 link) or download the video first."
)


class MediaUrlError(ValueError):
    """A URL cannot be sent to a receiver as media."""


@dataclass(frozen=True)
class MediaUrl:
    """A validated remote URL and what kind of resource it appears to be."""

    url: str
    host: str
    kind: str  # "direct" when the path names a media file, else "unknown"

    @property
    def is_direct(self) -> bool:
        return self.kind == "direct"


def _site_page(host: str) -> str:
    """Return the site name when *host* is (a subdomain of) a known page host."""
    host = host.lower().rstrip(".")
    for domain, name in SITE_PAGES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return ""


def classify_media_url(value: str) -> MediaUrl:
    """Validate *value* and classify it as direct media or an unsupported page.

    Raises :class:`MediaUrlError` with a plain-language, actionable message for
    local paths, non-web schemes, credentials, malformed ports and known site
    pages. Unknown hosts are allowed: many media URLs have no filename suffix,
    so SmoothCast does not guess that they are pages.
    """
    url = str(value).strip()
    if not url or any(ch.isspace() for ch in url):
        raise MediaUrlError("Enter a valid HTTP or HTTPS media URL")
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise MediaUrlError("Only HTTP and HTTPS media URLs are supported")
        if parsed.username or parsed.password:
            raise MediaUrlError("URLs containing usernames or passwords are not supported")
        _ = parsed.port  # Reject malformed port numbers.
    except ValueError as exc:
        if isinstance(exc, MediaUrlError):
            raise
        raise MediaUrlError(f"Invalid media URL: {exc}") from exc

    host = parsed.hostname.lower().rstrip(".")
    site = _site_page(host)
    if site:
        raise MediaUrlError(f"{site} pages are not direct media files. {SITE_PAGE_REMEDY}")

    kind = "direct" if _looks_like_media(parsed.path) else "unknown"
    return MediaUrl(url=url, host=host, kind=kind)


def _looks_like_media(path: str) -> bool:
    """True when the URL's final path component has a recognised media suffix."""
    name = path.rsplit("/", 1)[-1].lower()
    return any(name.endswith(extension) for extension in MEDIA_EXTENSIONS)


def validate_media_url(value: str) -> str:
    """Return an HTTP(S) direct media URL, or raise a clear :class:`ValueError`."""
    return classify_media_url(value).url


def is_direct_media_url(value: str) -> bool:
    """Best-effort, non-raising check for a URL that names a media file."""
    try:
        return classify_media_url(value).is_direct
    except (MediaUrlError, ValueError):
        return False