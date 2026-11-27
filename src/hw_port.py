"""HardwareEncoder port (ARCH-11, #703 slice). Pure: probing is injected.

One implementation per backend plus a fake. ``select`` ranks candidates, returns
the first that probes OK, and records a visible reason for every one skipped, so
missing hardware degrades to the next option instead of silently going software.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable, Protocol

import render_nodes


class HardwareEncoder(Protocol):
    name: str
    def available(self) -> tuple[bool, str]: ...      # (usable, reason)
    def input_args(self) -> list[str]: ...            # ffmpeg args before -i
    def encoder(self) -> str: ...                     # -c:v value


@dataclass
class Vaapi:
    name: str = "vaapi"
    nodes: Callable[[], list[str]] = render_nodes.render_nodes
    platform: str = sys.platform
    node: str = ""

    def available(self):
        if not self.platform.startswith("linux"):
            return False, f"VAAPI is Linux-only (platform {self.platform})"
        found = self.nodes()
        if not found:
            return False, "no /dev/dri render node found"
        self.node = found[0]
        return True, f"render node {self.node}"

    def input_args(self):
        return ["-hwaccel", "vaapi", "-hwaccel_device", self.node or render_nodes.FALLBACK,
                "-hwaccel_output_format", "vaapi"]

    def encoder(self):
        return "h264_vaapi"


@dataclass
class Nvenc:
    name: str = "nvenc"
    has_encoder: Callable[[str], bool] = lambda _n: False   # injected ffmpeg -encoders probe

    def available(self):
        if self.has_encoder("h264_nvenc"):
            return True, "ffmpeg lists h264_nvenc"
        return False, "ffmpeg has no h264_nvenc"

    def input_args(self):
        return ["-hwaccel", "cuda"]

    def encoder(self):
        return "h264_nvenc"


@dataclass
class Qsv:
    """Intel Quick Sync via ffmpeg's qsv encoders (Windows and Linux)."""
    name: str = "qsv"
    has_encoder: Callable[[str], bool] = lambda _n: False
    platform: str = sys.platform

    def available(self):
        if self.platform == "darwin":
            return False, "QSV is not available on macOS"
        if self.has_encoder("h264_qsv"):
            return True, "ffmpeg lists h264_qsv"
        return False, "ffmpeg has no h264_qsv"

    def input_args(self):
        return ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]

    def encoder(self):
        return "h264_qsv"


@dataclass
class VideoToolbox:
    """Apple VideoToolbox (macOS only)."""
    name: str = "videotoolbox"
    has_encoder: Callable[[str], bool] = lambda _n: False
    platform: str = sys.platform

    def available(self):
        if self.platform != "darwin":
            return False, f"VideoToolbox is macOS-only (platform {self.platform})"
        if self.has_encoder("h264_videotoolbox"):
            return True, "ffmpeg lists h264_videotoolbox"
        return False, "ffmpeg has no h264_videotoolbox"

    def input_args(self):
        return ["-hwaccel", "videotoolbox"]

    def encoder(self):
        return "h264_videotoolbox"


@dataclass
class Fake:
    name: str = "fake"
    ok: bool = True
    why: str = "fake"

    def available(self):
        return self.ok, self.why

    def input_args(self):
        return ["-fake"]

    def encoder(self):
        return "fake_enc"


@dataclass
class Selection:
    chosen: HardwareEncoder | None
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (name, reason)

    @property
    def reason(self) -> str:
        if self.chosen:
            return f"using {self.chosen.name}"
        detail = "; ".join(f"{n}: {r}" for n, r in self.skipped) or "no backends"
        return f"software encode ({detail})"


def select(ranked: list[HardwareEncoder]) -> Selection:
    skipped: list[tuple[str, str]] = []
    for backend in ranked:
        try:
            ok, why = backend.available()
        except Exception as exc:                       # a broken probe must not break casting
            ok, why = False, f"probe failed: {exc}"
        if ok:
            return Selection(backend, skipped)
        skipped.append((backend.name, why))
    return Selection(None, skipped)
