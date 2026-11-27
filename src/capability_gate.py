"""Veto-only bridge from the capability plan to the direct-play decision (#11).

``allowed`` may only turn direct play OFF, and only with certainty: the model
must be a recognised class (the generic baseline fallback means "unknown", and
unknown never forbids anything) and the plan must be a non-conservative
transcode. Everything else keeps the existing ``media.direct_ok`` and learned
receiver-memory logic, so capable TVs with built-in Cast are never downgraded.
"""
from __future__ import annotations

from capability_plan import MediaFacts, Request, plan_session
from receiver_profiles import profile_for_cast_model

UNKNOWN_LABEL = "Google Cast receiver"
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})


def direct_allowed(media: object, container: str, model: object) -> tuple[bool, str]:
    """(allowed, note). ``note`` explains a veto, else is empty. Never raises."""
    try:
        label, caps = profile_for_cast_model(model)
        if label == UNKNOWN_LABEL:
            return True, ""
        facts = MediaFacts(
            container=str(container or "").lower().lstrip("."),
            video_codec=str(getattr(media, "vcodec", "") or "").lower(),
            audio_codec=str(getattr(media, "acodec", "") or "").lower(),
            height=int(getattr(media, "height", 0) or 0),
            hdr=str(getattr(media, "color_transfer", "") or "").lower() in HDR_TRANSFERS,
            audio_only=bool(getattr(media, "audio_only", False)))
        plan = plan_session(caps, facts, Request())
        strips_video = plan.video == "none" and not facts.audio_only
        if (plan.mode == "transcode" or strips_video) and not plan.conservative:
            return False, f"{label}: {plan.notes[0] if plan.notes else 'needs conversion'}"
        return True, ""
    except Exception:  # noqa: BLE001 - a gate bug must never block casting
        return True, ""
