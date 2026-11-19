"""P0 #237: no signal or restored ownership without exact process birth identity.

All process creation and signal methods are fake. Never invoke a real PID,
os.kill, FFmpeg, desktop window or Chromecast while running this suite.
"""
from __future__ import annotations

from contextlib import nullcontext
import os
import pathlib
from types import SimpleNamespace
from unittest import mock

import process_identity as identity
import startup_cleanup
import streamer


class FakeProcess:
    def __init__(self, pid, argv=(), created=1234.5, user="tester"):
        self.pid = pid
        self.argv = tuple(argv)
        self.started = created
        self.owner = user
        self.actions = []

    def oneshot(self):
        return nullcontext(self)

    def cmdline(self):
        return list(self.argv)

    def create_time(self):
        return self.started

    def username(self):
        return self.owner

    def terminate(self):
        self.actions.append("TERM")

    def kill(self):
        self.actions.append("KILL")


def fake_psutil(*processes):
    owner = FakeProcess(os.getpid(), ("python",), user="tester")
    rows = {owner.pid: owner, **{p.pid: p for p in processes}}
    return SimpleNamespace(
        Process=lambda pid: rows[pid],
        process_iter=lambda: [p for pid, p in rows.items() if pid != owner.pid],
    )


def ffmpeg(pid=50001, created=1234.5, user="tester"):
    return FakeProcess(pid, ("C:\\ffmpeg\\bin\\ffmpeg.exe", "-progress",
                             str(streamer.PROGRESS_FILE)), created, user)


def server(pid=50002, created=1234.5, user="tester"):
    return FakeProcess(pid, ("C:\\Python313\\python.exe",
                             str(streamer.SERVER_SCRIPT), "--bind",
                             "192.168.1.10"), created, user)


def test_windows_and_posix_role_classification_is_exact_and_not_filename_only():
    roles = [
        (("C:\\Tools\\ffmpeg.exe", "-progress", str(streamer.PROGRESS_FILE)), "encoder"),
        (("/usr/bin/ffmpeg", "-progress", str(streamer.PROGRESS_FILE)), "encoder"),
        (("python3", str(streamer.SERVER_SCRIPT)), "server"),
        (("SmoothCast.exe", "--_smoothcast-hls-server"), "server"),
        (("C:\\Tools\\ffplay.exe", "-window_title", "SmoothCast — local playback"), "local"),
    ]
    for argv, role in roles:
        assert identity.role_of(
            argv, server_script=str(streamer.SERVER_SCRIPT),
            progress_file=str(streamer.PROGRESS_FILE),
        ) == role
    for argv in (
        ("C:\\Tools\\ffmpeg.exe", "-i", "user.mkv"),
        ("catt", "-d", "TV", "status"),
        ("python3", "-c", str(streamer.SERVER_SCRIPT)),
    ):
        assert identity.role_of(
            argv, server_script=str(streamer.SERVER_SCRIPT),
            progress_file=str(streamer.PROGRESS_FILE),
        ) is None


def test_snapshot_requires_same_user_command_and_birth_timestamp(monkeypatch):
    good = ffmpeg()
    wrong_owner = ffmpeg(50003, user="administrator")
    zero = server(50004, created=0)
    monkeypatch.setattr(identity, "psutil", fake_psutil(good, wrong_owner, zero))
    assert identity.snapshot(good.pid) == identity.Identity(
        good.pid, good.started, good.argv, "tester")
    assert identity.snapshot(wrong_owner.pid) is None
    assert identity.snapshot(zero.pid) is None
    assert identity.snapshot(os.getpid()) is None
    assert identity.snapshot(0) is None


def test_exact_birthday_prevents_pid_reuse_even_with_identical_command(monkeypatch):
    old = ffmpeg()
    monkeypatch.setattr(identity, "psutil", fake_psutil(old))
    assert streamer._pid_is_ours(old.pid, "encoder", old.started)
    assert not streamer._pid_is_ours(old.pid, "server", old.started)
    old.started += 30.0  # identical argv, different OS process.
    assert not streamer._pid_is_ours(old.pid, "encoder", 1234.5)
    streamer._terminate_pid(old.pid, "encoder", 1234.5)
    assert old.actions == []


def test_direct_signal_refuses_foreign_user_reused_pid_and_argv_mutation(monkeypatch):
    p = ffmpeg()
    monkeypatch.setattr(identity, "psutil", fake_psutil(p))
    kwargs = dict(expected_start=p.started, expected_argv=p.argv,
                  server_script=str(streamer.SERVER_SCRIPT),
                  progress_file=str(streamer.PROGRESS_FILE))
    assert identity.signal_verified(p.pid, "encoder", **kwargs)
    assert p.actions == ["TERM"]
    p.started += 2.0
    assert not identity.signal_verified(p.pid, "encoder", force=True, **kwargs)
    p.started -= 2.0
    p.argv += ("--unrelated",)
    assert not identity.signal_verified(p.pid, "encoder", force=True, **kwargs)
    p.argv = kwargs["expected_argv"]
    p.owner = "someone-else"
    assert not identity.signal_verified(p.pid, "encoder", force=True, **kwargs)
    assert p.actions == ["TERM"]


