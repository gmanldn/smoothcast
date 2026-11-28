"""Live input/output level + dialogue gain-reduction data for Cast Control.

Decodes the source audio in a fast background pass and measures, per short
window, the level *before* and *after* the dialogue/night filter chain (via
``astats`` metadata). Because both branches run in one fast decode they emit
identical ``pts_time`` streams, so windows are aligned by index and the UI can
look up the levels for whatever the playback position currently is. This makes
the DJM-style level + "pump" (gain-reduction) meters stay perfectly in step with
playback without a fragile real-time tap.

``dynaudnorm`` buffers several seconds of audio internally, so a real-time
post-chain tap is impossible; decoding to completion sidesteps that entirely.

This is observational only: it opens the media file read-only in a separate
process and never touches the HLS/cast pipeline. If it fails for any reason the
caller simply keeps a "no data" state; playback is unaffected.
"""
from __future__ import annotations

import array
import bisect
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
import media_tools

FLOOR_DB = -60.0
# 4096 samples per window ~= 93 ms at 44.1 kHz: responsive without exploding the
# window count on multi-hour sources.
_WINDOW = 4096
# ``ametadata`` files can accumulate a multi-hour stream's records between
# polls. Consume them in bounded chunks so a burst (or a slow reader) cannot
# read an unbounded amount of text into memory at once. Normal astats records
# are tiny, so these limits never split a real record in practice.
_MAX_READ_BYTES = 64 * 1024
_MAX_PENDING_BYTES = 256 * 1024
_FRAME = re.compile(r"^frame:\d+\s+pts:\d+\s+pts_time:([0-9.]+)")
# astats metadata keys we care about (per-channel index 1=Left, 2=Right).
_KEYS = {
    "lavfi.astats.Overall.RMS_level": "rms",
    "lavfi.astats.Overall.Peak_level": "peak",
    "lavfi.astats.1.RMS_level": "l",
    "lavfi.astats.2.RMS_level": "r",
}


