"""Generate the synthetic *video-only* decoder capability table (#513).

This is not a proof of Cast playback: audio, container, subtitles, remux and
HLS output decisions are outside the fake codec limits.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from runpy import run_path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import media_matrix  # noqa: E402

_profile_module = run_path(str(ROOT / "fakecast" / "profiles.py"))
PROFILES = _profile_module["PROFILES"]
supports = _profile_module["supports"]
REPORT = ROOT / "docs" / "PLAYBACK_MATRIX.md"


def source_video(shape: media_matrix.MediaShape) -> dict:
    codec = {"hevc": "h265", "mpeg2video": "mpeg2"}.get(shape.video, shape.video)
    profile = {
        "h264": "high",
        "h265": "main10" if shape.pix_fmt == "yuv420p10le" else "main",
        "vp9": "2" if shape.pix_fmt == "yuv420p10le" else "0",
        "av1": "main",
    }.get(codec, "")
    return {
        "codec": codec, "profile": profile,
        "level": "5.1" if shape.width > 1920 else "4.1",
        "width": shape.width, "height": shape.height, "fps": shape.fps,
    }


def render() -> str:
    names = tuple(PROFILES)
    rows = [
        "# SmoothCast synthetic video capability matrix (#513)",
        "",
        "**Not a direct/remux/transcode/playability matrix.** This tests only",
        "whether source video descriptors fit documented fake Cast decoder",
        "limits. It does not test audio, containers, subtitles, output encoding,",
        "player selection or real playback.",
        "",
        "Legend: `fit` = source video fits decoder; `adapt` = source video",
        "needs conversion or an explicit refusal; `unknown` = no model.",
        "",
        "| Source (video / audio / subs / pixels / fps) | " + " | ".join(names) + " |",
        "| --- | " + " | ".join("---" for _ in names) + " |",
    ]
    for shape in media_matrix.SHAPES:
        label = (
            f"{shape.name} ({shape.video} / {shape.audio} / "
            f"{shape.subtitles} / {shape.width}x{shape.height} / {shape.fps})"
        )
        stream = source_video(shape)
        verdicts = [
            "unknown" if profile == "generic" else
            ("fit" if supports(profile, stream) else "adapt")
            for profile in names
        ]
        rows.append("| " + label + " | " + " | ".join(verdicts) + " |")
    rows.extend([
        "",
        "Generated from 48 synthetic sources and 6 fake receiver profiles.",
        "Regenerate: `python3 scripts/ci/render_playback_matrix.py --write`.",
        "Verify: `python3 scripts/ci/render_playback_matrix.py --check`.",
        "",
        "**Outstanding #513:** actual direct/remux/transcode/refusal planner",
        "outcomes, all output codec/subtitle checks, six real FFmpeg fixtures",
        "and physical receiver validation. This table is capability evidence",
        "only, not playable-or-typed-refusal evidence.",
    ])
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic video capability report")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        REPORT.write_text(render(), encoding="utf-8")
        return 0
    if not REPORT.is_file() or REPORT.read_text(encoding="utf-8") != render():
        print("Playback matrix stale: run --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
