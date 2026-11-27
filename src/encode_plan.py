"""Pure video encode planning (ARCH-09, #697 first slice).

``plan_encode`` returns the video argv fragment and the *reason* for each choice.
No I/O, no ffmpeg calls: capabilities and measured speed are passed in. If the
chosen plan cannot sustain real time (``measured_speed < 1.0``), ``plan_sequence``
yields lighter plans in order, so the caller steps down explicitly instead of
timing out. Not wired into streamer.py yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_REALTIME = 1.05          # needs a little headroom to fill the start window


@dataclass(frozen=True)
class Media:
    codec: str = "h264"
    width: int = 1920
    height: int = 1080
    bit_depth: int = 8
    burn_subtitles: bool = False


@dataclass(frozen=True)
class Capabilities:
    hw_encoder: str = ""                 # e.g. "h264_vaapi", "" when none qualified
    hw_decodes: frozenset = frozenset()  # codecs the hardware can decode
    speed: dict = field(default_factory=dict)   # profile name -> measured x realtime


@dataclass(frozen=True)
class EncodePlan:
    profile: str
    encoder: str
    height: int
    preset: str
    reason: str
    argv: tuple = ()


def _plan(profile: str, encoder: str, height: int, preset: str, reason: str, media: Media) -> EncodePlan:
    scale = f"scale=-2:{height}" if height < media.height else ""
    vf = [f for f in (scale, "format=yuv420p" if media.bit_depth > 8 or scale else "") if f]
    argv = ["-c:v", encoder]
    if encoder == "libx264":
        argv += ["-preset", preset, "-pix_fmt", "yuv420p"]
    if vf:
        argv += ["-vf", ",".join(vf)]
    return EncodePlan(profile, encoder, min(height, media.height), preset, reason, tuple(argv))


def plan_encode(media: Media, caps: Capabilities) -> EncodePlan:
    # Burned subtitles need frames in software, so they keep the software path.
    if caps.hw_encoder and not media.burn_subtitles and media.codec in caps.hw_decodes:
        return _plan("hardware", caps.hw_encoder, media.height, "", "hardware encoder qualified and "
                     f"hardware decodes {media.codec}", media)
    why = ("burned subtitles require software frames" if media.burn_subtitles else
           "no qualified hardware encoder" if not caps.hw_encoder else
           f"hardware cannot decode {media.codec}")
    return _plan("software", "libx264", media.height, "veryfast", why, media)


def plan_sequence(media: Media, caps: Capabilities) -> list[EncodePlan]:
    """Ordered plans from best quality to lightest; the first predicted real-time one wins."""
    first = plan_encode(media, caps)
    plans = [first]
    if first.profile == "hardware" and media.burn_subtitles is False:
        plans.append(_plan("software", "libx264", media.height, "veryfast",
                           "hardware path unavailable at runtime", media))
    for height in (720, 480):
        if height < media.height:
            plans.append(_plan(f"software-{height}p", "libx264", height, "ultrafast",
                               f"lighter profile: {height}p ultrafast to sustain real time", media))
    return plans


def choose(media: Media, caps: Capabilities) -> tuple[EncodePlan, bool]:
    """Pick the first plan whose measured speed sustains real time; second value = degraded."""
    plans = plan_sequence(media, caps)
    for index, plan in enumerate(plans):
        speed = caps.speed.get(plan.profile)
        if speed is None or speed >= MIN_REALTIME:     # unmeasured: trust the plan, probe later
            return plan, index > 0
    return plans[-1], True
