"""Conservative, GTK-free HDR10-to-SDR conversion for unqualified receivers.

Only complete PQ / BT.2020 signalling is eligible. Unknown transfer or gamut
metadata must not be guessed into a colour conversion.
"""
from __future__ import annotations

from functools import lru_cache
import re
import subprocess

from async_jobs import UserFacingError

# Linearise the PQ signal before Hable tone mapping, then convert gamut,
# transfer and matrix to BT.709. Preserve the existing 8-bit 4:2:0 baseline.
SDR_FILTER = (
    "zscale=t=linear:npl=100,format=gbrpf32le,"
    "tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:p=bt709,format=yuv420p"
)


class TonemapUnavailable(UserFacingError):
    """FFmpeg cannot provide a safe SDR conversion for known HDR10 media."""


def filter_for(media: object) -> str | None:
    """Return an SDR filter only for verified HDR10 signalling."""
    transfer = str(getattr(media, "color_transfer", "") or "").lower()
    primaries = str(getattr(media, "color_primaries", "") or "").lower()
    matrix = str(getattr(media, "color_space", "") or "").lower()
    if transfer == "smpte2084" and primaries == "bt2020" and matrix in {
        "bt2020nc", "bt2020c"
    }:
        return SDR_FILTER
    return None


@lru_cache(maxsize=1)
def filters_available() -> bool:
    """Ask the selected FFmpeg once. No device or GUI access is involved."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode:
        return False
    names = set(re.findall(r"(?m)^\s*[.A-Z|]{3}\s+(\w+)\s+", result.stdout))
    return {"zscale", "tonemap"}.issubset(names)


def require_available(media: object) -> None:
    """Reject unsupported HDR before a current receiver session is replaced."""
    if filter_for(media) and not filters_available():
        raise TonemapUnavailable(
            "HDR10 conversion requires FFmpeg filters zscale and tonemap; "
            "install an FFmpeg build with both filters before casting this film"
        )