def test_restored_pid_handle_never_signals_when_identity_changes(monkeypatch):
    p = server()
    monkeypatch.setattr(identity, "psutil", fake_psutil(p))
    handle = streamer.PidHandle(p.pid, "server", p.started)
    assert handle.poll() is None
    p.started += 0.5
    assert handle.poll() == -1
    handle.terminate()
    assert p.actions == []


def test_legacy_session_without_birth_times_is_not_adopted(monkeypatch):
    p = ffmpeg()
    monkeypatch.setattr(identity, "psutil", fake_psutil(p))
    with mock.patch.object(streamer.Session, "_start_sampler"):
        session = streamer.Session()
        session.restore(streamer.SessionState(
            file="/media/movie.mkv", mode="transcode", offset=0, duration=120,
            device="TV", title="Movie", ffmpeg_pid=p.pid))
    assert session.ffmpeg is None
    assert not session.active()


def test_new_saved_session_can_restore_matching_process(monkeypatch, tmp_path):
    p = ffmpeg()
    monkeypatch.setattr(identity, "psutil", fake_psutil(p))
    original = streamer.SessionState(
        file="/media/movie.mkv", mode="transcode", offset=0, duration=120,
        device="TV", title="Movie", ffmpeg_pid=p.pid,
        ffmpeg_created_at=p.started)
    with mock.patch.object(streamer, "SESSION_FILE", tmp_path / "state.json"):
        streamer._save_session(original)
        loaded = streamer.load_session()
    assert loaded is not None
    assert loaded.ffmpeg_created_at == p.started
    with mock.patch.object(streamer.Session, "_start_sampler"):
        session = streamer.Session()
        session.restore(loaded)
    assert isinstance(session.ffmpeg, streamer.PidHandle)
    assert session.ffmpeg.poll() is None


def test_portable_orphan_discovery_filters_other_users_and_unowned_commands(monkeypatch):
    good = server()
    other = ffmpeg(50003, user="foreign")
    unrelated = FakeProcess(50004, ("C:\\Tools\\ffmpeg.exe", "-i", "private.mkv"))
    monkeypatch.setattr(identity, "psutil", fake_psutil(good, other, unrelated))
    with mock.patch.object(startup_cleanup.platform, "system", return_value="Windows"):
        processes = startup_cleanup.discover(pathlib.Path("N:/no-proc"))
    assert [(p.pid, p.kind) for p in processes] == [(good.pid, "server")]
    assert processes[0].start_ticks == round(good.started * 1_000_000)


def test_windows_stop_uses_verified_psutil_not_os_kill(monkeypatch):
    p = server()
    monkeypatch.setattr(identity, "psutil", fake_psutil(p))
    process = startup_cleanup.Process(
        p.pid, "server", round(p.started * 1_000_000), p.argv,
    )
    with mock.patch.object(startup_cleanup.platform, "system", return_value="Windows"), \
         mock.patch.object(startup_cleanup.os, "kill",
                           side_effect=AssertionError("Windows os.kill forbidden")):
        report = startup_cleanup.CleanupReport()
        startup_cleanup._stop_orphans(
            [process], pathlib.Path("N:/no-proc"), report, 0.0)
    assert report.stopped == [p.pid]
    assert p.actions == ["TERM", "KILL"]


def test_mac_pid_reuse_between_discovery_and_signal_never_sends_command(monkeypatch):
    p = server()
    monkeypatch.setattr(identity, "psutil", fake_psutil(p))
    old = startup_cleanup.Process(
        p.pid, "server", round(p.started * 1_000_000), p.argv,
    )
    p.started += 1.0
    with mock.patch.object(startup_cleanup.platform, "system", return_value="Darwin"), \
         mock.patch.object(startup_cleanup.os, "kill",
                           side_effect=AssertionError("unverified PID must not be signalled")):
        report = startup_cleanup.CleanupReport()
        startup_cleanup._stop_orphans(
            [old], pathlib.Path("/does-not-exist"), report, 0.0)
    assert report.stopped == []
    assert p.actions == []


def test_missing_psutil_fails_closed_on_windows_and_does_not_kill(monkeypatch):
    monkeypatch.setattr(identity, "psutil", None)
    with mock.patch.object(startup_cleanup.platform, "system", return_value="Windows"), \
         mock.patch.object(streamer.os, "kill",
                           side_effect=AssertionError("must not kill")):
        report = startup_cleanup.cleanup_before_window(keep_streaming=False)
        assert report.stopped == []
        assert streamer._pid_is_ours(50001, "encoder") is False
        streamer._terminate_pid(50001, "encoder")
