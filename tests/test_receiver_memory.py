"""GTK-free, deterministic receiver-learning contracts (#514, first slice)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import receiver_memory as memory  # noqa: E402
import direct_probe  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


class ReceiverMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state" / memory.STATE_NAME
        self.clock = Clock()
        self.store = memory.ReceiverMemory(self.path, clock=self.clock)
        self.key = memory.receiver_key(uuid="44ad6ed8-44de-48b9-959b-3e4cd075e234")
        self.sig = memory.codec_signature(
            container="mkv", video="h264", profile="High", level="4.1",
            audio="aac", subtitle="ass")

    def test_two_consecutive_direct_failures_prefer_hls(self):
        self.assertIsNone(self.store.advice(self.key, self.sig))
        self.assertTrue(self.store.record(self.key, self.sig, "direct", False))
        self.assertIsNone(self.store.advice(self.key, self.sig))
        self.store.record(self.key, self.sig, "hls", True)
        self.store.record(self.key, self.sig, "direct", False)
        self.assertEqual(self.store.advice(self.key, self.sig), "hls")
        self.assertIn("failed twice", self.store.explanation(self.key, self.sig))

    def test_direct_success_is_based_only_on_receiver_confirmations(self):
        self.store.record(self.key, self.sig, "direct", False)
        for attempt in range(3):
            self.store.record(self.key, self.sig, "direct", True)
            self.assertEqual(self.store.advice(self.key, self.sig),
                             "direct" if attempt == 2 else None)
        self.assertIn("succeeded three", self.store.explanation(self.key, self.sig))
        self.store.record(self.key, self.sig, "direct", False)
        self.assertIsNone(self.store.advice(self.key, self.sig))

    def test_stale_evidence_expires_and_codec_signatures_are_independent(self):
        for _ in range(2):
            self.store.record(self.key, self.sig, "direct", False)
        other = memory.codec_signature(container="mp4", video="h264", audio="aac")
        self.assertIsNone(self.store.advice(self.key, other))
        self.clock.tick(memory.MAX_AGE_SECONDS + 1)
        self.assertIsNone(self.store.advice(self.key, self.sig))
        self.assertEqual(self.store.explanation(self.key, self.sig),
                         "No reliable receiver playback preference has been learned.")

    def test_two_fake_receiver_rejections_skip_direct_and_keep_hard_guards(self):
        def rejected(_device):
            return {"player_state": "IDLE"}

        for attempt in range(2):
            self.assertTrue(memory.should_try_direct(
                True, self.store, self.key, self.sig))
            reply = direct_probe.verify_direct_start(
                "TV", "Film", get_info=rejected, pause=lambda _n: None,
                attempts=3, interval=0)
            self.assertEqual(reply, "rejected")
            self.store.record(self.key, self.sig, "direct", False)
        self.assertFalse(memory.should_try_direct(True, self.store, self.key, self.sig))
        self.assertFalse(memory.should_try_direct(False, self.store, "", ""))
        other = memory.codec_signature(container="webm", video="vp9", audio="opus")
        self.assertTrue(memory.should_try_direct(True, self.store, self.key, other))
        self.assertTrue(memory.should_try_direct(True, self.store, "", ""))

        def accepted(_device):
            return {"player_state": "PLAYING", "title": "Film"}

        for _ in range(3):
            reply = direct_probe.verify_direct_start(
                "TV", "Film", get_info=accepted, pause=lambda _n: None,
                attempts=3, interval=0)
            self.assertEqual(reply, "accepted")
            self.store.record(self.key, self.sig, "direct", True)
        self.assertTrue(memory.should_try_direct(True, self.store, self.key, self.sig))

    def test_media_signature_contains_only_codec_info(self):
        from types import SimpleNamespace
        media = SimpleNamespace(
            vcodec="h264", vprofile="High 10", pix_fmt="yuv420p10le", acodec="aac",
            title="/home/private/Secret.mkv")
        signature = memory.media_signature(
            media, container="mkv", subtitle_kind="sidecar")
        self.assertEqual(len(signature), 64)
        self.assertEqual(signature, memory.media_signature(
            SimpleNamespace(vcodec=media.vcodec, vprofile=media.vprofile,
                            pix_fmt=media.pix_fmt, acodec=media.acodec,
                            title="Different title"), container="mkv", subtitle_kind="sidecar"))
        with self.assertRaises(ValueError):
            memory.media_signature(media, container="../../private", subtitle_kind="none")

    def test_file_never_contains_raw_ip_uuid_or_media_names(self):
        ip = "192.168.12.123"
        key = memory.receiver_key(host=ip, port=8009)
        sig = memory.codec_signature(container="mp4", video="h264", audio="ac3")
        self.assertEqual(len(key), 64)
        self.assertNotEqual(key, self.key)
        self.store.record(key, sig, "direct", True)
        encoded = self.path.read_text()
        for secret in (ip, "8009", "44ad6ed8", "Movies", "/home/", "film.mkv"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(json.loads(encoded)["schema"], memory.SCHEMA)
        if sys.platform != "win32":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_data_is_quarantined_and_never_causes_loss_of_new_record(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema":1,"receivers":"not a mapping"}')
        self.assertIsNone(self.store.advice(self.key, self.sig))
        quarantine = self.path.with_name(self.path.name + ".corrupt")
        self.assertTrue(quarantine.exists())
        self.assertIn("not a mapping", quarantine.read_text())
        self.store.record(self.key, self.sig, "direct", True)
        self.assertEqual(len(json.loads(self.path.read_text())["receivers"]), 1)

    def test_invalid_inputs_never_reach_disk(self):
        for fn in (
            lambda: memory.receiver_key(host="http://example.com/a", port=8009),
            lambda: memory.receiver_key(host="192.168.1.4", port=0),
            lambda: memory.codec_signature(container="../film.mkv", video="h264", audio="aac"),
            lambda: self.store.record("my Living Room TV", self.sig, "direct", True),
            lambda: self.store.record(self.key, self.sig, "direct", 1),
            lambda: self.store.record(self.key, self.sig, "unknown", False),
        ):
            with self.assertRaises(ValueError):
                fn()
        self.assertFalse(self.path.exists())

    def test_eight_outcome_limit_and_thread_safe_serialisation(self):
        def record_many():
            for _ in range(15):
                self.assertTrue(self.store.record(self.key, self.sig, "hls", True))
        threads = [threading.Thread(target=record_many) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        rows = json.loads(self.path.read_text())["receivers"][self.key][self.sig]
        self.assertEqual(len(rows), memory.MAX_OUTCOMES)

    def test_lru_limits_are_enforced_without_dropping_recent_receivers(self):
        old = memory.Outcome("direct", False, self.clock.now - 1)
        new = memory.Outcome("direct", True, self.clock.now)
        receivers = {f"{index:064x}": {f"{sig:064x}": [old]
                     for sig in range(memory.MAX_SIGNATURES + 2)}
                     for index in range(memory.MAX_RECEIVERS + 3)}
        keep = f"{memory.MAX_RECEIVERS + 99:064x}"
        receivers[keep] = {self.sig: [new]}
        compact = memory._trim(receivers, self.clock.now)
        self.assertEqual(len(compact), memory.MAX_RECEIVERS)
        self.assertIn(keep, compact)
        self.assertTrue(all(len(sigs) <= memory.MAX_SIGNATURES for sigs in compact.values()))

    def test_write_failure_keeps_previous_state_and_no_temporary_files(self):
        self.store.record(self.key, self.sig, "direct", True)
        original = self.path.read_bytes()
        with mock.patch.object(memory.os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(self.store.record(self.key, self.sig, "direct", False))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_diagnostics_only_export_aggregates_no_identifiers_or_titles(self):
        import diagnostics

        self.store.record(self.key, self.sig, "direct", False)
        self.store.record(self.key, self.sig, "hls", True)
        summary = self.store.summary()
        self.assertEqual(summary, {
            "receivers": 1, "codec_signatures": 1, "direct_failures": 1})
        self.assertEqual(set(summary), {
            "receivers", "codec_signatures", "direct_failures"})
        with mock.patch.object(diagnostics, "tool_version", return_value=""):
            bundle = diagnostics.collect(home=self.temp.name, receiver_learning=self.path)
        self.assertEqual(bundle["receiver_learning"], summary)
        text = json.dumps(bundle["receiver_learning"])
        self.assertNotIn(self.key, text)
        self.assertNotIn(self.sig, text)
        self.assertNotIn("192.168.", text)
        self.assertNotIn("film.mkv", text)

    def test_headless_cli_can_forget_one_receiver_without_touching_any_other(self):
        import cli
        import io
        from contextlib import redirect_stdout

        uuid = "44ad6ed8-44de-48b9-959b-3e4cd075e234"
        other = memory.receiver_key(host="192.168.1.20", port=8009)
        self.store.record(self.key, self.sig, "direct", False)
        self.store.record(other, self.sig, "hls", True)
        output = io.StringIO()
        with redirect_stdout(output):
            status = memory.main(["--uuid", uuid, "--store", str(self.path)])
        self.assertEqual(status, 0)
        self.assertIn("cleared", output.getvalue())
        self.assertEqual(set(json.loads(self.path.read_text())["receivers"]), {other})
        with mock.patch.object(cli.sys, "argv",
                               ["smoothcast", "--forget-receiver", "--uuid", uuid,
                                "--store", str(self.path)]):
            self.assertEqual(cli._main(), 0)
        self.assertEqual(set(json.loads(self.path.read_text())["receivers"]), {other})

    def test_forget_cli_refuses_untrusted_path_input_without_mutating_state(self):
        self.store.record(self.key, self.sig, "direct", True)
        original = self.path.read_bytes()
        with self.assertRaises(SystemExit) as raised:
            memory.main(["--host", "../private/film.mkv", "--store", str(self.path)])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(self.path.read_bytes(), original)

    def test_forget_only_one_receiver_and_other_history_survives(self):
        other = memory.receiver_key(host="192.168.1.20", port=8009)
        self.store.record(self.key, self.sig, "direct", False)
        self.store.record(other, self.sig, "direct", True)
        self.assertTrue(self.store.forget(self.key))
        self.assertFalse(self.store.forget(self.key))
        saved = json.loads(self.path.read_text())["receivers"]
        self.assertEqual(list(saved), [other])
        self.assertFalse(self.store.forget("not-a-valid-receiver-key"))


if __name__ == "__main__":
    unittest.main()
