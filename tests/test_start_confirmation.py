"""A cast is treated as started only when the receiver confirms it (issue #238).

start_transcode()/start_direct() used a fixed 2.0 s / 2.5 s sleep and then a
one-off catt process check, so a cast that failed a moment later looked
successful. They now poll the receiver (a fake castctl.info here) until it
reports our media, or fail with a clear message.
"""
from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import streamer


class _FakeStdout:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def _ticking(values):
    seq = iter(values)
    return lambda: next(seq)


def _fake_caster(*, code=None, stdout=None):
    caster = mock.Mock()
    caster.poll.return_value = code
    caster.returncode = code
    caster.stdout = _FakeStdout(stdout) if stdout is not None else None
    return caster


class AwaitReceiverTests(unittest.TestCase):
    def test_confirms_once_the_receiver_reports_our_media(self):
        session = streamer.Session()
        session.caster = _fake_caster(code=None)
        with mock.patch.object(streamer.castctl, "info",
                               side_effect=[{}, {"player_state": "PLAYING"}]) as info, \
             mock.patch.object(streamer.time, "sleep"):
            session._await_receiver("TV", lambda value: bool(value))
        self.assertEqual(info.call_count, 2)

    def test_a_failed_caster_is_reported_immediately(self):
        session = streamer.Session()
        session.caster = _fake_caster(code=2, stdout="boom: not a receiver")
        with mock.patch.object(streamer.castctl, "info") as info:
            with self.assertRaisesRegex(streamer.StreamError, "boom: not a receiver"):
                session._await_receiver("TV", lambda value: True)
        info.assert_not_called()

    def test_an_unconfirmed_receiver_times_out_with_a_clear_message(self):
        session = streamer.Session()
        session.caster = _fake_caster(code=None)
        clock = _ticking([0.0] + [float(n) for n in range(1, 400)])
        with mock.patch.object(streamer.castctl, "info", return_value=None), \
             mock.patch.object(streamer.time, "monotonic", side_effect=clock), \
             mock.patch.object(streamer.time, "sleep"):
            with self.assertRaisesRegex(streamer.StreamError, "did not start playing"):
                session._await_receiver("TV", lambda value: False, timeout=5.0)

    def test_unavailable_info_does_not_crash_the_poll(self):
        session = streamer.Session()
        session.caster = _fake_caster(code=None)
        clock = _ticking([0.0] + [float(n) for n in range(1, 400)])
        with mock.patch.object(streamer.castctl, "info", side_effect=OSError("no catt")), \
             mock.patch.object(streamer.time, "monotonic", side_effect=clock), \
             mock.patch.object(streamer.time, "sleep"):
            with self.assertRaisesRegex(streamer.StreamError, "did not start playing"):
                session._await_receiver("TV", lambda value: False, timeout=5.0)


class StartDirectConfirmationTests(unittest.TestCase):
    def _media(self, root: pathlib.Path) -> streamer.MediaInfo:
        return streamer.MediaInfo(path=root / "movie.mp4", duration=90.0)

    def test_start_direct_succeeds_when_the_receiver_confirms(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = pathlib.Path(work)
            session = streamer.Session()
            with mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.castctl, "info",
                                   return_value={"player_state": "PLAYING",
                                                 "title": "Film"}) as info, \
                 mock.patch.object(streamer.subprocess, "Popen",
                                   return_value=_fake_caster(code=0)):
                session.start_direct(
                    self._media(root), device="TV", title="Film",
                    subs_file=None, subs_disabled=True)
            self.assertIsNotNone(session.state)
            info.assert_called_with("TV")

    def test_start_direct_fails_when_the_receiver_never_confirms(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = pathlib.Path(work)
            session = streamer.Session()
            clock = _ticking([0.0] + [float(n) for n in range(1, 400)])
            with mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.time, "monotonic", side_effect=clock), \
                 mock.patch.object(streamer.castctl, "info", return_value=None), \
                 mock.patch.object(streamer.subprocess, "Popen",
                                   return_value=_fake_caster(code=0)):
                with self.assertRaisesRegex(streamer.StreamError, "did not start playing"):
                    session.start_direct(
                        self._media(root), device="TV", title="Film",
                        subs_file=None, subs_disabled=True)
            self.assertIsNone(session.state)

    def test_start_functions_no_longer_sleep_a_fixed_time(self):
        for name, banned in (("start_transcode", "time.sleep(2.0)"),
                             ("start_direct", "time.sleep(2.5)")):
            body = inspect.getsource(getattr(streamer.Session, name))
            self.assertNotIn(banned, body)
            self.assertIn("_await_receiver", body)


if __name__ == "__main__":
    unittest.main()
