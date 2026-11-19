"""Headless control of a Chromecast: cast, pause, resume, stop, seek, status.

Scriptable without the GUI (issue #268). Nothing here imports GTK, opens a
window or needs a display; it reuses the same ``castctl`` / ``streamer``
building blocks as the application, so behaviour and ownership rules match.

Targets are Chromecast receivers (by name or IPv4). DLNA renderers are not
supported from the command line yet.

Exit codes (also in ``--help``):

    0  success
    1  the operation failed (receiver or catt refused it, or the cast did not start)
    2  usage error: bad arguments, no receiver given
    3  receiver unreachable or offline
    4  media problem: file missing, unreadable or unsupported

With ``--json`` exactly one JSON object is printed to stdout::

    {"ok": true,  "command": "pause", ...}
    {"ok": false, "command": "pause", "error": "failed", "message": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

import castctl
import streamer

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_UNREACHABLE, EXIT_MEDIA = 0, 1, 2, 3, 4
COMMANDS = ("cast", "pause", "resume", "stop", "seek", "status")
DEVICE_ENV = "SMOOTHCAST_DEVICE"
_ERROR_NAMES = {EXIT_FAILED: "failed", EXIT_USAGE: "usage",
                EXIT_UNREACHABLE: "unreachable", EXIT_MEDIA: "media"}

EPILOG = """\
exit codes: 0 success; 1 operation failed; 2 usage error; 3 receiver unreachable;
4 media unreadable or unsupported. Give the receiver with -d/--device or the
SMOOTHCAST_DEVICE environment variable. Chromecast receivers only (name or IPv4).
"""


class CliError(Exception):
    """A command failed with a specific exit code and message."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_time(text: str) -> float:
    """Seconds from ``90``, ``90.5``, ``125:30`` or ``1:02:03`` (non-negative, finite).

    In ``M:SS`` and ``H:MM:SS`` the seconds (and minutes, with hours) must be
    below 60; a bare number or the leading field may be any size.
    """
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or not all(re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts):
        raise CliError(EXIT_USAGE, f"not a time: {text!r} (use seconds, MM:SS or HH:MM:SS)")
    if any("." in p for p in parts[:-1]):
        raise CliError(EXIT_USAGE, f"only the seconds may have a fraction: {text!r}")
    if any(float(p) >= 60 for p in parts[1:]):
        raise CliError(EXIT_USAGE, f"minutes and seconds must be below 60: {text!r}")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    if seconds == float("inf"):
        raise CliError(EXIT_USAGE, f"not a finite time: {text!r}")
    return seconds


def _device(args: argparse.Namespace) -> str:
    device = (args.device or os.environ.get(DEVICE_ENV, "")).strip()
    if not device:
        raise CliError(EXIT_USAGE, f"no receiver: pass -d/--device or set {DEVICE_ENV}")
    return device


def _device_ip(device: str) -> str | None:
    """Only a literal IPv4 can be used for route selection without discovery."""
    try:
        castctl.validate_manual_target(device)
    except Exception:
        return None
    return device


def _saved_for(device: str) -> streamer.SessionState | None:
    state = streamer.load_session()
    return state if state is not None and state.device == device else None


def _stop_saved(state: streamer.SessionState, *, send_stop: bool) -> None:
    """End a SmoothCast-owned cast: verified child processes, files, session."""
    session = streamer.Session()
    session.restore(state)
    session.stop(state.device, send_stop=send_stop)


def _simple(args: argparse.Namespace, action) -> dict:
    device = _device(args)
    ok, message = action(device)
    if not ok:
        raise CliError(EXIT_FAILED, message or f"{args.command} failed")
    return {"device": device, "message": message}


def cmd_pause(args: argparse.Namespace) -> dict:
    return _simple(args, castctl.pause)


def cmd_resume(args: argparse.Namespace) -> dict:
    return _simple(args, castctl.play)


def cmd_stop(args: argparse.Namespace) -> dict:
    device = _device(args)
    state = _saved_for(device)
    if state is not None:
        _stop_saved(state, send_stop=True)   # also ends our ffmpeg / server / catt
        return {"device": device, "message": "stopped", "ended_session": state.mode}
    ok, message = castctl.stop(device)
    if not ok:
        raise CliError(EXIT_FAILED, message or "stop failed")
    return {"device": device, "message": message or "stopped", "ended_session": ""}


def cmd_seek(args: argparse.Namespace) -> dict:
    device = _device(args)
    target = parse_time(args.time)
    state = _saved_for(device)
    if state is not None and state.mode == "transcode":
        # A live HLS transcode cannot seek on the receiver: restart the
        # encoder at the new position, as the application does.
        target = _restart_transcode(state, target)
        return {"device": device, "position": target, "method": "restart"}
    ok, message = castctl.seek(device, target)
    if not ok:
        raise CliError(EXIT_FAILED, message or "seek failed")
    return {"device": device, "position": target, "method": "seek"}


def _restart_transcode(state: streamer.SessionState, target: float) -> float:
    source = Path(state.file)
    try:
        media = streamer.ffprobe(source)
    except (streamer.StreamError, OSError) as exc:
        raise CliError(EXIT_MEDIA, f"cannot read {source.name}: {exc}") from exc
    if media.duration:
        target = min(target, max(0.0, media.duration - 1.0))
    subs = Path(state.subs) if state.subs else None
    session = streamer.Session()
    session.restore(state)
    session.stop(state.device, send_stop=False)
    try:
        session.start_transcode(
            media, target, device=state.device, quality=state.quality,
            audio_profile=state.audio, subs_file=subs if subs and subs.is_file() else None,
            burn_subs=state.burn_subs, title=state.title, audio_gain_db=state.audio_gain_db,
            device_ip=_device_ip(state.device), speed=state.speed, rotation=state.rotation,
            embedded_subtitle_index=(None if state.embedded_subtitle_index < 0
                                     else state.embedded_subtitle_index),
            audio_track_index=state.audio_track_index,
        )
    except streamer.StreamError as exc:
        raise CliError(EXIT_FAILED, str(exc)) from exc
    return target


