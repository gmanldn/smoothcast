"""Deterministic FFprobe-shaped source catalogue for playback planning (#513).

No local media, network or receiver required. These are source descriptions,
not evidence that a real receiver can play the original files.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product


@dataclass(frozen=True)
class MediaShape:
    name: str
    extension: str
    video: str
    audio: str
    subtitles: str
    pix_fmt: str
    width: int = 1920
    height: int = 1080
    fps: int = 30

    def probe(self) -> dict:
        """Return the same top-level keys and stream fields as ffprobe JSON."""
        streams: list[dict] = [{
            "index": 0,
            "codec_type": "video",
            "codec_name": self.video,
            "profile": "High" if self.video == "h264" else "Main",
            "pix_fmt": self.pix_fmt,
            "width": self.width,
            "height": self.height,
            "avg_frame_rate": f"{self.fps}/1",
            "disposition": {"default": 1},
        }, {
            "index": 1,
            "codec_type": "audio",
            "codec_name": self.audio,
            "channels": 2,
            "channel_layout": "stereo",
            "disposition": {"default": 1},
        }]
        if self.subtitles != "none":
            streams.append({
                "index": 2,
                "codec_type": "subtitle",
                "codec_name": self.subtitles,
                "disposition": {"default": 0},
                "tags": {"language": "eng"},
            })
        return {
            "format": {
                "filename": f"{self.name}.{self.extension}",
                "format_name": self.extension,
                "duration": "120.000000",
                "bit_rate": "3000000",
            },
            "streams": streams,
            "chapters": [],
        }


# A reproducible 6 x 8 corpus with varied audio, subtitle and pixel formats.
# The 8 video codecs deliberately include incompatible and high-cost sources;
# no codec support or fall-back decision is asserted merely by listing them.
CONTAINERS = ("mp4", "mkv", "webm", "avi", "ts", "mov")
VIDEOS = ("h264", "hevc", "vp9", "av1", "mpeg2video", "mpeg4", "h264", "hevc")
AUDIOS = ("aac", "ac3", "eac3", "dts", "flac", "opus", "mp3", "aac")
SUBTITLES = ("none", "subrip", "ass", "hdmv_pgs_subtitle", "mov_text", "none", "subrip", "ass")
PIX_FMTS = ("yuv420p", "yuv420p10le", "yuv420p", "yuv420p10le",
            "yuv420p", "yuv420p", "yuv420p", "yuv420p10le")


def source_shapes() -> tuple[MediaShape, ...]:
    """Stable order and names: safe for CI table generation and regression IDs."""
    return tuple(
        MediaShape(
            name=f"sample-{container}-{index:02}",
            extension=container,
            video=VIDEOS[index],
            audio=AUDIOS[(index + container_index) % len(AUDIOS)],
            subtitles=SUBTITLES[(index + container_index) % len(SUBTITLES)],
            pix_fmt=PIX_FMTS[index],
            width=3840 if index in (1, 3) else 1920,
            height=2160 if index in (1, 3) else 1080,
            fps=60 if index in (1, 3) else 30,
        )
        for container_index, container in enumerate(CONTAINERS)
        for index, _ in enumerate(VIDEOS)
    )


SHAPES = source_shapes()