def _db(text: object) -> float:
    """Parse an astats dB value; silence/-inf clamps to the meter floor."""
    try:
        value = float(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return FLOOR_DB
    if value != value or value == float("-inf") or value <= FLOOR_DB:  # NaN / -inf
        return FLOOR_DB
    if value == float("inf"):
        return 0.0
    return max(FLOOR_DB, min(0.0, value))


@dataclass
class LevelSample:
    """One analysis window: source level vs processed level, in dBFS."""

    in_rms: float
    out_rms: float
    in_peak: float
    out_peak: float
    in_l: float
    in_r: float
    out_l: float
    out_r: float

    @property
    def gain_db(self) -> float:
        """Applied gain (out - in): >0 lifts quiet, <0 pulls loud down."""
        return self.out_rms - self.in_rms


class _Reader:
    """Incrementally parse ``ametadata=mode=print`` output into window records.

    A record is one ``frame:`` line plus the ``key=value`` lines that follow it;
    the next ``frame:`` line closes the previous record. ``poll`` consumes any
    newly written bytes; ``finish`` flushes the final record at EOF.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self._fh = None
        self._pending = ""
        self.records: list[dict] = []
        self._current: dict | None = None

    def poll(self) -> None:
        if self._fh is None:
            try:
                self._fh = open(self.path, "r")
            except OSError:
                return
        chunk = self._fh.read(_MAX_READ_BYTES)
        if not chunk:
            return
        self._pending += chunk
        lines = self._pending.split("\n")
        self._pending = lines.pop()  # trailing fragment may be incomplete
        # A malformed stream without newlines must not grow the fragment
        # without bound; keep only the newest bytes and resynchronise on the
        # next complete record.
        if len(self._pending) > _MAX_PENDING_BYTES:
            self._pending = self._pending[-_MAX_PENDING_BYTES:]
        for line in lines:
            self._consume(line)

    def finish(self) -> None:
        if self._pending:
            self._consume(self._pending)
            self._pending = ""
        if self._current is not None:
            self.records.append(self._current)
            self._current = None

    def _consume(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        if line.startswith("frame:"):
            if self._current is not None:
                self.records.append(self._current)
            match = _FRAME.match(line)
            self._current = {"pts": float(match.group(1)) if match else 0.0}
            return
        key, sep, raw = line.partition("=")
        field = _KEYS.get(key) if sep else None
        if field and self._current is not None:
            self._current[field] = _db(raw)

    def close(self) -> None:
        try:
            if self._fh:
                self._fh.close()
        except OSError:
            pass
        self._fh = None


class AudioMonitor:
    """Measure source vs processed loudness for the live meters.

    Typical use: ``mon = AudioMonitor(); mon.start(path, chain, offset=off)`` then
    each UI frame call ``mon.sample_at(playback_position)`` which returns the
    :class:`LevelSample` for that instant (or ``None`` before the fast decode has
    reached that point). Call ``mon.stop()`` when playback stops.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._rin: _Reader | None = None
        self._rout: _Reader | None = None
        self._dir: pathlib.Path | None = None
        self._lock = threading.Lock()
        self._offset = 0.0
        # Parallel arrays indexed by window; absolute time in ``_times``.
        self._times: array.array = array.array("d")
        self._in_l: array.array = array.array("f")
        self._in_r: array.array = array.array("f")
        self._out_l: array.array = array.array("f")
        self._out_r: array.array = array.array("f")
        self._in_rms: array.array = array.array("f")
        self._out_rms: array.array = array.array("f")
        self._in_peak: array.array = array.array("f")
        self._out_peak: array.array = array.array("f")

    # ---- lifecycle ----

    def start(self, media_path, chain, *, offset: float = 0.0, audio_track_index: int = 0) -> None:
        self.stop()
        self._stop.clear()
        self._offset = max(0.0, offset)
        for seq in (self._times, self._in_l, self._in_r, self._out_l, self._out_r,
                    self._in_rms, self._out_rms, self._in_peak, self._out_peak):
            del seq[:]
        directory = pathlib.Path(tempfile.mkdtemp(prefix="cast-mon-"))
        self._dir = directory
        in_path = directory / "in.txt"
        out_path = directory / "out.txt"
        chain_str = ",".join(chain) if chain else "anull"
        # Split the decoded stereo stream: [a] measures the untouched source,
        # [b] measures the same audio after the dialogue/night chain. asetnsamples
        # gives both branches identical windowing so their records align 1:1.
        track = audio_track_index if type(audio_track_index) is int and audio_track_index >= 0 else 0
        filter_complex = (
            f"[0:a:{track}]aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[a][b];"
            f"[a]asetnsamples={_WINDOW},astats=metadata=1:reset=1,"
            f"ametadata=mode=print:file={in_path}:direct=1[o1];"
            f"[b]{chain_str},asetnsamples={_WINDOW},astats=metadata=1:reset=1,"
            f"ametadata=mode=print:file={out_path}:direct=1[o2]"
        )
        args = [media_tools.resolve_media_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-vn"]
        if self._offset > 0:
            args += ["-ss", f"{self._offset:.3f}"]
        args += [
            "-i", str(media_path),
            "-filter_complex", filter_complex,
            "-map", "[o1]", "-map", "[o2]", "-f", "null", "-",
        ]
        try:
            self._proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._cleanup()
            return
        self._rin = _Reader(in_path)
        self._rout = _Reader(out_path)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            while not self._stop.is_set():
                proc = self._proc
                done = proc is not None and proc.poll() is not None
                if self._rin is not None:
                    self._rin.poll()
                if self._rout is not None:
                    self._rout.poll()
                self._pair()
                if done:
                    # Drain anything buffered at the very end, then finish.
                    if self._rin is not None:
                        self._rin.poll()
                        self._rin.finish()
                    if self._rout is not None:
                        self._rout.poll()
                        self._rout.finish()
                    self._pair()
                    return
                self._stop.wait(0.05)
        except Exception:  # noqa: BLE001 - the meter is best-effort and must never break playback
            return

    def _pair(self) -> None:
        rin = self._rin.records if self._rin else []
        rout = self._rout.records if self._rout else []
        total = min(len(rin), len(rout))
        if not total:
            return
        with self._lock:
            for i in range(total):
                src = rin[i]
                dst = rout[i]
                self._times.append(src.get("pts", 0.0) + self._offset)
                self._in_l.append(src.get("l", FLOOR_DB))
                self._in_r.append(src.get("r", FLOOR_DB))
                self._in_rms.append(src.get("rms", FLOOR_DB))
                self._in_peak.append(src.get("peak", FLOOR_DB))
                self._out_l.append(dst.get("l", FLOOR_DB))
                self._out_r.append(dst.get("r", FLOOR_DB))
                self._out_rms.append(dst.get("rms", FLOOR_DB))
                self._out_peak.append(dst.get("peak", FLOOR_DB))
            # Each record is now represented by compact arrays. Keeping both
            # branches' original dictionaries for an entire film wastes RAM.
            # Leave only unmatched frames for the next incremental pass.
            del rin[:total]
            del rout[:total]

    # ---- query ----

    def sample_at(self, position: float) -> LevelSample | None:
        """Return the analysed window covering ``position`` (absolute seconds)."""
        with self._lock:
            n = len(self._times)
            if n == 0:
                return None
            if position < self._offset - 0.05:
                return None
            idx = bisect.bisect_right(self._times, position) - 1
            if idx < 0:
                # The first decoded frame can start a little after offset.
                if position < self._times[0] - 0.05:
                    return None
                idx = 0
            # A window is valid only for its own short time interval.
            # Never replay the last analysed sample after a long seek: the
            # meter must report no data until the background decoder catches
            # up. Derive window width from adjacent PTS values where possible.
            width = (self._times[idx + 1] - self._times[idx]
                     if idx + 1 < n else
                     self._times[-1] - self._times[-2] if n > 1
                     else 0.1)
            width = max(0.02, min(0.5, width))
            if position >= self._times[idx] + width:
                return None
            return LevelSample(
                in_rms=self._in_rms[idx], out_rms=self._out_rms[idx],
                in_peak=self._in_peak[idx], out_peak=self._out_peak[idx],
                in_l=self._in_l[idx], in_r=self._in_r[idx],
                out_l=self._out_l[idx], out_r=self._out_r[idx],
            )

    @property
    def analyzed_until(self) -> float:
        with self._lock:
            return self._times[-1] if self._times else self._offset

    @property
    def started(self) -> bool:
        return self._proc is not None or self._thread is not None

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._rin is not None:
            self._rin.close()
            self._rin = None
        if self._rout is not None:
            self._rout.close()
            self._rout = None
        self._cleanup()

    def _cleanup(self) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None