def cmd_status(args: argparse.Namespace) -> dict:
    device = _device(args)
    info = castctl.info(device)
    if info is None:
        raise CliError(EXIT_UNREACHABLE, f"{device} did not respond (offline or unreachable)")
    result = {
        "device": device,
        "state": castctl.player_state(info),
        "playing": castctl.is_playing(info),
        "position": info.get("current_time"),
        "duration": info.get("duration"),
        "title": info.get("title") or "",
        "volume": castctl.volume_percent(info),
        "muted": castctl.volume_muted(info),
        "seekable": castctl.is_seekable(info),
    }
    state = _saved_for(device)
    result["session"] = ({"mode": state.mode, "file": Path(state.file).name,
                          "started_at": state.started_at} if state else None)
    return result


def cmd_cast(args: argparse.Namespace) -> dict:
    device = _device(args)
    path = Path(args.file).expanduser()
    if not path.is_file():
        raise CliError(EXIT_MEDIA, f"no such file: {path}")
    offset = parse_time(args.offset) if args.offset else 0.0
    try:
        media = streamer.ffprobe(path)
    except (streamer.StreamError, OSError, ValueError) as exc:
        raise CliError(EXIT_MEDIA, f"cannot read {path.name}: {exc}") from exc
    subs = None
    if args.subs:
        subs = Path(args.subs).expanduser()
        if not subs.is_file():
            raise CliError(EXIT_USAGE, f"no such subtitle file: {subs}")
    elif not args.no_subs:
        subs = streamer.find_subtitles(path)
    mode = args.mode
    if mode == "auto":
        mode = "direct" if media.direct_ok else "transcode"
    title = args.title or path.stem
    previous = streamer.load_session()
    if previous is not None:
        _stop_saved(previous, send_stop=False)   # replace our own earlier cast, never leak it
    session = streamer.Session()
    try:
        if mode == "direct":
            session.start_direct(media, device=device, subs_file=subs,
                                 subs_disabled=bool(args.no_subs), title=title, offset=offset)
        else:
            session.start_transcode(
                media, offset, device=device, quality=args.quality, audio_profile=args.audio,
                subs_file=subs, burn_subs=False, title=title, device_ip=_device_ip(device))
    except (streamer.StreamError, castctl.CastError) as exc:
        session.stop(device, send_stop=False)
        raise CliError(EXIT_FAILED, str(exc)) from exc
    return {"device": device, "mode": mode, "file": path.name, "title": title,
            "offset": offset, "stream_url": session.state.stream_url if session.state else ""}


HANDLERS = {"cast": cmd_cast, "pause": cmd_pause, "resume": cmd_resume,
            "stop": cmd_stop, "seek": cmd_seek, "status": cmd_status}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-d", "--device", help=f"receiver name or IPv4 (default: ${DEVICE_ENV})")
    common.add_argument("--json", action="store_true", help="print one JSON object")
    parser = argparse.ArgumentParser(
        prog="smoothcast", description="Control a Chromecast without the GUI.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cast = sub.add_parser("cast", parents=[common], help="cast a local file",
                          epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    cast.add_argument("file")
    cast.add_argument("--mode", choices=("auto", "direct", "transcode"), default="auto")
    cast.add_argument("--offset", help="start position (seconds, MM:SS or HH:MM:SS)")
    cast.add_argument("--subs", help="subtitle file (default: a matching sidecar)")
    cast.add_argument("--no-subs", action="store_true", help="no subtitles")
    cast.add_argument("--quality", choices=("high", "balanced", "saver"), default="balanced")
    cast.add_argument("--audio", choices=("original", "dialogue", "night"), default="original")
    cast.add_argument("--title", help="title shown on the receiver")
    for name, text in (("pause", "pause playback"), ("resume", "resume playback"),
                       ("stop", "stop and end the cast"), ("status", "show receiver state")):
        sub.add_parser(name, parents=[common], help=text)
    seek = sub.add_parser("seek", parents=[common], help="seek to a position")
    seek.add_argument("time", help="seconds, MM:SS or HH:MM:SS")
    return parser


def _human(command: str, result: dict) -> str:
    if command == "status":
        position = castctl.fmt_time(result["position"]) if result["position"] is not None else "-"
        duration = castctl.fmt_time(result["duration"]) if result["duration"] else "-"
        volume = "-" if result["volume"] is None else f"{result['volume']}%"
        return (f"{result['device']}: {result['state']}  {position} / {duration}  "
                f"volume {volume}{' (muted)' if result['muted'] else ''}"
                + (f"  \"{result['title']}\"" if result["title"] else ""))
    if command == "cast":
        return f"Casting {result['file']} to {result['device']} ({result['mode']})"
    if command == "seek":
        return f"Seeked {result['device']} to {castctl.fmt_time(result['position'])}"
    return f"{command}: {result.get('message') or 'ok'}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = HANDLERS[args.command](args)
        code, payload = EXIT_OK, {"ok": True, "command": args.command, **result}
    except CliError as exc:
        code = exc.code
        payload = {"ok": False, "command": args.command,
                   "error": _ERROR_NAMES.get(exc.code, "failed"), "message": exc.message}
    if args.json:
        print(json.dumps(payload))
    elif code == EXIT_OK:
        print(_human(args.command, result))
    else:
        print(f"smoothcast {args.command}: {payload['message']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
